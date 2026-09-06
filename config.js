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

  // PAT の持ち主のメールアドレスを晒さないよう、noreply を明示する。
  gitAuthor: 'tamura09 <82946547+tamura09@users.noreply.github.com>',

  // 共通のルール。リポジトリ側で extends しなくても当たる。
  extends: ['github>tamura09/renovate-runner//presets/default.json5'],
};
