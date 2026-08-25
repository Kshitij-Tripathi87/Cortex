import type { DecisionBrief } from "../api/client";
import { formatUsd, formatPct } from "../format";

interface ImpactCardProps {
  brief: DecisionBrief;
}

export function ImpactCard({ brief }: ImpactCardProps) {
  const bi = brief.business_impact;
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          Business Impact
       </h3>
        <p className="mt-1 text-xs text-slate-500">Six-component score, weighted aggregate</p>
     </header>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <MoneyRow label="Revenue Risk" value={bi.revenue_risk_usd} accent="text-slate-900" />
        <MoneyRow label="Margin Risk" value={bi.margin_risk_usd} accent="text-slate-900" />
        <MoneyRow label="Penalty Exposure" value={bi.penalty_exposure_usd} accent="text-red-700" />
        <MoneyRow label="Working Capital" value={bi.working_capital_impact_usd} accent="text-amber-700" />
        <ScoreRow label="Customer Impact" score={bi.customer_impact_score} />
        <ScoreRow label="Operational Impact" score={bi.operational_impact_score} />
     </dl>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Scoring Formula
       </summary>
        <p className="mt-2 leading-relaxed">{bi.formula}</p>
     </details>
   </section>
  );
}

function MoneyRow({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className={`mt-1 text-2xl font-bold tabular-nums ${accent}`}>{formatUsd(value)}</dd>
   </div>
  );
}

function ScoreRow({ label, score }: { label: string; score: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums text-slate-900">{formatPct(score)}</span>
        <span className="text-xs text-slate-500">0-100%</span>
     </dd>
   </div>
  );
}
