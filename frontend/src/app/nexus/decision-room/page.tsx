"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

type Envelope<T> = { data?: T };

interface Decision {
  decision_id: string;
  phase?: string;
  title?: string;
  situation?: string;
  recommended_option?: string;
  world_state_version?: number;
  world_state_hash?: string;
  [key: string]: unknown;
}

interface EvidenceGraph {
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  node_count?: number;
  edge_count?: number;
}

interface DecisionReceipt {
  receipt_version?: string;
  transitions?: Array<Record<string, unknown>>;
  scenarios?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown>;
}

export default function DecisionRoomPage() {
  const { status, workspace } = useAuth();
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selected, setSelected] = useState<Decision | null>(null);
  const [evidence, setEvidence] = useState<EvidenceGraph | null>(null);
  const [approvals, setApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [receipt, setReceipt] = useState<DecisionReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [outcomeText, setOutcomeText] = useState("");
  const [receiptReload, setReceiptReload] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "AUTHENTICATED" || !workspace?.id) return;
    let cancelled = false;
    void apiClient
      .get<Envelope<{ decisions?: Decision[] }>>("/nexus/decisions", {
        workspace_id: workspace.id,
      })
      .then((response) => {
        if (cancelled) return;
        const items = response.data?.decisions ?? [];
        setDecisions(items);
        setSelected(items[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("Decisions are unavailable for this workspace.");
      });
    return () => {
      cancelled = true;
    };
  }, [status, workspace?.id]);

  useEffect(() => {
    if (!selected?.decision_id) {
      setEvidence(null);
      setApprovals([]);
      setReceipt(null);
      return;
    }
    let cancelled = false;
    const decisionId = encodeURIComponent(selected.decision_id);
    void Promise.all([
      apiClient.get<Envelope<EvidenceGraph>>(`/nexus/decisions/${decisionId}/evidence`),
      apiClient.get<Envelope<{ approvals?: Array<Record<string, unknown>> }>>(
        `/nexus/decisions/${decisionId}/approvals`,
      ),
      apiClient.get<Envelope<{ receipt?: DecisionReceipt }>>(
        `/nexus/decisions/${decisionId}/receipt`,
      ),
    ])
      .then(([evidenceResponse, approvalResponse, receiptResponse]) => {
        if (cancelled) return;
        setEvidence(evidenceResponse.data ?? null);
        setApprovals(approvalResponse.data?.approvals ?? []);
        setReceipt(receiptResponse.data?.receipt ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("Evidence or approval history is unavailable.");
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.decision_id, receiptReload]);

  const advance = async (targetPhase: "approved" | "rejected") => {
    if (!selected || !workspace?.id) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiClient.post<Envelope<{ decision?: Decision }>>(
        `/nexus/decisions/${encodeURIComponent(selected.decision_id)}/advance`,
        { target_phase: targetPhase },
        { query: { workspace_id: workspace.id } },
      );
      const decision = response.data?.decision;
      if (decision) {
        setSelected(decision);
        setDecisions((current) => current.map((item) => item.decision_id === decision.decision_id ? decision : item));
      }
      setNotice(`Decision ${targetPhase}.`);
      setReceiptReload((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision transition failed");
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (!selected || !workspace?.id) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiClient.post<Envelope<{ decision?: Decision }>>(
        `/nexus/decisions/${encodeURIComponent(selected.decision_id)}/execute`,
        undefined,
        { query: { workspace_id: workspace.id } },
      );
      const decision = response.data?.decision;
      if (decision) {
        setSelected(decision);
        setDecisions((current) => current.map((item) => item.decision_id === decision.decision_id ? decision : item));
      }
      setNotice("Approved action executed and recorded.");
      setReceiptReload((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision execution failed");
    } finally {
      setBusy(false);
    }
  };

  const recordOutcome = async () => {
    if (!selected || !workspace?.id || !outcomeText.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiClient.post<Envelope<{ decision?: Decision }>>(
        `/nexus/decisions/${encodeURIComponent(selected.decision_id)}/outcome`,
        {
          outcome_status: "succeeded",
          actual_result_text: outcomeText.trim(),
          outcome_payload: { summary: outcomeText.trim() },
        },
        { query: { workspace_id: workspace.id } },
      );
      const decision = response.data?.decision;
      if (decision) {
        setSelected(decision);
        setDecisions((current) => current.map((item) => item.decision_id === decision.decision_id ? decision : item));
      }
      setOutcomeText("");
      setNotice("Outcome recorded in the Decision Receipt.");
      setReceiptReload((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Outcome recording failed");
    } finally {
      setBusy(false);
    }
  };

  if (status !== "AUTHENTICATED") {
    return <main className="min-h-screen bg-[#0a0a0b] p-8 font-mono text-xs text-[#9ca3af]">Authentication is required.</main>;
  }

  return (
    <main className="min-h-screen bg-[#0a0a0b] p-6 font-mono text-xs text-[#e5e5e5]">
      <header className="mb-6 flex items-center justify-between border-b border-[#26262b] pb-4">
        <div>
          <p className="text-[9px] uppercase tracking-widest text-[#06b6d4]">Cortex</p>
          <h1 className="mt-1 text-lg font-bold tracking-widest text-white">DECISION ROOM</h1>
          <p className="mt-1 text-[10px] text-[#6b7280]">Evidence, alternatives, approvals, and outcome trace</p>
        </div>
        <a href="/nexus/cockpit" className="border border-[#26262b] px-3 py-2 text-[10px] uppercase tracking-widest text-[#9ca3af] hover:text-white">Cockpit</a>
      </header>

      {error && <div className="mb-4 border border-[#e5484d]/50 bg-[#e5484d]/10 p-3 text-[#e5484d]">{error}</div>}
      {notice && <div className="mb-4 border border-[#86efac]/40 bg-[#86efac]/10 p-3 text-[#86efac]">{notice}</div>}
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <aside className="border border-[#26262b] bg-[#0f0f11]">
          <div className="border-b border-[#26262b] px-3 py-2 text-[9px] uppercase tracking-widest text-[#6b7280]">Decisions</div>
          {decisions.length === 0 && <p className="p-3 text-[#6b7280]">No decisions recorded.</p>}
          {decisions.map((decision) => (
            <button
              key={decision.decision_id}
              onClick={() => setSelected(decision)}
              className={`block w-full border-b border-[#1a1a1d] px-3 py-3 text-left ${selected?.decision_id === decision.decision_id ? "bg-[#1a1a1d]" : "hover:bg-[#151517]"}`}
            >
              <div className="text-white">{decision.title ?? decision.decision_id}</div>
              <div className="mt-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">{decision.phase ?? "UNKNOWN"}</div>
            </button>
          ))}
        </aside>

        <section className="space-y-4">
          {!selected && <div className="border border-[#26262b] p-6 text-[#6b7280]">Select a decision after the workspace produces one.</div>}
          {selected && (
            <>
              <div className="border border-[#26262b] bg-[#0f0f11] p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-[9px] uppercase tracking-widest text-[#06b6d4]">Decision</p>
                    <h2 className="mt-1 text-base font-bold text-white">{selected.title ?? selected.decision_id}</h2>
                    <p className="mt-2 text-[#9ca3af]">{selected.situation ?? "No situation summary recorded."}</p>
                  </div>
                  <span className="border border-[#06b6d4]/50 px-2 py-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">{selected.phase ?? "UNKNOWN"}</span>
                </div>
                <dl className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div><dt className="text-[9px] uppercase text-[#6b7280]">World state</dt><dd className="mt-1 text-white">{String(selected.world_state_version ?? "—")}</dd></div>
                  <div><dt className="text-[9px] uppercase text-[#6b7280]">Recommended option</dt><dd className="mt-1 text-white">{String(selected.recommended_option ?? "—")}</dd></div>
                  <div><dt className="text-[9px] uppercase text-[#6b7280]">Decision ID</dt><dd className="mt-1 break-all text-white">{selected.decision_id}</dd></div>
                </dl>
                <div className="mt-5 flex flex-wrap items-end gap-3 border-t border-[#26262b] pt-4">
                  {selected.phase === "awaiting_approval" && (
                    <>
                      <button disabled={busy} onClick={() => void advance("approved")} className="border border-[#86efac]/60 bg-[#14532d]/40 px-3 py-2 text-[10px] uppercase tracking-widest text-[#86efac] disabled:opacity-50">Approve proposal</button>
                      <button disabled={busy} onClick={() => void advance("rejected")} className="border border-[#e5484d]/60 bg-[#7f1d1d]/30 px-3 py-2 text-[10px] uppercase tracking-widest text-[#fca5a5] disabled:opacity-50">Reject proposal</button>
                    </>
                  )}
                  {selected.phase === "approved" && (
                    <button disabled={busy} onClick={() => void execute()} className="border border-[#facc15]/60 bg-[#713f12]/30 px-3 py-2 text-[10px] uppercase tracking-widest text-[#fde68a] disabled:opacity-50">Execute approved action</button>
                  )}
                  {selected.phase === "executed" && (
                    <>
                      <input value={outcomeText} onChange={(event) => setOutcomeText(event.target.value)} placeholder="Describe the observed outcome" className="min-w-[260px] flex-1 border border-[#26262b] bg-[#0a0a0b] px-3 py-2 text-[10px] text-white placeholder:text-[#6b7280]" />
                      <button disabled={busy || !outcomeText.trim()} onClick={() => void recordOutcome()} className="border border-[#06b6d4]/60 bg-[#164e63]/40 px-3 py-2 text-[10px] uppercase tracking-widest text-[#67e8f9] disabled:opacity-50">Record outcome</button>
                    </>
                  )}
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="border border-[#26262b] bg-[#0f0f11] p-4">
                  <h3 className="mb-3 text-[9px] uppercase tracking-widest text-[#06b6d4]">Evidence chain</h3>
                  <p className="text-2xl text-white">{evidence?.node_count ?? evidence?.nodes?.length ?? 0}</p>
                  <p className="text-[10px] text-[#6b7280]">evidence nodes · {evidence?.edge_count ?? evidence?.edges?.length ?? 0} relationships</p>
                  <p className="mt-3 text-[10px] text-[#9ca3af]">Inspect source and derivation records before approving a consequential action.</p>
                </div>
                <div className="border border-[#26262b] bg-[#0f0f11] p-4">
                  <h3 className="mb-3 text-[9px] uppercase tracking-widest text-[#06b6d4]">Approval history</h3>
                  <p className="text-2xl text-white">{approvals.length}</p>
                  <p className="text-[10px] text-[#6b7280]">recorded approval events</p>
                  {approvals.slice(0, 3).map((approval, index) => (
                    <p key={index} className="mt-2 text-[10px] text-[#9ca3af]">{String(approval.status ?? approval.phase ?? "Recorded approval")}</p>
                  ))}
                </div>
              </div>

              <div className="border border-[#26262b] bg-[#0f0f11] p-4">
                <h3 className="mb-3 text-[9px] uppercase tracking-widest text-[#06b6d4]">Decision Receipt</h3>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div><span className="text-[9px] uppercase text-[#6b7280]">Receipt version</span><p className="mt-1 text-white">{receipt?.receipt_version ?? "—"}</p></div>
                  <div><span className="text-[9px] uppercase text-[#6b7280]">Transitions</span><p className="mt-1 text-white">{receipt?.transitions?.length ?? 0}</p></div>
                  <div><span className="text-[9px] uppercase text-[#6b7280]">Scenarios</span><p className="mt-1 text-white">{receipt?.scenarios?.length ?? 0}</p></div>
                </div>
                <p className="mt-3 text-[10px] text-[#9ca3af]">This receipt is reconstructed from authoritative decision, evidence, approval, transition, and scenario records.</p>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
