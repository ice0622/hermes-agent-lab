"""今日やるトレーニングの目標を決める。**LLM を使わない。**

規則は1つだけ。**3セット揃っていない種目は重量を上げない。**

実測（docs/training-history.md）では、3セット目で回数が落ちている状態で重量を
上げ続けた期間に停滞している。だから「同じ重量で3セット揃える」→「揃ったら上げる」
の順を機械的に守らせる。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

TARGET_SETS = 3
TARGET_REPS = 10   # 表示用の上限目安（実際の目標は WORK_REPS で揃える）
# 重量の刻み。ダンベルとマシンで違うので、その種目の履歴に出た値から推定する
DEFAULT_STEP = 2.5
WORK_REPS = 8       # 「常用重量」と見なす最低レップ数
LOOKBACK_SESSIONS = 4  # 常用重量を探す範囲


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
    """各種目の今日の目標。

    基準は「最高重量」ではなく **常用重量**（直近数セッションで
    WORK_REPS 以上挙げられている最も重い重量）にする。
    最高重量を基準にすると、40kg×4 のような限界の1セットに引っ張られて
    「40kg を10回3セット」という非現実的な目標が出る。
    """
    rows = conn.execute(
        """SELECT r.ord, e.id, e.code, e.name FROM routines r
           JOIN exercises e ON e.id = r.exercise_id
           WHERE r.split = ? ORDER BY r.ord LIMIT ?""", (split, limit)).fetchall()
    out: list[Target] = []
    for r in rows:
        recent = [x["d"] for x in conn.execute(
            "SELECT DISTINCT date d FROM sets WHERE exercise_id=? ORDER BY d DESC LIMIT ?",
            (r["id"], LOOKBACK_SESSIONS))]
        if not recent:
            out.append(Target(r["code"], r["name"], 0, [TARGET_REPS] * TARGET_SETS,
                              "記録が無いので軽い重量から", "記録なし"))
            continue

        last = conn.execute(
            "SELECT weight, reps FROM sets WHERE exercise_id=? AND date=? ORDER BY set_no",
            (r["id"], recent[0])).fetchall()
        last_txt = " / ".join(
            (f"{x['weight']:g}kg×{x['reps']}" if x["weight"] else f"自重×{x['reps']}")
            for x in last)

        # 常用重量: 直近 LOOKBACK_SESSIONS で WORK_REPS 以上を1回でも挙げた最も重い重量
        rows_all = conn.execute(
            "SELECT date, weight, reps FROM sets WHERE exercise_id=? AND date IN (%s)"
            % ",".join("?" * len(recent)), (r["id"], *recent)).fetchall()
        work = [x for x in rows_all if x["reps"] >= WORK_REPS]
        if not work:
            # WORK_REPS に届いていない = 重すぎる。最も軽い重量まで落とす
            lightest = min(x["weight"] for x in rows_all)
            out.append(Target(r["code"], r["name"], lightest,
                              [WORK_REPS] * TARGET_SETS,
                              f"直近は{WORK_REPS}回に届いていない。{lightest:g}kg まで落として"
                              f"{WORK_REPS}回×{TARGET_SETS}セットを作る", last_txt))
            continue

        wt = max(x["weight"] for x in work)
        # その重量で WORK_REPS 以上が TARGET_SETS 本揃った日があるか
        best_day, best_n = None, 0
        for d in recent:
            n = sum(1 for x in rows_all
                    if x["date"] == d and x["weight"] == wt and x["reps"] >= WORK_REPS)
            if n > best_n:
                best_day, best_n = d, n

        if best_n >= TARGET_SETS:
            step = _step(conn, r["id"])
            out.append(Target(r["code"], r["name"], wt + step, [WORK_REPS] * TARGET_SETS,
                              f"{wt:g}kg で{WORK_REPS}回×{TARGET_SETS}セット揃っている"
                              f"（{best_day}）。{step:g}kg 上げる", last_txt))
        else:
            out.append(Target(r["code"], r["name"], wt, [WORK_REPS] * TARGET_SETS,
                              f"{wt:g}kg×{WORK_REPS}回 は{best_n}セットまで。"
                              f"重量は上げず{TARGET_SETS}セット揃える", last_txt))
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


def materialize(conn: sqlite3.Connection, *, limit: int = 20) -> int:
    """3分割ぶんの目標を `plans` に書き出す。Web ダッシュボードはこれを読む。

    targets() は DB だけの純関数なので Web 側でも同じ計算はできるが、そうすると
    「3セット揃うまで重量を上げない」という規則の実装が2箇所に増える。
    計算はここだけで行い、結果を置く。全行を置き換えるので冪等。
    """
    ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM exercises")}
    nxt, _ = suggest_split(conn)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    rows = []
    for split in ("push", "pull", "legs"):
        for i, t in enumerate(targets(conn, split, limit), 1):
            rows.append((stamp, split, i, ids[t.code], t.code, t.name, t.weight,
                         "/".join(str(r) for r in t.reps), t.reason, t.last,
                         1 if split == nxt else 0))

    conn.execute("DELETE FROM plans")
    conn.executemany(
        "INSERT INTO plans (computed_at, split, ord, exercise_id, code, name, weight,"
        " reps, reason, last_txt, is_next) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)
