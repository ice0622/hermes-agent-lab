"""診断。**LLM を通さない。**

数字を見て「何が問題か」「次に何をするか」を出すルールエンジン。
仕様（docs/spec/health-agent.md）の制御ループもここに含む。

設計方針:
  * 問題の指摘だけで終わらせない。必ず**次のアクション**を1つ付ける
  * 記録が無いときは他の分析を出さない。前提が無い分析はノイズになる
  * 「記録が伸びていない」ときは、目標ではなく**手段（入力形式）を疑う**
    → docs/plan.md の撤退条件に紐づく
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

# しきい値。ここだけ見れば判定基準が分かるようにまとめている
MIN_RECORD_DAYS_7 = 4  # 直近7日でこれ未満の記録日数なら「続いていない」
MIN_WEIGHT_DAYS_14 = 4  # 直近14日でこれ未満の体重記録なら制御ループが動かない
GAIN_LOW_G = 100  # 週あたりの増加がこれ未満なら摂取不足
GAIN_HIGH_G = 400  # これを超えると脂肪が乗る
INTAKE_RATIO = 0.90  # 目標カロリーに対する許容下限
PROTEIN_RATIO = 0.85  # 目標タンパク質に対する許容下限
MIN_TRAIN_DAYS_28 = 8  # 直近28日でこれ未満なら頻度不足（週2回換算）
LIFT_STALL_SESSIONS = 3  # 同一種目でこの回数、推定1RM が更新されなければ停滞
UNKNOWN_FOOD_LIMIT = 3  # 未知食品がこれ以上溜まったら報告

# 停滞判定の対象にする種目。サイドレイズのように20レップで回す補助種目は
# 推定1RM が意味を持たないので外す（「26セッション更新なし」が常に出てノイズになる）
MAIN_LIFTS = ("bp", "sq", "dl", "lpd", "sp", "msp", "lpr", "row", "pu")

KCAL_STEP_UP = 200  # 摂取不足のときに目標を上げる量
KCAL_STEP_DOWN = 150  # 増えすぎのときに下げる量


@dataclass
class Finding:
    prio: int  # 小さいほど先に出す
    severity: str  # 'stop' | 'warn' | 'ok'
    title: str
    evidence: str
    action: str


@dataclass
class TargetChange:
    """制御ループが提案する目標値の変更。--apply で targets に追記する。"""

    kcal: float
    protein: float
    fat: float
    carb: float
    note: str


@dataclass
class Report:
    findings: list[Finding]
    target_change: TargetChange | None = None


# ---------------------------------------------------------------- 集計


def _d(today: date, days: int) -> str:
    return (today - timedelta(days=days)).isoformat()


def _record_days(conn: sqlite3.Connection, today: date, days: int) -> int:
    lo = _d(today, days)
    hi = today.isoformat()
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM (
               SELECT date FROM meals WHERE date > ? AND date <= ?
               UNION SELECT date FROM sets  WHERE date > ? AND date <= ?
               UNION SELECT date FROM body  WHERE date > ? AND date <= ?)""",
        (lo, hi, lo, hi, lo, hi),
    ).fetchone()
    return row["n"]


def _weight_avg(conn: sqlite3.Connection, today: date, window: int) -> tuple[float | None, int]:
    """window=0 なら直近7日、1 ならその前の7日の平均体重。"""
    lo, hi = _d(today, 7 * (window + 1)), _d(today, 7 * window)
    row = conn.execute(
        "SELECT AVG(weight) AS a, COUNT(*) AS n FROM body WHERE date > ? AND date <= ?",
        (lo, hi),
    ).fetchone()
    return (row["a"], row["n"])


def _weight_days(conn: sqlite3.Connection, today: date, days: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM body WHERE date > ? AND date <= ?",
        (_d(today, days), today.isoformat()),
    ).fetchone()
    return row["n"]


def _intake_avg(conn: sqlite3.Connection, today: date, days: int) -> tuple[float, float, int]:
    """記録がある日だけの平均 kcal / protein と、その日数。"""
    rows = conn.execute(
        """SELECT date, SUM(kcal) AS k, SUM(protein) AS p FROM meals
           WHERE date > ? AND date <= ? GROUP BY date""",
        (_d(today, days), today.isoformat()),
    ).fetchall()
    if not rows:
        return (0.0, 0.0, 0)
    n = len(rows)
    return (sum(r["k"] for r in rows) / n, sum(r["p"] for r in rows) / n, n)


def _train_days(conn: sqlite3.Connection, today: date, days: int) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT date) AS n FROM sets WHERE date > ? AND date <= ?",
        (_d(today, days), today.isoformat()),
    ).fetchone()
    return row["n"]


def _stalled_lifts(conn: sqlite3.Connection) -> list[tuple[str, float, int]]:
    """直近 LIFT_STALL_SESSIONS 回、推定1RM の自己最高を更新していない種目。

    戻り値は (種目名, 自己最高1RM, 更新なしのセッション数)。
    セッション数が少ない種目は対象外（判断材料が足りない）。
    """
    out = []
    codes = conn.execute(
        """SELECT e.id, e.name, COUNT(DISTINCT s.date) AS n
           FROM exercises e JOIN sets s ON s.exercise_id = e.id
           WHERE e.code IN (%s)
           GROUP BY e.id HAVING n >= ?""" % ",".join("?" * len(MAIN_LIFTS)),
        (*MAIN_LIFTS, LIFT_STALL_SESSIONS + 1),
    ).fetchall()
    for ex in codes:
        per_date = conn.execute(
            """SELECT date, MAX(weight * (1 + reps / 30.0)) AS rm
               FROM sets WHERE exercise_id = ? AND weight > 0
               GROUP BY date ORDER BY date""",
            (ex["id"],),
        ).fetchall()
        if len(per_date) < LIFT_STALL_SESSIONS + 1:
            continue
        rms = [r["rm"] for r in per_date]
        best = max(rms)
        best_idx = max(i for i, v in enumerate(rms) if v == best)
        since = len(rms) - 1 - best_idx
        if since >= LIFT_STALL_SESSIONS:
            out.append((ex["name"], best, since))
    out.sort(key=lambda t: -t[2])
    return out


# ---------------------------------------------------------------- 診断本体


def run(conn: sqlite3.Connection, today: date | None = None) -> Report:
    today = today or date.today()
    f: list[Finding] = []
    change: TargetChange | None = None

    target = conn.execute("SELECT * FROM v_target").fetchone()

    # --- R1 記録が続いていない。最優先で、これが出たら他は出さない
    rec7 = _record_days(conn, today, 7)
    if rec7 == 0:
        f.append(
            Finding(
                0,
                "stop",
                "直近7日、記録が1件も無い",
                "記録日数 0/7 日",
                "分析する材料が無い。まず1件入れる: `health w 64.2`\n"
                "  それでも入らないなら、問題は意志ではなく**入力形式**。\n"
                "  CLI をやめて別経路（Telegram / 音声）に変える判断をする\n"
                "  （撤退条件: docs/plan.md — 2026-09-07 までに7日連続）",
            )
        )
        return Report(findings=f)

    if rec7 < MIN_RECORD_DAYS_7:
        f.append(
            Finding(
                0,
                "stop",
                "記録が続いていない",
                f"直近7日の記録日数 {rec7}/7 日（目安は {MIN_RECORD_DAYS_7} 日以上）",
                "記録の精度より継続が先。**入力を1日1回、体重だけでいい**まで軽くする: `health w 64.2`\n"
                "  2週間続いてから食事記録を足す",
            )
        )

    # --- R2 体重の記録が足りない → 制御ループが動かない
    wdays = _weight_days(conn, today, 14)
    if wdays < MIN_WEIGHT_DAYS_14:
        f.append(
            Finding(
                1,
                "stop",
                "体重の記録が足りず、目標カロリーを補正できない",
                f"直近14日の体重記録 {wdays} 件（目安は {MIN_WEIGHT_DAYS_14} 件以上）",
                "毎朝起きてすぐ測って `health w <体重>`。\n"
                "  この仕組みは体重の実測で目標を較正する。ここが欠けると全部が推定値のまま動く",
            )
        )
    else:
        # --- R3/R4 制御ループ
        cur, n_cur = _weight_avg(conn, today, 0)
        prev, n_prev = _weight_avg(conn, today, 1)
        if cur is not None and prev is not None and n_cur and n_prev:
            delta_g = (cur - prev) * 1000
            base = (
                f"週平均 {prev:.2f}kg → {cur:.2f}kg（{delta_g:+.0f}g/週、"
                f"n={n_prev}→{n_cur}）"
            )
            if delta_g < GAIN_LOW_G:
                f.append(
                    Finding(
                        2,
                        "warn",
                        "体重が増えていない。摂取が足りない",
                        base,
                        f"目標カロリーを +{KCAL_STEP_UP}kcal する（`health check --apply`）。\n"
                        "  意志で食べる量を増やすのではなく、目標値を上げて不足表示に働かせる",
                    )
                )
                change = _bump(target, +KCAL_STEP_UP, f"週平均 {delta_g:+.0f}g/週 で増加不足")
            elif delta_g > GAIN_HIGH_G:
                f.append(
                    Finding(
                        2,
                        "warn",
                        "増えるペースが速い。脂肪が乗る",
                        base,
                        f"目標カロリーを -{KCAL_STEP_DOWN}kcal する（`health check --apply`）",
                    )
                )
                change = _bump(target, -KCAL_STEP_DOWN, f"週平均 {delta_g:+.0f}g/週 で増加過多")
            else:
                f.append(
                    Finding(
                        2,
                        "ok",
                        "増加ペースは適正",
                        base,
                        f"目標は変えない。この {delta_g:+.0f}g/週 を維持する",
                    )
                )

    # --- R5/R6 摂取
    if target:
        k_avg, p_avg, n_days = _intake_avg(conn, today, 7)
        if n_days == 0:
            f.append(
                Finding(
                    3,
                    "warn",
                    "食事の記録が直近7日で1件も無い",
                    "不足カロリーを計算できない",
                    "`health m サラダチキン, おにぎり*2` の形で1食から始める。\n"
                    "  全食を完璧に記録しようとすると続かない。まず夕食だけでいい",
                )
            )
        else:
            if k_avg < target["kcal"] * INTAKE_RATIO:
                gap = target["kcal"] - k_avg
                f.append(
                    Finding(
                        3,
                        "warn",
                        "摂取カロリーが目標に届いていない",
                        f"直近7日の平均 {k_avg:.0f}kcal / 目標 {target['kcal']:.0f}kcal"
                        f"（1日あたり {gap:.0f}kcal 不足、記録があった日 {n_days}日）",
                        f"1日 {gap:.0f}kcal を足す。手数が少ない順:\n"
                        "  牛丼（並）1杯 = 635kcal / おにぎり（鮭）2個+プロテイン+ナッツ = 635kcal・P39\n"
                        "  ※ この不足が「記録漏れ」なのか「本当に食べていない」のかは要確認",
                    )
                )
            if p_avg < target["protein"] * PROTEIN_RATIO:
                f.append(
                    Finding(
                        3,
                        "warn",
                        "タンパク質が足りない",
                        f"直近7日の平均 {p_avg:.0f}g / 目標 {target['protein']:.0f}g",
                        "供給源を1つ固定で足す。プロテイン1杯=P24 / サラダチキン1個=P21.7 / ゆで卵2個=P13",
                    )
                )

    # --- R7 未知食品
    unknown = conn.execute(
        "SELECT food_name, COUNT(*) AS n FROM meals WHERE food_id IS NULL "
        "GROUP BY food_name ORDER BY n DESC"
    ).fetchall()
    if len(unknown) >= UNKNOWN_FOOD_LIMIT:
        names = "、".join(r["food_name"] for r in unknown[:5])
        f.append(
            Finding(
                3,
                "warn",
                "マスタに無い食品が溜まっている（カロリーが 0 で集計されている）",
                f"{len(unknown)} 種類: {names}"
                + ("…" if len(unknown) > 5 else ""),
                "foods マスタに追記する。フェーズ1で Haiku が自動で埋めるが、\n"
                "  それまでは手で入れた方が集計が正しくなる",
            )
        )

    # --- R8 頻度
    tdays = _train_days(conn, today, 28)
    if tdays < MIN_TRAIN_DAYS_28:
        f.append(
            Finding(
                4,
                "warn",
                "トレーニング頻度が低い",
                f"直近28日で {tdays} 日（週 {tdays / 4:.1f} 回。目安は週2回以上）",
                "重量やメニューを変える前に頻度を戻す。\n"
                "  実測では週2.3回の時期に筋力が伸び、週1.2〜1.6回の時期に止まっている",
            )
        )

    # --- R9 漸進性過負荷の停止
    for name, best, since in _stalled_lifts(conn)[:3]:
        f.append(
            Finding(
                5,
                "warn",
                f"{name} が停滞している",
                f"自己最高の推定1RM {best:.1f}kg を、直近 {since} セッション更新していない",
                "重量を上げるのではなく、まず同じ重量でレップかセットを1つ増やす。\n"
                "  体重が増えていない期間は筋力も伸びにくいので、上の摂取の指摘を先に潰す",
            )
        )

    # --- R10 暫定値の食品
    est = conn.execute(
        """SELECT COUNT(*) AS n FROM foods f WHERE f.source = 'estimate'
           AND EXISTS (SELECT 1 FROM meals m WHERE m.food_id = f.id)"""
    ).fetchone()["n"]
    if est:
        f.append(
            Finding(
                6,
                "warn",
                "実際に食べている食品の栄養価が暫定値のまま",
                f"{est} 品が source='estimate'",
                "次に買ったとき実物の栄養成分表示を見て更新する。\n"
                "  暫定値のままだと「摂取不足」の判定自体が信用できない",
            )
        )

    f.sort(key=lambda x: (x.prio, {"stop": 0, "warn": 1, "ok": 2}[x.severity]))
    return Report(findings=f, target_change=change)


def _bump(target: sqlite3.Row | None, delta: float, why: str) -> TargetChange | None:
    """カロリーを delta 動かす。タンパク質と脂質は据え置き、差分は炭水化物で吸収する。"""
    if target is None:
        return None
    kcal = target["kcal"] + delta
    protein, fat = target["protein"], target["fat"]
    carb = max(0.0, (kcal - protein * 4 - fat * 9) / 4)
    return TargetChange(
        kcal=kcal,
        protein=protein,
        fat=fat,
        carb=round(carb),
        note=f"{why} → {delta:+.0f}kcal（炭水化物で調整）",
    )


def apply_change(conn: sqlite3.Connection, ch: TargetChange, today: date | None = None) -> None:
    today = today or date.today()
    conn.execute(
        "INSERT INTO targets (effective_from, kcal, protein, fat, carb, note) "
        "VALUES (?,?,?,?,?,?)",
        (today.isoformat(), ch.kcal, ch.protein, ch.fat, ch.carb, ch.note),
    )
    conn.commit()
