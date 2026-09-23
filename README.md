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

対象の追加・削除は、このリポジトリではなく非公開のインフラ設定で管理する。

## セキュリティ

- `main` は保護済み。force push とブランチ削除は禁止
- 書き込み権限と手動実行権限は所有者のみ
- 外部 fork の PR workflow は所有者の承認まで実行しない
- GitHub App の秘密鍵はリポジトリ secret に置かない。AWS OIDC で短期認証し、実行時に外部の秘密ストアから読む
- Renovate の AWS role はこのリポジトリの `main` からの定期実行・手動実行だけを許可する
- Actions の利用先は許可リストに限定し、コミット SHA 固定を必須にする

## ログ

Actions の履歴とログは public。対象リポジトリ名、認証情報、内部 URL を出力しない。
手動実行を含め、workflow のログレベルは `info` に固定する。

## 更新方針

- 通常の更新 PR は月曜日に作る
- 脆弱性修正、GitHub Actions の SHA 固定、`tamura09/**` の Action digest 更新は曜日を待たない
- npm パッケージは公開から7日経過後に更新する
- 第三者 Action の digest 更新は通常更新として月曜に作り、自動マージしない
- ベースブランチが進んだ PR は、次の実行で Renovate がベースに追随させる (人がコミットを足した PR は除く)

詳細なルールは [presets/default.json5](presets/default.json5) を参照。
