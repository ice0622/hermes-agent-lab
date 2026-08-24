"""パース結果を DB に書き込む層。

直前の書き込みを `last_insert.json` に残しており、`health undo` で取り消せる。
打ち間違いを消せないと、記録が汚れるのが嫌で入力自体をやめてしまう。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db, parse, resolve

LAST_INSERT = "last_insert.json"


@dataclass
class Written:
    table: str
    ids: list[int]
    summary: str
    warnings: list[str]


def _remember(w: Written, path: Path | None = None) -> None:
    p = path or db.db_path().parent / LAST_INSERT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"table": w.table, "ids": w.ids, "summary": w.summary}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- 筋トレ


def write_train(conn: sqlite3.Connection, cmd: parse.Train, *, state_dir: Path | None = None) -> Written:
    if cmd.by_menu_no is not None:
        ex = resolve.exercise_by_menu_no(
            conn, cmd.by_menu_no, (state_dir / resolve.LAST_MENU) if state_dir else None
        )
        if ex is None:
            raise SystemExit(
                f"メニュー番号 {cmd.by_menu_no} を解決できません。\n"
                "  先に `health t push` などでメニューを表示してください。"
            )
    else:
        ex = resolve.resolve_exercise(conn, cmd.exercise)
        if ex is None:
            hints = resolve.suggest_exercises(conn, cmd.exercise)
            msg = f"種目が見つかりません: `{cmd.exercise}`"
            if hints:
                msg += "\n  候補: " + "、".join(f"{h['code']}({h['name']})" for h in hints)
            raise SystemExit(msg)

    at, day = db.now_str(), db.today_str()
    ids = []
    for i, (weight, reps) in enumerate(cmd.sets, start=1):
        cur = conn.execute(
            "INSERT INTO sets (trained_at, date, exercise_id, weight, reps, set_no) "
            "VALUES (?,?,?,?,?,?)",
            (at, day, ex["id"], weight, reps, i),
        )
        ids.append(cur.lastrowid)
    conn.commit()

    body = ", ".join(
        (f"{w:g}kg×{r}" if w else f"自重×{r}") for w, r in cmd.sets
    )
    w = Written("sets", ids, f"{ex['name']}  {body}  （{len(ids)}セット）", [])
    _remember(w, (state_dir / LAST_INSERT) if state_dir else None)
    return w


# ---------------------------------------------------------------- 体重


def write_body(conn: sqlite3.Connection, cmd: parse.Body, *, state_dir: Path | None = None) -> Written:
    at, day = db.now_str(), db.today_str()
    prev = conn.execute("SELECT weight FROM body WHERE date = ?", (day,)).fetchone()
    conn.execute(
        """INSERT INTO body (measured_at, date, weight, body_fat, source)
           VALUES (?,?,?,?, 'manual')
           ON CONFLICT(date) DO UPDATE SET
             measured_at = excluded.measured_at,
             weight      = excluded.weight,
             body_fat    = COALESCE(excluded.body_fat, body.body_fat)""",
        (at, day, cmd.weight, cmd.body_fat),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM body WHERE date = ?", (day,)).fetchone()

    s = f"体重 {cmd.weight}kg"
    if cmd.body_fat is not None:
        s += f" / 体脂肪 {cmd.body_fat}%"
    warns = []
    if prev is not None:
        warns.append(f"同じ日の記録を上書きしました（{prev['weight']}kg → {cmd.weight}kg）")
    w = Written("body", [row["id"]], s, warns)
    _remember(w, (state_dir / LAST_INSERT) if state_dir else None)
    return w


# ---------------------------------------------------------------- 食事


def write_meal(conn: sqlite3.Connection, cmd: parse.Meal, *, state_dir: Path | None = None) -> Written:
    day = db.today_str()
    at = f"{day} {cmd.at}" if cmd.at else db.now_str()

    ids, parts, warns = [], [], []
    for item in cmd.items:
        food, how = resolve.resolve_food(conn, item.name)
        if how == "partial":
            warns.append(f"`{item.name}` を「{food['name']}」として記録しました")
        elif how == "ambiguous":
            others = conn.execute(
                "SELECT name FROM foods WHERE name LIKE ? AND id != ? ORDER BY length(name)",
                (f"%{item.name}%", food["id"]),
            ).fetchall()
            warns.append(
                f"`{item.name}` は複数該当したので「{food['name']}」にしました"
                f"（他: {'、'.join(r['name'] for r in others[:3])}）"
            )
        if food is None:
            # マスタに無くても記録は止めない。栄養価 0 の「未知」として入れる
            cur = conn.execute(
                "INSERT INTO meals (eaten_at, date, food_id, food_name, qty, kcal, protein, fat, carb) "
                "VALUES (?,?,NULL,?,?,0,0,0,0)",
                (at, day, item.name, item.qty),
            )
            ids.append(cur.lastrowid)
            parts.append(f"{item.name}×{item.qty:g}（未知）")
            warns.append(f"`{item.name}` はマスタに無いので栄養価 0 で記録しました")
            continue
        q = item.qty
        cur = conn.execute(
            "INSERT INTO meals (eaten_at, date, food_id, food_name, qty, kcal, protein, fat, carb) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                at, day, food["id"], food["name"], q,
                food["kcal"] * q, food["protein"] * q, food["fat"] * q, food["carb"] * q,
            ),
        )
        ids.append(cur.lastrowid)
        parts.append(f"{food['name']}×{q:g}")
    conn.commit()

    tot = conn.execute(
        "SELECT SUM(kcal) k, SUM(protein) p FROM meals WHERE id IN (%s)"
        % ",".join("?" * len(ids)),
        ids,
    ).fetchone()
    summary = (
        "  ".join(parts) + f"  →  {tot['k']:.0f}kcal / P {tot['p']:.0f}g"
    )
    w = Written("meals", ids, summary, warns)
    _remember(w, (state_dir / LAST_INSERT) if state_dir else None)
    return w


# ---------------------------------------------------------------- 取り消し


def undo(conn: sqlite3.Connection, *, state_dir: Path | None = None) -> str:
    p = (state_dir / LAST_INSERT) if state_dir else db.db_path().parent / LAST_INSERT
    if not p.exists():
        raise SystemExit("取り消せる記録がありません。")
    data = json.loads(p.read_text(encoding="utf-8"))
    table, ids = data["table"], data["ids"]
    if table not in {"sets", "body", "meals"}:
        raise SystemExit(f"未知のテーブルです: {table}")
    conn.execute(
        f"DELETE FROM {table} WHERE id IN (%s)" % ",".join("?" * len(ids)), ids
    )
    conn.commit()
    p.unlink()
    return data["summary"]
