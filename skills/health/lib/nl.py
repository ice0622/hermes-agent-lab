"""自由入力の解釈。**ここだけ LLM を使う。**

「8/25は朝おにぎり2つ。ベンチ40キロ8回8回6回。65.2キロ」のような自然文を、
foods / exercises マスタに突き合わせて構造化する。

## 役割分担（ここが設計の要）

| 仕事 | 担当 | 理由 |
|---|---|---|
| 品名・種目名・数量の抽出 | **LLM** | 表記が不規則で規則化できない |
| 日付の**表記の抽出** | **LLM** | 「先週の火曜」がどこにあるかは文脈依存 |
| 日付の**計算** | `dates.py`（規則） | 実行日で結果が変わると記録が信用できない |
| 種目名 → 種目ID | `resolve.py`（DB） | マスタが唯一の真実 |
| 既知食品の栄養価 | `resolve.py`（DB） | 同じ品が日によってずれると集計が壊れる |
| 未知食品の栄養価 | **LLM**（推定して追記） | 二度目以降はマスタ参照で済み API を呼ばない |

**モデルに計算・判断をさせない。抽出だけさせる。**

## マスタの扱い

foods / exercises を丸ごとプロンプトに入れる（合計 100件強、約2.6Kトークン）。
プロンプトキャッシュは**張らない**。claude-haiku-4-5 の最小キャッシュ長は
4096 トークンで、この prefix は届かないため marker を付けても黙って無効になる。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import dates, parse, resolve

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 8192

_DATE_RAW = {
    "type": ["string", "null"],
    "description": (
        "入力に日付の表記があればその文字列をそのまま入れる（'8/25' '昨日' '先週の火曜' '3日前'）。"
        "無ければ null。**日付を自分で計算してはいけない。表記をそのまま返すだけ。**"
    ),
}

_MEAL = {
    "type": "object",
    "properties": {
        "raw": {"type": "string", "description": "入力中の元の表記"},
        "food_name": {
            "type": "string",
            "description": "foods マスタにあればその name をそのまま。無ければ簡潔な新しい名前",
        },
        "qty": {"type": "number", "description": "マスタの unit を1としたときの個数"},
        "at": {
            "type": "string",
            "description": "HH:MM。朝食は08:00、昼食は12:00、夕食は19:00、間食は15:00を既定とする",
        },
        "date_raw": _DATE_RAW,
        "is_new": {"type": "boolean", "description": "foods マスタに無い品かどうか"},
        "unit": {
            "type": ["string", "null"],
            "description": "is_new のときのみ。'個' '本' '200ml' など",
        },
        "kcal": {"type": ["number", "null"], "description": "is_new のときのみ。1単位あたり"},
        "protein": {"type": ["number", "null"]},
        "fat": {"type": ["number", "null"]},
        "carb": {"type": ["number", "null"]},
    },
    "required": ["raw", "food_name", "qty", "at", "date_raw", "is_new",
                 "unit", "kcal", "protein", "fat", "carb"],
    "additionalProperties": False,
}

_TRAINING = {
    "type": "object",
    "properties": {
        "raw": {"type": "string", "description": "入力中の元の表記"},
        "exercise": {
            "type": "string",
            "description": "exercises マスタの code をそのまま返す。マスタに無い種目は作らない",
        },
        "sets": {
            "type": "array",
            "description": "セットを実施順に並べる。'40キロ8回3セット' は同じ要素を3つ",
            "items": {
                "type": "object",
                "properties": {
                    "weight": {
                        "type": ["number", "null"],
                        "description": "kg。自重種目や重量が書かれていなければ null",
                    },
                    "reps": {"type": "integer"},
                },
                "required": ["weight", "reps"],
                "additionalProperties": False,
            },
        },
        "note": {
            "type": ["string", "null"],
            "description": "その種目についての一言があれば（'呼吸を意識する' 'start53kg+プレート50kg'）",
        },
        "date_raw": _DATE_RAW,
    },
    "required": ["raw", "exercise", "sets", "note", "date_raw"],
    "additionalProperties": False,
}

_BODY = {
    "type": "object",
    "properties": {
        "raw": {"type": "string"},
        "weight_kg": {"type": "number"},
        "body_fat": {"type": ["number", "null"]},
        "date_raw": _DATE_RAW,
    },
    "required": ["raw", "weight_kg", "body_fat", "date_raw"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "meals": {"type": "array", "items": _MEAL},
        "trainings": {"type": "array", "items": _TRAINING},
        "body": {"type": "array", "items": _BODY},
        "unclear": {
            "type": "array",
            "items": {"type": "string"},
            "description": "判別できず推定で埋めた点。ユーザーに確認を促す1行",
        },
    },
    "required": ["meals", "trainings", "body", "unclear"],
    "additionalProperties": False,
}

SYSTEM = """あなたは健康記録の構造化だけを行う。会話も助言もしない。

## 日付

1. 日付の表記を見つけたら `date_raw` にその文字列をそのまま入れる。
   **自分で日付を計算しない。** '8/25' は '8/25' のまま返す。
2. 日付の表記が無ければ `date_raw` は null にする。null は「今日のこと」として扱われる。
3. 1つの入力に複数の日が混ざることがある（「8/25は〜、昨日は〜」）。
   要素ごとに、その要素が属する日の表記を入れる。
   「8/25は朝おにぎり、昼は弁当」なら両方の date_raw が '8/25'。

## 食事（meals）

4. foods マスタに載っている品は、必ず `food_name` にマスタの name をそのまま使い
   is_new=false にする。別名（alias）で書かれていてもマスタの name に直す。
5. `qty` はマスタの unit を1とした個数。unit が '200ml' で入力が '350ml' なら qty=1.75。
   unit が '100g' で入力が '200g' なら qty=2。
6. マスタに無い品だけ is_new=true にし、unit と1単位あたりの kcal/protein/fat/carb を
   日本の一般的な商品の値で推定する。控えめにせず現実的な値を出す。
7. is_new=false の品では unit/kcal/protein/fat/carb を必ず null にする（マスタの値を使う）。

## 筋トレ（trainings）

8. `exercise` には exercises マスタの **code** を入れる。名前ではなく code。
9. マスタに無い種目は**作らない**。近い code が無ければ trainings に入れず、
   `unclear` に「種目『○○』はマスタに無いので記録しなかった」と書く。
   種目は分割（push/pull/legs）の割り当てが必要で、勝手に増やすと集計が壊れる。
10. 「40キロ8回8回6回」は sets を3つ（weight=40, reps=8 / 8 / 6）。
    「40キロ8回3セット」も sets を3つに展開する。
    「40kg×8, 37.5kg×8」のようにセットごとに重量が違う場合はそのまま反映する。
11. 懸垂など自重種目、または重量が書かれていない場合は weight=null にする。

## 体重（body）

12. 体重が書かれていれば body に入れる。体脂肪率があれば body_fat に。
    「65.2キロ」「65.2kg」「体重65.2」はすべて体重。

## 共通

13. 質問・感想・相談は完全に無視する。記録に該当するものだけ返す。
14. 量や種類が定まらない語（「パン」「肉」「プロテイン」）は、もっとも一般的な
    解釈で埋めた上で `unclear` にその旨を1行で入れる。黙って決めない。"""


@dataclass
class NLResult:
    meals: list[dict] = field(default_factory=list)
    trainings: list[dict] = field(default_factory=list)
    body: list[dict] = field(default_factory=list)
    unclear: list[str] = field(default_factory=list)
    new_foods: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.meals or self.trainings or self.body)


@dataclass
class Plan:
    """書き込む直前の形。**API を使わずに組み立てられる**のでテストできる。"""

    trainings: list[tuple[parse.Train, dates.Resolved]] = field(default_factory=list)
    meals: list[tuple[parse.Meal, dates.Resolved]] = field(default_factory=list)
    body: list[tuple[parse.Body, dates.Resolved]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.trainings or self.meals or self.body)


# ---------------------------------------------------------------- API


def _venv_site_packages() -> Path | None:
    """リポジトリ直下の .venv を探す。pip が無い環境なので uv で作った venv を使う。"""
    root = Path(__file__).resolve().parents[3]
    for p in (root / ".venv").glob("lib/python*/site-packages"):
        return p
    return None


def _client():
    if (sp := _venv_site_packages()) and str(sp) not in sys.path:
        sys.path.insert(0, str(sp))
    try:
        import anthropic
    except ModuleNotFoundError:
        raise SystemExit(
            "anthropic SDK が見つかりません。リポジトリ直下で:\n"
            "    uv venv .venv && uv pip install --python .venv/bin/python anthropic"
        ) from None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit(
            "ANTHROPIC_API_KEY が設定されていません。\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  ※ 先に Anthropic Console で spend limit を設定してください"
        )
    return anthropic.Anthropic()


def _food_master(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT name, alias, unit, kcal, protein, fat, carb FROM foods ORDER BY id"
    ).fetchall()
    return "\n".join(
        f"- {r['name']} | unit={r['unit']} | {r['kcal']:g}kcal P{r['protein']:g} "
        f"F{r['fat']:g} C{r['carb']:g}" + (f" | 別名: {r['alias']}" if r["alias"] else "")
        for r in rows
    )


def _exercise_master(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT code, name, muscle, split FROM exercises ORDER BY split, id"
    ).fetchall()
    return "\n".join(
        f"- {r['code']} = {r['name']} ({r['muscle']} / {r['split']})" for r in rows
    )


def interpret(conn: sqlite3.Connection, text: str) -> NLResult:
    client = _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"# foods マスタ\n{_food_master(conn)}\n\n"
                    f"# exercises マスタ（code = 名前）\n{_exercise_master(conn)}\n\n"
                    f"# 入力\n{text}"
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    # output_config.format を指定すると先頭の text ブロックが妥当な JSON になる
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    return NLResult(
        meals=data.get("meals") or [],
        trainings=data.get("trainings") or [],
        body=data.get("body") or [],
        unclear=data.get("unclear") or [],
    )


# ---------------------------------------------------------------- マスタへの追記


def upsert_new_foods(conn: sqlite3.Connection, res: NLResult) -> list[str]:
    """is_new の品を foods に追記する。以降は API を呼ばずに済む。

    **種目は追記しない。** 分割と部位の割り当てが集計に効くので、人が決める。
    """
    added = []
    for it in res.meals:
        if not it.get("is_new") or it.get("kcal") is None:
            continue
        name = it["food_name"]
        if conn.execute("SELECT 1 FROM foods WHERE name = ?", (name,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO foods (name, unit, kcal, protein, fat, carb, source) "
            "VALUES (?,?,?,?,?,?, 'llm')",
            (name, it.get("unit") or "個", it["kcal"],
             it.get("protein") or 0, it.get("fat") or 0, it.get("carb") or 0),
        )
        added.append(
            f"{name}  {it['kcal']:g}kcal P{it.get('protein') or 0:g} "
            f"F{it.get('fat') or 0:g} C{it.get('carb') or 0:g} /{it.get('unit') or '個'}"
        )
    conn.commit()
    res.new_foods = added
    return added


# ---------------------------------------------------------------- 書き込み計画


def build_plan(conn: sqlite3.Connection, res: NLResult, today: date | None = None) -> Plan:
    """NLResult を「そのまま store に流せる形」に落とす。**API を使わない。**

    日付の解決と種目の解決をここでやる。どちらも決定的なので、
    LLM の出力を固定すればテストできる。
    """
    plan = Plan(problems=list(res.unclear))

    for t in res.trainings:
        when = dates.resolve(t.get("date_raw"), today)
        ex = resolve.resolve_exercise(conn, str(t.get("exercise") or ""))
        if ex is None:
            plan.problems.append(
                f"種目 `{t.get('exercise')}`（{t.get('raw')}）はマスタに無いので記録しませんでした"
            )
            continue
        sets = [
            (float(s["weight"] or 0), int(s["reps"]))
            for s in (t.get("sets") or [])
            if s.get("reps")
        ]
        if not sets:
            plan.problems.append(f"`{t.get('raw')}` はレップ数が読み取れませんでした")
            continue
        plan.trainings.append(
            (parse.Train(exercise=ex["code"], sets=sets, note=t.get("note")), when)
        )

    # 日付と時刻でまとめる。1回の write_meal = 1回の undo 単位になるので、
    # 同じ食事のものは1つにまとめたほうが取り消しやすい
    by_slot: dict[tuple[str, str], list[parse.MealItem]] = {}
    slot_when: dict[tuple[str, str], dates.Resolved] = {}
    for m in res.meals:
        when = dates.resolve(m.get("date_raw"), today)
        at = str(m.get("at") or "12:00")
        key = (when.iso, at)
        by_slot.setdefault(key, []).append(
            parse.MealItem(name=m["food_name"], qty=float(m.get("qty") or 1))
        )
        slot_when.setdefault(key, when)
    for (iso, at), items in sorted(by_slot.items()):
        plan.meals.append((parse.Meal(items=items, at=at), slot_when[(iso, at)]))

    for b in res.body:
        when = dates.resolve(b.get("date_raw"), today)
        try:
            plan.body.append(
                (
                    parse.Body(
                        weight=float(b["weight_kg"]),
                        body_fat=float(b["body_fat"]) if b.get("body_fat") else None,
                    ),
                    when,
                )
            )
        except (KeyError, TypeError, ValueError):
            plan.problems.append(f"体重が読み取れませんでした: {b.get('raw')}")

    return plan
