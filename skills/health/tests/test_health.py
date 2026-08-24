#!/usr/bin/env python3
"""パーサー・取り込み・診断のテスト。

外部ライブラリを使わない（pytest 不要）。実行:

    python3 skills/health/tests/test_health.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import diagnose, history, parse  # noqa: E402

_fails: list[str] = []


def eq(got, want, label=""):
    if got != want:
        _fails.append(f"{label}: got {got!r}, want {want!r}")


def ok(cond, label=""):
    if not cond:
        _fails.append(f"{label}: 条件が偽")


def raises(fn, label=""):
    try:
        fn()
    except parse.ParseError:
        return
    except Exception as e:  # noqa: BLE001
        _fails.append(f"{label}: ParseError 以外が出た: {type(e).__name__}")
        return
    _fails.append(f"{label}: エラーが出なかった")


# ============================================================ parse


def test_parse_train():
    c = parse.parse("bp 60 8,8,7")
    eq(c.exercise, "bp", "同一重量: 種目")
    eq(c.sets, [(60.0, 8), (60.0, 8), (60.0, 7)], "同一重量: セット")

    c = parse.parse("bp 60x8,60x8,55x7")
    eq(c.sets, [(60.0, 8), (60.0, 8), (55.0, 7)], "セットごと重量")

    eq(parse.parse("sq 37.5 10").sets, [(37.5, 10)], "小数の重量")
    eq(parse.parse("bp 60×8, 55×6").sets, [(60.0, 8), (55.0, 6)], "全角×とスペース")

    # 自重種目
    eq(parse.parse("pu 5,4,3").sets, [(0.0, 5), (0.0, 4), (0.0, 3)], "自重: 複数セット")
    eq(parse.parse("pu 5").sets, [(0.0, 5)], "自重: 1セット")

    # メニュー番号
    c = parse.parse("1 60 8,8")
    eq(c.by_menu_no, 1, "メニュー番号")
    eq(c.sets, [(60.0, 8), (60.0, 8)], "メニュー番号のセット")

    # 種目コードは大文字でも通る
    eq(parse.parse("BP 60 8").exercise, "BP", "大文字コード")

    raises(lambda: parse.parse("bp"), "重量とレップが無い")
    raises(lambda: parse.parse("bp 60 abc"), "レップが数値でない")
    raises(lambda: parse.parse("bp 9999 8"), "重量が範囲外")
    raises(lambda: parse.parse("bp 60 999"), "レップが範囲外")
    raises(lambda: parse.parse(""), "空行")
    raises(lambda: parse.parse("bp 60 8 55 8"), "曖昧な3トークン以上")


def test_parse_body():
    eq(parse.parse("w 64.2").weight, 64.2, "体重")
    eq(parse.parse("w 64.2").body_fat, None, "体脂肪なし")
    c = parse.parse("w 64.2 15.3")
    eq((c.weight, c.body_fat), (64.2, 15.3), "体重+体脂肪")
    raises(lambda: parse.parse("w"), "体重なし")
    raises(lambda: parse.parse("w abc"), "体重が数値でない")
    raises(lambda: parse.parse("w 5"), "体重が範囲外")
    raises(lambda: parse.parse("w 64 99"), "体脂肪が範囲外")


def test_parse_meal():
    c = parse.parse("m サラダチキン, おにぎり*2, 味噌汁")
    eq([(i.name, i.qty) for i in c.items],
       [("サラダチキン", 1.0), ("おにぎり", 2.0), ("味噌汁", 1.0)], "食事: 基本")
    eq(c.at, None, "食事: 時刻なし")

    for src, want in (
        ("m おにぎり x2", 2.0), ("m おにぎり×3", 3.0),
        ("m おにぎり:2", 2.0), ("m おにぎり2個", 2.0),
        ("m プロテイン2杯", 2.0), ("m 食パン2枚", 2.0),
    ):
        eq(parse.parse(src).items[0].qty, want, f"数量表記 {src!r}")

    # 数字を含む商品名を数量と誤解しない
    eq(parse.parse("m 6Pチーズ").items[0].name, "6Pチーズ", "数字入りの商品名")
    eq(parse.parse("m 6Pチーズ*3").items[0], parse.MealItem("6Pチーズ", 3.0), "数字入り+数量")

    c = parse.parse("m 12:30 牛丼")
    eq(c.at, "12:30", "時刻指定")
    eq(c.items[0].name, "牛丼", "時刻のあとの品目")
    eq(parse.parse("m 9:05 卵").at, "09:05", "時刻のゼロ埋め")

    eq(len(parse.parse("m あ, , い").items), 2, "空要素を無視")
    raises(lambda: parse.parse("m"), "品目なし")
    raises(lambda: parse.parse("m 12:30"), "時刻だけ")


def test_parse_menu():
    eq(parse.parse("t").split, None, "t 単独")
    eq(parse.parse("t push").split, "push", "t push")
    eq(parse.parse("t LEGS").split, "legs", "t は大文字も通る")
    raises(lambda: parse.parse("t chest"), "不正な分割名")


# ============================================================ history


HISTORY_SAMPLE = """
## 2025年

### 9/20（土）A — Push
- ベンチプレス 20kg×10 / 25kg×7 / 30kg×5
- ダンベルロー 左12kg×10 / 右12kg×10
- **体重 65.2kg**

---

### 9/22（月）B — Legs
- シーテッドレッグプレス 85kg×10 / 95kg×9
- シーテッドカーフレイズ 55kg×10
- LATERAL LOW 20kg×10（左右）
- **体重 65.7kg**

## 2026年

### 6/23（火）Pull
- **懸垂 1回 → 初めてあがった!!** / 1回
- ラットプルダウン 47kg×7 / 40kg×10

### 7/7（火）Legs
- レッグプレス 15kg (?) ×10 / 25kg×10
- メモ: 今日から重量を落として丁寧にこなしていく。

### 7/30（木）Legs
- スクワット 40kg×4
- レッグプレス 50+30kg×10
- **有酸素:** トレッドミル 傾斜9% / 4.5km/h
- **体重 64.8kg**
"""


def test_history_parse():
    sessions, res = history.parse_markdown(HISTORY_SAMPLE)
    eq(res.sessions, 5, "セッション数")
    eq(res.body_rows, 3, "体重の行数")
    eq(res.unmapped, [], "対応表に無い表記は無いこと")
    eq(len(res.skipped), 1, "スキップは LATERAL LOW だけ")
    ok("LATERAL LOW" in res.skipped[0], "スキップの内容")

    by_date = {s.date: s for s in sessions}
    eq(sorted(by_date), ["2025-09-20", "2025-09-22", "2026-06-23", "2026-07-07", "2026-07-30"],
       "年の割り当て")

    # 「ダンベルロー 左」の左右表記を落として dbr に解決する
    eq(by_date["2025-09-20"].sets,
       [("bp", 20.0, 10), ("bp", 25.0, 7), ("bp", 30.0, 5),
        ("dbr", 12.0, 10), ("dbr", 12.0, 10)], "左右表記つき種目")

    # シーテッド系は SKIP の部分一致で落とさない
    codes = [c for c, _, _ in by_date["2025-09-22"].sets]
    eq(codes, ["slp", "slp", "cr"], "シーテッド系を取り込む")

    # 自重種目（重量表記なしの「N回」）
    eq(by_date["2026-06-23"].sets[:2], [("pu", 0.0, 1), ("pu", 0.0, 1)], "懸垂の回数表記")

    # (?) を除去して重量を読む / 重量の加算表記
    eq(by_date["2026-07-07"].sets, [("lpr", 15.0, 10), ("lpr", 25.0, 10)], "(?) 混じり")
    eq(by_date["2026-07-30"].sets, [("sq", 40.0, 4), ("lpr", 80.0, 10)], "50+30kg を 80kg にする")

    # メモ・有酸素・水平線を種目として拾わない
    ok(all("メモ" not in c and "有酸素" not in c for c, _, _ in
            [x for s in sessions for x in s.sets]), "メモ・有酸素を拾わない")


def test_history_idempotent():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.db"
        conn = sqlite3.connect(p)
        conn.row_factory = sqlite3.Row
        for f in ("schema.sql", "seed_exercises.sql", "seed_foods.sql"):
            conn.executescript((ROOT / "db" / f).read_text(encoding="utf-8"))
        md = Path(td) / "hist.md"
        md.write_text(HISTORY_SAMPLE, encoding="utf-8")

        history.import_into(conn, md)
        n1 = conn.execute("SELECT COUNT(*) c FROM sets").fetchone()["c"]
        history.import_into(conn, md)
        n2 = conn.execute("SELECT COUNT(*) c FROM sets").fetchone()["c"]
        eq(n2, n1, "2回流しても増えない（冪等）")
        ok(n1 > 0, "セットが入っている")
        conn.close()


# ============================================================ diagnose


def _fresh_db(td: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(td) / "d.db")
    conn.row_factory = sqlite3.Row
    for f in ("schema.sql", "seed_exercises.sql", "seed_foods.sql"):
        conn.executescript((ROOT / "db" / f).read_text(encoding="utf-8"))
    return conn


def _add_weight(conn, today: date, days_ago: int, w: float):
    d = (today - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO body (measured_at, date, weight, source) VALUES (?,?,?,'manual') "
        "ON CONFLICT(date) DO UPDATE SET weight = excluded.weight",
        (f"{d} 07:00", d, w),
    )


def _titles(rep) -> list[str]:
    return [f.title for f in rep.findings]


def test_diagnose_no_records():
    today = date(2026, 8, 24)
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        rep = diagnose.run(conn, today)
        eq(len(rep.findings), 1, "記録0件なら指摘は1つだけ")
        eq(rep.findings[0].severity, "stop", "記録0件は要対応")
        ok("記録が1件も無い" in rep.findings[0].title, "記録0件のタイトル")
        ok("入力形式" in rep.findings[0].action, "手段を疑う助言が入る")
        conn.close()


def test_diagnose_control_loop():
    today = date(2026, 8, 24)

    # 体重が増えていない → +200kcal の提案
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        for i in range(14):
            _add_weight(conn, today, i, 64.0)
        conn.commit()
        rep = diagnose.run(conn, today)
        ok("体重が増えていない。摂取が足りない" in _titles(rep), "停滞を検出")
        ok(rep.target_change is not None, "目標変更が提案される")
        eq(rep.target_change.kcal, 2830 + diagnose.KCAL_STEP_UP, "+200kcal")
        # 炭水化物で吸収し、P/F は据え置き
        eq(rep.target_change.protein, 130.0, "P は据え置き")
        eq(rep.target_change.fat, 60.0, "F は据え置き")

        diagnose.apply_change(conn, rep.target_change, today)
        eq(conn.execute("SELECT kcal FROM v_target").fetchone()["kcal"], 3030.0, "--apply で反映")
        conn.close()

    # 増えすぎ → -150kcal
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        for i in range(7):
            _add_weight(conn, today, i, 65.0)
        for i in range(7, 14):
            _add_weight(conn, today, i, 64.0)
        conn.commit()
        rep = diagnose.run(conn, today)
        ok("増えるペースが速い。脂肪が乗る" in _titles(rep), "増加過多を検出")
        eq(rep.target_change.kcal, 2830 - diagnose.KCAL_STEP_DOWN, "-150kcal")
        conn.close()

    # 適正 → 変更なし
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        for i in range(7):
            _add_weight(conn, today, i, 64.25)
        for i in range(7, 14):
            _add_weight(conn, today, i, 64.0)
        conn.commit()
        rep = diagnose.run(conn, today)
        ok("増加ペースは適正" in _titles(rep), "適正を検出")
        eq(rep.target_change, None, "適正なら目標を変えない")
        conn.close()


def test_diagnose_stall_only_main_lifts():
    """サイドレイズのような補助種目で停滞を報告しない。"""
    today = date(2026, 8, 24)
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        # 直近の記録が無いと診断は早期リターンするので、体重を入れて土台を作る
        for i in range(14):
            _add_weight(conn, today, i, 64.0)
        sr = conn.execute("SELECT id FROM exercises WHERE code='sr'").fetchone()["id"]
        bp = conn.execute("SELECT id FROM exercises WHERE code='bp'").fetchone()["id"]
        # どちらも「最初が最高で以後更新なし」にする
        for i, ex in ((0, sr), (0, bp)):
            for k, w in enumerate([10.0, 5.0, 5.0, 5.0, 5.0]):
                d = (today - timedelta(days=60 - k * 5)).isoformat()
                conn.execute(
                    "INSERT INTO sets (trained_at, date, exercise_id, weight, reps, set_no) "
                    "VALUES (?,?,?,?,?,1)",
                    (f"{d} 10:00", d, ex, w, 10),
                )
        conn.commit()
        rep = diagnose.run(conn, today)
        titles = " ".join(_titles(rep))
        ok("ベンチプレス が停滞" in titles, "主要種目の停滞は報告する")
        ok("サイドレイズ" not in titles, "補助種目の停滞は報告しない")
        conn.close()


def test_diagnose_actions_always_present():
    today = date(2026, 8, 24)
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        for i in range(14):
            _add_weight(conn, today, i, 64.0)
        conn.commit()
        rep = diagnose.run(conn, today)
        ok(len(rep.findings) > 1, "指摘が複数出る")
        for f in rep.findings:
            ok(bool(f.action.strip()), f"指摘に次のアクションが付く: {f.title}")
            ok(bool(f.evidence.strip()), f"指摘に根拠の数字が付く: {f.title}")
        conn.close()


# ============================================================ runner

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    if _fails:
        print(f"失敗 {len(_fails)} 件 / テスト関数 {len(tests)} 個\n")
        for f in _fails:
            print("  x", f)
        sys.exit(1)
    print(f"全て通過（テスト関数 {len(tests)} 個）")
