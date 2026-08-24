#!/usr/bin/env python3
"""hello-hermes の診断スクリプト。

スキルが Hermes に正しく認識されているか、開発用リンク経由かどうかを JSON で返す。
新しいスキルで scripts/ を使うときの書き方の見本も兼ねている。

Hermes からは SKILL.md 内で ${HERMES_SKILL_DIR}/scripts/run.py として呼ばれる。
直接叩いても動くよう、環境変数が無い場合はこのファイルの位置から逆算する。
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path


def skill_dir() -> Path:
    """スキルのルート。Hermes 経由なら環境変数、直接実行ならファイル位置から。"""
    env = os.environ.get("HERMES_SKILL_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def main() -> int:
    root = skill_dir()

    report = {
        "skill": "hello-hermes",
        "ok": (root / "SKILL.md").is_file(),
        "skill_dir": str(root),
        # link-dev.sh でリンクを張っていれば true。開発モードかどうかの判定に使う
        "is_symlink": root.is_symlink() or root.parent.is_symlink(),
        "hermes_home": str(hermes_home()),
        "hermes_home_exists": hermes_home().is_dir(),
        "python": platform.python_version(),
        "platform": platform.system().lower(),
    }

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    # SKILL.md が隣に無い＝パス解決に失敗している
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
