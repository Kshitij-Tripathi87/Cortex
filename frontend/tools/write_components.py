"""Write all morning-brief component TSX files using placeholder substitution.

The literal text of each file uses the placeholder __CB__ for the closing brace
character so that we never write a pattern of __CB__</tag> in this Python source.
At write time we substitute chr(125) for __CB__.
"""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\21330\Documents\Cortex\frontend\src\features\morning-brief")
PAGE = Path(r"C:\Users\21330\Documents\Cortex\frontend\src\app\mvp\page.tsx")

CB = chr(125)  # '}'
OB = chr(123)  # '{'

# Helper builders - we build content with __CB__ / __OB__ placeholders

# === CriticalAlertCard.tsx ===
critical = f"""import type {{ DecisionBrief }} from "../api/client";
import {{ severityColor, severityFromScore, severityHeader, deadlineLabel, totalAffected }} from "../format";

interface CriticalAlertCardProps __OB__
  brief: DecisionBrief;
__CB__

export function CriticalAlertCard(__OB__ brief __CB__: CriticalAlertCardProps) __OB__
  const severity = severityFromScore(brief.business_impact.overall_score);
  const tone = severityColor(severity);
  const headline = severityHeader(severity);
  const total = totalAffected(brief);

  return (
    <section className=__OB__`rounded-2xl border-2 p-6 $__OB__tone__CB__`__CB__>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex-1 min-w-[280px]">
          <p className="text-xs font-semibold uppercase tracking-wider opacity-70">
            Decision Deadline: __OB__deadlineLabel(brief.deadline_hours)__CB__
         </p>
          <h2 className="mt-1 text-2xl font-bold leading-tight">__OB__brief.headline__CB__</h2>
          <p className="mt-2 text-sm opacity-90">
            __OB__brief.supplier.name__CB__ (__OB__brief.supplier.country__CB__, __OB__brief.supplier.tier__CB__) - __OB__brief.scenario.scenario_type.replace("_", " ")__CB__
         </p>
       </div>
        <div className="flex flex-col items-end gap-1">
          <div className="text-5xl font-bold tabular-nums">
            __OB__brief.business_impact.overall_score.toFixed(0)__CB__
         </div>
          <div className="text-xs font-medium uppercase tracking-wider opacity-70">
            Impact Score
         </div>
          <div className="mt-2 inline-block rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wider">
            __OB__headline__CB__
         </div>
       </div>
     </div>
      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Components" value=__OB__brief.propagation.affected_components.length__CB__ />
        <Stat label="Products" value=__OB__brief.propagation.affected_products.length__CB__ />
        <Stat label="Warehouses" value=__OB__brief.propagation.affected_warehouses.length__CB__ />
        <Stat label="Orders at risk" value=__OB__brief.propagation.open_orders_at_risk.length__CB__ />
        <div className="col-span-2 sm:col-span-4 mt-1 text-xs opacity-70">
          Total blast radius: __OB__total__CB__ entities
       </div>
     </div>
   </section>
  );
__CB__

function Stat(__OB__ label, value __CB__: __OB__ label: string; value: number __CB__) __OB__
  return (
    <div className="rounded-lg border border-current/20 bg-white/60 px-3 py-2">
      <div className="text-xs font-medium uppercase tracking-wider opacity-70">__OB__label__CB__</div>
      <div className="mt-0.5 text-2xl font-bold tabular-nums">__OB__value__CB__</div>
   </div>
  );
__CB__
"""

# === ImpactCard.tsx ===
impact = f"""import type {{ DecisionBrief }} from "../api/client";
import {{ formatUsd, formatPct }} from "../format";

interface ImpactCardProps __OB__
  brief: DecisionBrief;
__CB__

export function ImpactCard(__OB__ brief __CB__: ImpactCardProps) __OB__
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
        <MoneyRow label="Revenue Risk" value=__OB__bi.revenue_risk_usd__CB__ accent="text-slate-900" />
        <MoneyRow label="Margin Risk" value=__OB__bi.margin_risk_usd__CB__ accent="text-slate-900" />
        <MoneyRow label="Penalty Exposure" value=__OB__bi.penalty_exposure_usd__CB__ accent="text-red-700" />
        <MoneyRow label="Working Capital" value=__OB__bi.working_capital_impact_usd__CB__ accent="text-amber-700" />
        <ScoreRow label="Customer Impact" score=__OB__bi.customer_impact_score__CB__ />
        <ScoreRow label="Operational Impact" score=__OB__bi.operational_impact_score__CB__ />
     </dl>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Scoring Formula
       </summary>
        <p className="mt-2 leading-relaxed">__OB__bi.formula__CB__</p>
     </details>
   </section>
  );
__CB__

function MoneyRow(__OB__ label, value, accent __CB__: __OB__ label: string; value: number; accent: string __CB__) __OB__
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">__OB__label__CB__</dt>
      <dd className=__OB__`mt-1 text-2xl font-bold tabular-nums $__OB__accent__CB__`__CB__>__OB__formatUsd(value)__CB__</dd>
   </div>
  );
__CB__

function ScoreRow(__OB__ label, score __CB__: __OB__ label: string; score: number __CB__) __OB__
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">__OB__label__CB__</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums text-slate-900">__OB__formatPct(score)__CB__</span>
        <span className="text-xs text-slate-500">0-100%</span>
     </dd>
   </div>
  );
__CB__
"""

# === Timeline.tsx ===
timeline = f"""import type {{ DecisionBrief }} from "../api/client";

interface TimelineProps __OB__
  brief: DecisionBrief;
__CB__

export function Timeline(__OB__ brief __CB__: TimelineProps) __OB__
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Timeline</h3>
        <p className="mt-1 text-xs text-slate-500">Inventory depletion at fixed checkpoints</p>
     </header>
      <ol className="space-y-3">
        __OB__brief.timeline.events.map((event, i) => __OB__
          const tone =
            event.status === "stocked_out"
              ? "border-red-300 bg-red-50"
              : event.status === "at_safety"
                ? "border-amber-300 bg-amber-50"
                : event.status === "below_safety"
                  ? "border-orange-300 bg-orange-50"
                  : "border-slate-200 bg-slate-50";
          return (
            <li key=__OB__i__CB__ className=__OB__`flex gap-4 rounded-xl border p-4 $__OB__tone__CB__`__CB__>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 font-bold tabular-nums text-white">
                __OB__event.hour__CB__h
             </div>
              <div className="flex-1">
                <p className="text-sm font-bold">__OB__event.title__CB__</p>
                <p className="mt-0.5 text-xs text-slate-600">__OB__event.description__CB__</p>
             </div>
              <span className="self-start rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                __OB__event.status.replace("_", " ")__CB__
             </span>
           </li>
          );
        __CB__)__CB__
     </ol>
   </section>
  );
__CB__
"""

# === RecommendationPanel.tsx ===
recommendation = f"""import type {{ DecisionBrief }} from "../api/client";
import {{ formatUsd, formatHours }} from "../format";

interface RecommendationPanelProps __OB__
  brief: DecisionBrief;
__CB__

export function RecommendationPanel(__OB__ brief __CB__: RecommendationPanelProps) __OB__
  const recs = brief.recommendations.filter((r) => r.applicable);
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Recommended Actions
         </h3>
          <p className="mt-1 text-xs text-slate-500">
            Ranked by net benefit. Top __OB__recs.length__CB__ applicable.
         </p>
       </div>
     </header>
      <ol className="space-y-3">
        __OB__recs.map((rec) => (
          <li key=__OB__rec.rank__CB__ className="rounded-xl border-2 border-indigo-200 bg-indigo-50/50 p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 font-bold text-white">
                __OB__rec.rank__CB__
             </div>
              <div className="flex-1 min-w-[200px]">
                <h4 className="text-base font-bold text-slate-900">__OB__rec.name__CB__</h4>
                <p className="mt-1 text-sm text-slate-700">__OB__rec.explanation__CB__</p>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <Mini label="Net benefit" value=__OB__rec.scores.net_benefit.toFixed(2)__CB__ />
                  <Mini label="Cost" value=__OB__formatUsd(rec.scores.execution_cost_usd)__CB__ />
                  <Mini label="Time" value=__OB__formatHours(rec.scores.execution_time_hours)__CB__ />
                  <Mini label="Confidence" value=__OB__rec.scores.confidence.toFixed(2)__CB__ />
                  <Mini label="Impact reduction" value=__OB__rec.scores.business_impact_reduction.toFixed(2)__CB__ />
                  <Mini label="Customer protected" value=__OB__rec.scores.customer_impact_protected.toFixed(2)__CB__ />
                  <Mini label="Op risk" value=__OB__rec.scores.operational_risk.toFixed(2)__CB__ />
                  <Mini label="Dep readiness" value=__OB__rec.scores.dependency_readiness.toFixed(2)__CB__ />
               </dl>
             </div>
           </div>
         </li>
        ))__CB__
     </ol>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Ranking Formula
       </summary>
        <p className="mt-2 leading-relaxed">__OB__brief.ranking_formula__CB__</p>
     </details>
   </section>
  );
__CB__

function Mini(__OB__ label, value __CB__: __OB__ label: string; value: string __CB__) __OB__
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">__OB__label__CB__</dt>
      <dd className="font-mono text-sm font-medium text-slate-900">__OB__value__CB__</dd>
   </div>
  );
__CB__
"""

# === EvidenceDrawer.tsx ===
evidence = f"""import __OB__ useState __CB__ from "react";
import type {{ DecisionBrief }} from "../api/client";

interface EvidenceDrawerProps __OB__
  brief: DecisionBrief;
__CB__

type Tab = "components" | "products" | "warehouses" | "orders";

export function EvidenceDrawer(__OB__ brief __CB__: EvidenceDrawerProps) __OB__
  const [tab, setTab] = useState<Tab>("components");

  const counts: Record<Tab, number> = __OB__
    components: brief.propagation.affected_components.length,
    products: brief.propagation.affected_products.length,
    warehouses: brief.propagation.affected_warehouses.length,
    orders: brief.propagation.open_orders_at_risk.length,
  __CB__;

  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Evidence</h3>
        <p className="mt-1 text-xs text-slate-500">Direct traceability from the supply-chain graph</p>
     </header>
      <div className="flex gap-2 border-b border-slate-200">
        __OB__(["components", "products", "warehouses", "orders"] as Tab[]).map((t) => (
          <button
            key=__OB__t__CB__
            type="button"
            onClick=__OB__() => setTab(t)__CB__
            className=__OB__`px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors $__OB__
              tab === t
                ? "border-b-2 border-indigo-600 text-indigo-700"
                : "text-slate-500 hover:text-slate-700"
            __CB__`__CB__
          >
            __OB__t__CB__ (__OB__counts[t]__CB__)
         </button>
        ))__CB__
     </div>
      <div className="mt-4 max-h-96 overflow-y-auto">
        __OB__tab === "components" && <ComponentsList items=__OB__brief.propagation.affected_components__CB__ />__CB__
        __OB__tab === "products" && <ProductsList items=__OB__brief.propagation.affected_products__CB__ />__CB__
        __OB__tab === "warehouses" && <WarehousesList items=__OB__brief.propagation.affected_warehouses__CB__ />__CB__
        __OB__tab === "orders" && <OrdersList items=__OB__brief.propagation.open_orders_at_risk__CB__ />__CB__
     </div>
   </section>
  );
__CB__

function ComponentsList(__OB__ items __CB__: __OB__ items: DecisionBrief["propagation"]["affected_components"] __CB__) __OB__
  if (items.length === 0) return <EmptyState />;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
        <tr>
          <th className="py-2">SKU</th>
          <th className="py-2">Name</th>
          <th className="py-2 text-right">Hop</th>
          <th className="py-2 text-right">Exposure</th>
       </tr>
     </thead>
      <tbody>
        __OB__items.map((c) => (
          <tr key=__OB__c.component_id__CB__ className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">__OB__c.sku__CB__</td>
            <td className="py-2">__OB__c.name__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__c.hop__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__(c.attenuated_exposure * 100).toFixed(1)__CB__%</td>
         </tr>
        ))__CB__
     </tbody>
   </table>
  );
__CB__

function ProductsList(__OB__ items __CB__: __OB__ items: DecisionBrief["propagation"]["affected_products"] __CB__) __OB__
  if (items.length === 0) return <EmptyState />;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
        <tr>
          <th className="py-2">SKU</th>
          <th className="py-2">Name</th>
          <th className="py-2 text-right">Qty/Unit</th>
          <th className="py-2 text-right">Hop</th>
       </tr>
     </thead>
      <tbody>
        __OB__items.map((p) => (
          <tr key=__OB__p.product_id__CB__ className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">__OB__p.sku__CB__</td>
            <td className="py-2">__OB__p.name__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__p.qty_needed_per_unit__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__p.hop__CB__</td>
         </tr>
        ))__CB__
     </tbody>
   </table>
  );
__CB__

function WarehousesList(__OB__ items __CB__: __OB__ items: DecisionBrief["propagation"]["affected_warehouses"] __CB__) __OB__
  if (items.length === 0) return <EmptyState />;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
        <tr>
          <th className="py-2">Component</th>
          <th className="py-2 text-right">Quantity</th>
          <th className="py-2 text-right">Safety Stock</th>
          <th className="py-2 text-right">Daily Usage</th>
          <th className="py-2 text-right">Coverage (days</th>
       </tr>
     </thead>
      <tbody>
        __OB__items.map((w) => (
          <tr key=__OB__`$__OB__w.warehouse_id__CB__-$__OB__w.component_id__CB__`__CB__ className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">__OB__w.component_id.slice(0, 8)__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__w.quantity__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__w.safety_stock__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__w.daily_usage__CB__</td>
            <td className="py-2 text-right tabular-nums">
              __OB__w.coverage_days === null ? "inf" : w.coverage_days.toFixed(1)__CB__
           </td>
         </tr>
        ))__CB__
     </tbody>
   </table>
  );
__CB__

function OrdersList(__OB__ items __CB__: __OB__ items: DecisionBrief["propagation"]["open_orders_at_risk"] __CB__) __OB__
  if (items.length === 0) return <EmptyState />;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
        <tr>
          <th className="py-2">Order</th>
          <th className="py-2">Customer</th>
          <th className="py-2 text-right">Quantity</th>
          <th className="py-2 text-right">Status</th>
       </tr>
     </thead>
      <tbody>
        __OB__items.map((o) => (
          <tr key=__OB__o.order_id__CB__ className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">__OB__o.order_id.slice(0, 8)__CB__</td>
            <td className="py-2 font-mono text-xs">__OB__o.customer_id.slice(0, 8)__CB__</td>
            <td className="py-2 text-right tabular-nums">__OB__o.quantity__CB__</td>
            <td className="py-2 text-right">
              <span className="rounded-full border border-slate-300 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                __OB__o.status__CB__
             </span>
           </td>
         </tr>
        ))__CB__
     </tbody>
   </table>
  );
__CB__

function EmptyState() __OB__
  return <p className="py-8 text-center text-sm text-slate-500">No items in this category</p>;
__CB__
"""

# === TrustPanel.tsx ===
trust = f"""import type {{ DecisionBrief }} from "../api/client";
import {{ confidenceLabel, formatPct }} from "../format";

interface TrustPanelProps __OB__
  brief: DecisionBrief;
__CB__

export function TrustPanel(__OB__ brief __CB__: TrustPanelProps) __OB__
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
          <div className=__OB__`text-4xl font-bold tabular-nums $__OB__overall.tone__CB__`__CB__>__OB__formatPct(c.overall)__CB__</div>
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">__OB__overall.label__CB__</div>
       </div>
     </header>
      <dl className="space-y-2">
        <Bar label="Completeness" value=__OB__c.completeness__CB__ />
        <Bar label="Freshness" value=__OB__c.freshness__CB__ />
        <Bar label="Agreement" value=__OB__c.agreement__CB__ />
        <Bar label="Conflict Density" value=__OB__c.conflict_density__CB__ />
     </dl>
      <details className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold uppercase tracking-wider text-slate-500">
          Scoring Formula
       </summary>
        <p className="mt-2 leading-relaxed">__OB__c.formula__CB__</p>
     </details>
   </section>
  );
__CB__

function Bar(__OB__ label, value __CB__: __OB__ label: string; value: number __CB__) __OB__
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <dt className="font-medium text-slate-700">__OB__label__CB__</dt>
        <dd className="font-mono tabular-nums text-slate-900">__OB__pct__CB__%</dd>
     </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-200">
        <div
          className=__OB__`h-full rounded-full transition-all $__OB__
            pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500"
          __CB__`__CB__
          style=__OB____OB__ width: `$__OB__pct__CB__%` __CB____CB__
        />
     </div>
   </div>
  );
__CB__
"""

# === RoleSwitcher.tsx ===
roleswitcher = f"""import type {{ Role }} from "../roles";
import __OB__ ROLES __CB__ from "../roles";

interface RoleSwitcherProps __OB__
  current: Role;
  onChange: (r: Role) => void;
__CB__

export function RoleSwitcher(__OB__ current, onChange __CB__: RoleSwitcherProps) __OB__
  return (
    <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
      __OB__ROLES.map((role) => __OB__
        const active = role.id === current;
        return (
          <button
            key=__OB__role.id__CB__
            type="button"
            onClick=__OB__() => onChange(role.id)__CB__
            className=__OB__`rounded-lg px-4 py-2 text-sm font-semibold transition-colors $__OB__
              active ? "bg-indigo-600 text-white shadow" : "text-slate-600 hover:bg-slate-100"
            __CB__`__CB__
            title=__OB__role.subtitle__CB__
          >
            __OB__role.label__CB__
         </button>
        );
      __CB__)__CB__
    </div>
  );
__CB__
"""

# === Main page (mvp/page.tsx) ===
page = f""""use client";

import __OB__ FormEvent, useMemo, useState __CB__ from "react";
import __OB__ ApiError __CB__ from "@/lib/api";
import __OB__ createSupplierFailureBrief, type DecisionBrief __CB__ from "@/features/morning-brief/api/client";
import __OB__ CriticalAlertCard __CB__ from "@/features/morning-brief/components/CriticalAlertCard";
import __OB__ ImpactCard __CB__ from "@/features/morning-brief/components/ImpactCard";
import __OB__ Timeline __CB__ from "@/features/morning-brief/components/Timeline";
import __OB__ RecommendationPanel __CB__ from "@/features/morning-brief/components/RecommendationPanel";
import __OB__ EvidenceDrawer __CB__ from "@/features/morning-brief/components/EvidenceDrawer";
import __OB__ TrustPanel __CB__ from "@/features/morning-brief/components/TrustPanel";
import __OB__ RoleSwitcher __CB__ from "@/features/morning-brief/components/RoleSwitcher";
import __OB__ getRole, type Role __CB__ from "@/features/morning-brief/roles";

type Section = "critical" | "financial" | "operational" | "timeline" | "recommendations" | "evidence" | "trust";

export default function MorningBriefPage() __OB__
  const [workspaceId, setWorkspaceId] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [brief, setBrief] = useState<DecisionBrief | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState<Role>("cfo");
  const roleConfig = useMemo(() => getRole(role), [role]);

  async function run(event: FormEvent) __OB__
    event.preventDefault();
    setLoading(true);
    setError("");
    try __OB__
      setBrief(
        await createSupplierFailureBrief(__OB__
          workspace_id: workspaceId,
          supplier_id: supplierId,
          severity: "critical",
        __CB__),
      );
    __CB__ catch (err) __OB__
      setError(err instanceof ApiError ? err.detail : "Unable to compute the Decision Brief.");
    __CB__ finally __OB__
      setLoading(false);
    __CB__
  __CB__

  const sections = useMemo(() => __OB__
    if (!brief) return [] as Section[];
    return roleConfig.ordering;
  __CB__, [brief, roleConfig]);

  return (
    <main className="mx-auto max-w-7xl p-6 sm:p-8">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
          Cortex / Morning Brief
       </p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Supplier Disruption Decision Brief</h1>
            <p className="mt-1 text-sm text-slate-600">
              __OB__roleConfig.subtitle__CB__. One screen, one decision, deterministic math.
           </p>
         </div>
          <RoleSwitcher current=__OB__role__CB__ onChange=__OB__setRole__CB__ />
       </div>
     </header>

      <form
        onSubmit=__OB__run__CB__
        className="mb-6 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[1fr_1fr_auto]"
      >
        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">
            Workspace UUID
         </span>
          <input
            required
            value=__OB__workspaceId__CB__
            onChange=__OB__(e) => setWorkspaceId(e.target.value)__CB__
            placeholder="e.g. 55555555-5555-5555-5555-555555555555"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
       </label>
        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">
            Supplier UUID
         </span>
          <input
            required
            value=__OB__supplierId__CB__
            onChange=__OB__(e) => setSupplierId(e.target.value)__CB__
            placeholder="e.g. aaaaaaa1-0000-0000-0000-000000000001"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
       </label>
        <button
          type="submit"
          disabled=__OB__loading__CB__
          className="self-end rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-60"
        >
          __OB__loading ? "Computing..." : "Supplier fails"__CB__
       </button>
     </form>

      __OB__error && (
        <div className="mb-6 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">__OB__error__CB__</div>
      )__CB__

      __OB__brief && (
        <div className="space-y-6">
          __OB__sections.map((section) => __OB__
            switch (section) __OB__
              case "critical":
                return <CriticalAlertCard key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "financial":
                return <ImpactCard key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "operational":
                return <ImpactCard key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "timeline":
                return <Timeline key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "recommendations":
                return <RecommendationPanel key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "evidence":
                return <EvidenceDrawer key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              case "trust":
                return <TrustPanel key=__OB__section__CB__ brief=__OB__brief__CB__ />;
              default:
                return null;
            __CB__
          __CB__)__CB__
       </div>
      )__CB__

      __OB__!brief && !error && !loading && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <p className="text-sm font-semibold text-slate-700">No brief yet</p>
          <p className="mt-1 text-xs text-slate-500">
            Enter a workspace UUID and a supplier UUID, then click <b>Supplier fails</b> to compute the brief.
         </p>
       </div>
      )__CB__
   </main>
  );
__CB__
"""

# Write all files
files = {
    ROOT / "components" / "CriticalAlertCard.tsx": critical,
    ROOT / "components" / "ImpactCard.tsx": impact,
    ROOT / "components" / "Timeline.tsx": timeline,
    ROOT / "components" / "RecommendationPanel.tsx": recommendation,
    ROOT / "components" / "EvidenceDrawer.tsx": evidence,
    ROOT / "components" / "TrustPanel.tsx": trust,
    ROOT / "components" / "RoleSwitcher.tsx": roleswitcher,
    PAGE: page,
}

for path, content in files.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    final = content.replace("__CB__", CB).replace("__OB__", OB)
    path.write_text(final, encoding="utf-8")
    opens = final.count(OB)
    closes = final.count(CB)
    bal = "OK" if opens == closes else "UNBALANCED"
    print(f"{path.name}: {len(final)} chars, {{={opens}, }}={closes}, {bal}")
