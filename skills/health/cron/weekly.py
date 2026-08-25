#!/usr/bin/env python3
"""週次の配信（日曜21:00）。Hermes cron から --no-agent で呼ばれる。LLM を使わない。

health check の指摘を優先度順に3つまで。目標カロリーの変更は勝手に適用せず、
提案として出す（いつ・なぜ変えたかを本人が知っている状態を保つ）。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import db, diagnose, report  # noqa: E402

MAX_FINDINGS = 3


def main() -> int:
    p = db.db_path()
    if not p.exists():
        return 0
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    rep = diagnose.run(conn)
    report.write(conn, p.parent / "dashboard.html")

    if not rep.findings:
        print("今週は指摘なし。記録を続けてください。")
        return 0

    print("■ 今週のふりかえり\n")
    for f in rep.findings[:MAX_FINDINGS]:
        mark = {"stop": "【要対応】", "warn": "【注意】", "ok": "【OK】"}[f.severity]
        print(f"{mark} {f.title}")
        print(f"  {f.evidence}")
        act = " ".join(ln.strip() for ln in f.action.splitlines() if ln.strip())
        act = act.replace("**", "")
        print(f"  → {act[:150]}" + ("…" if len(act) > 150 else ""))
        print()

    if rep.target_change:
        c = rep.target_change
        cur = conn.execute("SELECT kcal FROM v_target").fetchone()["kcal"]
        print("■ 目標カロリーの変更を提案します\n")
        print(f"  {cur:.0f}kcal → {c.kcal:.0f}kcal")
        print(f"  理由: {c.note}")
        print("  適用するなら: health check --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
