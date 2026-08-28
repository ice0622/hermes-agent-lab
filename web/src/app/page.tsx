import MonthBars from "@/components/MonthBars";
import Setup from "@/components/Setup";
import Spark from "@/components/Spark";
import StackedVolume from "@/components/StackedVolume";
import WeightLine from "@/components/WeightLine";
import { configured } from "@/lib/db";
import { n0, n1, sign, SPLIT_JP, ymd } from "@/lib/fmt";
import {
  body, bodyFill, lifts, months, muscleVolume, nextSession, regular, totals,
} from "@/lib/queries";

// 単一ユーザーなのでキャッシュしない。記録した内容が次の表示で必ず出る。
export const dynamic = "force-dynamic";

const STALE_DAYS = 60;

export default async function Page() {
  const cfg = configured();
  if (!cfg.ok) return <Setup reason={cfg.reason} />;

  const today = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD（ローカル）
  const [plan, allLifts, ms, mv, bd, fill, tot] = await Promise.all([
    nextSession(), lifts(today), months(), muscleVolume(), body(), bodyFill(), totals(today),
  ]);

  const main = regular(allLifts);
  const grown = main.filter((l) => l.best - l.first > 0.5);
  const stalled = main.filter((l) => (l.prDays ?? 0) >= STALE_DAYS);

  // 部位別に前半と後半を比べる。積み上げが増えているのか減っているのかを数字で出す
  const monthKeys = [...new Set(mv.map((r) => r.month))].sort();
  const half = Math.ceil(monthKeys.length / 2);
  const h1 = new Set(monthKeys.slice(0, half));
  const byMuscle = new Map<string, { a: number; b: number }>();
  for (const r of mv) {
    const e = byMuscle.get(r.muscle) ?? { a: 0, b: 0 };
    if (h1.has(r.month)) e.a += r.vol;
    else e.b += r.vol;
    byMuscle.set(r.muscle, e);
  }
  const compare = [...byMuscle.entries()]
    .map(([muscle, v]) => ({ muscle, ...v, pct: v.a ? ((v.b - v.a) / v.a) * 100 : 0 }))
    .sort((x, y) => y.a + y.b - (x.a + x.b));
  const sumA = compare.reduce((s, c) => s + c.a, 0);
  const sumB = compare.reduce((s, c) => s + c.b, 0);
  const maxVol = Math.max(...compare.map((c) => Math.max(c.a, c.b)));

  const wFirst = bd[0];
  const wLast = bd.at(-1)!;
  const wDelta = wLast.weight - wFirst.weight;

  return (
    <main className="wrap">
      <h1 className="rise">筋トレ</h1>
      <p className="sub rise" style={{ ["--i" as string]: 1 }}>
        {ymd(tot.first)} から {tot.spanDays}日 · {tot.days}セッション · {n0(tot.sets)}セット ·
        総挙上量 {n0(tot.vol)}kg
      </p>

      {/* ---------------------------------------------- 次のセッション */}
      <h2>次のセッション</h2>
      {plan ? (
        <div className="card rise">
          <div className="plan-head">
            <span className="plan-split">{SPLIT_JP[plan.split] ?? plan.split}</span>
            <span className="plan-meta">
              {plan.split} · {plan.computedAt} 時点
            </span>
          </div>
          <div className="plan-list">
            {plan.rows.map((r, i) => (
              <div className="plan-row rise" key={r.code} style={{ ["--i" as string]: i + 1 }}>
                <div className="plan-no">{r.ord}</div>
                <div>
                  <div className="plan-name">{r.name}</div>
                  <div className="plan-why">
                    {r.reason}
                    <br />
                    <span className="prev">前回 {r.last_txt}</span>
                  </div>
                </div>
                <div className="plan-target">
                  <div className="plan-kg">
                    {r.weight === 0 ? "自重" : <>{n1(r.weight)}<small>kg</small></>}
                  </div>
                  <div className="plan-reps">{r.reps.replace(/\//g, " → ")} 回</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="lede">
          メニューがまだ計算されていません。<code>health plan</code> を1回実行してください。
        </p>
      )}
      <p className="note">
        重量は <code>skills/health/lib/train.py</code> が決めている。規則は1つだけ —
        <b> 同じ重量で3セット揃うまで上げない</b>。記録するたびに再計算される。
      </p>

      {/* ---------------------------------------------- 強くなっているか */}
      <h2>
        強くなっているか<span className="cnt">推定1RM · Epley</span>
      </h2>
      <p className="lede">
        継続している {main.length}種目のうち <b>{grown.length}</b>種目は伸び、
        <b>{stalled.length}</b>種目は{STALE_DAYS}日以上自己記録が止まっている。伸び幅の大きい順。
      </p>
      <div className="lift-grid">
        {main.map((l, i) => {
          const gain = l.best - l.first;
          const stale = (l.prDays ?? 0) >= STALE_DAYS;
          return (
            <div className="lift rise" key={l.code} style={{ ["--i" as string]: i }}>
              <div className="lift-name">
                <span>{l.name}</span>
                <span className="tag">{l.split}</span>
              </div>
              <div className="lift-rm">
                {n1(l.best)}<small>kg</small>
              </div>
              <div className={`lift-delta ${gain > 0.5 ? "up" : "flat"}`}>
                {sign(gain)}{n1(gain)}kg · 初回 {n1(l.first)}kg
              </div>
              <div className="lift-stale">
                {stale
                  ? `自己記録 ${ymd(l.prDate!)}（${l.prDays}日前）`
                  : `自己記録 ${ymd(l.prDate!)}（${l.prDays}日前）· ${l.days}セッション`}
              </div>
              <Spark lift={l} />
            </div>
          );
        })}
      </div>

      {/* ---------------------------------------------- 積み上げているか */}
      <h2>
        積み上げているか<span className="cnt">月 × 部位の挙上量</span>
      </h2>
      <p className="lede">
        体脂肪率が <b>0/{fill.n}</b> 件しか入っていないので、筋肉量は直接測れない。
        <b> 積み上げた総量</b>が唯一の代理指標になる。
        前半{half}ヶ月 <b>{n0(sumA)}kg</b> → 後半{monthKeys.length - half}ヶ月 <b>{n0(sumB)}kg</b>
        （{sign(((sumB - sumA) / sumA) * 100)}{n1(((sumB - sumA) / sumA) * 100)}%）。
      </p>
      <StackedVolume rows={mv} />

      <table style={{ marginTop: 34 }}>
        <thead>
          <tr>
            <th>部位</th>
            <th className="bar-cell">前半 / 後半</th>
            <th className="num">前半 kg</th>
            <th className="num">後半 kg</th>
            <th className="num">変化</th>
          </tr>
        </thead>
        <tbody>
          {compare.map((c) => (
            <tr key={c.muscle}>
              <td className="name">{c.muscle}</td>
              <td className="bar-cell">
                <div className="bar-track" style={{ marginBottom: 3 }}>
                  <div className="bar-in" style={{ width: `${(c.a / maxVol) * 100}%` }} />
                </div>
                <div className="bar-track">
                  <div className="bar-in" style={{ width: `${(c.b / maxVol) * 100}%`, background: "var(--mark2)" }} />
                </div>
              </td>
              <td className="num">{n0(c.a)}</td>
              <td className="num">{n0(c.b)}</td>
              <td className="num">{c.a ? `${sign(c.pct)}${n1(c.pct)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* ---------------------------------------------- 続いているか */}
      <h2>
        続いているか<span className="cnt">月ごとのセッション日数</span>
      </h2>
      <p className="lede">
        週あたり <b>{n1(tot.days / (tot.spanDays / 7))}</b>回。
        最も少ない月は {ms.reduce((a, b) => (a.days <= b.days ? a : b)).month.replace("-", "/")} の
        <b> {ms.reduce((a, b) => (a.days <= b.days ? a : b)).days}</b>日。
      </p>
      <MonthBars months={ms} />

      {/* ---------------------------------------------- 体重 */}
      <h2>
        体重<span className="cnt">{bd.length}点</span>
      </h2>
      <p className="lede">
        {ymd(wFirst.date)} {n1(wFirst.weight)}kg → {ymd(wLast.date)} {n1(wLast.weight)}kg
        （<b>{sign(wDelta)}{n1(wDelta)}kg</b> / {tot.spanDays}日）。
      </p>
      <WeightLine body={bd} />
      <div className="warn">
        <b>筋肉量はこの DB では測れない。</b>
        {fill.n}件の体組成のうち体脂肪率が {fill.bf}件、筋肉量が {fill.mu}件。
        除脂肪体重を出すには体脂肪率が必要で、それはタニタ Health Planet 連携（docs/plan.md T18〜T20）が
        入るまで埋まらない。それまでは上の「積み上げているか」と「強くなっているか」が代替になる。
      </div>

      <p className="foot">
        書き込みはしない。記録は <code>health</code> CLI、次のメニューの計算は{" "}
        <code>lib/train.py</code>、この画面は読むだけ。
      </p>
    </main>
  );
}
