"""自由入力の解釈（T14）。**ここだけ LLM を使う。**

「朝はカフェラテ350mlとワッフル、昼はパン3つ」のような自然文を、
foods マスタに突き合わせて構造化する。

設計:
  * **マスタを丸ごとプロンプトに入れる。** 36品程度なので安い。モデルには
    「マスタにあるものはその名前を返す」「無いものだけ栄養価を推定する」と指示する
  * **新規と判定された品は foods に source='llm' で追記する。** これで
    二度目以降はマスタ参照だけで済み、API を呼ばなくなる（仕様の「二度目以降は $0」）
  * 筋トレはここを通さない。`bp 60 8,8,7` の方が速く、しかも無料

モデルは docs/spec/health-agent.md の階層に従い claude-haiku-4-5。
記録のパースは機械的な作業で、判断を要しない。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string", "description": "入力中の元の表記"},
                    "food_name": {
                        "type": "string",
                        "description": "マスタにあればその name をそのまま。無ければ簡潔な新しい名前",
                    },
                    "qty": {"type": "number", "description": "マスタの unit を1としたときの個数"},
                    "at": {
                        "type": "string",
                        "description": "HH:MM。朝食は08:00、昼食は12:00、夕食は19:00、間食は15:00を既定とする",
                    },
                    "is_new": {"type": "boolean", "description": "マスタに無い品かどうか"},
                    "unit": {
                        "type": ["string", "null"],
                        "description": "is_new のときのみ。'個' '本' '200ml' など",
                    },
                    "kcal": {"type": ["number", "null"], "description": "is_new のときのみ。1単位あたり"},
                    "protein": {"type": ["number", "null"]},
                    "fat": {"type": ["number", "null"]},
                    "carb": {"type": ["number", "null"]},
                },
                "required": ["raw", "food_name", "qty", "at", "is_new",
                             "unit", "kcal", "protein", "fat", "carb"],
                "additionalProperties": False,
            },
        },
        "weight_kg": {"type": ["number", "null"], "description": "体重が書かれていれば"},
        "body_fat": {"type": ["number", "null"], "description": "体脂肪率が書かれていれば"},
        "unclear": {
            "type": "array",
            "items": {"type": "string"},
            "description": "量や種類が判別できず推定で埋めたもの。ユーザーに確認を促す",
        },
    },
    "required": ["items", "weight_kg", "body_fat", "unclear"],
    "additionalProperties": False,
}

SYSTEM = """あなたは食事記録の構造化だけを行う。会話はしない。

規則:
1. マスタに載っている品は、必ず `food_name` にマスタの name をそのまま使い is_new=false にする。
   別名（alias）で書かれていても、マスタの name に直す。
2. `qty` はマスタの unit を1とした個数。unit が '200ml' で入力が '350ml' なら qty=1.75。
   unit が '100g' で入力が '200g' なら qty=2。
3. マスタに無い品だけ is_new=true にし、unit と1単位あたりの kcal/protein/fat/carb を
   日本の一般的な商品の値で推定する。推定は控えめにせず現実的な値を出す。
4. is_new=false の品では unit/kcal/protein/fat/carb を必ず null にする（マスタの値を使うため）。
5. 「パン」「肉」のように種類が定まらない語、個数が書かれていない品は、
   もっとも一般的な解釈で埋めた上で `unclear` にその旨を1行で入れる。
6. 食べ物・飲み物・体重以外（トレーニング内容、質問、感想）は完全に無視する。"""


@dataclass
class NLResult:
    items: list[dict]
    weight_kg: float | None
    body_fat: float | None
    unclear: list[str]
    new_foods: list[str]


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


def _master(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT name, alias, unit, kcal, protein, fat, carb FROM foods ORDER BY id"
    ).fetchall()
    lines = [
        f"- {r['name']} | unit={r['unit']} | {r['kcal']:g}kcal P{r['protein']:g} "
        f"F{r['fat']:g} C{r['carb']:g}" + (f" | 別名: {r['alias']}" if r["alias"] else "")
        for r in rows
    ]
    return "\n".join(lines)


def interpret(conn: sqlite3.Connection, text: str) -> NLResult:
    client = _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"# foods マスタ\n{_master(conn)}\n\n# 入力\n{text}",
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    # output_config.format を指定すると先頭の text ブロックが妥当な JSON になる
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    return NLResult(
        items=data["items"],
        weight_kg=data.get("weight_kg"),
        body_fat=data.get("body_fat"),
        unclear=data.get("unclear") or [],
        new_foods=[],
    )


def upsert_new_foods(conn: sqlite3.Connection, res: NLResult) -> list[str]:
    """is_new の品を foods に追記する。以降は API を呼ばずに済む。"""
    added = []
    for it in res.items:
        if not it.get("is_new"):
            continue
        name = it["food_name"]
        if conn.execute("SELECT 1 FROM foods WHERE name = ?", (name,)).fetchone():
            continue
        if it.get("kcal") is None:
            continue
        conn.execute(
            "INSERT INTO foods (name, unit, kcal, protein, fat, carb, source) "
            "VALUES (?,?,?,?,?,?, 'llm')",
            (name, it.get("unit") or "個", it["kcal"],
             it.get("protein") or 0, it.get("fat") or 0, it.get("carb") or 0),
        )
        added.append(name)
    conn.commit()
    res.new_foods = added
    return added
