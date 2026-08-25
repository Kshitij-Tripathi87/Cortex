import { useState } from "react";
import type { DecisionBrief } from "../api/client";

interface EvidenceDrawerProps {
  brief: DecisionBrief;
}

type Tab = "components" | "products" | "warehouses" | "orders";

export function EvidenceDrawer({ brief }: EvidenceDrawerProps) {
  const [tab, setTab] = useState<Tab>("components");

  const counts: Record<Tab, number> = {
    components: brief.propagation.affected_components.length,
    products: brief.propagation.affected_products.length,
    warehouses: brief.propagation.affected_warehouses.length,
    orders: brief.propagation.open_orders_at_risk.length,
  };

  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Evidence</h3>
        <p className="mt-1 text-xs text-slate-500">Direct traceability from the supply-chain graph</p>
     </header>
      <div className="flex gap-2 border-b border-slate-200">
        {(["components", "products", "warehouses", "orders"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors ${
              tab === t
                ? "border-b-2 border-indigo-600 text-indigo-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t} ({counts[t]})
         </button>
        ))}
     </div>
      <div className="mt-4 max-h-96 overflow-y-auto">
        {tab === "components" && <ComponentsList items={brief.propagation.affected_components} />}
        {tab === "products" && <ProductsList items={brief.propagation.affected_products} />}
        {tab === "warehouses" && <WarehousesList items={brief.propagation.affected_warehouses} />}
        {tab === "orders" && <OrdersList items={brief.propagation.open_orders_at_risk} />}
     </div>
   </section>
  );
}

function ComponentsList({ items }: { items: DecisionBrief["propagation"]["affected_components"] }) {
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
        {items.map((c) => (
          <tr key={c.component_id} className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">{c.sku}</td>
            <td className="py-2">{c.name}</td>
            <td className="py-2 text-right tabular-nums">{c.hop}</td>
            <td className="py-2 text-right tabular-nums">{(c.attenuated_exposure * 100).toFixed(1)}%</td>
         </tr>
        ))}
     </tbody>
   </table>
  );
}

function ProductsList({ items }: { items: DecisionBrief["propagation"]["affected_products"] }) {
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
        {items.map((p) => (
          <tr key={p.product_id} className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">{p.sku}</td>
            <td className="py-2">{p.name}</td>
            <td className="py-2 text-right tabular-nums">{p.qty_needed_per_unit}</td>
            <td className="py-2 text-right tabular-nums">{p.hop}</td>
         </tr>
        ))}
     </tbody>
   </table>
  );
}

function WarehousesList({ items }: { items: DecisionBrief["propagation"]["affected_warehouses"] }) {
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
        {items.map((w) => (
          <tr key={`${w.warehouse_id}-${w.component_id}`} className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">{w.component_id.slice(0, 8)}</td>
            <td className="py-2 text-right tabular-nums">{w.quantity}</td>
            <td className="py-2 text-right tabular-nums">{w.safety_stock}</td>
            <td className="py-2 text-right tabular-nums">{w.daily_usage}</td>
            <td className="py-2 text-right tabular-nums">
              {w.coverage_days === null ? "inf" : w.coverage_days.toFixed(1)}
           </td>
         </tr>
        ))}
     </tbody>
   </table>
  );
}

function OrdersList({ items }: { items: DecisionBrief["propagation"]["open_orders_at_risk"] }) {
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
        {items.map((o) => (
          <tr key={o.order_id} className="border-t border-slate-100">
            <td className="py-2 font-mono text-xs">{o.order_id.slice(0, 8)}</td>
            <td className="py-2 font-mono text-xs">{o.customer_id.slice(0, 8)}</td>
            <td className="py-2 text-right tabular-nums">{o.quantity}</td>
            <td className="py-2 text-right">
              <span className="rounded-full border border-slate-300 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                {o.status}
             </span>
           </td>
         </tr>
        ))}
     </tbody>
   </table>
  );
}

function EmptyState() {
  return <p className="py-8 text-center text-sm text-slate-500">No items in this category</p>;
}
