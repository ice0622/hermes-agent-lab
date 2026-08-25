#!/usr/bin/env python3
"""朝の配信（07:00）。Hermes cron から --no-agent で呼ばれる。LLM を使わない。

stdout がそのまま Discord に届く。空なら送られない（--no-agent の仕様）。
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import db, suggest, train  # noqa: E402

W = "月火水木金土日"


def main() -> int:
    p = db.db_path()
    if not p.exists():
        return 0  # 未セットアップなら黙る
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    d = date.today()

    out = [f"おはようございます。{d.month}月{d.day}日（{W[d.weekday()]}）", ""]

    body = conn.execute("SELECT weight FROM body WHERE date=?", (d.isoformat(),)).fetchone()
    if body is None:
        out += ["■ 朝いちばんに", "", "  □ 体重を測る", ""]

    t = conn.execute("SELECT * FROM v_target").fetchone()
    if t:
        out += ["■ 今日の目標", "",
                f"  {t['kcal']:.0f}kcal / タンパク質 {t['protein']:.0f}g", ""]

    split, last = train.suggest_split(conn)
    out += ["■ ジムでやること", ""]
    out += ["  " + ln if ln else "" for ln in
            train.format_targets(split, train.targets(conn, split), last).split("\n")]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
