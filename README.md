# renovate-runner

アカウント全体の依存更新をまとめて回す Renovate の実行役。

各リポジトリに Renovate のワークフローは置かない。ここ1本が対象リポジトリを順に
見て、更新があれば PR を作る。

## 対象リポジトリの決め方

対象は [tamura09/github-terraform](https://github.com/tamura09/github-terraform) が
決める。`locals.tf` の `enable_renovate` を `true` にして apply すると、このリポジトリの
Actions 変数 `RENOVATE_REPOSITORIES` にそのリポジトリが載る。**既定は無効**。

```hcl
    <NAME> = {
      enable_renovate = true
    }
```

止めたいときも同じ場所で `false` にする。リポジトリ側のファイルを消す必要はない。

`autodiscover` は使わない。PAT から見えるリポジトリを全部拾ってしまい、どこを回すかが
GitHub の権限設定側に散らばるため。

## 設定の置き場所

| ファイル | 何を書くか |
| --- | --- |
| [config.js](config.js) | Renovate 自体の設定 (platform、対象の渡し方、gitAuthor)。全リポジトリに継承される |
| [presets/default.json5](presets/default.json5) | 全リポジトリに当たる共通ルール (スケジュール、グループ分け、ラベル) |
| 各リポジトリの `renovate.json` | そのリポジトリ固有の設定だけ |

共通ルールは `config.js` の `extends` から全リポジトリに当たる。各リポジトリの
`renovate.json` は同じプリセットを extends しているが、二重に読んでも結果は変わらない。
リポジトリを見ただけで何が当たっているか分かるようにと、固有の設定を足す場所として
置いてある。**無くても動く**。

共通の形は次のとおり。

- PR が出るのは月曜の朝だけ (`before 9am on monday`、`Asia/Tokyo`)
- 同時に開く PR は5本まで
- GitHub Actions と Terraform provider は、マイナーとパッチをまとめて1本にする
- メジャーは個別の PR にする。破壊的変更を1つずつ読むため
- コミットメッセージは `chore(deps): ...`
- 更新の一覧と止まっている理由は Dependency Dashboard の Issue にまとまる

## 認証

Renovate は GitHub App **tamura09-renovate** として動く (App ID `4847603`、
Client ID `Iv23liMXUkOapjdcfgG4`)。

秘密鍵を SSM の `/renovate/app-private-key` に1本だけ置き、ワークフローが AWS の OIDC で
`github-actions-renovate` ロールを引いて読む。読んだ鍵から installation access token を
作り、Renovate に渡す。GitHub のリポジトリ secret には何も置かない。

Client ID は秘密ではないのでワークフローに直接書いてある。秘密鍵が無ければ ID だけでは
何もできない。`actions/create-github-app-token` は `app-id` を deprecated にしていて、
`client-id` を使う。

App に必要な権限は次のとおり。

| 権限 | 用途 |
| --- | --- |
| Contents: read/write | ブランチを作って push する |
| Pull requests: read/write | PR を作る |
| Workflows: read/write | `.github/workflows` 配下を更新する PR を push する |
| Issues: read/write | Dependency Dashboard を作る |
| Dependabot alerts: read | 脆弱性のある依存を schedule を無視して先に上げる |
| Metadata: read | 他の権限の前提 |

インストール先は Renovate を有効にしたリポジトリすべてと、**このリポジトリ自身**。
共有プリセットを `github>tamura09/renovate-runner//presets/default.json5` で参照して
いるので、ここを読めないと全リポジトリで設定の解決に失敗して何も動かない。

```bash
aws ssm put-parameter --region ap-northeast-1 --name /renovate/app-private-key \
  --type SecureString --overwrite --value "$(cat <ダウンロードした .pem>)"
```

`--region` を省くと CLI の既定リージョンに同名のパラメータが新しく作られて成功するので、
必ず付けること。

installation access token の寿命は1時間。1回の実行がそれを超えると途中で失効する。
今の規模では届かないが、対象リポジトリが増えて実行が長引くようなら分割する。

## 動かす

毎日 08:00 JST に走る。ただし PR が出るのは月曜の朝だけで、他の曜日はプリセットの
`schedule` に弾かれて何もしない。毎日走らせているのは、Dependency Dashboard の
チェックボックス操作や、閉じた PR の作り直しに週1では反応が遅いため。

手で走らせるときは Actions から `Renovate` を `workflow_dispatch` する。`dry_run` を
付けると PR を作らず、何をするかだけログに出る。`log_level` を `debug` にすると
どのリポジトリで何を見たかが全部出る。

`schedule` は「PR を作ってよい時間帯」なので、手で走らせても月曜の朝でなければ PR は
出ない。今すぐ作らせたいときは Dependency Dashboard の該当項目にチェックを入れる。

## PR は誰の名義で来るか

`tamura09-renovate[bot]`。コミットの author も同じ。持ち主が手で作った PR と機械的に
区別できる。

Dependabot の PR と違って、通常の PR と同じように CI が走る。Dependabot の PR では
secrets も OIDC も渡されず、AWS を触るワークフローが必ず落ちていた。それが無くなる。

Claude のレビューは付かない。`tamura09/claude-pr-review` の既定の `skip_authors` に
入れてある。依存の更新 PR は差分が機械的で、上流のリリースノートを読み込ませる意味も
薄いため。レビューさせたいリポジトリは呼び出し側で `skip_authors` を上書きする。

`monstdb` だけは自前の自動マージ機構 (`renovate-auto-review.yml`) が別に走る。

## Dependabot

使わない。以前 `aws-terraform` / `hetzner-terraform` / `monstdb` に入れていたが、
Renovate に寄せた。
