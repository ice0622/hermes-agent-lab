"""今日やるトレーニングの目標を決める。**LLM を使わない。**

規則は1つだけ。**3セット揃っていない種目は重量を上げない。**

実測（docs/training-history.md）では、3セット目で回数が落ちている状態で重量を
上げ続けた期間に停滞している。だから「同じ重量で3セット揃える」→「揃ったら上げる」
の順を機械的に守らせる。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

TARGET_SETS = 3
TARGET_REPS = 10
# 重量の刻み。ダンベルとマシンで違うので、その種目の履歴に出た値から推定する
DEFAULT_STEP = 2.5


@dataclass
class Target:
    code: str
    name: str
    weight: float
    reps: list[int]
    reason: str
    last: str  # 前回の内容（表示用）


def _step(conn: sqlite3.Connection, ex_id: int) -> float:
    """その種目で実際に使われた重量の最小間隔。無ければ 2.5kg。"""
    ws = sorted({r["weight"] for r in conn.execute(
        "SELECT DISTINCT weight FROM sets WHERE exercise_id=? AND weight>0", (ex_id,))})
    diffs = [round(b - a, 2) for a, b in zip(ws, ws[1:]) if 0 < b - a <= 10]
    return min(diffs) if diffs else DEFAULT_STEP


def targets(conn: sqlite3.Connection, split: str, limit: int = 3) -> list[Target]:
    rows = conn.execute(
        """SELECT r.ord, e.id, e.code, e.name FROM routines r
           JOIN exercises e ON e.id = r.exercise_id
           WHERE r.split = ? ORDER BY r.ord LIMIT ?""", (split, limit)).fetchall()
    out: list[Target] = []
    for r in rows:
        # 直近3セッションを見る。1セッションだけだと、書き起こしで判読不明だった行や
        # ウォームアップだけの日に引っ張られて、目標が実力より大幅に低く出る
        recent = [x["d"] for x in conn.execute(
            "SELECT DISTINCT date d FROM sets WHERE exercise_id=? ORDER BY d DESC LIMIT 3",
            (r["id"],))]
        last_date = recent[0] if recent else None
        if last_date is None:
            out.append(Target(r["code"], r["name"], 0, [TARGET_REPS] * TARGET_SETS,
                              "記録が無いので軽い重量から", "記録なし"))
            continue
        sets = conn.execute(
            "SELECT weight, reps FROM sets WHERE exercise_id=? AND date=? ORDER BY set_no",
            (r["id"], last_date)).fetchall()
        last_txt = " / ".join(
            (f"{s['weight']:g}kg×{s['reps']}" if s["weight"] else f"自重×{s['reps']}")
            for s in sets)
        # 基準重量は直近3セッションの最高。その重量を出した日で3セット揃ったかを見る
        per_day = {}
        for d in recent:
            ss = conn.execute(
                "SELECT weight, reps FROM sets WHERE exercise_id=? AND date=?",
                (r["id"], d)).fetchall()
            if ss:
                per_day[d] = ss
        top = max(x["weight"] for ss in per_day.values() for x in ss)
        ref_day = next(d for d, ss in per_day.items() if any(x["weight"] == top for x in ss))
        at_top = [x for x in per_day[ref_day] if x["weight"] == top]
        done = len(at_top) >= TARGET_SETS and all(x["reps"] >= TARGET_REPS for x in at_top)
        if ref_day != last_date:
            last_txt += f"（基準は {ref_day} の {top:g}kg）"

        if done:
            step = _step(conn, r["id"])
            out.append(Target(r["code"], r["name"], top + step,
                              [8, 8, 8],
                              f"{top:g}kg で3セット揃っている。{step:g}kg 上げる", last_txt))
        else:
            got = len(at_top)
            out.append(Target(r["code"], r["name"], top,
                              [TARGET_REPS] * TARGET_SETS,
                              f"{top:g}kg が{got}セットまで。重量は上げず3セット揃える",
                              last_txt))
    return out


def format_targets(split: str, ts: list[Target], last_day: str | None) -> str:
    jp = {"push": "胸と肩", "pull": "背中と腕", "legs": "脚"}
    L = [f"今日は {jp.get(split, split)} の日です。"]
    if last_day:
        L.append(f"（前回 {last_day}）")
    L.append("")
    for i, t in enumerate(ts, 1):
        L.append(f"{i}）{t.name}")
        if t.weight:
            reps = " → ".join(f"{r}回" for r in t.reps)
            L.append(f"   {t.weight:g}kg で")
            L.append(f"   {reps}")
        else:
            L.append(f"   軽い重量で 10回 → 10回 → 10回")
        L.append(f"   {t.reason}")
        L.append("")
    return "\n".join(L).rstrip()


def suggest_split(conn: sqlite3.Connection) -> tuple[str, str | None]:
    """最も久しぶりの分割と、その最終実施日。"""
    best, best_date = "push", None
    for s in ("push", "pull", "legs"):
        d = conn.execute(
            """SELECT MAX(s.date) d FROM sets s JOIN exercises e ON e.id=s.exercise_id
               WHERE e.split=?""", (s,)).fetchone()["d"]
        if d is None:
            return s, None
        if best_date is None or d < best_date:
            best, best_date = s, d
    return best, best_date
