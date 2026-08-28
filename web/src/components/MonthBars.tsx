import type { MonthVolume } from "@/lib/queries";

/** 月ごとのセッション日数。頻度が落ちた月が目で分かればよいので数値も添える。 */
export default function MonthBars({ months }: { months: MonthVolume[] }) {
  const max = Math.max(...months.map((m) => m.days));
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${months.length}, 1fr)`, gap: 6 }}>
      {months.map((m, i) => (
        <div key={m.month} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 11, color: "var(--ink2)", textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
            {m.days}
          </div>
          <div style={{ height: 84, display: "flex", alignItems: "flex-end" }}>
            <div
              className="rise"
              style={{
                ["--i" as string]: i,
                width: "100%",
                height: `${Math.max(3, (m.days / max) * 84)}px`,
                background: "var(--fill)",
                borderRadius: "3px 3px 0 0",
              }}
            />
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
            {m.month.slice(5).replace(/^0/, "")}
          </div>
        </div>
      ))}
    </div>
  );
}
