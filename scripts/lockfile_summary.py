#!/usr/bin/env python3
"""Add version changes from immutable lockfile snapshots to Renovate PR bodies."""

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import quote

import yaml

START = "<!-- renovate-lockfile-summary:start -->"
END = "<!-- renovate-lockfile-summary:end -->"
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "uv.lock", "flake.lock"}


def versions(filename, content):
    result = defaultdict(set)

    def add(name, version):
        if isinstance(name, str) and isinstance(version, str) and name and version:
            result[name].add(version)

    kind = PurePosixPath(filename).name
    if kind in {"package-lock.json", "npm-shrinkwrap.json"}:
        data = json.loads(content)
        if "packages" in data:
            for path, package in data["packages"].items():
                if "node_modules/" in path:
                    add(package.get("name") or path.rsplit("node_modules/", 1)[1], package.get("version"))
        else:
            def walk(dependencies):
                for name, package in dependencies.items():
                    add(name, package.get("version"))
                    walk(package.get("dependencies", {}))
            walk(data.get("dependencies", {}))
    elif kind == "pnpm-lock.yaml":
        # pnpm 12 can retain multiple YAML documents in one lockfile.
        for data in yaml.safe_load_all(content):
            if data is None:
                continue
            for key, package in data.get("packages", {}).items():
                key = key.lstrip("/").split("(", 1)[0]
                match = re.fullmatch(r"((?:@[^/]+/)?[^/@]+)@(.+)", key)
                if match:
                    name, version = match.groups()
                else:
                    name, separator, version = key.rpartition("/")
                    if not separator:
                        raise ValueError("Unsupported pnpm package key")
                add(name, (package or {}).get("version") or version.split("_", 1)[0])
    elif kind == "uv.lock":
        for package in tomllib.loads(content).get("package", []):
            add(package.get("name"), package.get("version"))
    elif kind == "flake.lock":
        for name, node in json.loads(content).get("nodes", {}).items():
            locked = node.get("locked", {})
            # A revision identifies the input even when it has no release version.
            add(name, locked.get("rev") or locked.get("narHash"))
    else:
        raise ValueError(f"Unsupported lockfile: {filename}")
    return dict(result)


def changes(before, after):
    return [(name, sorted(before.get(name, set())), sorted(after.get(name, set())))
            for name in sorted(before.keys() | after.keys())
            if before.get(name, set()) != after.get(name, set())]


def code(value):
    escaped = html.escape(" ".join(value.split()))
    for character in "|`*_[]{}\\":
        escaped = escaped.replace(character, f"&#{ord(character)};")
    return "<code>" + escaped + "</code>"


def strip_summary(body):
    if body.count(START) != body.count(END) or body.count(START) > 1:
        raise ValueError("Incomplete or duplicate lockfile summary markers")
    return re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n*", "", body, flags=re.S)


def render(body, files, repo, number, base_sha, head_sha):
    original = strip_summary(body).lstrip()
    budget = min(48000, 62000 - len(original.encode("utf-8")))
    if budget < 1500:
        raise ValueError("PR body has no room for a lockfile summary")
    counts = {"更新": 0, "追加": 0, "削除": 0}
    for _, rows in files:
        for _, old, new in rows:
            counts["更新" if old and new else "追加" if new else "削除"] += 1
    total = sum(counts.values())
    lines = [START, "### Lockfile のバージョン変更", "",
             f"**ファイル別の合計: 更新 {counts['更新']}件 · 追加 {counts['追加']}件 · 削除 {counts['削除']}件**", "",
             "複数の版があるパッケージは、更新前後の版の集合を表示します。"
             "同じ版の配布元・ハッシュ・依存関係だけの変更は、この表には含みません。", "",
             f"比較: `{base_sha[:12]}` → `{head_sha[:12]}`（PR の分岐点と head）", ""]
    shown = 0
    if any(PurePosixPath(name).name == "flake.lock" for name, _ in files):
        lines.extend(["Nix 入力は revision（無ければ content hash）を表示します。", ""])
    for filename, rows in files:
        heading = [f"#### {code(filename)}", "", "| パッケージ / Nix 入力 | 更新前 | 更新後 |", "|---|---|---|"]
        if not rows:
            heading = [f"#### {code(filename)}", "", "パッケージの版の変更はありません。"]
        if len("\n".join(lines + heading).encode("utf-8")) > budget - 600:
            break
        lines.extend(heading)
        for name, old, new in rows:
            row = f"| {code(name)} | {', '.join(map(code, old)) or '—'} | {', '.join(map(code, new)) or '—'} |"
            if len("\n".join(lines + [row]).encode("utf-8")) > budget - 600:
                break
            lines.append(row)
            shown += 1
        lines.append("")
        if shown < total and rows and len("\n".join(lines).encode("utf-8")) > budget - 1200:
            break
    if shown < total:
        lines.extend([f"本文の長さ制限により {total - shown}件を省略しました。"
                      f"[PR の差分](https://redirect.github.com/{repo}/pull/{number}/files)で確認してください。", ""])
    lines.append(END)
    section = "\n".join(lines)
    if START in body:
        return re.sub(re.escape(START) + r".*?" + re.escape(END),
                      lambda _: section, body, flags=re.S)
    return section + "\n\n" + original


def api(endpoint, payload=None, paginate=False):
    command = ["gh", "api", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if payload is not None:
        command += ["--method", "PATCH", "--input", "-"]
    response = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, check=True)
    return json.loads(response.stdout)


def read_file(repo, filename, ref):
    data = api(f"repos/{repo}/contents/{quote(filename, safe='/')}?ref={ref}")
    if data.get("type") != "file":
        raise ValueError(f"Not a regular file: {filename}")
    if data.get("encoding") != "base64":
        data = api(f"repos/{repo}/git/blobs/{data['sha']}")
    if data.get("encoding") != "base64":
        raise ValueError(f"Unsupported content encoding: {filename}")
    encoded = "".join(data["content"].split())
    return base64.b64decode(encoded, validate=True).decode("utf-8")


def eligible(pr, repo):
    head = pr.get("head", {})
    branch = head.get("ref", "")
    return (pr.get("user", {}).get("login") == "tamura09-renovate[bot]"
            and pr.get("base", {}).get("ref") == "main"
            and (head.get("repo") or {}).get("full_name") == repo
            and (branch == "renovate/lock-file-maintenance"
                 or branch.startswith("renovate/lock-file-maintenance-")))


def update(repo, number, dry_run=False):
    endpoint = f"repos/{repo}/pulls/{number}"
    pr = api(endpoint)
    if pr["state"] != "open" or not eligible(pr, repo):
        raise ValueError(f"Not an open Renovate maintenance PR: {repo} #{number}")
    head = pr["head"]["sha"]
    comparison = api(f"repos/{repo}/compare/{pr['base']['sha']}...{head}")
    base = comparison["merge_base_commit"]["sha"]
    files = [file for page in api(endpoint + "/files?per_page=100", paginate=True) for file in page]
    if len(files) != pr["changed_files"]:
        raise ValueError("GitHub did not return the complete PR file list")
    summaries = []
    for file in files:
        name = file["filename"]
        old_name = file.get("previous_filename", name)
        old_supported = PurePosixPath(old_name).name in LOCKFILES
        new_supported = PurePosixPath(name).name in LOCKFILES
        if not (old_supported or new_supported):
            continue
        before = versions(old_name, read_file(repo, old_name, base)) if old_supported and file["status"] != "added" else {}
        after = versions(name, read_file(repo, name, head)) if new_supported and file["status"] != "removed" else {}
        summaries.append((name, changes(before, after)))
    if not summaries:
        print("Unsupported lockfile format; summary skipped.")
        return
    # Recheck the head and preserve body edits made while files were fetched.
    current = api(endpoint)
    if current["state"] != "open" or current["head"]["sha"] != head:
        raise ValueError("PR changed while generating its lockfile summary; retry next run")
    body = render(current.get("body") or "", summaries, repo, number, base, head)
    if dry_run:
        print(body)
    elif body != (current.get("body") or ""):
        api(endpoint, {"body": body})
        print("Lockfile summary updated.")
    else:
        print("Lockfile summary unchanged.")


def prepare_rules(repo, prs):
    """Keep the existing canonical PR summary in Renovate's native notes."""
    rules = []
    candidates = [pr for pr in prs if pr["head"]["ref"] == "renovate/lock-file-maintenance"]
    if len(candidates) == 1:
        body = candidates[0].get("body") or ""
        strip_summary(body)  # Validate marker ownership before reuse.
        match = re.search(re.escape(START) + r".*?" + re.escape(END), body, flags=re.S)
        if match:
            # Notes are Handlebars templates. Never interpret lockfile data as a template.
            note = match.group().replace("{", "&#123;").replace("}", "&#125;")
            rules.append({"matchUpdateTypes": ["lockFileMaintenance"], "prBodyNotes": [note]})
    # The action mounts only its configuration file into the Renovate container.
    # Put notes in that file, never in step env or outputs (which Actions logs).
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "config.js"
    destination = Path(os.environ.get("LOCKFILE_CONFIG_PATH", ".renovate-runtime.cjs"))
    destination.write_text(source.read_text(encoding="utf-8") +
        "\nmodule.exports.packageRules = [...(module.exports.packageRules ?? []), ..." +
        json.dumps(rules, ensure_ascii=True) + "];\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("TARGET_REPOSITORY"))
    parser.add_argument("--pr", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-rules", action="store_true")
    args = parser.parse_args()
    if not args.repo or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be owner/name")
    prs = [pr for page in api(f"repos/{args.repo}/pulls?state=open&per_page=100", paginate=True)
           for pr in page if eligible(pr, args.repo)] if not args.pr else []
    if args.prepare_rules:
        if args.pr:
            parser.error("--prepare-rules scans open maintenance PRs without --pr")
        prepare_rules(args.repo, prs)
        return
    numbers = [args.pr] if args.pr else [pr["number"] for pr in prs]
    failed = False
    for number in numbers:
        try:
            update(args.repo, number, args.dry_run)
        except Exception:
            failed = True
            print("::error::One lockfile summary failed; continuing with other PRs.", file=sys.stderr)
    if failed:
        raise RuntimeError("Some lockfile summaries failed")


def run():
    try:
        main()
    except Exception as error:
        # API exceptions and parser tracebacks can contain private names or file contents.
        print(f"::error::Lockfile summary failed ({type(error).__name__}). "
              "Check the target PR and lockfile format.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
