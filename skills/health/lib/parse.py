"""入力パーサー。**LLM を通さない。**

対応する書式:

    bp 60 8,8,7          ベンチプレス 60kg を 8/8/7 レップ（同一重量の省略記法）
    bp 60x8,60x8,55x7    セットごとに重量が違う場合
    pu 5,4,3             自重種目（重量なし）
    1 60 8,8,7           直前に `t` で出したメニューの番号で種目を指定
    w 64.2               体重
    w 64.2 15.3          体重 + 体脂肪率
    m サラダチキン, おにぎり*2, 味噌汁     食事（カンマ区切り、`*n` で個数）
    m カフェラテ350ml, 鶏むね肉200g       量で指定（マスタの基準量から個数を算出）
    m 12:30 サラダチキン                  時刻を明示する場合
    t / t push / t legs                  ルーティンのメニュー表示

数量の書き方は `*2` `x2` `×2` `:2` と `2個` `2本` `2枚` などに対応する。

このモジュールは**DB を触らない**（構文解析だけ）。種目名・食品名の解決は
resolve.py が担当する。テストしやすさのために分けている。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ParseError(ValueError):
    """入力の書式が解釈できない。メッセージはそのままユーザーに出す。"""


@dataclass
class Train:
    """筋トレ。exercise は code / 名前 / メニュー番号のいずれかの生文字列。"""

    exercise: str
    sets: list[tuple[float, int]]  # [(重量kg, レップ), ...]
    by_menu_no: int | None = None
    # 「呼吸を意識しないといけない」「start53kg + プレート50kg」のような一言。
    # 定型入力では受け取らない（打鍵が増える）。自由入力からのみ入る
    note: str | None = None


@dataclass
class Body:
    weight: float
    body_fat: float | None = None


@dataclass
class MealItem:
    name: str
    qty: float = 1.0
    # 「350ml」「200g」のように量で指定された場合。個数はマスタの基準量から算出する
    amount: float | None = None
    amount_unit: str | None = None


@dataclass
class Meal:
    items: list[MealItem] = field(default_factory=list)
    at: str | None = None  # 'HH:MM'


@dataclass
class Menu:
    split: str | None = None  # 'push' | 'pull' | 'legs' | None(全部)


Command = Train | Body | Meal | Menu

_SPLITS = {"push", "pull", "legs"}
_COUNTERS = "個|本|枚|杯|パック|缶|玉|切|袋|粒|つ|コ|ヶ|かけ|切れ|房|株"
_AMOUNT_UNITS = "ml|mL|ML|cc|CC|g|G|kg|kG|KG|L|l"
_TIME_RE = re.compile(r"^([0-2]?\d):([0-5]\d)$")
_NUM = r"\d+(?:\.\d+)?"

# 'おにぎり*2' / 'おにぎり x2' / 'おにぎり×2' / 'おにぎり:2'
_QTY_MARK_RE = re.compile(rf"^(?P<name>.+?)\s*[*xX×:]\s*(?P<qty>{_NUM})$")
# 'おにぎり2個' / 'プロテイン2杯' / 'パン3つ'
_QTY_COUNTER_RE = re.compile(rf"^(?P<name>.+?)\s*(?P<qty>{_NUM})\s*(?:{_COUNTERS})$")
# 'カフェラテ350ml' / '鶏むね肉200g' — 個数ではなく**量**。マスタの基準量で割って個数に直す
_QTY_AMOUNT_RE = re.compile(
    rf"^(?P<name>.+?)\s*(?P<amount>{_NUM})\s*(?P<unit>{_AMOUNT_UNITS})$")
# '60x8' / '60×8' / '60kg×8'
_SET_PAIR_RE = re.compile(rf"^(?P<w>{_NUM})\s*(?:kg)?\s*[xX×]\s*(?P<r>\d+)$")


def parse(line: str) -> Command:
    """1行を Command に変換する。空行や解釈不能なら ParseError。"""
    line = line.strip()
    if not line:
        raise ParseError("入力が空です。")

    head, *rest = line.split()
    low = head.lower()

    if low == "t":
        return _parse_menu(rest)
    if low == "w":
        return _parse_body(rest)
    if low == "m":
        return _parse_meal(rest)
    if head.isdigit() and rest:
        # 直前の `t` のメニュー番号での指定
        return Train(exercise=head, sets=_parse_sets(rest), by_menu_no=int(head))
    if not rest:
        raise ParseError(
            f"`{head}` だけでは何をしたいか分かりません。\n"
            "  例: bp 60 8,8,7 / w 64.2 / m サラダチキン / t push"
        )
    return Train(exercise=head, sets=_parse_sets(rest))


# ---------------------------------------------------------------- 個別


def _parse_menu(rest: list[str]) -> Menu:
    if not rest:
        return Menu(split=None)
    s = rest[0].lower()
    if s not in _SPLITS:
        raise ParseError(
            f"分割名が不正です: `{rest[0]}`\n  使えるのは push / pull / legs です。"
        )
    return Menu(split=s)


def _parse_body(rest: list[str]) -> Body:
    if not rest:
        raise ParseError("体重がありません。例: w 64.2")
    try:
        weight = float(rest[0])
    except ValueError:
        raise ParseError(f"体重が数値ではありません: `{rest[0]}`") from None
    if not 20 <= weight <= 300:
        raise ParseError(f"体重が現実的な範囲外です: {weight}kg")

    fat = None
    if len(rest) >= 2:
        try:
            fat = float(rest[1])
        except ValueError:
            raise ParseError(f"体脂肪率が数値ではありません: `{rest[1]}`") from None
        if not 1 <= fat <= 70:
            raise ParseError(f"体脂肪率が現実的な範囲外です: {fat}%")
    return Body(weight=weight, body_fat=fat)


def _parse_meal(rest: list[str]) -> Meal:
    if not rest:
        raise ParseError("食べたものがありません。例: m サラダチキン, おにぎり*2")

    at = None
    if m := _TIME_RE.match(rest[0]):
        at = f"{int(m.group(1)):02d}:{m.group(2)}"
        rest = rest[1:]
        if not rest:
            raise ParseError("時刻のあとに食べたものがありません。")

    meal = Meal(at=at)
    for chunk in " ".join(rest).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        meal.items.append(_parse_meal_item(chunk))
    if not meal.items:
        raise ParseError("食べたものが1つも読み取れませんでした。")
    return meal


def _parse_meal_item(chunk: str) -> MealItem:
    # 量指定（350ml / 200g）を先に見る。'g' は個数の単位と紛れないので順序が重要
    if m := _QTY_AMOUNT_RE.match(chunk):
        name, amount = m.group("name").strip(), float(m.group("amount"))
        if name and amount > 0:
            return MealItem(name=name, amount=amount, amount_unit=m.group("unit").lower())
    for rx in (_QTY_MARK_RE, _QTY_COUNTER_RE):
        if m := rx.match(chunk):
            name = m.group("name").strip()
            qty = float(m.group("qty"))
            if name and qty > 0:
                return MealItem(name=name, qty=qty)
    return MealItem(name=chunk)


def _parse_sets(rest: list[str]) -> list[tuple[float, int]]:
    """セット部分を [(重量, レップ), ...] にする。

    `60 8,8,7`（同一重量）と `60x8,55x7`（セットごと）の2形式。
    自重種目は `5,4,3` のように重量を省略でき、重量0で入る。
    """
    body = " ".join(rest)

    # セットごと形式: 'x' か '×' が含まれる
    if re.search(r"[xX×]", body):
        sets: list[tuple[float, int]] = []
        for chunk in body.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            m = _SET_PAIR_RE.match(chunk)
            if not m:
                raise ParseError(
                    f"セットの書式が読めません: `{chunk}`\n"
                    "  例: bp 60x8,60x8,55x7"
                )
            sets.append((float(m.group("w")), int(m.group("r"))))
        if not sets:
            raise ParseError("セットが1つも読み取れませんでした。")
        return sets

    tokens = body.split()

    # 自重種目: 'pu 5,4,3' / 'pu 5'
    if len(tokens) == 1:
        reps = _parse_reps(tokens[0])
        return [(0.0, r) for r in reps]

    if len(tokens) != 2:
        raise ParseError(
            f"セットの書式が読めません: `{body}`\n"
            "  例: bp 60 8,8,7  /  bp 60x8,55x7  /  pu 5,4,3"
        )

    try:
        weight = float(tokens[0])
    except ValueError:
        raise ParseError(f"重量が数値ではありません: `{tokens[0]}`") from None
    if not 0 <= weight <= 500:
        raise ParseError(f"重量が現実的な範囲外です: {weight}kg")

    return [(weight, r) for r in _parse_reps(tokens[1])]


def _parse_reps(token: str) -> list[int]:
    reps: list[int] = []
    for part in token.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ParseError(f"レップ数が整数ではありません: `{part}`")
        r = int(part)
        if not 1 <= r <= 200:
            raise ParseError(f"レップ数が現実的な範囲外です: {r}")
        reps.append(r)
    if not reps:
        raise ParseError("レップ数が読み取れませんでした。")
    return reps
