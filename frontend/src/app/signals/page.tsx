"use client";

import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge, SeverityBadge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@/lib/api";

interface Signal { signal_id: string; signal_name: string; signal_version: string; severity: string; confidence: number; category: string; affected_node_ids: string[]; affected_entity_types: string[]; affected_entity_ids: string[]; explanation: string; feature_evidence: Record<string, number>; created_at: string; }
interface SignalResponse { workspace_id: string; signals: Signal[]; metadata: Record<string, any>; }

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 };
const severityRank = (s: string) => SEVERITY_ORDER[s] ?? 99;
const CATEGORY_MAP: Record<string, string> = { concentration: "Concentration", bottleneck: "Bottleneck", isolation: "Isolation", criticality: "Criticality", spof: "Single Point of Failure" };

export default function SignalsPage() {
  const [workspaceId] = useWorkspace();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [severityFilter, setSeverityFilter] = useState("All");
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [metadata, setMetadata] = useState<Record<string, any>>({});

  const fetchSignals = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<SignalResponse>("/api/v1/graph/signals", { workspace_id: workspaceId });
      setSignals(data.signals);
      setMetadata(data.metadata);
    } catch (e) { setError(e); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { fetchSignals(); }, [fetchSignals]);

  const filteredSignals = signals.filter((s) => {
    if (severityFilter !== "All" && s.severity !== severityFilter) return false;
    if (categoryFilter !== "All" && s.category !== categoryFilter.toLowerCase()) return false;
    return true;
  });

  const severityCounts = { info: signals.filter((s) => s.severity === "info").length, warning: signals.filter((s) => s.severity === "warning").length, critical: signals.filter((s) => s.severity === "critical").length };
  const categories = Array.from(new Set(signals.map((s) => s.category)));

  const getConfidenceColor = (conf: number) => conf > 0.8 ? "bg-green-500" : conf > 0.5 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div>
      <PageHeader title="Signals" description="Operational signals detected from graph features" actions={<button onClick={fetchSignals} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Refresh</button>} />
      <div className="mb-6 grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg shadow p-4"><div className="text-2xl font-bold text-blue-600">{severityCounts.info}</div><div className="text-sm text-gray-500">Info Signals</div></div>
        <div className="bg-white rounded-lg shadow p-4"><div className="text-2xl font-bold text-yellow-600">{severityCounts.warning}</div><div className="text-sm text-gray-500">Warning Signals</div></div>
        <div className="bg-white rounded-lg shadow p-4"><div className="text-2xl font-bold text-red-600">{severityCounts.critical}</div><div className="text-sm text-gray-500">Critical Signals</div></div>
      </div>
      <div className="mb-4 flex gap-4">
        <div className="flex items-center gap-2"><label className="text-sm text-gray-600">Severity:</label><select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} className="border border-gray-300 rounded px-3 py-1.5 text-sm"><option>All</option><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></div>
        <div className="flex items-center gap-2"><label className="text-sm text-gray-600">Category:</label><select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="border border-gray-300 rounded px-3 py-1.5 text-sm"><option>All</option>{categories.map((c) => <option key={c} value={c}>{CATEGORY_MAP[c] || c}</option>)}</select></div>
      </div>
      {loading ? <LoadingState message="Loading signals..." /> : error ? <ErrorState error={error} onRetry={fetchSignals} /> : filteredSignals.length === 0 ? <EmptyState title="No signals" description="No operational signals detected for this workspace" /> : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Signal</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Severity</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Confidence</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Affected</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th></tr></thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredSignals.sort((a, b) => severityRank(a.severity) - severityRank(b.severity)).map((s) => (
                <tr key={s.signal_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm"><div className="font-medium">{s.signal_name}</div><div className="text-xs text-gray-500 font-mono">{s.signal_version}</div></td>
                  <td className="px-4 py-3 text-sm"><SeverityBadge severity={s.severity} /></td>
                  <td className="px-4 py-3 text-sm"><Badge>{CATEGORY_MAP[s.category] || s.category}</Badge></td>
                  <td className="px-4 py-3 text-sm"><div className="flex items-center gap-2"><div className="w-24 bg-gray-200 rounded h-2"><div className={`h-2 rounded ${getConfidenceColor(s.confidence)}`} style={{ width: `${s.confidence * 100}%` }} /></div><span className="text-xs font-mono">{(s.confidence * 100).toFixed(0)}%</span></div></td>
                  <td className="px-4 py-3 text-sm"><div className="flex gap-1 flex-wrap">{s.affected_entity_types.slice(0, 3).map((t) => <Badge key={t} variant="neutral">{t}</Badge>)}{s.affected_entity_types.length > 3 && <Badge variant="neutral">+{s.affected_entity_types.length - 3}</Badge>}</div></td>
                  <td className="px-4 py-3 text-sm text-xs">{new Date(s.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-sm"><button onClick={() => setSelectedSignal(s)} className="text-blue-600 hover:text-blue-800">View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selectedSignal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setSelectedSignal(null)}>
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-3xl w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Signal Details</h3>
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-4"><div><span className="font-medium">Signal ID:</span> <span className="font-mono text-xs">{selectedSignal.signal_id}</span></div><div><span className="font-medium">Name:</span> {selectedSignal.signal_name}</div></div>
              <div className="grid grid-cols-3 gap-4"><div><span className="font-medium">Severity:</span> <SeverityBadge severity={selectedSignal.severity} /></div><div><span className="font-medium">Category:</span> <Badge>{CATEGORY_MAP[selectedSignal.category] || selectedSignal.category}</Badge></div><div><span className="font-medium">Confidence:</span> {(selectedSignal.confidence * 100).toFixed(1)}%</div></div>
              <div><h4 className="font-semibold mb-2">Explanation</h4><p className="text-gray-700 bg-gray-50 p-3 rounded">{selectedSignal.explanation}</p></div>
              <div><h4 className="font-semibold mb-2">Feature Evidence</h4><div className="space-y-1">{Object.entries(selectedSignal.feature_evidence).sort((a, b) => b[1] - a[1]).map(([k, v]) => <div key={k} className="flex justify-between text-xs"><span className="font-mono">{k}</span><span className="font-mono">{v.toFixed(4)}</span></div>)}</div></div>
              <div><h4 className="font-semibold mb-2">Affected Nodes ({selectedSignal.affected_node_ids.length})</h4><div className="flex flex-wrap gap-1">{selectedSignal.affected_node_ids.slice(0, 10).map((id) => <Badge key={id} variant="neutral">{id.slice(0, 8)}...</Badge>)}{selectedSignal.affected_node_ids.length > 10 && <Badge variant="neutral">+{selectedSignal.affected_node_ids.length - 10} more</Badge>}</div></div>
              <div><h4 className="font-semibold mb-2">Affected Entities ({selectedSignal.affected_entity_ids.length})</h4><div className="flex flex-wrap gap-1">{selectedSignal.affected_entity_ids.slice(0, 10).map((id) => <Badge key={id} variant="neutral">{id.slice(0, 12)}...</Badge>)}{selectedSignal.affected_entity_ids.length > 10 && <Badge variant="neutral">+{selectedSignal.affected_entity_ids.length - 10} more</Badge>}</div></div>
            </div>
            <div className="flex justify-end mt-4"><button onClick={() => setSelectedSignal(null)} className="px-4 py-2 bg-gray-200 rounded text-sm hover:bg-gray-300">Close</button></div>
          </div>
        </div>
      )}
    </div>
  );
}