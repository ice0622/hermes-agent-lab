#!/usr/bin/env bash
#
# 開発用。skills/ 配下の各スキルを ~/.hermes/skills/ にシンボリックリンクする。
# これで install し直さずに、このリポジトリの編集がそのまま Hermes に反映される。
#
#   ./scripts/link-dev.sh            リンクを張る
#   ./scripts/link-dev.sh --unlink   リンクを外す
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="${REPO_ROOT}/skills"
DEST_ROOT="${HERMES_HOME:-$HOME/.hermes}/skills"

UNLINK=false
[ "${1:-}" = "--unlink" ] && UNLINK=true

info() { printf '\033[36m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$1"; }

if [ ! -d "$SRC_ROOT" ]; then
  warn "skills/ が見つかりません: ${SRC_ROOT}"
  exit 1
fi

mkdir -p "$DEST_ROOT"

count=0
# skills/<category>/<skill-name>/ の2階層を辿る
while IFS= read -r -d '' skill_md; do
  skill_dir="$(dirname "$skill_md")"
  name="$(basename "$skill_dir")"
  category="$(basename "$(dirname "$skill_dir")")"

  dest_dir="${DEST_ROOT}/${category}"
  dest="${dest_dir}/${name}"

  if [ "$UNLINK" = true ]; then
    if [ -L "$dest" ]; then
      rm "$dest"
      info "unlinked  ${category}/${name}"
      count=$((count + 1))
    fi
    continue
  fi

  mkdir -p "$dest_dir"

  # 実体のディレクトリがある場合は消さない。上書き事故を防ぐ
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then
    warn "skipped   ${category}/${name} — 実体が既にあります: ${dest}"
    warn "          install 済みのものを消してから張り直してください"
    continue
  fi

  ln -sfn "$skill_dir" "$dest"
  info "linked    ${category}/${name} -> ${skill_dir}"
  count=$((count + 1))
done < <(find "$SRC_ROOT" -mindepth 3 -maxdepth 3 -name SKILL.md -print0)

if [ "$count" -eq 0 ]; then
  warn "対象がありませんでした"
  exit 0
fi

echo
if [ "$UNLINK" = true ]; then
  info "${count} 件のリンクを解除しました"
else
  info "${count} 件をリンクしました。Hermes を再起動すると反映されます"
  info "確認: hermes skills list"
fi
