import type { DecisionBrief } from "../api/client";
import { formatUsd, formatHours } from "../format";

interface RecommendationPanelProps {
  brief: DecisionBrief;
}

export function RecommendationPanel({ brief }: RecommendationPanelProps) {
  const recs = brief.recommendations.filter((r) => r.applicable);
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Recommended Actions
         </h3>
          <p className="mt-1 text-xs text-slate-500">
            Ranked by net benefit. Top {recs.length} applicable.
         </p>
       </div>
     </header>
      <ol className="space-y-3">
        {recs.map((rec) => (
          <li key={rec.rank} className="rounded-xl border-2 border-indigo-200 bg-indigo-50/50 p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 font-bold text-white">
                {rec.rank}
             </div>
              <div className="flex-1 min-w-[200px]">
                <h4 className="text-base font-bold text-slate-900">{rec.name}</h4>
                <p className="mt-1 text-sm text-slate-700">{rec.explanation}</p>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <Mini label="Net benefit" value={rec.scores.net_benefit.toFixed(2)} />
                  <Mini label="Cost" value={formatUsd(rec.scores.execution_cost_usd)} />
                  <Mini label="Time" value={formatHours(rec.scores.execution_time_hours)} />
                  <Mini label="Confidence" value={rec.scores.confidence.toFixed(2)} />
                  <Mini label="Impact reduction" value={rec.scores.business_impact_reduction.toFixed(2)} />
                  <Mini label="Customer protected" value={rec.scores.customer_impact_protected.toFixed(2)} />
                  <Mini label="Op risk" value={rec.scores.operational_risk.toFixed(2)} />
                  <Mini label="Dep readiness" value={rec.scores.dependency_readiness.toFixed(2)} />
               </dl>
             </div>
           </div>
         </li>
        ))}
     </ol>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Ranking Formula
       </summary>
        <p className="mt-2 leading-relaxed">{brief.ranking_formula}</p>
     </details>
   </section>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="font-mono text-sm font-medium text-slate-900">{value}</dd>
   </div>
  );
}
