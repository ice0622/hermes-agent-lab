import type { BodyPoint } from "@/lib/queries";
import { movingAvg, path, scale, ts, type Pt } from "@/lib/svg";

const W = 960;
const H = 150;
const PAD = { l: 34, r: 8, t: 10, b: 22 };

/** 体重。増量が進んでいないことが分かればよいので、実測点と移動平均だけ。 */
export default function WeightLine({ body }: { body: BodyPoint[] }) {
  const pts: Pt[] = body.map((b) => [ts(b.date), b.weight]);
  const ys = pts.map((p) => p[1]);
  const lo = Math.floor(Math.min(...ys) - 0.6);
  const hi = Math.ceil(Math.max(...ys) + 0.6);
  const x = scale(pts[0][0], pts.at(-1)![0], PAD.l, W - PAD.r);
  const y = scale(lo, hi, H - PAD.b, PAD.t);
  const avg = movingAvg(pts, 3).map((p) => [x(p[0]), y(p[1])] as Pt);

  const gridKg: number[] = [];
  for (let g = lo; g <= hi; g++) gridKg.push(g);

  // 3ヶ月ごとの目盛り
  const first = new Date(pts[0][0]);
  const labels: { at: number; text: string }[] = [];
  for (let yr = first.getUTCFullYear(), mo = first.getUTCMonth(); ; mo++) {
    if (mo > 11) { mo = 0; yr++; }
    const d = Date.UTC(yr, mo, 1);
    if (d > pts.at(-1)![0]) break;
    if (d >= pts[0][0] && mo % 3 === 0) labels.push({ at: d, text: `${yr % 100}/${mo + 1}` });
  }

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="体重の推移">
      {gridKg.map((g) => (
        <g key={g}>
          <line className="gridline" x1={PAD.l} y1={y(g)} x2={W - PAD.r} y2={y(g)} />
          <text className="axis" x={0} y={y(g) + 3.5}>{g}</text>
        </g>
      ))}
      {labels.map((l) => (
        <text key={l.at} className="axis" textAnchor="middle" x={x(l.at)} y={H - 6}>{l.text}</text>
      ))}
      <path d={path(avg)} fill="none" stroke="var(--mark2)" strokeWidth={2} strokeLinejoin="round" />
      {pts.map((p) => (
        <circle key={p[0]} cx={x(p[0]).toFixed(1)} cy={y(p[1]).toFixed(1)} r={2.6} fill="var(--mark)" />
      ))}
    </svg>
  );
}
