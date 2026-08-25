"""買い物リストの生成（T15）。**LLM を使わない。**

残りの kcal / タンパク質 / 脂質の上限に対して、foods マスタから組み合わせを作る。
貪欲法を3つの重み付けで回して、性格の違う3案を出す。

LLM を使わない理由:
  * 候補は37品しかない。探索で足りる
  * モデルの記憶で栄養価を出すと、マスタとの整合が壊れる
  * 定時通知（cron --no-agent）から呼ぶので、トークンを消費できない

脂質の扱いが要点。増量では脂質が先に上限に達するので、
**脂質が超過している日は脂質の多い食品を候補から外す**。
ここを見落とすと「揚げ物を足せ」という逆向きの助言になる。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

MAX_ITEMS = 7  # これ以上並べると買いに行かない
MAX_QTY = 3  # 同じ品をこれ以上は勧めない
REPEAT_PENALTY = 0.55  # 同じ品を重ねるほど魅力を下げる（1品を積み上げた案は買いに行かない）
FAT_HARD_RATIO = 0.35  # 残りカロリーのうち脂質由来がこの割合を超える品は避ける


@dataclass
class Need:
    kcal: float
    protein: float
    fat: float  # 残り。負なら超過
    carb: float


@dataclass
class Plan:
    label: str
    items: list[tuple[str, float]] = field(default_factory=list)
    kcal: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carb: float = 0.0

    @property
    def n_items(self) -> int:
        return len(self.items)


def current_need(conn: sqlite3.Connection) -> Need | None:
    t = conn.execute("SELECT * FROM v_target").fetchone()
    if t is None:
        return None
    g = conn.execute("SELECT * FROM v_today").fetchone()
    got = {k: (g[k] if g else 0) for k in ("kcal", "protein", "fat", "carb")}
    return Need(
        kcal=t["kcal"] - got["kcal"], protein=t["protein"] - got["protein"],
        fat=t["fat"] - got["fat"], carb=t["carb"] - got["carb"],
    )


def _candidates(conn: sqlite3.Connection, need: Need) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM foods WHERE kcal > 0").fetchall()
    if need.fat > 0:
        return rows
    # 脂質が既に超過している日は、脂質の比率が高い品を候補から外す
    out = []
    for r in rows:
        fat_share = (r["fat"] * 9) / r["kcal"] if r["kcal"] else 1.0
        if fat_share <= FAT_HARD_RATIO:
            out.append(r)
    return out or rows


def _score(r: sqlite3.Row, need: Need, mode: str) -> float:
    """1単位あたりの「効き」。大きいほど良い。"""
    if r["kcal"] <= 0:
        return -1e9
    kind_w = 0.2 if r["kind"] == "item" else 1.0  # 素材そのままは勧めにくい
    if mode == "fewest":  # 手数最小 = 1品でカロリーを稼ぐ
        return r["kcal"] * kind_w
    if mode == "dish":
        # 料理名で出せるものを優先する。素材（item）の羅列にしない
        w = {"dish": 3.0, "staple": 2.0, "side": 1.2, "snack": 0.9,
             "drink": 0.8, "item": 0.15}.get(r["kind"], 0.5)
        return (r["kcal"] + r["protein"] * 12) * w
    if mode == "protein":  # タンパク質優先
        return (r["protein"] * 10 + r["kcal"] * 0.05) * kind_w
    # balanced: 残りの比率に近い品を選ぶ
    want_p = max(need.protein, 0) / max(need.kcal, 1)
    got_p = r["protein"] / r["kcal"]
    return r["kcal"] * (1.0 - min(abs(got_p - want_p) * 40, 0.95)) * kind_w


def _build(cands: list[sqlite3.Row], need: Need, mode: str, label: str) -> Plan:
    p = Plan(label=label)
    qty: dict[str, float] = {}
    by_name = {r["name"]: r for r in cands}
    fat_ceiling = need.fat if need.fat > 0 else 0.0

    for _ in range(MAX_ITEMS):
        best, best_s = None, -1e9
        for r in cands:
            if qty.get(r["name"], 0) >= MAX_QTY:
                continue
            # 入れたらカロリーを大きく超える品は選ばない
            if p.kcal + r["kcal"] > need.kcal * 1.12:
                continue
            # 脂質に余裕がある日は、その枠も超えないようにする
            if fat_ceiling and p.fat + r["fat"] > fat_ceiling * 1.15:
                continue
            s = _score(r, need, mode)
            # タンパク質が既に足りたら、タンパク質重みを落とす
            if p.protein >= need.protein and mode == "protein":
                s = r["kcal"]
            # 同じ品の積み上げを避ける。パスタ乾麺300g のような案を出さないため
            s *= REPEAT_PENALTY ** qty.get(r["name"], 0)
            if s > best_s:
                best, best_s = r, s
        if best is None:
            break
        qty[best["name"]] = qty.get(best["name"], 0) + 1
        p.kcal += best["kcal"]
        p.protein += best["protein"]
        p.fat += best["fat"]
        p.carb += best["carb"]
        # 目標に十分近づいたら止める
        if p.kcal >= need.kcal * 0.92 and p.protein >= need.protein * 0.92:
            break

    p.items = [(n, q) for n, q in qty.items()]
    p.items.sort(key=lambda t: -by_name[t[0]]["kcal"] * t[1])
    return p


def plans(conn: sqlite3.Connection, need: Need | None = None) -> list[Plan]:
    need = need or current_need(conn)
    if need is None or need.kcal <= 50:
        return []
    cands = _candidates(conn, need)
    out, seen = [], set()
    for mode, label in (("dish", "料理で組む"), ("protein", "タンパク質を優先"),
                        ("fewest", "手数が少ない")):
        p = _build(cands, need, mode, label)
        key = tuple(sorted(p.items))
        if p.items and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def format_plans(need: Need, ps: list[Plan], *, plain: bool = False) -> str:
    """通知に貼れる形。plain=True ならスマホ向けに1行を短くする。"""
    if not ps:
        return "今日はもう足りています。"
    L = []
    L.append(f"あと {need.kcal:.0f}kcal / タンパク質 {need.protein:.0f}g")
    if need.fat < 0:
        L.append(f"※脂質は {-need.fat:.0f}g 超過。揚げ物とナッツは足さない")
    L.append("")
    for i, p in enumerate(ps, 1):
        L.append(f"{i}) {p.label}")
        for name, q in p.items:
            L.append(f"   ・{name}" + (f" ×{q:g}" if q != 1 else ""))
        if not plain:
            L.append(f"   → {p.kcal:.0f}kcal / P{p.protein:.0f} / F{p.fat:.0f}")
        L.append("")
    return "\n".join(L).rstrip()
