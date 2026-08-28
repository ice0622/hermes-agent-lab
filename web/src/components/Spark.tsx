import type { Lift } from "@/lib/queries";
import { path, scale, ts, type Pt } from "@/lib/svg";

const W = 280;
const H = 56;
const PAD = 5;

/** 推定1RM の推移。自己記録を更新した日に点を打ち、最新の更新だけ大きくする。 */
export default function Spark({ lift }: { lift: Lift }) {
  const pts: Pt[] = lift.series.map((p) => [ts(p.date), p.rm]);
  const ys = pts.map((p) => p[1]);
  const x = scale(pts[0][0], pts.at(-1)![0], PAD, W - PAD);
  const y = scale(Math.min(...ys) * 0.94, Math.max(...ys) * 1.03, H - PAD, PAD);
  const scaled: Pt[] = pts.map((p) => [x(p[0]), y(p[1])]);
  const prSet = new Set(lift.prs);
  const latestPr = lift.prs.at(-1);

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`${lift.name} の推定1RM 推移`}
    >
      <path d={path(scaled)} fill="none" stroke="var(--mark2)" strokeWidth={1.75} strokeLinejoin="round" />
      {lift.series.map((p, i) =>
        prSet.has(p.date) ? (
          <circle
            key={p.date}
            cx={scaled[i][0].toFixed(1)}
            cy={scaled[i][1].toFixed(1)}
            r={p.date === latestPr ? 3.6 : 2.3}
            fill="var(--mark)"
          />
        ) : null,
      )}
    </svg>
  );
}
