"""Write CriticalAlertCard.tsx with correct JSX closing braces."""

CONTENT = '''import type { DecisionBrief } from "../api/client";
import { severityColor, severityFromScore, severityHeader, deadlineLabel, totalAffected } from "../format";

interface CriticalAlertCardProps {
  brief: DecisionBrief;
}

export function CriticalAlertCard({ brief }: CriticalAlertCardProps) {
  const severity = severityFromScore(brief.business_impact.overall_score);
  const tone = severityColor(severity);
  const headline = severityHeader(severity);
  const total = totalAffected(brief);

  return (
    <section className={`rounded-2xl border-2 p-6 ${tone}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex-1 min-w-[280px]">
          <p className="text-xs font-semibold uppercase tracking-wider opacity-70">
            Decision Deadline: {deadlineLabel(brief.deadline_hours)}
        </p>
          <h2 className="mt-1 text-2xl font-bold leading-tight">{brief.headline</h2>
          <p className="mt-2 text-sm opacity-90">
            {brief.supplier.name} ({brief.supplier.country}, {brief.supplier.tier}) - {brief.scenario.scenario_type.replace("_", " ")}
        </p>
      </div>
        <div className="flex flex-col items-end gap-1">
          <div className="text-5xl font-bold tabular-nums">
            {brief.business_impact.overall_score.toFixed(0)}
        </div>
          <div className="text-xs font-medium uppercase tracking-wider opacity-70">
            Impact Score
        </div>
          <div className="mt-2 inline-block rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wider">
            {headline}
        </div>
      </div>
    </div>
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Components" value={brief.propagation.affected_components.length} />
        <Stat label="Products" value={brief.propagation.affected_products.length} />
        <Stat label="Warehouses" value={brief.propagation.affected_warehouses.length} />
        <Stat label="Orders at risk" value={brief.propagation.open_orders_at_risk.length} />
        <div className="col-span-2 sm:col-span-4 mt-1 text-xs opacity-70">
          Total blast radius: {total} entities
      </div>
    </div>
  </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-current/20 bg-white/60 px-3 py-2">
      <div className="text-xs font-medium uppercase tracking-wider opacity-70">{label</div>
      <div className="mt-0.5 text-2xl font-bold tabular-nums">{value</div>
  </div>
  );
}
'''

with open(r'C:\Users\21330\Documents\Cortex\frontend\src\features\morning-brief\components\CriticalAlertCard.tsx', 'w', encoding='utf-8') as f:
    f.write(CONTENT)

print('written:', len(CONTENT), 'chars')
