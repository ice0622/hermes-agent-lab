"""貼り付け入力。**API を呼ばない。**

`ANTHROPIC_API_KEY` が無い環境では `nl` が使えない。代わりに LLM を呼ぶ主体を
**ブラウザの Claude** に移す。

    1. `health prompt` の出力をブラウザの Claude に渡す（マスタ + 指示）
    2. 自由文で報告する
    3. Claude が返す `health batch <<'EOF' ... EOF` を端末に貼る

`nl` との違いは「LLM を誰が呼ぶか」だけで、**役割分担は同じ**。
抽出は LLM、日付の計算とマスタ解決と書き込みはここ（規則）。

## 書式

1行1コマンド。`#` で始まる行と空行は無視する。

    food 惣菜弁当 | 個 | 650 20 20 92 | dish | 総菜弁当,幕の内弁当
    ex   slp | シーテッドレッグプレス | 脚 | legs
    --date 8/25 bp 40 8,8,6 --note 呼吸を意識する
    --date 8/25 w 65.2
    --date 8/25 m 08:00 おにぎり（鮭）*2, 納豆
    m 15:00 ギリシャヨーグルト（トップバリュ バニラ）

**記録行の書式は既存の CLI とまったく同じ。** 新しい構文を覚える必要がない代わりに、
`food` / `ex` の2つだけ足してある（マスタに無い品や種目を SQL 直叩きで
入れるしかなかった穴を閉じるため）。

## 約束

* **1行が失敗しても止めない。** 通った行は記録され、失敗した行だけ最後に報告する。
  1行のミスで全部やり直しになると、貼り直すのが面倒で記録をやめる
* **貼り付け1回でできた記録は、`health undo` 1回で全部消える**
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import dates, parse, resolve, store

COMMENT = "#"
NOTE_FLAG = "--note"


@dataclass
class Result:
    echo: list[str] = field(default_factory=list)      # 実行順にそのまま出す行
    writes: list[store.Written] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def days(self) -> list[str]:
        return sorted({w.day for w in self.writes})


def apply(conn: sqlite3.Connection, text: str, today: date | None = None) -> Result:
    res = Result()
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(COMMENT):
            continue
        try:
            _one(conn, line, res, today)
        except (parse.ParseError, ValueError) as e:
            res.errors.append(f"{no}行目: {e}\n    {line}")
        except SystemExit as e:  # resolve が種目を見つけられないとき
            res.errors.append(f"{no}行目: {e}\n    {line}")

    # 貼り付け1回 = undo 1回。行ごとに消せても、どこまで戻したか分からなくなる
    if res.writes:
        store.remember_batch(res.writes)
    return res


# ---------------------------------------------------------------- 1行


def _one(conn: sqlite3.Connection, line: str, res: Result, today: date | None) -> None:
    head, _, rest = line.partition(" ")
    if head == "food":
        return _food(conn, rest, res)
    if head == "ex":
        return _exercise(conn, rest, res)
    return _record(conn, line, res, today)


def _record(conn: sqlite3.Connection, line: str, res: Result, today: date | None) -> None:
    # --note は行末までを取る（引用符が無い書式なので、途中で切ると壊れる）
    body, note = line, None
    if NOTE_FLAG in line:
        body, _, note = line.partition(NOTE_FLAG)
        note = note.strip() or None

    argv, when = dates.pop_flag(body.split(), today)
    cmd = parse.parse(" ".join(argv))
    if isinstance(cmd, parse.Menu):
        raise parse.ParseError("`t`（メニュー表示）は貼り付けでは使えません。")

    on = None if when.assumed else when.date
    if isinstance(cmd, parse.Train):
        cmd.note = note
        w = store.write_train(conn, cmd, on=on)
    elif isinstance(cmd, parse.Body):
        w = store.write_body(conn, cmd, on=on)
    else:
        w = store.write_meal(conn, cmd, on=on)

    res.writes.append(w)
    res.echo.append(f"記録 [{w.day}]: {w.summary}")
    if when.warning:
        res.echo.append(f"  ! {when.warning}")
    res.echo.extend(f"  ! {x}" for x in w.warnings)


def _fields(rest: str, n: int, usage: str) -> list[str]:
    parts = [p.strip() for p in rest.split("|")]
    if len(parts) < n or not all(parts[:n]):
        raise ValueError(f"項目が足りません。書式: {usage}")
    return parts


def _food(conn: sqlite3.Connection, rest: str, res: Result) -> None:
    parts = _fields(
        rest, 3,
        "food <名前> | <単位> | <kcal> <P> <F> <C> [| <種別>] [| <別名,別名>]",
    )
    name, unit, macros = parts[0], parts[1], parts[2].split()
    if len(macros) != 4:
        raise ValueError("栄養価は kcal P F C の4つを空白区切りで書きます。")
    kcal, protein, fat, carb = (float(x) for x in macros)
    kind = parts[3] if len(parts) > 3 and parts[3] else "item"
    alias = parts[4] if len(parts) > 4 and parts[4] else None

    if conn.execute("SELECT 1 FROM foods WHERE name = ?", (name,)).fetchone():
        res.echo.append(f"マスタ済み（変更しません）: {name}")
        return
    conn.execute(
        "INSERT INTO foods (name, alias, unit, kcal, protein, fat, carb, kind, source) "
        "VALUES (?,?,?,?,?,?,?,?, 'llm')",
        (name, alias, unit, kcal, protein, fat, carb, kind),
    )
    conn.commit()
    res.echo.append(
        f"マスタに追加: {name}  {kcal:g}kcal P{protein:g} F{fat:g} C{carb:g} /{unit}"
        "  （source='llm' — 実物のラベルで直す）"
    )


_SPLITS = {"push", "pull", "legs"}


def _exercise(conn: sqlite3.Connection, rest: str, res: Result) -> None:
    code, name, muscle, split = _fields(
        rest, 4, "ex <コード> | <名前> | <部位> | <push|pull|legs>"
    )[:4]
    if split not in _SPLITS:
        raise ValueError(f"分割は push / pull / legs のどれかです: `{split}`")
    if conn.execute("SELECT 1 FROM exercises WHERE code = ?", (code,)).fetchone():
        res.echo.append(f"マスタ済み（変更しません）: {code}")
        return
    conn.execute(
        "INSERT INTO exercises (code, name, muscle, split) VALUES (?,?,?,?)",
        (code, name, muscle, split),
    )
    conn.commit()
    res.echo.append(
        f"マスタに追加: {code} = {name}（{muscle} / {split}）"
        "  （seed_exercises.sql にも足すと health init で消えない）"
    )


# ---------------------------------------------------------------- 貼り付け用プロンプト


HOWTO = """あなたは健康記録を `health` CLI のコマンドに変換する。会話も助言もしない。
ユーザーが食べたもの・やった筋トレ・体重を自由文で報告する。それを下の書式に直す。

## 出力の形

**端末にそのまま貼れる1ブロックだけを返す。** 説明は前後に1〜2行まで。

```
health batch <<'EOF'
--date 8/25 bp 40 8,8,6
--date 8/25 w 65.2
--date 8/25 m 08:00 おにぎり（鮭）*2, 納豆
EOF
```

## 書式

| 種類 | 書き方 |
|---|---|
| 筋トレ（同一重量） | `bp 40 8,8,6` |
| 筋トレ（セット別重量） | `bp 40x8,37.5x8,35x6` |
| 自重種目 | `pu 5,4,3` |
| 一言メモ | 行末に `--note 呼吸を意識する`（行末までがメモ） |
| 体重 | `w 65.2` / `w 65.2 15.3`（体脂肪率つき） |
| 食事 | `m 08:00 おにぎり（鮭）*2, 納豆` |
| 日付 | 行頭に `--date 8/25`（`昨日` `3日前` `先週の火曜` も可） |
| 食品をマスタに追加 | `food <名前> \\| <単位> \\| <kcal> <P> <F> <C> \\| <種別> \\| <別名,別名>` |
| 種目をマスタに追加 | `ex <コード> \\| <名前> \\| <部位> \\| <push\\|pull\\|legs>` |

食品の種別: `dish`（一皿で成立する料理） `staple`（主食） `side`（副菜・単品）
`drink` `snack` `item`（素材）

## 規則

1. **日付が書かれていなければ `--date` を付けない。** 今日として記録される。
2. 1つの報告に複数の日が混ざったら、行ごとに `--date` を分けて書く。
3. **食品名は下のマスタの名前をそのまま使う。** 1文字も変えない。
   別名で報告されていてもマスタの名前に直す。
4. **マスタに無い食品は `food` 行を先に置いてから記録する。**
   栄養価は日本の一般的な商品の値で推定する。控えめにせず現実的な値を出す。
   `--date` は `food` 行には付けない。
5. **種目は下のマスタのコードを使う。** マスタに無い種目は `ex` 行を先に置く。
   分割（push/pull/legs）と部位は自分で判断して埋める。
6. 数量はマスタの単位を1とした個数。単位が `200ml` で報告が `350ml` なら `*1.75`。
   単位が `100g` で報告が `200g` なら `*2`。
7. 時刻は分かれば書く。分からなければ朝 `08:00` 昼 `12:00` 夕 `19:00` 間食 `15:00`。
8. **量や種類が判別できない点は、ブロックの後に `?` 付きで1行ずつ挙げる。**
   勝手に決めて黙らない。
9. 質問・感想・相談は無視する。記録に該当するものだけ変換する。
"""


def prompt(conn: sqlite3.Connection) -> str:
    """ブラウザの Claude に渡す文字列。マスタが増えたら貼り直す。"""
    foods = conn.execute(
        "SELECT name, alias, unit, kcal, protein, fat, carb, kind FROM foods ORDER BY kind, id"
    ).fetchall()
    exercises = conn.execute(
        "SELECT code, name, muscle, split FROM exercises ORDER BY split, id"
    ).fetchall()

    food_lines = "\n".join(
        f"- {r['name']} | {r['unit']} | {r['kcal']:g}kcal P{r['protein']:g} "
        f"F{r['fat']:g} C{r['carb']:g} | {r['kind']}"
        + (f" | 別名: {r['alias']}" if r["alias"] else "")
        for r in foods
    )
    ex_lines = "\n".join(
        f"- {r['code']} = {r['name']}（{r['muscle']} / {r['split']}）" for r in exercises
    )
    return (
        f"{HOWTO}\n"
        f"# foods マスタ（{len(foods)}品）\n\n{food_lines}\n\n"
        f"# exercises マスタ（{len(exercises)}種目）\n\n{ex_lines}\n"
    )
