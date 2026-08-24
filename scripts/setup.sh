#!/usr/bin/env bash
#
# Hermes Agent 本体を導入し、このリポジトリのスキルを入れる。
# 本体がすでに入っている場合は、そこはスキップする。
#
#   ./scripts/setup.sh
#
set -euo pipefail

REPO="ice0622/hermes-agent-lab"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$1"; }

# --- 1. Hermes 本体 --------------------------------------------------------
if command -v hermes >/dev/null 2>&1; then
  info "Hermes は導入済み: $(command -v hermes)"
else
  info "Hermes Agent を導入します"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

  # インストーラは PATH を rc ファイルに書くだけなので、この shell には効いていない
  if ! command -v hermes >/dev/null 2>&1; then
    warn "導入は完了しましたが、この shell からはまだ hermes が見えません。"
    warn "次を実行してから、もう一度このスクリプトを走らせてください:"
    warn "    source ~/.bashrc"
    exit 1
  fi
fi

# --- 2. プロバイダ設定 -----------------------------------------------------
# 対話ウィザードなので、未設定のときだけ案内する（勝手に起動しない）
if [ ! -f "${HERMES_HOME:-$HOME/.hermes}/config.yaml" ]; then
  warn "プロバイダが未設定です。先に次を実行してください:"
  warn "    hermes setup"
  warn "（Nous Portal / OpenRouter / OpenAI / 自前エンドポイントから選択）"
fi

# --- 3. このリポジトリのスキル ---------------------------------------------
info "スキルを導入します: ${REPO}"
hermes skills install "${REPO}"

info "完了。認識されているか確認します"
hermes skills list

cat <<'EOS'

--------------------------------------------------------------------
開発するなら、次にこれを実行してください:

    ./scripts/link-dev.sh

install はスキルをコピーするので、編集しても元リポジトリに戻りません。
シンボリックリンクに張り替えると、このリポジトリの編集が直接反映されます。
--------------------------------------------------------------------
EOS
