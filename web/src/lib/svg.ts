/** SVG を直に組むための最小限のヘルパ。グラフのライブラリは入れない。 */

export type Pt = [number, number];

export function scale(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

export function path(pts: Pt[]): string {
  return pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
}

/** 直近 k 点の移動平均。実測点が不定間隔なので週平均ではなく点数で取る。 */
export function movingAvg(pts: Pt[], k: number): Pt[] {
  return pts.map((p, i) => {
    const win = pts.slice(Math.max(0, i - k + 1), i + 1);
    return [p[0], win.reduce((a, b) => a + b[1], 0) / win.length] as Pt;
  });
}

export const ts = (d: string) => Date.parse(d + "T00:00:00Z");
