import { all, one } from "./db";

/** 継続してやっていると見なす最低セッション数。単発で試した種目を主役から外す。 */
const REGULAR_DAYS = 8;

export type PlanRow = {
  computed_at: string;
  split: string;
  ord: number;
  code: string;
  name: string;
  weight: number;
  reps: string;
  reason: string;
  last_txt: string;
};

/** 次にやるメニュー。計算は lib/train.py が済ませてあり、ここは読むだけ。 */
export async function nextSession() {
  const rows = await all<PlanRow>("SELECT * FROM v_next_plan");
  return rows.length ? { split: rows[0].split, computedAt: rows[0].computed_at, rows } : null;
}

export type Lift = {
  code: string;
  name: string;
  muscle: string;
  split: string;
  days: number;
  sets: number;
  maxw: number;
  best: number;
  bw: boolean;
  series: { date: string; rm: number }[];
  prs: string[];
  first: number;
  current: number;
  prDate: string | null;
  prDays: number | null;
};

/**
 * 種目ごとの推定1RM（Epley）の推移。
 *
 * 体脂肪率が1件も入っていないので筋肉量は直接測れない。ここが唯一の代理指標になる。
 */
export async function lifts(today: string): Promise<Lift[]> {
  const base = await all<{
    code: string; name: string; muscle: string; split: string;
    days: number; sets: number; maxw: number;
  }>(
    `SELECT e.code, e.name, e.muscle, e.split,
            COUNT(DISTINCT s.date) days, COUNT(*) sets, MAX(s.weight) maxw
       FROM sets s JOIN exercises e ON e.id = s.exercise_id
      GROUP BY e.code
      ORDER BY days DESC`,
  );

  const points = await all<{ code: string; date: string; rm: number }>(
    `SELECT e.code, s.date, ROUND(MAX(s.weight * (1 + s.reps / 30.0)), 1) rm
       FROM sets s JOIN exercises e ON e.id = s.exercise_id
      GROUP BY e.code, s.date
      ORDER BY s.date`,
  );

  const byCode = new Map<string, { date: string; rm: number }[]>();
  for (const p of points) {
    const arr = byCode.get(p.code) ?? [];
    arr.push({ date: p.date, rm: p.rm });
    byCode.set(p.code, arr);
  }

  return base.map((b) => {
    const series = byCode.get(b.code) ?? [];
    // 自己記録を更新した日。自重種目は重量0で推定1RMも0になるので対象外
    const prs: string[] = [];
    let best = 0;
    for (const p of series) {
      if (p.rm > best) {
        best = p.rm;
        prs.push(p.date);
      }
    }
    const bw = b.maxw === 0;
    const prDate = bw ? null : (prs.at(-1) ?? null);
    return {
      ...b,
      best,
      bw,
      series,
      prs,
      first: series[0]?.rm ?? 0,
      current: series.at(-1)?.rm ?? 0,
      prDate,
      prDays: prDate ? daysBetween(prDate, today) : null,
    };
  });
}

/** 主役に出す種目。継続していて、重量が乗るもの。伸び幅の大きい順。 */
export function regular(ls: Lift[]): Lift[] {
  return ls
    .filter((l) => !l.bw && l.days >= REGULAR_DAYS && l.series.length >= 3)
    .sort((a, b) => b.best - b.first - (a.best - a.first));
}

export type MonthVolume = { month: string; days: number; sets: number; vol: number };

/** 月ごとの総挙上量と頻度。 */
export async function months(): Promise<MonthVolume[]> {
  return all<MonthVolume>(
    `SELECT strftime('%Y-%m', date) month, COUNT(DISTINCT date) days,
            COUNT(*) sets, ROUND(SUM(weight * reps)) vol
       FROM sets GROUP BY month ORDER BY month`,
  );
}

export type MuscleVolume = { month: string; muscle: string; vol: number };

/** 月 × 部位の挙上量。積み上げの内訳に使う。 */
export async function muscleVolume(): Promise<MuscleVolume[]> {
  return all<MuscleVolume>(
    `SELECT strftime('%Y-%m', s.date) month, e.muscle, ROUND(SUM(s.weight * s.reps)) vol
       FROM sets s JOIN exercises e ON e.id = s.exercise_id
      WHERE s.weight > 0
      GROUP BY month, e.muscle ORDER BY month`,
  );
}

export type BodyPoint = { date: string; weight: number; body_fat: number | null };

export async function body(): Promise<BodyPoint[]> {
  return all<BodyPoint>("SELECT date, weight, body_fat FROM body ORDER BY date");
}

/** 体組成がどれだけ埋まっているか。筋肉量を出せるかの判定に使う。 */
export async function bodyFill() {
  return (await one<{ n: number; bf: number; mu: number }>(
    "SELECT COUNT(*) n, COUNT(body_fat) bf, COUNT(muscle) mu FROM body",
  ))!;
}

export async function totals(today: string) {
  const t = (await one<{ days: number; sets: number; vol: number; first: string; last: string }>(
    `SELECT COUNT(DISTINCT date) days, COUNT(*) sets, ROUND(SUM(weight * reps)) vol,
            MIN(date) first, MAX(date) last FROM sets`,
  ))!;
  return { ...t, spanDays: daysBetween(t.first, today) };
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
}
