#!/usr/bin/env python3
"""夕方の配信（18:00）。Hermes cron から --no-agent で呼ばれる。LLM を使わない。

その日のうちに行動を変えられる唯一のタイミングなので、通知はこれを本命にする。
足りていれば1行だけ返す。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import db, suggest  # noqa: E402


def main() -> int:
    p = db.db_path()
    if not p.exists():
        return 0
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    need = suggest.current_need(conn)
    if need is None:
        return 0
    if need.kcal <= 150:
        print("今日はもう足りています。")
        return 0
    n = conn.execute(
        "SELECT COUNT(*) c FROM meals WHERE date=date('now','localtime')").fetchone()["c"]
    if n == 0:
        print("今日はまだ食事の記録が入っていません。")
        print("入れてから見ると、残りが正確になります。\n")
    print("■ 今日の残り\n")
    print(suggest.format_plans(need, suggest.plans(conn, need), plain=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
