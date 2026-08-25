"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge, SeverityBadge, StatusBadge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@/lib/api";

const SCENARIO_TYPES = ["supplier_failure", "warehouse_outage", "route_closure", "shipment_delay", "demand_spike", "demand_drop", "inventory_shortage", "capacity_constraint", "custom"];

export default function ScenariosPage() {
  const [workspaceId] = useWorkspace();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenarioType, setScenarioType] = useState("supplier_failure");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);
  const [history, setHistory] = useState<any[]>([]);

  const runScenario = async () => {
    if (!name) return;
    setRunning(true);
    setError(null);
    try {
      const data = await api.post<{ snapshot: any }>("/api/v1/graph/scenarios", { workspace_id: workspaceId, scenario_definition: { scenario_id: `scenario-${Date.now()}`, workspace_id: workspaceId, scenario_type: scenarioType, name, description, parameters: [] }, dry_run: false });
      setResult(data.snapshot);
      setHistory((h) => [data.snapshot, ...h]);
    } catch (e) { setError(e); }
    finally { setRunning(false); }
  };

  const getConfidenceColor = (c: number) => c > 0.8 ? "bg-green-500" : c > 0.5 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div>
      <PageHeader title="Scenarios" description="Run what-if scenario simulations" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Scenario Definition</h3>
          <div className="space-y-3">
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Name *</label><input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full border border-gray-300 rounded px-3 py-2 text-sm" /></div>
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Description</label><textarea value={description} onChange={(e) => setDescription(e.target.value)} className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={3} /></div>
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Type</label><select value={scenarioType} onChange={(e) => setScenarioType(e.target.value)} className="w-full border border-gray-300 rounded px-3 py-2 text-sm">{SCENARIO_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}</option>)}</select></div>
            <button onClick={runScenario} disabled={!name || running} className="w-full px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">{running ? "Running..." : "Run Scenario"}</button>
          </div>
        </div>
        <div>
          {running ? <LoadingState message="Running scenario..." /> : error ? <ErrorState error={error} onRetry={runScenario} /> : result ? (
            <div className="space-y-4">
              <div className="bg-white rounded-lg shadow p-4"><div className="flex items-center justify-between mb-2"><h3 className="text-sm font-semibold">{result.scenario_definition.name}</h3><StatusBadge status={result.status} /></div><div className="grid grid-cols-2 gap-3 text-sm"><div><span className="text-gray-500">Type:</span> <Badge>{result.scenario_definition.scenario_type}</Badge></div><div><span className="text-gray-500">Impacted:</span> <span className="font-semibold">{result.summary.total_impacted_entities}</span></div><div><span className="text-gray-500">Max Hop:</span> {result.summary.max_hop}</div><div><span className="text-gray-500">Recovery:</span> {result.summary.total_estimated_recovery_hours.toFixed(1)}h</div><div><span className="text-gray-500">Financial:</span> ${result.summary.total_estimated_financial_impact.toFixed(0)}</div><div><span className="text-gray-500">SL Impact:</span> {result.summary.max_service_level_impact_pct.toFixed(1)}%</div></div></div>
              <div className="bg-white rounded-lg shadow p-4"><h4 className="text-sm font-semibold mb-2">By Severity</h4><div className="flex gap-2 flex-wrap">{Object.entries(result.summary.by_severity).map(([s, c]) => <span key={s}><SeverityBadge severity={s} /> ({Number(c)})</span>)}</div></div>
              <div className="bg-white rounded-lg shadow overflow-hidden"><h4 className="text-sm font-semibold p-3 border-b">Impacts</h4><table className="min-w-full"><thead className="bg-gray-50"><tr><th className="px-3 py-2 text-left text-xs text-gray-500">Entity</th><th className="px-3 py-2 text-left text-xs text-gray-500">Type</th><th className="px-3 py-2 text-left text-xs text-gray-500">Severity</th><th className="px-3 py-2 text-left text-xs text-gray-500">Recovery</th></tr></thead><tbody>{result.impacts.slice(0, 20).map((i: any) => <tr key={i.affected_entity_id}><td className="px-3 py-2 text-sm font-mono">{i.affected_entity_id}</td><td className="px-3 py-2 text-sm"><Badge>{i.affected_entity_type}</Badge></td><td className="px-3 py-2 text-sm"><SeverityBadge severity={i.severity} /></td><td className="px-3 py-2 text-sm">{i.estimated_recovery_hours?.toFixed(1) || "—"}h</td></tr>)}</tbody></table></div>
            </div>
          ) : history.length > 0 ? (
            <div className="space-y-2"><h3 className="text-sm font-semibold text-gray-700 mb-2">Recent Scenarios</h3>{history.map((h) => <div key={h.scenario_id} onClick={() => setResult(h)} className="p-3 bg-white rounded shadow cursor-pointer hover:bg-gray-50"><div className="flex justify-between items-center"><span className="text-sm font-medium">{h.scenario_definition.name}</span><StatusBadge status={h.status} /></div><div className="text-xs text-gray-500">{h.scenario_definition.scenario_type} • {new Date(h.created_at).toLocaleString()}</div></div>)}</div>
          ) : <EmptyState title="No scenarios yet" description="Define a scenario on the left and run it to see effects" action={<a href="/graph" className="text-blue-600 hover:text-blue-800 text-sm">Go to Graph</a>} />}
        </div>
      </div>
    </div>
  );
}