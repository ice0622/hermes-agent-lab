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

from lib import batch, dates, diagnose, history, nl, parse, store  # noqa: E402

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

# ============================================================ dates


def test_dates_absolute():
    T = date(2026, 8, 27)  # 木曜
    for raw, want in (
        ("8/25", "2026-08-25"),
        ("08/25", "2026-08-25"),
        ("8-25", "2026-08-25"),
        ("8月25日", "2026-08-25"),
        ("8月25", "2026-08-25"),
        ("25日", "2026-08-25"),
        ("2026-08-25", "2026-08-25"),
        ("2026/08/25", "2026-08-25"),
        # 全角と、後置の助詞や時間帯が付いた形
        ("８/２５", "2026-08-25"),
        ("8/25の朝", "2026-08-25"),
        ("8/25は", "2026-08-25"),
    ):
        eq(dates.resolve(raw, T).iso, want, f"絶対日付 {raw}")


def test_dates_relative():
    T = date(2026, 8, 27)  # 木曜
    for raw, want in (
        ("今日", "2026-08-27"),
        ("昨日", "2026-08-26"),
        ("きのう", "2026-08-26"),
        ("おととい", "2026-08-25"),
        ("一昨日", "2026-08-25"),
        ("3日前", "2026-08-24"),
        ("木曜", "2026-08-27"),        # 今日が木曜なら今日
        ("火曜", "2026-08-25"),        # 直近の過去
        ("先週の火曜", "2026-08-18"),
        ("金曜", "2026-08-21"),        # 明日の金曜ではなく先週の金曜
    ):
        eq(dates.resolve(raw, T).iso, want, f"相対日付 {raw}")


def test_dates_default_is_today():
    """日付を書かなければ今日。これが自由入力の前提になっている。"""
    T = date(2026, 8, 27)
    for raw in (None, "", "   "):
        r = dates.resolve(raw, T)
        eq(r.iso, "2026-08-27", f"既定は今日 {raw!r}")
        ok(r.assumed, f"assumed が立つ {raw!r}")


def test_dates_future_rolls_back():
    """年の無い M/D が未来になったら去年と読む。未来の記録は存在しない。"""
    T = date(2026, 1, 5)
    r = dates.resolve("12/30", T)
    eq(r.iso, "2025-12-30", "未来の M/D は去年")
    ok(r.warning is not None, "補正したことを警告する")

    # 1日先までは許す（日付が変わった直後の入力）
    eq(dates.resolve("1/6", T).iso, "2026-01-06", "翌日はそのまま")


def test_dates_unparseable_falls_back_to_today():
    """読めない日付で記録を落とさない。今日として入れ、警告に回す。"""
    T = date(2026, 8, 27)
    for raw in ("ほげ", "2/30", "13/40"):
        r = dates.resolve(raw, T)
        eq(r.iso, "2026-08-27", f"読めない日付は今日 {raw}")
        ok(r.assumed, f"assumed が立つ {raw}")
        ok(r.warning is not None, f"警告が出る {raw}")


def test_dates_pop_flag():
    T = date(2026, 8, 27)
    for argv in (["w", "65.2", "--date", "8/25"], ["w", "65.2", "--date=8/25"],
                 ["--date", "8/25", "w", "65.2"]):
        rest, when = dates.pop_flag(argv, T)
        eq(rest, ["w", "65.2"], f"--date を抜く {argv}")
        eq(when.iso, "2026-08-25", f"--date を解決 {argv}")

    rest, when = dates.pop_flag(["w", "65.2"], T)
    eq(rest, ["w", "65.2"], "--date なし: 残り")
    ok(when.assumed, "--date なし: 今日を当てる")


# ============================================================ nl.build_plan（API を使わない）


def _nl_conn(td: str) -> sqlite3.Connection:
    return _fresh_db(td)


def test_build_plan_dates_and_grouping():
    """LLM の出力を固定して、日付の解決と食事のまとめ方を検証する。"""
    T = date(2026, 8, 27)
    with tempfile.TemporaryDirectory() as td:
        conn = _nl_conn(td)
        res = nl.NLResult(
            meals=[
                {"food_name": "おにぎり（鮭）", "qty": 2, "at": "08:00",
                 "date_raw": "8/25", "is_new": False},
                {"food_name": "納豆", "qty": 1, "at": "08:00",
                 "date_raw": "8/25", "is_new": False},
                # 日付が無い → 今日
                {"food_name": "サラダチキン", "qty": 1, "at": "19:00",
                 "date_raw": None, "is_new": False},
            ],
            trainings=[
                {"raw": "ベンチ40キロ8回8回6回", "exercise": "bp",
                 "sets": [{"weight": 40, "reps": 8}, {"weight": 40, "reps": 8},
                          {"weight": 40, "reps": 6}],
                 "note": None, "date_raw": "8/25"},
                # マスタに無い種目は記録せず problems に回す
                {"raw": "謎マシン30キロ10回", "exercise": "zzz",
                 "sets": [{"weight": 30, "reps": 10}], "note": None, "date_raw": None},
                # 自重種目は weight=null → 0
                {"raw": "懸垂5回4回", "exercise": "pu",
                 "sets": [{"weight": None, "reps": 5}, {"weight": None, "reps": 4}],
                 "note": "反動なし", "date_raw": None},
            ],
            body=[{"raw": "65.2キロ", "weight_kg": 65.2, "body_fat": None, "date_raw": "8/25"}],
            unclear=["おにぎりの具は鮭と仮定した"],
        )
        plan = nl.build_plan(conn, res, T)

        # 食事は (日付, 時刻) でまとめる。8/25 08:00 に2品、今日 19:00 に1品
        eq(len(plan.meals), 2, "食事のグループ数")
        eq([w.iso for _, w in plan.meals], ["2026-08-25", "2026-08-27"], "食事の日付")
        eq(len(plan.meals[0][0].items), 2, "8/25 朝は2品まとまる")
        ok(plan.meals[1][1].assumed, "日付なしの食事は今日と明示される")

        # 種目
        eq(len(plan.trainings), 2, "解決できた種目だけ通る")
        eq(plan.trainings[0][0].exercise, "bp", "種目コード")
        eq(plan.trainings[0][0].sets, [(40.0, 8), (40.0, 8), (40.0, 6)], "セット")
        eq(plan.trainings[0][1].iso, "2026-08-25", "種目の日付")
        eq(plan.trainings[1][0].sets, [(0.0, 5), (0.0, 4)], "自重は重量0")
        eq(plan.trainings[1][0].note, "反動なし", "メモが乗る")

        eq(len(plan.body), 1, "体重の件数")
        eq(plan.body[0][1].iso, "2026-08-25", "体重の日付")

        # 未解決の種目と unclear が両方 problems に入る
        ok(any("zzz" in p for p in plan.problems), "未知の種目を報告する")
        ok(any("おにぎり" in p for p in plan.problems), "unclear を引き継ぐ")


def test_build_plan_skips_setless_training():
    with tempfile.TemporaryDirectory() as td:
        conn = _nl_conn(td)
        res = nl.NLResult(trainings=[
            {"raw": "ベンチやった", "exercise": "bp", "sets": [], "note": None, "date_raw": None},
        ])
        plan = nl.build_plan(conn, res, date(2026, 8, 27))
        eq(plan.trainings, [], "レップが無ければ記録しない")
        ok(plan.problems, "理由を報告する")


# ============================================================ store（日付と一括 undo）


def test_store_backdate():
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        sd = Path(td)
        on = date(2026, 8, 25)

        w = store.write_train(
            conn, parse.Train(exercise="bp", sets=[(40.0, 8)], note="呼吸"), on=on, state_dir=sd
        )
        eq(w.day, "2026-08-25", "筋トレの日付")
        row = conn.execute("SELECT date, trained_at, note FROM sets").fetchone()
        eq(row["date"], "2026-08-25", "sets.date")
        eq(row["trained_at"], "2026-08-25 00:00", "遡りの時刻は 00:00")
        eq(row["note"], "呼吸", "note が入る")

        w = store.write_body(conn, parse.Body(weight=65.2), on=on, state_dir=sd)
        eq(w.day, "2026-08-25", "体重の日付")
        eq(conn.execute("SELECT date FROM body").fetchone()["date"], "2026-08-25", "body.date")

        w = store.write_meal(
            conn, parse.Meal(items=[parse.MealItem(name="納豆")], at="19:00"), on=on, state_dir=sd
        )
        eq(w.day, "2026-08-25", "食事の日付")
        eq(conn.execute("SELECT eaten_at FROM meals").fetchone()["eaten_at"],
           "2026-08-25 19:00", "eaten_at は指定時刻")

        # 当日は現在時刻。00:00 に固定してしまうと今日の記録の順序が失われる
        store.write_body(conn, parse.Body(weight=64.9), state_dir=sd)
        today = conn.execute(
            "SELECT measured_at FROM body WHERE date = ?", (date.today().isoformat(),)
        ).fetchone()
        ok(today is not None and not today["measured_at"].endswith("00:00"),
           "当日は現在時刻を入れる")


def test_store_batch_undo():
    """自由入力1回で入った複数テーブルを、1回の undo で消せること。"""
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        sd = Path(td)
        on = date(2026, 8, 25)
        writes = [
            store.write_train(conn, parse.Train(exercise="bp", sets=[(40.0, 8)]), on=on, state_dir=sd),
            store.write_meal(conn, parse.Meal(items=[parse.MealItem(name="納豆")]), on=on, state_dir=sd),
            store.write_body(conn, parse.Body(weight=65.2), on=on, state_dir=sd),
        ]
        store.remember_batch(writes, sd / store.LAST_INSERT)

        store.undo(conn, state_dir=sd)
        for table in ("sets", "meals", "body"):
            eq(conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"], 0,
               f"{table} が空になる")


def test_store_undo_reads_legacy_format():
    """旧形式（単一テーブル）の last_insert.json も読めること。移行で DB を触らないため。"""
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        sd = Path(td)
        w = store.write_body(conn, parse.Body(weight=65.2), on=date(2026, 8, 25), state_dir=sd)
        (sd / store.LAST_INSERT).write_text(
            _json.dumps({"table": "body", "ids": w.ids, "summary": w.summary}), encoding="utf-8"
        )
        store.undo(conn, state_dir=sd)
        eq(conn.execute("SELECT COUNT(*) c FROM body").fetchone()["c"], 0, "旧形式でも消える")


# ============================================================ batch（貼り付け経路・API 不要）


def test_batch_records_and_dates():
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        res = batch.apply(conn, """
# コメント行は無視される

--date 8/25 bp 40 8,8,6 --note 呼吸を意識する
--date 8/25 w 65.2
--date 8/25 m 08:00 納豆, 冷奴
w 64.9
""", date(2026, 8, 27))

        eq(res.errors, [], "エラーなし")
        eq(len(res.writes), 4, "書き込み件数")
        eq(res.days, ["2026-08-25", "2026-08-27"], "2日分に分かれる")

        row = conn.execute("SELECT date, weight, reps, note FROM sets ORDER BY set_no").fetchone()
        eq(row["date"], "2026-08-25", "筋トレの日付")
        eq(row["note"], "呼吸を意識する", "--note が行末まで取られる")

        eq(conn.execute("SELECT COUNT(*) c FROM meals WHERE date='2026-08-25'").fetchone()["c"],
           2, "食事2品が同じ行から入る")
        # --date 無しの行は今日
        ok(conn.execute("SELECT 1 FROM body WHERE date = ?",
                        (date.today().isoformat(),)).fetchone() is not None,
           "--date 無しは今日")


def test_batch_food_directive():
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        res = batch.apply(conn, """
food 惣菜弁当X | 個 | 650 20 20 92 | dish | 総菜弁当X,幕の内X
m 12:00 惣菜弁当X
""", date(2026, 8, 27))
        eq(res.errors, [], "エラーなし")

        f = conn.execute("SELECT * FROM foods WHERE name = '惣菜弁当X'").fetchone()
        ok(f is not None, "food 行でマスタに入る")
        eq(f["source"], "llm", "source は llm")
        eq(f["kind"], "dish", "kind が入る")
        eq(f["alias"], "総菜弁当X,幕の内X", "alias が入る")

        # 同じ行から記録した食事に、その栄養価が反映されている
        m = conn.execute("SELECT kcal, protein FROM meals").fetchone()
        eq(m["kcal"], 650.0, "追加した栄養価で記録される")
        eq(m["protein"], 20.0, "P も反映")

        # 2回目は上書きしない（実物のラベルで直した値を潰さないため）
        res2 = batch.apply(conn, "food 惣菜弁当X | 個 | 1 1 1 1", date(2026, 8, 27))
        eq(res2.errors, [], "既存でもエラーにしない")
        eq(conn.execute("SELECT kcal FROM foods WHERE name='惣菜弁当X'").fetchone()["kcal"],
           650.0, "既存の値を変更しない")


def test_batch_exercise_directive():
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        # 同じ貼り付けの中で、追加した種目をすぐ使えること
        res = batch.apply(conn, """
ex hipx | ヒップスラストX | 臀部 | legs
hipx 60 10,10,10
""", date(2026, 8, 27))
        eq(res.errors, [], "エラーなし")
        e = conn.execute("SELECT * FROM exercises WHERE code = 'hipx'").fetchone()
        ok(e is not None, "ex 行でマスタに入る")
        eq(e["split"], "legs", "分割が入る")
        eq(conn.execute("SELECT COUNT(*) c FROM sets").fetchone()["c"], 3,
           "追加した種目で同じ貼り付け内に記録できる")

        res = batch.apply(conn, "ex badx | だめ | 部位 | ぜんぶ", date(2026, 8, 27))
        ok(res.errors, "分割が不正なら弾く")
        ok(conn.execute("SELECT 1 FROM exercises WHERE code='badx'").fetchone() is None,
           "弾いた行はマスタに入らない")


def test_batch_bad_lines_do_not_stop_good_ones():
    """1行のミスで全部やり直しにしない。貼り直すのが面倒だと記録をやめる。"""
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        res = batch.apply(conn, """
--date 8/25 w 64.5
これはコマンドではない
--date 8/25 zzz 40 8,8,8
food 名前だけ
--date 8/25 m 12:00 納豆
""", date(2026, 8, 27))

        eq(len(res.errors), 3, "壊れた行の件数")
        eq(len(res.writes), 2, "通った行は記録される")
        ok(all("行目" in e for e in res.errors), "行番号が付く")
        ok(any("zzz" in e for e in res.errors), "未知の種目を報告")


def test_batch_is_one_undo():
    """貼り付け1回 = undo 1回。どこまで戻したか分からなくなるのを避ける。"""
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        sd = Path(td)
        # state_dir を使うため、batch が書いた last_insert を差し替えて検証する
        res = batch.apply(conn, """
--date 8/25 bp 40 8,8,6
--date 8/25 w 65.2
--date 8/25 m 12:00 納豆
""", date(2026, 8, 27))
        eq(len(res.writes), 3, "3件入る")
        store.remember_batch(res.writes, sd / store.LAST_INSERT)
        store.undo(conn, state_dir=sd)
        for table in ("sets", "body", "meals"):
            eq(conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"], 0,
               f"{table} が1回の undo で空になる")


def test_batch_rejects_menu_command():
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        res = batch.apply(conn, "t push", date(2026, 8, 27))
        ok(res.errors, "メニュー表示は貼り付けでは使えない")
        eq(res.writes, [], "何も書かない")


def test_batch_prompt_contains_masters():
    """ブラウザに渡すプロンプトに、マスタと書式が両方入っていること。

    どちらかが欠けると、ブラウザ側の Claude が品名や書式を発明する。
    """
    with tempfile.TemporaryDirectory() as td:
        conn = _fresh_db(td)
        conn.execute(
            "INSERT INTO foods (name, unit, kcal, protein, fat, carb, kind) "
            "VALUES ('テスト食品', '個', 100, 10, 5, 3, 'side')"
        )
        conn.commit()
        text = batch.prompt(conn)
        for needle in ("health batch <<'EOF'", "--date", "food <名前>", "ex <コード>",
                       "テスト食品", "bp = ベンチプレス", "foods マスタ", "exercises マスタ"):
            ok(needle in text, f"プロンプトに含まれる: {needle}")


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
