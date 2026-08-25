import type { DecisionBrief } from "../api/client";
import { confidenceLabel, formatPct } from "../format";

interface TrustPanelProps {
  brief: DecisionBrief;
}

export function TrustPanel({ brief }: TrustPanelProps) {
  const c = brief.confidence;
  const overall = confidenceLabel(c.overall);
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Decision Confidence
         </h3>
          <p className="mt-1 text-xs text-slate-500">Five deterministic sub-scores; no AI trust</p>
       </div>
        <div className="text-right">
          <div className={`text-4xl font-bold tabular-nums ${overall.tone}`}>{formatPct(c.overall)}</div>
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">{overall.label}</div>
       </div>
     </header>
      <dl className="space-y-2">
        <Bar label="Completeness" value={c.completeness} />
        <Bar label="Freshness" value={c.freshness} />
        <Bar label="Agreement" value={c.agreement} />
        <Bar label="Conflict Density" value={c.conflict_density} />
     </dl>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Scoring Formula
       </summary>
        <p className="mt-2 leading-relaxed">{c.formula}</p>
     </details>
   </section>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <dt className="font-medium text-slate-700">{label}</dt>
        <dd className="font-mono tabular-nums text-slate-900">{pct}%</dd>
     </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full rounded-full transition-all ${
            pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500"
          }`}
          style={{ width: `${pct}%` }}
        />
     </div>
   </div>
  );
}
