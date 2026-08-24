"""種目名・食品名をマスタに解決する。DB を触る層。

食品がマスタに無い場合は **None を返すが記録は止めない**。
記録が止まるのが最悪なので、栄養価 0 の「未知」として入れておき、
`health check` が「未知の食品が溜まっている」として報告する。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import db

LAST_MENU = "last_menu.json"


# ---------------------------------------------------------------- 種目


def resolve_exercise(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    t = token.strip()
    q = conn.execute
    for sql, arg in (
        ("SELECT * FROM exercises WHERE lower(code) = lower(?)", t),
        ("SELECT * FROM exercises WHERE name = ?", t),
        ("SELECT * FROM exercises WHERE name LIKE ? ORDER BY length(name) LIMIT 1", f"%{t}%"),
    ):
        if row := q(sql, (arg,)).fetchone():
            return row
    return None


def suggest_exercises(conn: sqlite3.Connection, token: str, limit: int = 5) -> list[sqlite3.Row]:
    """解決できなかったときに出す候補。先頭1文字が一致するものを優先する。"""
    rows = conn.execute(
        "SELECT * FROM exercises WHERE code LIKE ? OR name LIKE ? LIMIT ?",
        (f"{token[:1]}%", f"%{token[:1]}%", limit),
    ).fetchall()
    return rows


# ---------------------------------------------------------------- 食品


def resolve_food(conn: sqlite3.Connection, name: str) -> tuple[sqlite3.Row | None, str]:
    """(行, 解決方法) を返す。方法は 'exact' | 'alias' | 'partial' | 'none'。

    partial のときは呼び出し側が警告を出す。「おにぎり」が
    「おにぎり（鮭）」と「おにぎり（ツナマヨ）」のどちらに当たったかを
    黙って決めると、カロリーが静かにずれる。
    """
    n = name.strip()
    if row := conn.execute("SELECT * FROM foods WHERE name = ?", (n,)).fetchone():
        return row, "exact"

    # alias はカンマ区切りの1カラム。件数が小さいので Python 側で突き合わせる
    for row in conn.execute("SELECT * FROM foods WHERE alias IS NOT NULL").fetchall():
        if n in [a.strip() for a in row["alias"].split(",") if a.strip()]:
            return row, "alias"

    cands = conn.execute(
        "SELECT * FROM foods WHERE name LIKE ? ORDER BY length(name)", (f"%{n}%",)
    ).fetchall()
    if cands:
        return cands[0], "partial" if len(cands) == 1 else "ambiguous"
    return None, "none"


# ---------------------------------------------------------------- 単位の換算

_VOL = {"ml": 1.0, "cc": 1.0, "l": 1000.0}
_MASS = {"g": 1.0, "kg": 1000.0}


def _norm(value: float, unit: str) -> tuple[float, str] | None:
    """量を (ml換算値, 'volume') か (g換算値, 'mass') に正規化する。"""
    u = unit.strip().lower()
    if u in _VOL:
        return value * _VOL[u], "volume"
    if u in _MASS:
        return value * _MASS[u], "mass"
    return None


def base_amount(unit: str) -> tuple[float, str] | None:
    """マスタの unit 文字列（'200ml' '100g' '個'）から基準量を取り出す。

    個数の単位（'個' '本'）なら None。
    """
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$", unit or "")
    return _norm(float(m.group(1)), m.group(2)) if m else None


def qty_from_amount(food_unit: str, amount: float, amount_unit: str) -> float | None:
    """「350ml」をマスタの基準量（'200ml'）で割って個数にする。単位が噛み合わなければ None。"""
    base = base_amount(food_unit)
    got = _norm(amount, amount_unit)
    if base is None or got is None or base[1] != got[1] or base[0] <= 0:
        return None
    return got[0] / base[0]


# ---------------------------------------------------------------- メニュー


def menu(conn: sqlite3.Connection, split: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.ord, e.id, e.code, e.name, e.muscle
           FROM routines r JOIN exercises e ON e.id = r.exercise_id
           WHERE r.split = ? ORDER BY r.ord""",
        (split,),
    ).fetchall()


def suggest_split(conn: sqlite3.Connection) -> str:
    """最も久しぶりの分割を返す。`t` を引数なしで呼んだときの既定。"""
    best, best_date = "push", None
    for split in ("push", "pull", "legs"):
        row = conn.execute(
            """SELECT MAX(s.date) AS d FROM sets s
               JOIN exercises e ON e.id = s.exercise_id WHERE e.split = ?""",
            (split,),
        ).fetchone()
        d = row["d"]
        if d is None:
            return split  # 一度もやっていない分割が最優先
        if best_date is None or d < best_date:
            best, best_date = split, d
    return best


def save_last_menu(rows: list[sqlite3.Row], split: str, path: Path | None = None) -> None:
    p = path or db.db_path().parent / LAST_MENU
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"split": split, "items": [{"ord": r["ord"], "code": r["code"]} for r in rows]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_last_menu(path: Path | None = None) -> dict | None:
    p = path or db.db_path().parent / LAST_MENU
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def exercise_by_menu_no(conn: sqlite3.Connection, no: int, path: Path | None = None) -> sqlite3.Row | None:
    last = load_last_menu(path)
    if not last:
        return None
    for item in last["items"]:
        if item["ord"] == no:
            return resolve_exercise(conn, item["code"])
    return None
