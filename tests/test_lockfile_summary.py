import json
import io
import os
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lockfile_summary as summary


class LockfileTests(unittest.TestCase):
    def test_npm_nested_scoped_alias_and_multiple_versions(self):
        data = {"packages": {
            "": {"name": "application", "version": "1.0.0"},
            "node_modules/@scope/pkg": {"version": "1.2.3"},
            "node_modules/a/node_modules/@scope/pkg": {"version": "2.0.0"},
            "node_modules/alias": {"name": "real-name", "version": "3.0.0"},
            "node_modules/workspace": {"link": True},
        }}
        self.assertEqual(summary.versions("package-lock.json", json.dumps(data)), {
            "@scope/pkg": {"1.2.3", "2.0.0"}, "real-name": {"3.0.0"}})

    def test_legacy_npm_lock(self):
        data = {"dependencies": {"a": {"version": "1", "dependencies": {"b": {"version": "2"}}}}}
        self.assertEqual(summary.versions("npm-shrinkwrap.json", json.dumps(data)), {"a": {"1"}, "b": {"2"}})

    def test_pnpm_peer_variants_do_not_duplicate_versions(self):
        data = """lockfileVersion: '9.0'
packages:
  '@scope/pkg@1.2.3': {}
  '@scope/pkg@1.2.3(peer@2.0.0)': {}
  undici@7.30.1: {}
snapshots:
  undici@7.30.1: {}
"""
        self.assertEqual(summary.versions("nested/pnpm-lock.yaml", data), {
            "@scope/pkg": {"1.2.3"}, "undici": {"7.30.1"}})

    def test_older_pnpm_formats(self):
        data = "packages:\n  /@scope/pkg/1.2.3_peer@2: {}\n  /other@2.0.0: {}\n"
        self.assertEqual(summary.versions("pnpm-lock.yaml", data), {"@scope/pkg": {"1.2.3"}, "other": {"2.0.0"}})

    def test_pnpm_multiple_documents_and_empty_document(self):
        data = "packages:\n  foo@1.0.0: {}\n---\npackages:\n  foo@2.0.0: {}\n  bar@1.0.0: {}\n---\n"
        self.assertEqual(summary.versions("pnpm-lock.yaml", data), {
            "foo": {"1.0.0", "2.0.0"}, "bar": {"1.0.0"}})

    def test_uv_versions_are_sets(self):
        data = '[[package]]\nname="a"\nversion="1.0"\n[[package]]\nname="a"\nversion="2.0"\n'
        self.assertEqual(summary.versions("uv.lock", data), {"a": {"1.0", "2.0"}})

    def test_nix_revision_and_tarball_hash(self):
        data = {"nodes": {"root": {"inputs": {}}, "nixpkgs": {"locked": {"rev": "abc", "narHash": "hash"}},
                          "tarball": {"locked": {"narHash": "sha256-value"}}}}
        self.assertEqual(summary.versions("flake.lock", json.dumps(data)), {
            "nixpkgs": {"abc"}, "tarball": {"sha256-value"}})

    def test_retained_versions_and_additions_removals(self):
        self.assertEqual(summary.changes({"a": {"1", "2"}, "old": {"1"}}, {"a": {"2", "3"}, "new": {"1"}}),
                         [("a", ["1", "2"], ["2", "3"]), ("new", [], ["1"]), ("old", ["1"], [])])

    def test_no_changes_for_only_peer_or_hash_metadata(self):
        self.assertEqual(summary.changes({"a": {"1"}}, {"a": {"1"}}), [])

    def test_yaml_does_not_construct_objects(self):
        with self.assertRaises(Exception):
            summary.versions("pnpm-lock.yaml", "!!python/object/apply:os.system ['exit 0']")


class BodyTests(unittest.TestCase):
    def test_idempotent_and_preserves_renovate_and_manual_text(self):
        original = "Manual notes\n\n- [x] <!-- rebase-check -->retry\n<!--renovate-debug:abc-->\n"
        args = ([("uv.lock", [("pkg", ["1"], ["2"])])], "owner/repo", 1, "a" * 40, "b" * 40)
        first = summary.render(original, *args)
        self.assertEqual(first, summary.render(first, *args))
        self.assertIn(original, first)
        self.assertIn("<code>pkg</code> | <code>1</code> | <code>2</code>", first)

    def test_escapes_untrusted_names(self):
        value = summary.code('<script>|`[x](url)\n*name*')
        self.assertNotIn("<script>", value)
        self.assertNotIn("|", value)
        self.assertNotIn("`", value)
        self.assertNotIn("[", value)
        self.assertNotIn("\n", value)

    def test_replaces_native_note_in_place(self):
        body = "Renovate intro\n\n" + summary.START + "old" + summary.END + "\n\nRebase checkbox"
        updated = summary.render(body, [("uv.lock", [])], "owner/repo", 1, "a", "b")
        self.assertTrue(updated.startswith("Renovate intro\n\n"))
        self.assertTrue(updated.endswith("\n\nRebase checkbox"))
        self.assertEqual(updated, summary.render(updated, [("uv.lock", [])], "owner/repo", 1, "a", "b"))

    def test_body_limit_is_explicit(self):
        files = [("uv.lock", [(f"pkg-{n}", ["1" * 100], ["2" * 100]) for n in range(1000)])]
        body = summary.render("Original body", files, "owner/repo", 1, "a", "b")
        self.assertLess(len(body.encode()), 62000)
        self.assertIn("件を省略しました", body)
        self.assertIn("https://redirect.github.com/owner/repo/pull/1/files", body)
        self.assertIn("Original body", body)
        self.assertEqual(body, summary.render(body, files, "owner/repo", 1, "a", "b"))

    def test_large_existing_body_stays_below_native_renovate_limit(self):
        original = "x" * 14000
        files = [("uv.lock", [(f"pkg-{n}", ["1" * 100], ["2" * 100]) for n in range(1000)])]
        body = summary.render(original, files, "owner/repo", 1, "a", "b")
        self.assertLess(len(body.encode()), 54000)
        self.assertIn(original, body)
        self.assertIn(summary.END, body)
        self.assertIn("件を省略しました", body)

    def test_broken_owned_section_is_not_overwritten(self):
        with self.assertRaises(ValueError):
            summary.strip_summary(summary.START + "manual text")

    def test_metadata_only_change_is_explained(self):
        body = summary.render("", [("uv.lock", [])], "owner/repo", 1, "a", "b")
        self.assertIn("パッケージの版の変更はありません", body)
        self.assertIn("最新の PR head と異なる場合は **未更新**", body)
        self.assertIn("`a` → `b`", body)


class GitHubTests(unittest.TestCase):
    def pr(self):
        return {"number": 1, "state": "open", "user": {"login": "tamura09-renovate[bot]"},
                "head": {"ref": "renovate/lock-file-maintenance", "sha": "head", "repo": {"full_name": "owner/repo"}},
                "base": {"ref": "main", "sha": "main-tip"}, "changed_files": 1, "body": "Original"}

    def test_only_owned_bot_maintenance_prs(self):
        pr = self.pr()
        self.assertTrue(summary.eligible(pr, "owner/repo"))
        for field, value in [("user", {"login": "human"}), ("head", {"ref": "renovate/other"}),
                             ("base", {"ref": "other"})]:
            changed = dict(pr, **{field: value})
            self.assertFalse(summary.eligible(changed, "owner/repo"))
        self.assertFalse(summary.eligible(pr, "other/repo"))

    def run_update(self, *, moved=False, dry_run=False, status="renamed"):
        pr = self.pr()
        current = self.pr()
        if moved:
            current["head"]["sha"] = "new-head"
        responses = [pr, {"merge_base_commit": {"sha": "merge-base"}}, [[{
            "filename": "new/uv.lock", "previous_filename": "old/uv.lock", "status": status}]], current]
        with patch.object(summary, "api", side_effect=responses + [{}]) as api, \
             patch.object(summary, "read_file", return_value='[[package]]\nname="pkg"\nversion="1"\n') as read, \
             patch("builtins.print"):
            if moved:
                with self.assertRaises(ValueError):
                    summary.update("owner/repo", 1, dry_run)
            else:
                summary.update("owner/repo", 1, dry_run)
            return api, read

    def test_compares_immutable_merge_base_and_handles_rename(self):
        api, read = self.run_update()
        self.assertEqual(read.call_args_list[0].args, ("owner/repo", "old/uv.lock", "merge-base"))
        self.assertEqual(read.call_args_list[1].args, ("owner/repo", "new/uv.lock", "head"))
        self.assertIn("body", api.call_args.args[1])

    def test_dry_run_never_writes(self):
        api, _ = self.run_update(dry_run=True)
        self.assertEqual(api.call_count, 4)

    def test_head_change_never_writes_stale_summary(self):
        api, _ = self.run_update(moved=True)
        self.assertEqual(api.call_count, 4)

    def test_new_lockfile_does_not_fetch_missing_base(self):
        _, read = self.run_update(status="added")
        self.assertEqual(read.call_count, 1)

    def test_removed_lockfile_does_not_fetch_missing_head(self):
        _, read = self.run_update(status="removed")
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[2], "merge-base")

    def test_unsupported_format_skips_without_writing_or_raising(self):
        responses = [self.pr(), {"merge_base_commit": {"sha": "base"}},
                     [[{"filename": ".terraform.lock.hcl", "status": "modified"}]]]
        with patch.object(summary, "api", side_effect=responses) as api, patch("builtins.print"):
            summary.update("owner/repo", 1)
        self.assertEqual(api.call_count, 3)

    def test_removes_old_summary_when_supported_diff_disappears(self):
        pr = self.pr()
        pr["body"] = summary.START + "outdated versions" + summary.END + "\n\nManual notes"
        responses = [pr, {"merge_base_commit": {"sha": "base"}},
                     [[{"filename": ".terraform.lock.hcl", "status": "modified"}]], pr, {}]
        with patch.object(summary, "api", side_effect=responses) as api, patch("builtins.print"):
            summary.update("owner/repo", 1)
        self.assertEqual(api.call_args.args[1], {"body": "Manual notes"})

    def prepared_config(self, prs):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime.cjs"
            with patch.dict(os.environ, {"LOCKFILE_CONFIG_PATH": str(output)}):
                summary.prepare_rules("owner/repo", prs)
            # Load exactly the generated CommonJS file used by the Docker action.
            result = summary.subprocess.run(["node", "-e",
                "console.log(JSON.stringify(require(process.argv[1])))", str(output)],
                capture_output=True, text=True, check=True)
            return json.loads(result.stdout)

    def test_native_rules_are_file_only_and_escape_templates(self):
        pr = self.pr()
        pr["body"] = summary.START + "{{secret}}" + summary.END
        output = io.StringIO()
        with patch("sys.stdout", output):
            config = self.prepared_config([pr])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(config["platform"], "github")
        self.assertEqual(config["extends"], ["github>tamura09/renovate-runner//presets/default.json5"])
        self.assertNotIn("{{", config["packageRules"][0]["prBodyNotes"][0])
        self.assertEqual(config["packageRules"][0]["matchUpdateTypes"], ["lockFileMaintenance"])
        self.assertEqual(config["packageRules"][0]["matchBaseBranches"], ["main"])

    def test_multiple_maintenance_prs_do_not_inject_another_prs_summary(self):
        canonical = self.pr()
        canonical["body"] = summary.START + "private dependency versions" + summary.END
        variant = self.pr()
        variant["head"]["ref"] += "-variant"
        self.assertEqual(self.prepared_config([canonical, variant])["packageRules"], [])

    def test_native_rules_without_owned_summary_leave_rules_empty(self):
        self.assertEqual(self.prepared_config([self.pr()])["packageRules"], [])

    def test_errors_do_not_disclose_private_diagnostics(self):
        output = io.StringIO()
        with patch.object(summary, "main", side_effect=ValueError("private-repo secret file content")), \
             patch("sys.stderr", output):
            self.assertEqual(summary.run(), 1)
        self.assertIn("ValueError", output.getvalue())
        self.assertNotIn("private-repo", output.getvalue())
        self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
