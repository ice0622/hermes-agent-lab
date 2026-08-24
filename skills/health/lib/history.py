"""手書き記録の Markdown（docs/training-history.md）を DB に取り込む。

初日から1年分のグラフが出る状態にするためのもの。空のダッシュボードは続かない。
データは既に構造化されているのでコストはゼロ。

**冪等**。取り込む日付範囲を先に消してから入れるので、何度流しても重複しない。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# 記録中の表記 → exercises.code
ALIASES: dict[str, str] = {
    # Push
    "ベンチプレス": "bp", "ベンチ": "bp", "スミスベンチ": "smb",
    "ダンベルプレス": "dbp", "ダンベルショルダー": "sp",
    "インクラインダンベルプレス": "idp", "インクラインプレス": "idp",
    "インクラインシーテッドプレス": "isp", "ペックフライ": "pf",
    "ショルダープレス": "sp", "ショルダープレス（ダンベル）": "sp",
    "ショルダープレス（マシン）": "msp", "ショルダー": "msp",
    "サイドレイズ": "sr", "ケーブルサイドレイズ": "csr",
    "ケーブルプレスダウン": "cpd", "ケーブルアームダウン": "cad",
    # Pull
    "ラットプルダウン": "lpd", "ワイドプルダウン": "wpd", "ケーブルプルダウン": "cpl",
    "ローイング": "row", "シーテッドロー": "row",
    "パラレルローイング": "prow", "パラレルロー": "prow",
    "アイソラテラルロー": "iso", "シーテッドISOロー": "iso",
    "ダンベルロー": "dbr", "ダンベルワンハンドロー": "dbr",
    "バーベルロー": "bbr", "オーバーグリップロー": "ogr",
    "ロー（ショルダー13）": "shr", "ショルダーロー": "shr", "ロー": "row",
    "懸垂": "pu", "けんすい（肩上げ）": "pu", "けんすい": "pu",
    "フェイスプル": "fp",
    "ダンベルカール": "dbc", "インクラインダンベルカール": "idc",
    "ハンマーカール": "hc", "インクラインハンマーカール": "hc",
    "インクライン・ハンマーカール": "hc",
    "バーベルカール": "bbc", "EZバーカール": "ezc", "ケーブルカール": "cc",
    # Legs
    "スクワット": "sq", "デッドリフト": "dl",
    "レッグプレス": "lpr", "シーテッドレッグプレス": "slp",
    "レッグエクステンション": "le",
    "レッグカール": "lc", "シーテッドレッグカール": "slc",
    "シーテッドカーフレイズ": "cr", "ヒップアブダクター": "ha",
    "ヒップ・アブダクター": "ha",
}

# 意図的に取り込まない（マシン名が判読できず exercises に未登録）
SKIP = {"LATERAL LOW", "シーテッド"}

_YEAR_RE = re.compile(r"^##\s*(\d{4})年")
_DATE_RE = re.compile(r"^###\s*(\d{1,2})/(\d{1,2})")
_WEIGHT_RE = re.compile(r"体重\s*([\d.]+)\s*kg")
_SET_RE = re.compile(
    r"(?P<w1>\d+(?:\.\d+)?)\s*(?:\+\s*(?P<w2>\d+(?:\.\d+)?))?\s*(?:kg)?\s*[×xX]\s*"
    r"(?:左右)?(?P<r>\d+)(?:\s*→\s*(?P<r2>\d+))?"
)
_BODYWEIGHT_RE = re.compile(r"(\d+)\s*回")
_RULE_RE = re.compile(r"^-{2,}$")
_SIDE_RE = re.compile(r"[（(]?\s*(?:左右|左|右)\s*[)）]?$")
_NSETS_RE = re.compile(r"[×xX]\s*(\d+)\s*セット")
_NOISE_RE = re.compile(r"\(\?\)|«\?»|※.*$|※.*|\*\*")


@dataclass
class Session:
    date: str
    sets: list[tuple[str, float, int]] = field(default_factory=list)  # (code, weight, reps)
    weight: float | None = None


@dataclass
class ImportResult:
    sessions: int = 0
    set_rows: int = 0
    body_rows: int = 0
    skipped: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    return _NOISE_RE.sub("", s).strip()


def _lookup(name: str) -> str | None:
    n = name.strip().strip("*").strip()
    # 「ダンベルロー 左」「ローイング（左右）」の左右表記を落とす
    n = _SIDE_RE.sub("", n).strip()
    if n in ALIASES:
        return ALIASES[n]
    # 「サイドレイズ（座）」のような括弧付きを落として再試行
    base = re.sub(r"[（(].*?[)）]", "", n).strip()
    return ALIASES.get(base)


def _parse_sets(text: str) -> list[tuple[float, int]]:
    """1種目分のセット表記を [(重量, レップ), ...] にする。"""
    out: list[tuple[float, int]] = []
    for chunk in re.split(r"[/・]", text):
        chunk = _clean(chunk)
        if not chunk:
            continue
        m = _SET_RE.search(chunk)
        if m is None and (bw := _BODYWEIGHT_RE.search(chunk)):
            # 自重種目（懸垂など）。重量表記が無く「N回」だけのもの
            out.append((0.0, int(bw.group(1))))
            continue
        if not m:
            continue
        w = float(m.group("w1")) + (float(m.group("w2")) if m.group("w2") else 0.0)
        r = int(m.group("r2") or m.group("r"))
        if not (0 <= w <= 500 and 1 <= r <= 200):
            continue
        n = int(m2.group(1)) if (m2 := _NSETS_RE.search(chunk)) else 1
        out.extend([(w, r)] * n)
    return out


def parse_markdown(text: str) -> tuple[list[Session], ImportResult]:
    res = ImportResult()
    sessions: list[Session] = []
    year, cur, cur_ex = None, None, None

    for raw in text.splitlines():
        line = raw.rstrip()

        if m := _YEAR_RE.match(line):
            year = int(m.group(1))
            continue
        if m := _DATE_RE.match(line):
            if year is None:
                continue
            cur = Session(date=f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
            sessions.append(cur)
            cur_ex = None
            continue
        if cur is None:
            continue

        indented = raw.startswith(("  -", "\t-", "   -"))
        if not (stripped := line.lstrip()).startswith("-"):
            continue
        if _RULE_RE.match(stripped):
            continue  # 水平線（---）
        item = stripped[1:].strip()

        if m := _WEIGHT_RE.search(item):
            cur.weight = float(m.group(1))
            continue
        if item.startswith(("メモ", "**メモ", "有酸素", "**有酸素")):
            continue

        if indented and cur_ex:
            cur.sets.extend((cur_ex, w, r) for w, r in _parse_sets(item))
            continue

        # 「種目名 セット表記」を分割する。最初の数字の手前までが種目名
        m = re.match(r"^(?P<name>[^\d]+?)\s*(?P<sets>[\d（(].*)$", item)
        name = (m.group("name") if m else item).strip().strip("*").strip()
        sets_text = m.group("sets") if m else ""

        # 対応表を先に引く。SKIP は「引けなかったもの」の中の既知の未登録種目だけに使う
        # （部分一致で判定すると「シーテッドレッグプレス」まで落ちる）
        code = _lookup(name)
        if code is None:
            bucket = res.skipped if name.strip().strip("*") in SKIP else res.unmapped
            bucket.append(f"{cur.date} {name}")
            cur_ex = None
            continue

        cur_ex = code
        cur.sets.extend((code, w, r) for w, r in _parse_sets(sets_text))

    sessions = [s for s in sessions if s.sets or s.weight is not None]
    res.sessions = len(sessions)
    res.set_rows = sum(len(s.sets) for s in sessions)
    res.body_rows = sum(1 for s in sessions if s.weight is not None)
    return sessions, res


def import_into(conn: sqlite3.Connection, path: Path) -> ImportResult:
    sessions, res = parse_markdown(path.read_text(encoding="utf-8"))
    if not sessions:
        return res

    codes = {c for s in sessions for c, _, _ in s.sets}
    ex_id = {
        r["code"]: r["id"]
        for r in conn.execute(
            "SELECT id, code FROM exercises WHERE code IN (%s)" % ",".join("?" * len(codes)),
            tuple(codes),
        )
    }
    missing = codes - ex_id.keys()
    if missing:
        raise SystemExit(
            "exercises に無い code があります: " + ", ".join(sorted(missing))
            + "\n先に `health init` でシードを投入してください。"
        )

    lo = min(s.date for s in sessions)
    hi = max(s.date for s in sessions)
    # 冪等性: 取り込む範囲を消してから入れる
    conn.execute("DELETE FROM sets WHERE date BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM body WHERE date BETWEEN ? AND ? AND source = 'manual'", (lo, hi))

    for s in sessions:
        by_ex: dict[str, int] = {}
        for code, w, r in s.sets:
            by_ex[code] = by_ex.get(code, 0) + 1
            conn.execute(
                "INSERT INTO sets (trained_at, date, exercise_id, weight, reps, set_no) "
                "VALUES (?,?,?,?,?,?)",
                (f"{s.date} 00:00", s.date, ex_id[code], w, r, by_ex[code]),
            )
        if s.weight is not None:
            conn.execute(
                "INSERT INTO body (measured_at, date, weight, source) VALUES (?,?,?,'manual') "
                "ON CONFLICT(date) DO UPDATE SET weight = excluded.weight",
                (f"{s.date} 00:00", s.date, s.weight),
            )
    conn.commit()
    return res
