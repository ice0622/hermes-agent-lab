"""ダッシュボード生成（T07）。**LLM を使わない。**

`dashboard.html` を1ファイル書き出す。常駐プロセスなし、JS なし、CDN なし。
グラフは SVG を直接埋め込む。ブラウザで開くだけで見える。

配色は仕様どおり白黒モノクロ。単一系列のグラフしか使わないので
カテゴリカル配色の問題は起きない。2系列になる体重グラフだけ、
色ではなく**マークの形**（点と線）で区別し、凡例を付ける。

守っていること（dataviz のアンチパターン対策）:
  * 二軸グラフを作らない。尺度が違うものは別のグラフにする
  * 罫線は実線のヘアライン。破線は使わない（破線は「閾値」に見える）
  * 全ての点に数値を置かない。端点と極値だけ直接ラベルする
  * 1本だけの棒グラフを作らない。数字1つなら stat タイルにする
  * 隣接する棒の間に 2px の余白を空ける（枠線で区切らない）
  * 表ビューを必ず併置する（グラフを読めなくても値に到達できる）
  * x軸のラベルが入る高さを確保する
"""

from __future__ import annotations

import html
import sqlite3
from datetime import date, timedelta
from pathlib import Path

MAIN_LIFTS = [("bp", "ベンチプレス"), ("sq", "スクワット"),
              ("dl", "デッドリフト"), ("lpd", "ラットプルダウン")]


# ---------------------------------------------------------------- SVG 部品


def _sv(v: float) -> str:
    """座標を短く。SVG が無駄に長くならないように。"""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _scale(vals: list[float], lo_pad: float = 0.05) -> tuple[float, float]:
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return lo - 1, hi + 1
    m = (hi - lo) * lo_pad
    return lo - m, hi + m


def line_chart(
    pts: list[tuple[str, float]],
    *,
    w: int = 820,
    h: int = 220,
    unit: str = "",
    avg: list[tuple[str, float]] | None = None,
) -> str:
    """折れ線。pts は (ラベル, 値) の時系列。avg があれば平均線を重ねる。"""
    if not pts:
        return '<p class="empty">データがありません</p>'
    pad_l, pad_r, pad_t, pad_b = 52, 16, 16, 30  # pad_b は x 軸ラベルの帯
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    ys = [v for _, v in pts] + ([v for _, v in avg] if avg else [])
    lo, hi = _scale(ys)

    def X(i: int) -> float:
        return pad_l + (iw * i / max(1, len(pts) - 1))

    def Y(v: float) -> float:
        return pad_t + ih - (v - lo) / (hi - lo) * ih

    out = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart">']

    # 罫線と y 軸目盛（実線のヘアライン）
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        y = Y(v)
        out.append(f'<line class="grid" x1="{pad_l}" y1="{_sv(y)}" x2="{w - pad_r}" y2="{_sv(y)}"/>')
        out.append(f'<text class="tick" x="{pad_l - 8}" y="{_sv(y + 3.5)}" text-anchor="end">{v:.1f}</text>')

    # 平均線（体重の週平均など）。太めの実線
    if avg:
        d = " ".join(f"{'M' if i == 0 else 'L'}{_sv(X(i))} {_sv(Y(v))}"
                     for i, (_, v) in enumerate(avg))
        out.append(f'<path class="avg" d="{d}"/>')

    # 日次の点。線は細く、点は 8px 以上
    d = " ".join(f"{'M' if i == 0 else 'L'}{_sv(X(i))} {_sv(Y(v))}" for i, (_, v) in enumerate(pts))
    out.append(f'<path class="line" d="{d}"/>')
    for i, (lab, v) in enumerate(pts):
        out.append(
            f'<circle class="dot" cx="{_sv(X(i))}" cy="{_sv(Y(v))}" r="4">'
            f"<title>{html.escape(lab)}  {v:g}{unit}</title></circle>"
        )
        # 当たり判定を 24px 以上に広げる（点そのものを狙わせない）
        out.append(
            f'<rect class="hit" x="{_sv(X(i) - 12)}" y="{pad_t}" width="24" height="{ih}">'
            f"<title>{html.escape(lab)}  {v:g}{unit}</title></rect>"
        )

    # 直接ラベルは端点と極値だけ
    marks = {0, len(pts) - 1,
             max(range(len(pts)), key=lambda i: pts[i][1]),
             min(range(len(pts)), key=lambda i: pts[i][1])}
    for i in sorted(marks):
        lab, v = pts[i]
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        dx = 6 if i == 0 else (-6 if i == len(pts) - 1 else 0)
        out.append(
            f'<text class="dlabel" x="{_sv(X(i) + dx)}" y="{_sv(Y(v) - 9)}" '
            f'text-anchor="{anchor}">{v:g}</text>'
        )

    # x 軸: 最初 / 中間 / 最後だけ
    for i in {0, len(pts) // 2, len(pts) - 1}:
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        out.append(
            f'<text class="tick" x="{_sv(X(i))}" y="{h - 10}" '
            f'text-anchor="{anchor}">{html.escape(pts[i][0])}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def bar_chart(pts: list[tuple[str, float]], *, w: int = 820, h: int = 200, unit: str = "") -> str:
    """棒グラフ。全ての棒を同じ色にする（長さが既に量を表しているので色は使わない）。"""
    if not pts:
        return '<p class="empty">データがありません</p>'
    pad_l, pad_r, pad_t, pad_b = 40, 16, 20, 30
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    hi = max(v for _, v in pts) or 1
    step = iw / len(pts)
    bw = max(4.0, step - 2)  # 隣接する棒の間に 2px の余白

    out = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart">']
    for k in range(3):
        v = hi * (k + 1) / 3
        y = pad_t + ih - v / hi * ih
        out.append(f'<line class="grid" x1="{pad_l}" y1="{_sv(y)}" x2="{w - pad_r}" y2="{_sv(y)}"/>')
        out.append(f'<text class="tick" x="{pad_l - 8}" y="{_sv(y + 3.5)}" text-anchor="end">{v:.0f}</text>')
    for i, (lab, v) in enumerate(pts):
        bh = v / hi * ih
        x = pad_l + step * i + (step - bw) / 2
        y = pad_t + ih - bh
        out.append(
            f'<rect class="bar" x="{_sv(x)}" y="{_sv(y)}" width="{_sv(bw)}" '
            f'height="{_sv(max(bh, 0.5))}" rx="2">'
            f"<title>{html.escape(lab)}  {v:g}{unit}</title></rect>"
        )
        if len(pts) <= 14:
            out.append(
                f'<text class="tick" x="{_sv(x + bw / 2)}" y="{h - 10}" '
                f'text-anchor="middle">{html.escape(lab)}</text>'
            )
    out.append("</svg>")
    return "".join(out)


def progress(label: str, got: float, target: float, unit: str) -> str:
    """今日の摂取 vs 目標。1本ずつの進捗バー（1本だけの棒グラフにはしない）。"""
    pct = 0 if target <= 0 else min(got / target, 1.4)
    over = got > target
    return (
        f'<div class="prow"><div class="plabel">{html.escape(label)}</div>'
        f'<div class="ptrack"><div class="pfill{" over" if over else ""}" '
        f'style="width:{min(pct, 1.0) * 100:.1f}%"></div>'
        f'<div class="ptarget"></div></div>'
        f'<div class="pval"><b>{got:.0f}</b><span class="pmuted"> / {target:.0f}{unit}</span></div>'
        f'<div class="prest">{"超過 " if over else "残り "}'
        f'{abs(target - got):.0f}{unit}</div></div>'
    )


# ---------------------------------------------------------------- データ取得


def _q(conn: sqlite3.Connection, sql: str, *a):
    return conn.execute(sql, a).fetchall()


def collect(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()
    t = conn.execute("SELECT * FROM v_target").fetchone()
    got = conn.execute("SELECT * FROM v_today").fetchone()

    body = _q(conn, "SELECT date, weight FROM body ORDER BY date")
    weekly = _q(conn, """SELECT MIN(date) d, ROUND(AVG(weight),2) w FROM body
                         GROUP BY strftime('%Y-%W', date) ORDER BY d""")
    months = _q(conn, """SELECT substr(date,1,7) m, COUNT(DISTINCT date) n
                         FROM sets GROUP BY m ORDER BY m""")
    lifts = {}
    for code, name in MAIN_LIFTS:
        lifts[name] = _q(conn, """SELECT s.date d, MAX(ROUND(s.weight*(1+s.reps/30.0),1)) rm
              FROM sets s JOIN exercises e ON e.id=s.exercise_id
              WHERE e.code=? AND s.weight>0 GROUP BY s.date ORDER BY s.date""", code)
    sessions = _q(conn, """SELECT s.date d, GROUP_CONCAT(x, ' / ') detail, SUM(vol) vol FROM (
              SELECT s.date, e.name || ' ' ||
                     GROUP_CONCAT(CAST(s.weight AS TEXT) || 'x' || s.reps, ',') AS x,
                     SUM(s.weight*s.reps) vol
              FROM sets s JOIN exercises e ON e.id=s.exercise_id
              GROUP BY s.date, e.id ORDER BY s.date DESC, e.id) s
              GROUP BY s.date ORDER BY s.date DESC LIMIT 12""")
    protein_src = _q(conn, """SELECT food_name, ROUND(SUM(protein),1) p, COUNT(*) n
              FROM meals WHERE date > ? GROUP BY food_name
              ORDER BY p DESC LIMIT 8""", (today - timedelta(days=30)).isoformat())
    month_avg = _q(conn, """SELECT substr(date,1,7) m, ROUND(AVG(weight),2) w, COUNT(*) n
              FROM body GROUP BY m ORDER BY m DESC""")

    streak = 0
    d = today
    have = {r["d"] for r in _q(conn, """SELECT DISTINCT date d FROM (
              SELECT date FROM meals UNION SELECT date FROM sets UNION SELECT date FROM body)""")}
    while d.isoformat() in have:
        streak += 1
        d -= timedelta(days=1)

    return dict(today=today, target=t, got=got, body=body, weekly=weekly, months=months,
                lifts=lifts, sessions=sessions, protein_src=protein_src,
                month_avg=month_avg, streak=streak,
                train_this_month=next((r["n"] for r in months
                                       if r["m"] == today.strftime("%Y-%m")), 0))


# ---------------------------------------------------------------- HTML

CSS = """
:root{
  --surface:#ffffff; --card:#ffffff; --ink:#111111; --ink2:#5a5a5a; --muted:#8f8f8f;
  --grid:#e8e8e8; --mark:#1a1a1a; --mark2:#bcbcbc; --line:#e2e2e2; --fill:#2b2b2b;
}
@media (prefers-color-scheme:dark){
  /* 自動反転ではなく、暗い面に対して選び直した段階 */
  :root{ --surface:#0e0e0e; --card:#161616; --ink:#f2f2f2; --ink2:#b4b4b4; --muted:#7e7e7e;
         --grid:#2a2a2a; --mark:#ededed; --mark2:#5c5c5c; --line:#2a2a2a; --fill:#e4e4e4; }
}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--surface);color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:19px;font-weight:600;letter-spacing:.02em;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin:0 0 28px}
h2{font-size:13px;font-weight:600;letter-spacing:.08em;color:var(--ink2);
  margin:40px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.tile .k{font-size:11px;letter-spacing:.08em;color:var(--muted);margin-bottom:6px}
/* hero と stat の数値は等幅にしない（大きい字だと間延びして見える） */
.tile .v{font-size:30px;font-weight:600;line-height:1.1;letter-spacing:-.01em}
.tile .v small{font-size:14px;font-weight:500;color:var(--ink2);margin-left:3px}
.tile .n{font-size:12px;color:var(--muted);margin-top:4px}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}
.line{fill:none;stroke:var(--mark);stroke-width:1.5;stroke-linejoin:round}
.avg{fill:none;stroke:var(--mark2);stroke-width:3;stroke-linejoin:round;stroke-linecap:round}
.dot{fill:var(--mark)}
.hit{fill:transparent}
.bar{fill:var(--fill)}
.tick{fill:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums}
.dlabel{fill:var(--ink);font-size:11px;font-weight:600}
.legend{display:flex;gap:18px;margin:2px 0 10px;font-size:12px;color:var(--ink2)}
.legend i{display:inline-block;vertical-align:middle;margin-right:6px}
.legend .sw-dot{width:8px;height:8px;border-radius:50%;background:var(--mark)}
.legend .sw-line{width:18px;height:3px;border-radius:2px;background:var(--mark2)}
.prow{display:grid;grid-template-columns:52px 1fr 122px 96px;gap:12px;align-items:center;
  padding:9px 0;border-bottom:1px solid var(--line)}
.prow:last-child{border-bottom:0}
.plabel{font-size:13px;color:var(--ink2)}
.ptrack{position:relative;height:9px;background:var(--grid);border-radius:5px;overflow:hidden}
.pfill{height:100%;background:var(--fill);border-radius:5px}
.pfill.over{background:repeating-linear-gradient(135deg,var(--fill) 0 5px,transparent 5px 10px),var(--fill)}
.pval{text-align:right;font-variant-numeric:tabular-nums;font-size:14px}
.pval .pmuted{color:var(--muted);font-size:12px}
.prest{text-align:right;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.small{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:14px}
.small .card h3{font-size:12px;font-weight:600;color:var(--ink2);margin:0 0 8px;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;font-size:11px;letter-spacing:.06em;color:var(--muted);
  padding:0 10px 8px 0;border-bottom:1px solid var(--line)}
td{padding:8px 10px 8px 0;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums;vertical-align:top}
td.d{white-space:nowrap;color:var(--ink2)}
td.detail{font-variant-numeric:normal;color:var(--ink)}
tr:last-child td{border-bottom:0}
.num{text-align:right}
details{margin-top:12px}
summary{cursor:pointer;font-size:12px;color:var(--muted);padding:6px 0}
.empty{color:var(--muted);font-size:13px;margin:6px 0}
.note{font-size:12px;color:var(--muted);margin:10px 0 0}
"""


def render(d: dict) -> str:
    t, got = d["target"], d["got"]
    gv = {k: (got[k] if got else 0) for k in ("kcal", "protein", "fat", "carb")}
    latest = d["body"][-1] if d["body"] else None
    o: list[str] = []
    A = o.append

    A(f'<!doctype html><html lang="ja"><head><meta charset="utf-8">'
      f'<meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>健康管理 {d["today"].isoformat()}</title><style>{CSS}</style></head><body><div class="wrap">')
    A(f'<h1>健康管理</h1><p class="sub">{d["today"].isoformat()} 時点 / '
      f'目標 {t["kcal"]:.0f}kcal・タンパク質 {t["protein"]:.0f}g</p>')

    # --- stat タイル（数字1つのものはグラフにしない）
    A('<div class="tiles">')
    if latest:
        A(f'<div class="tile"><div class="k">体重</div><div class="v">{latest["weight"]:g}'
          f'<small>kg</small></div><div class="n">{latest["date"]}</div></div>')
    A(f'<div class="tile"><div class="k">今日の摂取</div><div class="v">{gv["kcal"]:.0f}'
      f'<small>kcal</small></div><div class="n">目標まで {t["kcal"] - gv["kcal"]:.0f}</div></div>')
    A(f'<div class="tile"><div class="k">今月のトレーニング</div><div class="v">{d["train_this_month"]}'
      f'<small>日</small></div><div class="n">週 {d["train_this_month"] / 4.3:.1f} 回</div></div>')
    A(f'<div class="tile"><div class="k">連続記録</div><div class="v">{d["streak"]}'
      f'<small>日</small></div><div class="n">途切れると分析が止まる</div></div>')
    A("</div>")

    # --- 今日の摂取
    A("<h2>今日の摂取</h2><div class=\"card\">")
    for key, label, unit in (("kcal", "kcal", ""), ("protein", "P", "g"),
                             ("fat", "F", "g"), ("carb", "C", "g")):
        A(progress(label, gv[key], t[key], unit))
    A('<p class="note">網掛けは目標超過。脂質が超過している日は、揚げ物・ナッツ・チーズを足さない。</p>')
    A("</div>")

    # --- 体重（2系列なので凡例を付け、色ではなくマークの形で区別する）
    A("<h2>体重の推移</h2><div class=\"card\">")
    A('<div class="legend"><span><i class="sw-dot"></i>日々の実測</span>'
      '<span><i class="sw-line"></i>週平均（目標カロリーの補正に使う値）</span></div>')
    A(line_chart([(r["date"][5:], r["weight"]) for r in d["body"]],
                 unit="kg", avg=[(r["d"][5:], r["w"]) for r in d["weekly"]]))
    A('<details><summary>表で見る（月平均）</summary><table><thead><tr><th>月</th>'
      '<th class="num">平均体重</th><th class="num">記録数</th></tr></thead><tbody>')
    for r in d["month_avg"]:
        A(f'<tr><td class="d">{r["m"]}</td><td class="num">{r["w"]:g} kg</td>'
          f'<td class="num">{r["n"]}</td></tr>')
    A("</tbody></table></details></div>")

    # --- 主要種目（尺度が違うので1枚にまとめず小さいグラフを並べる）
    A("<h2>主要種目の推定1RM</h2><div class=\"small\">")
    for name, rows in d["lifts"].items():
        A(f'<div class="card"><h3>{html.escape(name)}</h3>')
        A(line_chart([(r["d"][5:], r["rm"]) for r in rows], w=390, h=170, unit="kg"))
        A("</div>")
    A("</div>")
    A('<p class="note">Epley 式（重量×(1+レップ/30)）。同じ重量でレップが増えても上がる。</p>')

    # --- 頻度
    A("<h2>月ごとのトレーニング日数</h2><div class=\"card\">")
    A(bar_chart([(r["m"][2:], r["n"]) for r in d["months"]], unit="日"))
    A('<p class="note">週2回（月8〜9日）を下回った期間に、筋力の伸びが止まっている。</p></div>')

    # --- セッション一覧
    A("<h2>直近のトレーニング</h2><div class=\"card\"><table><thead><tr><th>日付</th>"
      "<th>内容</th><th class=\"num\">総挙上重量</th></tr></thead><tbody>")
    for r in d["sessions"]:
        A(f'<tr><td class="d">{r["d"]}</td><td class="detail">{html.escape(r["detail"] or "")}</td>'
          f'<td class="num">{(r["vol"] or 0):.0f} kg</td></tr>')
    A("</tbody></table></div>")

    # --- タンパク質の供給源
    A("<h2>タンパク質の供給源（直近30日）</h2><div class=\"card\"><table><thead><tr>"
      "<th>食品</th><th class=\"num\">合計タンパク質</th><th class=\"num\">回数</th>"
      "</tr></thead><tbody>")
    if not d["protein_src"]:
        A('<tr><td colspan="3" class="detail">まだ食事の記録がありません</td></tr>')
    for r in d["protein_src"]:
        A(f'<tr><td class="detail">{html.escape(r["food_name"])}</td>'
          f'<td class="num">{r["p"]:g} g</td><td class="num">{r["n"]}</td></tr>')
    A("</tbody></table><p class=\"note\">品目単位で記録しているので、どこからタンパク質を"
      "取っているかが分かる。上位が炭水化物源に偏っていたら供給源を足す。</p></div>")

    A("</div></body></html>")
    return "".join(o)


def write(conn: sqlite3.Connection, out: Path, today: date | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(collect(conn, today)), encoding="utf-8")
    return out
