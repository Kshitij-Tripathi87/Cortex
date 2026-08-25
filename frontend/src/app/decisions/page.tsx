"use client";

import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge, StatusBadge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@/lib/api";

interface Decision { decision_id: string; decision_type: string; decision_status: string; reviewer_id: string; rationale: string; scenario_id: string; selected_recommendation_id?: string; created_at: string; }
interface DecisionDetail { decision: Decision; outcomes: { outcome_id: string; outcome_status: string; outcome_summary: string; created_at: string }[]; lessons: { lesson_id: string; category: string; title: string; description: string }[]; }

const DECISION_TYPES = ["approve_recommendation", "approve_with_modification", "reject_recommendation", "defer_decision", "request_more_evidence", "escalate_for_review", "no_action_monitor"];
const DECISION_STATUS = ["pending", "approved", "rejected", "deferred", "escalated", "implemented", "closed"];

export default function DecisionsPage() {
  const [workspaceId] = useWorkspace();
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<DecisionDetail | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showOutcome, setShowOutcome] = useState(false);
  const [formData, setFormData] = useState({ scenario_id: "", recommendation_snapshot_id: "", decision_type: "approve_recommendation", reviewer_id: "", rationale: "" });
  const [outcomeData, setOutcomeData] = useState({ outcome_status: "success", outcome_summary: "", recorded_by: "" });

  const fetchDecisions = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const data = await api.get<Decision[]>("/api/v1/graph/decisions", { workspace_id: workspaceId });
      setDecisions(data);
    } catch (e) { setError(e); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { fetchDecisions(); }, [fetchDecisions]);

  const createDecision = async () => {
    try {
      await api.post("/api/v1/graph/decisions", { ...formData, workspace_id: workspaceId });
      setShowCreate(false);
      fetchDecisions();
    } catch (e) { alert("Failed: " + e); }
  };

  const addOutcome = async (decisionId: string) => {
    try {
      await api.post(`/api/v1/graph/decisions/${decisionId}/outcomes?workspace_id=${workspaceId}`, outcomeData);
      setShowOutcome(false);
      fetchDecisions();
    } catch (e) { alert("Failed: " + e); }
  };

  const viewDetail = async (id: string) => {
    try {
      const data = await api.get<DecisionDetail>(`/api/v1/graph/decisions/${id}`, { workspace_id: workspaceId });
      setSelected(data);
    } catch (e) { alert("Failed: " + e); }
  };

  const getTypeVariant = (t: string) => t.includes("approve") ? "success" : t.includes("reject") ? "error" : t.includes("defer") ? "warning" : "neutral";

  return (
    <div>
      <PageHeader title="Decision Memory" description="Record decisions with rationale, outcomes, and lessons" actions={<button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Create Decision</button>} />
      {loading ? <LoadingState message="Loading decisions..." /> : error ? <ErrorState error={error} onRetry={fetchDecisions} /> : decisions.length === 0 ? <EmptyState title="No decisions yet" description="Create your first decision to start tracking outcomes" /> : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reviewer</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rationale</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th></tr></thead>
            <tbody className="divide-y divide-gray-200">
              {decisions.map((d) => (
                <tr key={d.decision_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm"><Badge variant={getTypeVariant(d.decision_type)}>{d.decision_type.replace(/_/g, " ")}</Badge></td>
                  <td className="px-4 py-3 text-sm"><StatusBadge status={d.decision_status} /></td>
                  <td className="px-4 py-3 text-sm font-mono text-xs">{d.reviewer_id}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 truncate max-w-xs">{d.rationale}</td>
                  <td className="px-4 py-3 text-sm text-xs">{new Date(d.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-sm"><button onClick={() => viewDetail(d.decision_id)} className="text-blue-600 hover:text-blue-800">View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showCreate && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-lg w-full">
            <h3 className="text-lg font-semibold mb-4">Create Decision</h3>
            <div className="space-y-3">
              <input placeholder="Scenario ID" value={formData.scenario_id} onChange={(e) => setFormData({ ...formData, scenario_id: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" />
              <input placeholder="Recommendation Snapshot ID" value={formData.recommendation_snapshot_id} onChange={(e) => setFormData({ ...formData, recommendation_snapshot_id: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" />
              <select value={formData.decision_type} onChange={(e) => setFormData({ ...formData, decision_type: e.target.value })} className="w-full border rounded px-3 py-2 text-sm">{DECISION_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}</select>
              <input placeholder="Reviewer ID" value={formData.reviewer_id} onChange={(e) => setFormData({ ...formData, reviewer_id: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" />
              <textarea placeholder="Rationale" value={formData.rationale} onChange={(e) => setFormData({ ...formData, rationale: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" rows={3} />
              <div className="flex justify-end gap-2"><button onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm border rounded">Cancel</button><button onClick={createDecision} className="px-4 py-2 bg-blue-600 text-white text-sm rounded">Create</button></div>
            </div>
          </div>
        </div>
      )}
      {selected && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-start justify-center z-50 overflow-y-auto p-8" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-3xl w-full my-8" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Decision Details</h3>
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-4"><div><span className="font-medium">Type:</span> <Badge>{selected.decision.decision_type.replace(/_/g, " ")}</Badge></div><div><span className="font-medium">Status:</span> <StatusBadge status={selected.decision.decision_status} /></div></div>
              <div><span className="font-medium">Rationale:</span> <p className="text-gray-700 bg-gray-50 p-2 rounded">{selected.decision.rationale}</p></div>
              <div><span className="font-medium">Outcomes ({selected.outcomes.length})</span><button onClick={() => setShowOutcome(true)} className="ml-2 text-blue-600 text-xs">+ Add</button>
                <div className="space-y-2 mt-2">{selected.outcomes.map((o) => <div key={o.outcome_id} className="p-3 border rounded"><div className="flex justify-between"><StatusBadge status={o.outcome_status} /><span className="text-xs text-gray-500">{new Date(o.created_at).toLocaleDateString()}</span></div><p className="text-sm text-gray-700 mt-1">{o.outcome_summary}</p></div>)}</div>
              </div>
              <div><span className="font-medium">Lessons ({selected.lessons.length})</span><div className="space-y-2 mt-2">{selected.lessons.map((l) => <div key={l.lesson_id} className="p-3 border rounded"><div className="flex justify-between"><Badge>{l.category.replace(/_/g, " ")}</Badge><span className="font-medium">{l.title}</span></div><p className="text-sm text-gray-700 mt-1">{l.description}</p></div>)}</div></div>
            </div>
            <div className="flex justify-end mt-4"><button onClick={() => setSelected(null)} className="px-4 py-2 bg-gray-200 rounded text-sm">Close</button></div>
          </div>
        </div>
      )}
      {showOutcome && selected && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
            <h3 className="text-lg font-semibold mb-4">Add Outcome</h3>
            <div className="space-y-3">
              <select value={outcomeData.outcome_status} onChange={(e) => setOutcomeData({ ...outcomeData, outcome_status: e.target.value })} className="w-full border rounded px-3 py-2 text-sm"><option value="success">Success</option><option value="partial_success">Partial Success</option><option value="failed">Failed</option><option value="no_impact">No Impact</option></select>
              <textarea placeholder="Summary" value={outcomeData.outcome_summary} onChange={(e) => setOutcomeData({ ...outcomeData, outcome_summary: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" rows={3} />
              <input placeholder="Recorded By" value={outcomeData.recorded_by} onChange={(e) => setOutcomeData({ ...outcomeData, recorded_by: e.target.value })} className="w-full border rounded px-3 py-2 text-sm" />
              <div className="flex justify-end gap-2"><button onClick={() => setShowOutcome(false)} className="px-4 py-2 text-sm border rounded">Cancel</button><button onClick={() => addOutcome(selected.decision.decision_id)} className="px-4 py-2 bg-blue-600 text-white text-sm rounded">Add</button></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}