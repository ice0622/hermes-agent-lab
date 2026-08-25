#!/usr/bin/env bash
#
# 健康管理エージェントの定時通知を Hermes cron に登録する。
#
#   ./scripts/install-cron.sh [deliver先]
#
# deliver先の既定は local。Discord を設定したら `./scripts/install-cron.sh discord`。
#
# Hermes は ~/.hermes/scripts/ の外を指すシンボリックリンクを
# パストラバーサルとして拒否するので、リポジトリを呼ぶ薄いラッパを生成する。
# こうするとリポジトリ側を編集すればそのまま反映される（コピーだと反映されない）。
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DELIVER="${1:-local}"
SCRIPTS="${HERMES_HOME:-$HOME/.hermes}/scripts"
HERMES="$(command -v hermes || echo "$HOME/.hermes/hermes-agent/venv/bin/hermes")"

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }

mkdir -p "$SCRIPTS"

# name / cron式 / 説明
JOBS=(
  "morning|0 7 * * *|朝の今日のメニュー"
  "evening|0 18 * * *|夕方の不足通知"
  "weekly|0 21 * * 0|日曜の週次ふりかえり"
)

for job in "${JOBS[@]}"; do
  IFS='|' read -r name sched desc <<<"$job"
  target="${REPO_ROOT}/skills/health/cron/${name}.py"
  wrapper="${SCRIPTS}/health-${name}.py"

  cat > "$wrapper" <<PYEOF
#!/usr/bin/env python3
"""${desc}（自動生成。編集しない）

実体は ${target}。
Hermes は scripts/ の外へのシンボリックリンクを拒否するため、
実体ファイルとしてここに置き、リポジトリ側を呼び出している。
再生成: ${REPO_ROOT}/scripts/install-cron.sh
"""
import runpy
import sys

TARGET = "${target}"
sys.argv[0] = TARGET
runpy.run_path(TARGET, run_name="__main__")
PYEOF
  chmod +x "$wrapper"
  info "ラッパを生成: health-${name}.py -> ${target}"

  # 同名ジョブがあれば作り直す
  "$HERMES" cron remove "health-${name}" >/dev/null 2>&1 || true
  "$HERMES" cron create "$sched" \
    --name "health-${name}" \
    --script "health-${name}.py" \
    --no-agent \
    --deliver "$DELIVER" >/dev/null
  info "登録: health-${name}  [${sched}]  deliver=${DELIVER}"
done

echo
info "一覧を確認します"
"$HERMES" cron list
cat <<'EOS'

--------------------------------------------------------------------
すべて --no-agent です。LLM を一切通さないので、この3本の配信は
トークンを消費しません。

Discord を設定したら、配信先を切り替えてください:
    ./scripts/install-cron.sh discord
--------------------------------------------------------------------
EOS
