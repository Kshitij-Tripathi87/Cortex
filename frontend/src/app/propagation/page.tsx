"use client";

import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge, SeverityBadge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@/lib/api";

interface Signal { signal_id: string; signal_name: string; affected_node_ids: string[]; severity: string; }
interface PropagationResult { propagation_id: string; source_signal_id: string; source_node_id: string; tree: { steps: { affected_node_id: string; affected_entity_id: string; affected_entity_type: string; hop_number: number; impact_type: string; impact_severity: string; impact_reason: string; relationship_type: string }[] }; affected_entities: { node_id: string; entity_id: string; entity_type: string; hop_number: number; impact_type: string; impact_severity: string; confidence: number; impact_reason: string }[]; summary: { total_affected: number; by_impact_type: Record<string, number>; by_severity: Record<string, number>; by_entity_type: Record<string, number>; max_hop: number; avg_confidence: number; min_confidence: number }; execution_time_ms: number; rules_applied: string[]; }

export default function PropagationPage() {
  const [workspaceId] = useWorkspace();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [selectedSignalId, setSelectedSignalId] = useState("");
  const [sourceNodeId, setSourceNodeId] = useState("");
  const [maxDepth, setMaxDepth] = useState(5);
  const [minConfidence, setMinConfidence] = useState(0.1);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PropagationResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  const fetchSignals = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const data = await api.get<{ signals: Signal[] }>("/api/v1/graph/signals", { workspace_id: workspaceId });
      setSignals(data.signals);
      if (data.signals.length > 0) {
        setSelectedSignalId(data.signals[0].signal_id);
        setSourceNodeId(data.signals[0].affected_node_ids[0] || "");
      }
    } catch (e) { setError(e); }
  }, [workspaceId]);

  useEffect(() => {
    fetchSignals();
  }, [fetchSignals]);

  const runPropagation = async () => {
    if (!selectedSignalId || !sourceNodeId) return;
    setRunning(true);
    setError(null);
    try {
      const data = await api.post<PropagationResult>("/api/v1/graph/propagate", { workspace_id: workspaceId, source_signal_id: selectedSignalId, source_node_id: sourceNodeId, max_depth: maxDepth, min_confidence: minConfidence });
      setResult(data);
    } catch (e) { setError(e); }
    finally { setRunning(false); }
  };

  return (
    <div>
      <PageHeader title="Propagation" description="Run impact propagation from a signal across the operational graph" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-1 bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Propagation Settings</h3>
          <div className="space-y-3">
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Signal</label><select value={selectedSignalId} onChange={(e) => { setSelectedSignalId(e.target.value); const sig = signals.find((s) => s.signal_id === e.target.value); if (sig) setSourceNodeId(sig.affected_node_ids[0] || ""); }} className="w-full border border-gray-300 rounded px-3 py-2 text-sm">{signals.map((s) => <option key={s.signal_id} value={s.signal_id}>{s.signal_name} ({s.severity})</option>)}</select></div>
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Source Node ID</label><input type="text" value={sourceNodeId} onChange={(e) => setSourceNodeId(e.target.value)} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" /></div>
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Max Depth: {maxDepth}</label><input type="range" min="1" max="20" value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} className="w-full" /></div>
            <div><label className="block text-sm font-medium text-gray-700 mb-1">Min Confidence: {minConfidence.toFixed(2)}</label><input type="range" min="0" max="1" step="0.05" value={minConfidence} onChange={(e) => setMinConfidence(Number(e.target.value))} className="w-full" /></div>
            <button onClick={runPropagation} disabled={!selectedSignalId || !sourceNodeId || running} className="w-full px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">{running ? "Running..." : "Run Propagation"}</button>
          </div>
        </div>
        <div className="lg:col-span-2">
          {running ? <LoadingState message="Running propagation..." /> : error ? <ErrorState error={error} onRetry={runPropagation} /> : !result ? <EmptyState title="No propagation run yet" description="Select a signal and run propagation to see impact analysis" /> : (
            <div className="space-y-4">
              <div className="bg-white rounded-lg shadow p-4">
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Summary</h3>
                <div className="grid grid-cols-4 gap-4 text-center"><div><div className="text-2xl font-bold text-blue-600">{result.summary.total_affected}</div><div className="text-xs text-gray-500">Affected Entities</div></div><div><div className="text-2xl font-bold">{result.summary.max_hop}</div><div className="text-xs text-gray-500">Max Hop</div></div><div><div className="text-2xl font-bold">{(result.summary.avg_confidence * 100).toFixed(0)}%</div><div className="text-xs text-gray-500">Avg Confidence</div></div><div><div className="text-2xl font-bold">{result.execution_time_ms.toFixed(0)}</div><div className="text-xs text-gray-500">Execution (ms)</div></div></div>
              </div>
              <div className="bg-white rounded-lg shadow p-4">
                <h3 className="text-sm font-semibold text-gray-700 mb-2">By Severity</h3>
                <div className="flex gap-2 flex-wrap">{Object.entries(result.summary.by_severity).map(([sev, count]) => (
                  <span key={sev} className="inline-flex items-center gap-1">
                    <SeverityBadge severity={sev} />
                    <span className="text-xs text-gray-500">({count})</span>
                  </span>
                ))}</div>
              </div>
              <div className="bg-white rounded-lg shadow overflow-hidden">
                <h3 className="text-sm font-semibold text-gray-700 p-3 border-b">Affected Entities</h3>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50"><tr><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Entity</th><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Hop</th><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Impact</th><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Severity</th><th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Confidence</th></tr></thead>
                  <tbody className="divide-y divide-gray-200">
                    {result.affected_entities.sort((a, b) => a.hop_number - b.hop_number).slice(0, 50).map((e) => (
                      <tr key={e.node_id}><td className="px-4 py-2 text-sm font-mono">{e.entity_id}</td><td className="px-4 py-2 text-sm"><Badge>{e.entity_type}</Badge></td><td className="px-4 py-2 text-sm">{e.hop_number}</td><td className="px-4 py-2 text-sm"><Badge variant="neutral">{e.impact_type}</Badge></td><td className="px-4 py-2 text-sm"><SeverityBadge severity={e.impact_severity} /></td><td className="px-4 py-2 text-sm">{(e.confidence * 100).toFixed(0)}%</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}