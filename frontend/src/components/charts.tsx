import { useState } from "react";

type Tip = { x: number; y: number; text: string } | null;

/** Single-series column chart with hover tooltips (one accent hue; title names the series). */
export function BarChart({ data, height = 120, labelEvery = 5 }: { data: { label: string; value: number }[]; height?: number; labelEvery?: number }) {
  const [tip, setTip] = useState<Tip>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      <div className="bars" style={{ height }} role="img" aria-label={`Bar chart, max ${max}`}>
        {data.map((d) => (
          <div
            key={d.label}
            className={`bar ${d.value ? "" : "zero"}`}
            style={{ height: `${Math.max(2, (d.value / max) * 100)}%` }}
            onMouseMove={(e) => setTip({ x: e.clientX + 12, y: e.clientY - 30, text: `${d.label}: ${d.value}` })}
            onMouseLeave={() => setTip(null)}
          />
        ))}
      </div>
      <div className="row small muted" style={{ justifyContent: "space-between", marginTop: 4 }}>
        {data.filter((_, i) => i % labelEvery === 0).map((d) => (
          <span key={d.label}>{d.label.slice(5)}</span>
        ))}
      </div>
      {tip && <div className="tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  );
}

/** Horizontal funnel: bar length = count relative to the first stage; conversion vs previous stage on the right. */
export function Funnel({ stages }: { stages: { stage: string; count: number }[] }) {
  const [tip, setTip] = useState<Tip>(null);
  const top = Math.max(1, stages[0]?.count || 1);
  return (
    <div>
      {stages.map((s, i) => {
        const prev = i > 0 ? stages[i - 1].count : null;
        const conv = prev ? (s.count / prev) * 100 : null;
        return (
          <div key={s.stage} className="funnel-row">
            <div className="secondary small">{s.stage}</div>
            <div
              className="funnel-track"
              onMouseMove={(e) => setTip({ x: e.clientX + 12, y: e.clientY - 30, text: `${s.stage}: ${s.count.toLocaleString()}${conv != null ? ` (${conv.toFixed(1)}% of previous)` : ""}` })}
              onMouseLeave={() => setTip(null)}
            >
              <div className="funnel-fill" style={{ width: `${s.count ? Math.max(1.5, (s.count / top) * 100) : 0}%` }} />
            </div>
            <div className="num" style={{ textAlign: "right" }}>
              <b>{s.count.toLocaleString()}</b>
              {conv != null && <span className="muted small"> · {conv.toFixed(0)}%</span>}
            </div>
          </div>
        );
      })}
      {tip && <div className="tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  );
}

export function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}
