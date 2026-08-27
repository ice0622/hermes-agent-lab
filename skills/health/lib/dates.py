"""日付表現の解決。**LLM を使わない。**

自由入力から抜き出された日付の表記（`8/25` `昨日` `先週の火曜`）を、
決定的な規則で `date` に落とす。

なぜモデルに日付計算をさせないか:

  * 「先週の火曜」は週の起点の解釈でずれる。同じ入力が実行日によって
    違う結果になると、記録そのものが信用できなくなる
  * 未来日付を弾く判断（`8/25` を来年と読むか去年と読むか）は規則で決めたい

**モデルの仕事は「日付の表記を見つけてそのまま返す」ところまで。**
表記が無ければ `None` を返させ、その場合は「今日」として扱う。
これが「日にちを書かなければ今日のこと」という挙動の実装。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = "月火水木金土日"

# 未来に解決された M/D は去年と読む。1年より先は誤入力として弾く
_FUTURE_SLACK_DAYS = 1


@dataclass
class Resolved:
    """解決結果。`assumed` が True なら日付の指定が無く今日を当てた。"""

    date: date
    raw: str | None = None
    assumed: bool = False
    warning: str | None = None

    @property
    def iso(self) -> str:
        return self.date.isoformat()

    def label(self) -> str:
        """ユーザーに返す1行。省略や補正を黙って通さないための文言。"""
        md = f"{self.date.month}/{self.date.day}（{WEEKDAYS[self.date.weekday()]}）"
        if self.assumed:
            return f"日付の指定が無いので今日 {md} として記録"
        if self.warning:
            return f"{self.raw} → {md}  ※{self.warning}"
        return f"{self.raw} → {md}"


class DateError(ValueError):
    """日付として解釈できない。記録は止めず、今日として扱ってこれを警告に回す。"""


# ---------------------------------------------------------------- 表記の正規化

_ZEN = str.maketrans("０１２３４５６７８９／－", "0123456789/-")

_RELATIVE = {
    "今日": 0, "きょう": 0, "本日": 0, "today": 0,
    "昨日": -1, "きのう": -1, "前日": -1, "昨夜": -1, "昨晩": -1, "ゆうべ": -1,
    "おととい": -2, "一昨日": -2, "おとつい": -2, "いっさくじつ": -2,
}

_ISO_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_MD_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})$")
_MD_KANJI_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日?$")
_D_ONLY_RE = re.compile(r"^(\d{1,2})日$")
_N_AGO_RE = re.compile(r"^(\d{1,2})日前$")
_WEEKDAY_RE = re.compile(r"^(先週|今週|先|この)?の?([月火水木金土日])曜日?$")


def _clean(raw: str) -> str:
    s = raw.translate(_ZEN).strip()
    # 「8/25の朝」「8/25は」のような後置の助詞を落とす
    s = re.sub(r"(の(朝|昼|夜|晩|夕方|間食)|は|に|、|。)+$", "", s)
    return s.strip()


# ---------------------------------------------------------------- 本体


def resolve(raw: str | None, today: date | None = None) -> Resolved:
    """日付表記を解決する。**解釈できなくても例外を投げず、今日を返して warning に回す。**

    記録をエラーで止めない方針（README「設計上の約束」）に合わせている。
    日付が読めないことは、記録を捨てる理由にならない。
    """
    today = today or date.today()
    if raw is None or not str(raw).strip():
        return Resolved(date=today, raw=None, assumed=True)

    s = _clean(str(raw))
    if not s:
        return Resolved(date=today, raw=None, assumed=True)

    try:
        d, warning = _parse(s, today)
    except DateError as e:
        return Resolved(date=today, raw=str(raw), assumed=True, warning=str(e))
    return Resolved(date=d, raw=str(raw), warning=warning)


def _parse(s: str, today: date) -> tuple[date, str | None]:
    if (delta := _RELATIVE.get(s)) is not None:
        return today + timedelta(days=delta), None

    if m := _N_AGO_RE.match(s):
        return today - timedelta(days=int(m.group(1))), None

    if m := _ISO_RE.match(s):
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), None

    for rx in (_MD_RE, _MD_KANJI_RE):
        if m := rx.match(s):
            return _from_md(int(m.group(1)), int(m.group(2)), today)

    if m := _D_ONLY_RE.match(s):
        return _from_md(today.month, int(m.group(1)), today)

    if m := _WEEKDAY_RE.match(s):
        return _from_weekday(m.group(1), WEEKDAYS.index(m.group(2)), today)

    raise DateError(f"日付として読めません: `{s}`")


def _mk(y: int, mo: int, d: int) -> date:
    try:
        return date(y, mo, d)
    except ValueError:
        raise DateError(f"存在しない日付です: {y}-{mo:02d}-{d:02d}") from None


def _from_md(mo: int, d: int, today: date) -> tuple[date, str | None]:
    """年の無い `8/25`。**未来になったら去年と読む。**

    記録は過去に対して行うもので、未来の記録は入らない。
    1月に「12/30」と書けば去年の12/30を指す。
    """
    cand = _mk(today.year, mo, d)
    if (cand - today).days > _FUTURE_SLACK_DAYS:
        cand = _mk(today.year - 1, mo, d)
        return cand, f"未来の日付になるので {cand.year} 年と解釈しました"
    return cand, None


def _from_weekday(qualifier: str | None, target: int, today: date) -> tuple[date, str | None]:
    """`火曜` は直近の過去の火曜（今日が火曜なら今日）。`先週の火曜` はその7日前。"""
    back = (today.weekday() - target) % 7
    d = today - timedelta(days=back)
    if qualifier in {"先週", "先"}:
        d -= timedelta(days=7)
    return d, None


# ---------------------------------------------------------------- 引数からの取り出し


_FLAG_RE = re.compile(r"^--date(?:=(.*))?$")


def pop_flag(argv: list[str], today: date | None = None) -> tuple[list[str], Resolved]:
    """`--date 8/25` / `--date=8/25` を argv から抜き、残りと解決結果を返す。

    定型入力（`health w 65.2 --date 8/25`）と自由入力の両方で同じ解決規則を使う。
    """
    rest: list[str] = []
    raw: str | None = None
    i = 0
    while i < len(argv):
        if m := _FLAG_RE.match(argv[i]):
            if m.group(1) is not None:
                raw = m.group(1)
            elif i + 1 < len(argv):
                raw = argv[i + 1]
                i += 1
            else:
                raise SystemExit("--date のあとに日付がありません。例: --date 8/25")
            i += 1
            continue
        rest.append(argv[i])
        i += 1
    return rest, resolve(raw, today)
