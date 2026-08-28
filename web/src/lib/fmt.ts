export const n0 = (v: number) => Math.round(v).toLocaleString("ja-JP");
export const n1 = (v: number) => (Math.round(v * 10) / 10).toFixed(1);
export const ymd = (s: string) => s.replace(/-/g, "/");
export const sign = (v: number) => (v > 0 ? "+" : v < 0 ? "" : "±");
export const SPLIT_JP: Record<string, string> = { push: "胸と肩", pull: "背中と腕", legs: "脚" };
