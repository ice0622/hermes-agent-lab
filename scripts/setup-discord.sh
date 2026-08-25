#!/usr/bin/env bash
#
# Discord を「1チャンネルで完結」する設定にする。
#
#   ./scripts/setup-discord.sh <BOT_TOKEN> <あなたのUSER_ID> <CHANNEL_ID>
#
# 事前に Discord Developer Portal での作業が必要（docs/discord-usage.md 参照）。
# 特に **Message Content Intent** を ON にしていないと、bot はオンラインになるが
# メッセージの中身が空で届き、永久に無反応になる。公式ドキュメントが
# 「Discord bot が動かない理由の1位」と書いている項目。
#
set -euo pipefail

if [ $# -lt 3 ]; then
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  exit 1
fi

TOKEN="$1"; USER_ID="$2"; CHANNEL_ID="$3"
ENV_FILE="${HERMES_HOME:-$HOME/.hermes}/.env"
HERMES="$(command -v hermes || echo "$HOME/.hermes/hermes-agent/venv/bin/hermes")"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }

touch "$ENV_FILE"; chmod 600 "$ENV_FILE"

set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# --- 必須 -------------------------------------------------------------------
set_env DISCORD_BOT_TOKEN      "$TOKEN"
set_env DISCORD_ALLOWED_USERS  "$USER_ID"

# --- 「1チャンネルで完結」させるための設定 ----------------------------------
# 定時通知（cron --no-agent）の配信先
set_env DISCORD_HOME_CHANNEL       "$CHANNEL_ID"
set_env DISCORD_HOME_CHANNEL_NAME  "#health"
# このチャンネルでは @メンション不要にする。毎回タグ付けが要ると記録をやめる
set_env DISCORD_FREE_RESPONSE_CHANNELS "$CHANNEL_ID"
# このチャンネル以外では反応しない（他のサーバーに巻き込まれない）
set_env DISCORD_ALLOWED_CHANNELS   "$CHANNEL_ID"
# 既定では @メンションごとにスレッドが立つ。記録用チャンネルでは
# 1メッセージごとにスレッドができて履歴が断片化するので切る
set_env DISCORD_AUTO_THREAD        "false"
# 👀 → ✅ の絵文字で処理中/完了が分かる。入ったかどうかの確認に効く
set_env DISCORD_REACTIONS          "true"

info "設定を書きました: ${ENV_FILE}"
echo
grep -E '^DISCORD_' "$ENV_FILE" | sed 's/^\(DISCORD_BOT_TOKEN=\).*/\1********（伏せて表示）/'
echo
info "定時通知の配信先を Discord に切り替えます"
"$(dirname "$0")/install-cron.sh" discord >/dev/null
"$HERMES" cron list 2>&1 | grep -E 'Name:|Deliver:' | paste - - | sed 's/^/  /'

cat <<'EOS'

--------------------------------------------------------------------
次にゲートウェイを起動します。WSL では foreground 推奨です。

    hermes gateway run

bot が Discord でオンラインになったら、そのチャンネルに
「w 64.2」と送ってみてください。記録されれば疎通完了です。

無反応の場合はほぼ Message Content Intent が OFF です。
Developer Portal → Bot → Privileged Gateway Intents を確認してください。
--------------------------------------------------------------------
EOS
