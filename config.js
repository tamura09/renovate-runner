// Renovate 自体の設定。リポジトリごとの設定ではない。
//
// ここに書いた設定はすべての対象リポジトリに継承される。各リポジトリの
// renovate.json は、これを上書きしたり足したりするためだけに置く。
module.exports = {
  platform: 'github',

  // 対象は Actions の変数 RENOVATE_REPOSITORIES で明示的に渡す
  // (tamura09/github-terraform が enable_renovate から生成する)。
  //
  // autodiscover は使わない。PAT から見えるリポジトリを全部拾ってしまい、
  // どこを回すかが GitHub の権限設定側に散らばるため。
  autodiscover: false,

  // onboarding PR は出さない。何を回すかは Terraform が決めているので、
  // リポジトリ側の同意を取り直す意味がない。
  onboarding: false,

  // renovate.json が無いリポジトリも回す。共通の設定はこのファイルの extends で
  // 全リポジトリに当たっているので、リポジトリ固有の指定が無ければファイルは
  // 要らない。
  requireConfig: 'optional',

  // GitHub App (tamura09-renovate) として動く。PR の作成者もコミットの author も
  // bot になるので、持ち主が手で作った PR と機械的に区別できる。
  //
  // username は Renovate が「自分が作った PR」を見分けるのに使う。ID は
  // `gh api /users/tamura09-renovate%5Bbot%5D --jq .id` から。
  username: 'tamura09-renovate[bot]',
  gitAuthor:
    'tamura09-renovate[bot] <325525690+tamura09-renovate[bot]@users.noreply.github.com>',

  // 共通のルール。リポジトリ側で extends しなくても当たる。
  extends: ['github>tamura09/renovate-runner//presets/default.json5'],
};
