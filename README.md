# renovate-runner

アカウント内の管理対象リポジトリへ依存更新 PR を作る Renovate 実行役。

このリポジトリは標準 GitHub-hosted runner の実行時間を利用するため public にしている。
対象リポジトリ、認証情報、更新対象の一覧は公開しない。

## 何をするか

- 定期実行で管理対象リポジトリを確認し、依存更新 PR を作る
- [config.js](config.js) が全対象へ共通プリセットを適用する
- 共通の Renovate ルールは [presets/default.json5](presets/default.json5) に置く
- 各リポジトリの `renovate.json` は任意の個別設定用
- Renovate の PR 作成者は `tamura09-renovate[bot]`
- 新規 PR では、対象リポジトリのコミット数が最多の contributor 1人へレビューを依頼する。bot と匿名 contributor は除外し、同数の場合はユーザー名の昇順で選ぶ
- 自動マージ対象の PR にもレビューを依頼する。対象者がいない場合は警告を出し、依頼せずに続行する。既存 PR のレビュアーは変更しない

対象の追加・削除は、このリポジトリではなく非公開のインフラ設定で管理する。

## セキュリティ

- `main` は保護済み。force push とブランチ削除は禁止
- 書き込み権限と手動実行権限は所有者のみ
- 外部 fork の PR workflow は所有者の承認まで実行しない
- GitHub App の秘密鍵はリポジトリ secret に置かない。AWS OIDC で短期認証し、実行時に外部の秘密ストアから読む
- Renovate の AWS role はこのリポジトリの `main` からの定期実行・手動実行だけを許可する
- Actions の利用先は許可リストに限定し、コミット SHA 固定を必須にする
- App の秘密鍵を取得した直後に AWS 認証情報を消去する。要約用コマンドの開始時に OIDC トークン取得用の環境変数も `unset` し、子プロセスへ渡さない（runner が step env の後に再注入するため、YAML の env 上書きだけには依存しない）

## ログ

Actions の履歴とログは public。対象リポジトリ名、認証情報、内部 URL を出力しない。
手動実行を含め、workflow のログレベルは `info` に固定する。

## 更新方針

- 通常の更新 PR は月曜日に作る
- 脆弱性修正 (GitHub の Dependabot alerts と OSV の両方を見る。go.mod の indirect 依存は脆弱性があるときだけ更新する)、GitHub Actions の SHA 固定、`tamura09/**` の Action digest 更新は曜日を待たない
- npm / pnpm / uv などの lockfile を月曜日に更新し、直接依存の版が変わらない間接依存も追う。lockfile の再解決では、範囲指定の直接依存と間接依存の両方が再解決され、14日の待機期間が適用される保証はない。自動マージはしない
- security-scan bot が作成した未解決の依存脆弱性 issue があるリポジトリでは、lockfile 更新の曜日・待機期間・同時 PR 数の制限を外す。`false-positive` / `accepted-risk` は対象外。修正版が親依存の制約で選べない場合や、スキャナと Renovate の脆弱性 DB の差は別途確認が必要
- 通常の依存更新は公開から14日経過した版だけに更新する (脆弱性修正、GitHub Actions の SHA 固定、`tamura09/**` の Action digest 更新は待たない)
- 第三者 Action の digest 更新は通常更新として月曜に作り、自動マージしない
- ベースブランチが進んだ PR は、次の実行で Renovate がベースに追随させる (人がコミットを足した PR は除く)

詳細なルールは [presets/default.json5](presets/default.json5) を参照。

## Lockfile 更新 PR の変更一覧

Renovate 実行後、同じ App が作成した、base が `main` の open な lockfile maintenance PR の本文を補足します。
パッケージ名、更新前・更新後の版をファイルごとに表示し、追加・削除も記載します。
複数の版が残る場合は、対応関係を推測せず版の集合で比較します。対応する形式は
`package-lock.json` / `npm-shrinkwrap.json`、`pnpm-lock.yaml`、`uv.lock`、`flake.lock` です。
Nix 入力は release version の代わりに revision（無ければ content hash）を表示します。

比較には PR の merge base と head の不変な SHA を使います。対象リポジトリのコードや
依存インストールは実行しません。本文中の専用マーカーの範囲だけを更新し、Renovate の
チェックボックスとそれ以外の説明は維持します。再実行・rebase 後も一覧を再生成します。
表には対象 head と、最新 head が異なる場合は未更新である旨を明記します。Renovate 本体が失敗しても
認証が利用可能なら一覧の再生成を試みます。キャンセル時には本文を更新しません。
標準ブランチ `renovate/lock-file-maintenance` の既存一覧を実行前に `prBodyNotes` へ引き継ぎ、
単一の標準 PR では、変更のない実行で Renovate が一覧を削除して再追加することを防ぎます。
複数の maintenance PR が併存する場合は別 PR の表が混ざらないよう引き継ぎを省略し、実行後に PR ごとに再生成します。
一覧は一時的な設定ファイル経由で渡し、公開ログに展開される step env / output には入れません。
要約用依存の導入や事前の一覧取得に失敗しても標準設定へ戻し、セキュリティ用の強制更新を含む Renovate 本体は実行します。
同じ版の配布元・ハッシュ・依存関係だけの変更は版の表には含みません。本文の長さ制限に
達する場合は省略件数と差分へのリンクを表示します。workflow の dry run では本文を更新しません。

既存 PR を手動で更新・確認する場合:

```sh
python3 -m venv /tmp/lockfile-summary-venv
/tmp/lockfile-summary-venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.txt
/tmp/lockfile-summary-venv/bin/python scripts/lockfile_summary.py --repo owner/repo --pr 123 --dry-run
```

`--dry-run` を外すと本文を更新します。認証には `gh` のログインまたは `GH_TOKEN` を使います。
