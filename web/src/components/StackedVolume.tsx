import type { MuscleVolume } from "@/lib/queries";

const W = 960;
const H = 230;
const PAD = { l: 46, r: 8, t: 10, b: 26 };
const SHADES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"];
const TOP = 5;

/**
 * 月 × 部位の挙上量を積み上げる。
 *
 * 体脂肪率が空なので筋肉量は測れない。「積み上げた総量」が唯一の代理指標であり、
 * この画面で一番大きく出すべきものになる。部位は総量の多い順に TOP 件、残りは「その他」。
 */
export default function StackedVolume({ rows }: { rows: MuscleVolume[] }) {
  const months = [...new Set(rows.map((r) => r.month))].sort();

  const totalBy = new Map<string, number>();
  for (const r of rows) totalBy.set(r.muscle, (totalBy.get(r.muscle) ?? 0) + r.vol);
  const ranked = [...totalBy.entries()].sort((a, b) => b[1] - a[1]).map(([m]) => m);
  const keys = ranked.slice(0, TOP);
  const hasRest = ranked.length > TOP;
  const bands = hasRest ? [...keys, "その他"] : keys;

  const cell = new Map<string, number>();
  for (const r of rows) {
    const k = keys.includes(r.muscle) ? r.muscle : "その他";
    cell.set(`${r.month}|${k}`, (cell.get(`${r.month}|${k}`) ?? 0) + r.vol);
  }
  const totals = months.map((m) => bands.reduce((a, k) => a + (cell.get(`${m}|${k}`) ?? 0), 0));
  const top = Math.max(...totals);
  const step = (W - PAD.l - PAD.r) / months.length;
  const barW = Math.min(46, step * 0.62);
  const y = (v: number) => PAD.t + (1 - v / top) * (H - PAD.t - PAD.b);

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="月ごとの部位別挙上量">
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={PAD.l} y1={y(t)} x2={W - PAD.r} y2={y(t)} />
            <text className="axis" x={0} y={y(t) + 3.5}>
              {t === 0 ? "0" : `${Math.round(t / 1000)}t`}
            </text>
          </g>
        ))}
        {months.map((m, mi) => {
          const cx = PAD.l + step * mi + step / 2;
          let acc = 0;
          return (
            <g key={m} className="rise" style={{ ["--i" as string]: mi }}>
              {bands.map((k, ki) => {
                const v = cell.get(`${m}|${k}`) ?? 0;
                if (v === 0) return null;
                const y1 = y(acc);
                acc += v;
                const y2 = y(acc);
                return (
                  <rect
                    key={k}
                    x={cx - barW / 2}
                    y={y2}
                    width={barW}
                    height={Math.max(0.6, y1 - y2)}
                    fill={SHADES[ki]}
                  >
                    <title>{`${m} ${k} ${Math.round(v).toLocaleString("ja-JP")}kg`}</title>
                  </rect>
                );
              })}
              <text className="axis" textAnchor="middle" x={cx} y={H - 8}>
                {m.slice(5).replace(/^0/, "")}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {bands.map((k, ki) => (
          <span key={k}>
            <i style={{ background: SHADES[ki] }} />
            {k}
          </span>
        ))}
      </div>
    </>
  );
}
