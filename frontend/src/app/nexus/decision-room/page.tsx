"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

/**
 * Decision Room (demo spec §2.E).
 *
 * The human-approval gate of the governed pipeline. All records come from
 * the canonical `/nexus/decisions/*` surface: decision state machine,
 * evidence DAG, approval trail (including policy-check results), and the
 * reconstructable Decision Receipt. Approval and rejection are the only
 * phase changes an operator can trigger here — the backend enforces
 * authorization, transitions, and world-state freshness.
 */

type Envelope<T> = { data?: T };

interface Decision {
  decision_id: string;
  phase?: string;
  situation?: string | null;
  recommended_option_id?: string | null;
  chosen_option?: string | null;
  options?: Array<Record<string, unknown>> | null;
  policy_id?: string | null;
  recommended_nev?: number | null;
  recommended_sla?: number | null;
  recommended_cost?: number | null;
  confidence?: number | null;
  world_state_version?: number | null;
  world_state_hash?: string | null;
  evidence_root_id?: string | null;
  evidence_root_hash?: string | null;
  deterministic_hash?: string | null;
  outcome_status?: string | null;
  actual_result_text?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

interface EvidenceNode {
  node_id?: string;
  node_type?: string;
  label?: string;
  checksum?: string;
  source_entity_id?: string | null;
  created_at?: string | null;
}

interface EvidenceGraph {
  nodes?: EvidenceNode[];
  edges?: Array<Record<string, unknown>>;
  node_count?: number;
  edge_count?: number;
}

interface ApprovalRecord {
  approval_id?: string;
  approver_id?: string;
  approver_role?: string | null;
  approved?: boolean;
  rejection_reason?: string | null;
  policy_checks?: Record<string, unknown> | null;
  created_at?: string | null;
}

interface DecisionReceipt {
  receipt_version?: string;
  transitions?: Array<Record<string, unknown>>;
  scenarios?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown>;
}

const PHASE_BADGES: Record<string, string> = {
  simulated: "badge badge-neutral",
  policy_checked: "badge badge-neutral",
  awaiting_approval: "badge border-warning/50 bg-warning-subtle text-warning",
  approved: "badge badge-positive",
  rejected: "badge border-critical/50 bg-critical-subtle text-critical",
  authorized: "badge badge-positive",
  executing: "badge badge-neutral",
  executed: "badge badge-positive",
  stale: "badge border-critical/50 bg-critical-subtle text-critical",
};

function phaseBadge(phase?: string): string {
  return PHASE_BADGES[phase ?? ""] ?? "badge badge-neutral";
}

function money(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10_000_000) return `₹${(value / 10_000_000).toFixed(1)}Cr`;
  if (Math.abs(value) >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (Math.abs(value) >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

function shortHash(value?: string | null): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 18)}…` : value;
}

export default function DecisionRoomPage() {
  const { status, workspace } = useAuth();
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selected, setSelected] = useState<Decision | null>(null);
  const [evidence, setEvidence] = useState<EvidenceGraph | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const [receipt, setReceipt] = useState<DecisionReceipt | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<"all" | "awaiting_approval" | "approved">("all");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [outcomeText, setOutcomeText] = useState("");
  const [receiptReload, setReceiptReload] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("phase");
    if (requested === "awaiting_approval" || requested === "approved") setPhaseFilter(requested);
  }, []);

  const loadDecisions = useCallback(async () => {
    if (status !== "AUTHENTICATED" || !workspace?.id) return;
    void apiClient
      .get<Envelope<{ decisions?: Decision[] }>>("/nexus/decisions", {
        workspace_id: workspace.id,
      })
      .then((response) => {
        const items = response.data?.decisions ?? [];
        setDecisions(items);
        setSelected((current) => {
          if (current && items.some((item) => item.decision_id === current.decision_id)) return current;
          return items[0] ?? null;
        });
      })
      .catch(() => setError("Decisions are unavailable for this workspace."));
  }, [status, workspace?.id]);

  useEffect(() => {
    void loadDecisions();
  }, [loadDecisions]);

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
      apiClient.get<Envelope<{ approvals?: ApprovalRecord[] }>>(`/nexus/decisions/${decisionId}/approvals`),
      apiClient.get<Envelope<{ receipt?: DecisionReceipt }>>(`/nexus/decisions/${decisionId}/receipt`),
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
        setDecisions((current) => current.map((item) => (item.decision_id === decision.decision_id ? decision : item)));
      }
      setNotice(`Decision ${targetPhase}. The transition is recorded in the Decision Receipt.`);
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
        setDecisions((current) => current.map((item) => (item.decision_id === decision.decision_id ? decision : item)));
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
        setDecisions((current) => current.map((item) => (item.decision_id === decision.decision_id ? decision : item)));
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

  const filteredDecisions = useMemo(() => {
    if (phaseFilter === "all") return decisions;
    return decisions.filter((decision) => decision.phase === phaseFilter);
  }, [decisions, phaseFilter]);

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <CenteredNote title="Opening Cortex" detail="Checking your workspace session…" />;
  }
  if (status !== "AUTHENTICATED") {
    return (
      <CenteredNote
        title="Sign in to Cortex"
        detail="The Decision Room is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Fdecision-room" className="button-primary">Sign in</Link>}
      />
    );
  }

  return (
    <div className="min-w-0">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-4 border-b border-border px-5 py-3 sm:px-8">
        <div>
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span className="font-semibold text-ink">Cortex</span>
            <span>/</span>
            <span>Decision Room</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">Evidence, policy results, approvals, and outcome trace</p>
        </div>
        <span className="font-mono text-[10px] text-ink-muted">{workspace?.name ?? "Workspace"}</span>
      </header>

      <div className="space-y-5 px-5 py-6 sm:px-8">
        {error && <div className="notice-error" role="alert">{error}</div>}
        {notice && (
          <div className="border border-border bg-surface px-4 py-3 text-xs text-ink-secondary" role="status">{notice}</div>
        )}

        <div className="flex flex-wrap gap-px border border-border bg-border" role="tablist" aria-label="Decision phase filter">
          {([["all", "All decisions"], ["awaiting_approval", "Pending decisions"], ["approved", "Approved"]] as const).map(
            ([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={phaseFilter === value}
                onClick={() => setPhaseFilter(value)}
                className={`px-4 py-2 text-xs font-medium transition-colors ${
                  phaseFilter === value ? "bg-surface-2 text-ink" : "bg-surface text-ink-secondary hover:text-ink"
                }`}
              >
                {label}
              </button>
            ),
          )}
        </div>

        <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
          <div className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Decisions ({filteredDecisions.length})</span>
            </div>
            {filteredDecisions.length === 0 ? (
              <p className="px-4 py-8 text-center text-xs text-ink-secondary">
                {decisions.length === 0
                  ? "No decisions recorded. Decisions appear after the pipeline proposes a governed action."
                  : "No decisions in this phase."}
              </p>
            ) : (
              <div className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {filteredDecisions.map((decision) => (
                  <button
                    key={decision.decision_id}
                    type="button"
                    onClick={() => setSelected(decision)}
                    className={`block w-full px-4 py-3 text-left transition-colors hover:bg-surface-2 ${
                      selected?.decision_id === decision.decision_id ? "border-l-2 border-accent bg-surface-2" : "border-l-2 border-transparent"
                    }`}
                  >
                    <div className="truncate text-sm font-medium text-ink">{decision.decision_id}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className={phaseBadge(decision.phase)}>{(decision.phase ?? "UNKNOWN").toUpperCase()}</span>
                      {decision.outcome_status && (
                        <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-ink-muted">
                          {decision.outcome_status}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {selected ? (
            <div className="min-w-0 space-y-5">
              <div className="border border-border bg-surface">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
                  <div>
                    <span className="eyebrow">Recommended action</span>
                    <h2 className="mt-1 text-base font-semibold">
                      {selected.recommended_option_id ?? selected.chosen_option ?? "—"}
                    </h2>
                    <p className="mt-1 font-mono text-[10px] text-ink-muted">{selected.decision_id}</p>
                  </div>
                  <span className={phaseBadge(selected.phase)}>{(selected.phase ?? "UNKNOWN").toUpperCase()}</span>
                </div>

                {selected.situation && (
                  <p className="border-b border-border px-5 py-3 text-xs leading-5 text-ink-secondary">{selected.situation}</p>
                )}

                <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-3">
                  <Detail label="World state" value={selected.world_state_version ? `v${selected.world_state_version}` : "—"} />
                  <Detail label="Expected NEV" value={money(selected.recommended_nev)} />
                  <Detail label="Expected SLA" value={selected.recommended_sla === null || selected.recommended_sla === undefined ? "—" : `${Math.round(selected.recommended_sla * 100)}%`} />
                  <Detail label="Expected cost" value={money(selected.recommended_cost)} />
                  <Detail label="Confidence" value={selected.confidence === null || selected.confidence === undefined ? "—" : `${Math.round(selected.confidence * 100)}%`} />
                  <Detail label="Policy" value={selected.policy_id ?? "not recorded"} />
                  <Detail label="Alternatives on record" value={String(selected.options?.length ?? 0)} />
                  <Detail label="Evidence root" value={shortHash(selected.evidence_root_hash)} />
                  <Detail label="State hash" value={shortHash(selected.world_state_hash)} />
                </dl>

                {(selected.options ?? []).length > 0 && (
                  <div className="border-t border-border px-5 py-3">
                    <span className="eyebrow">Alternative actions considered</span>
                    <ul className="mt-2 space-y-1 font-mono text-[10px] text-ink-secondary">
                      {(selected.options ?? []).map((option, index) => (
                        <li key={index}>· {JSON.stringify(option)}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="flex flex-wrap items-end gap-3 border-t border-border px-5 py-4">
                  {selected.phase === "awaiting_approval" && (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void advance("approved")}
                        className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Approve proposal
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void advance("rejected")}
                        className="button-secondary border-critical/50 text-critical hover:bg-critical-subtle disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Reject proposal
                      </button>
                    </>
                  )}
                  {selected.phase === "approved" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void execute()}
                      className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Execute approved action
                    </button>
                  )}
                  {selected.phase === "executed" && (
                    <>
                      <input
                        value={outcomeText}
                        onChange={(event) => setOutcomeText(event.target.value)}
                        placeholder="Describe the observed outcome"
                        className="field min-w-[240px] flex-1"
                        aria-label="Observed outcome"
                      />
                      <button
                        type="button"
                        disabled={busy || !outcomeText.trim()}
                        onClick={() => void recordOutcome()}
                        className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Record outcome
                      </button>
                    </>
                  )}
                  {selected.phase === "stale" && (
                    <p className="text-xs text-warning">
                      World state advanced past this decision — it is invalid and requires a fresh proposal.
                    </p>
                  )}
                </div>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <div className="border border-border bg-surface">
                  <div className="border-b border-border px-4 py-3">
                    <span className="eyebrow">Supporting evidence ({evidence?.node_count ?? evidence?.nodes?.length ?? 0})</span>
                    <p className="mt-1 text-[11px] text-ink-secondary">
                      {evidence?.edge_count ?? evidence?.edges?.length ?? 0} relationships · every claim is inspectable before approval
                    </p>
                  </div>
                  <ul className="max-h-72 divide-y divide-border overflow-y-auto">
                    {(evidence?.nodes ?? []).map((node) => (
                      <li key={node.node_id} className="px-4 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs text-ink" title={node.label}>{node.label ?? node.node_id}</span>
                          <span className="badge badge-neutral">{(node.node_type ?? "claim").toUpperCase()}</span>
                        </div>
                        <p className="mt-0.5 font-mono text-[9px] text-ink-muted">
                          {node.checksum ? `checksum ${node.checksum.slice(0, 14)}…` : "no checksum"}
                          {node.created_at ? ` · ${new Date(node.created_at).toLocaleString()}` : ""}
                        </p>
                      </li>
                    ))}
                    {(evidence?.nodes ?? []).length === 0 && (
                      <li className="px-4 py-6 text-center text-xs text-ink-secondary">No evidence nodes recorded.</li>
                    )}
                  </ul>
                </div>

                <div className="border border-border bg-surface">
                  <div className="border-b border-border px-4 py-3">
                    <span className="eyebrow">Approval & policy trail ({approvals.length})</span>
                  </div>
                  <ul className="max-h-72 divide-y divide-border overflow-y-auto">
                    {approvals.map((approval) => (
                      <li key={approval.approval_id} className="px-4 py-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[10px] text-ink">
                            {approval.approver_id ?? "unknown actor"}
                            {approval.approver_role ? ` · ${approval.approver_role}` : ""}
                          </span>
                          <span className={approval.approved ? "badge badge-positive" : "badge border-critical/50 bg-critical-subtle text-critical"}>
                            {approval.approved ? "APPROVED" : "REJECTED"}
                          </span>
                        </div>
                        {approval.rejection_reason && (
                          <p className="mt-1 text-[11px] text-critical">Reason: {approval.rejection_reason}</p>
                        )}
                        {approval.policy_checks && Object.keys(approval.policy_checks).length > 0 && (
                          <div className="mt-1 font-mono text-[9px] leading-4 text-ink-muted">
                            {Object.entries(approval.policy_checks).map(([key, value]) => (
                              <div key={key}>{key}: {String(value)}</div>
                            ))}
                          </div>
                        )}
                        {approval.created_at && (
                          <p className="mt-0.5 font-mono text-[9px] text-ink-muted">{new Date(approval.created_at).toLocaleString()}</p>
                        )}
                      </li>
                    ))}
                    {approvals.length === 0 && (
                      <li className="px-4 py-6 text-center text-xs text-ink-secondary">No approval events recorded.</li>
                    )}
                  </ul>
                </div>
              </div>

              <div id="receipt" className="border border-border bg-surface">
                <div className="border-b border-border px-4 py-3">
                  <span className="eyebrow">Decision receipt ({receipt?.receipt_version ?? "—"})</span>
                  <p className="mt-1 text-[11px] text-ink-secondary">
                    Reconstructed from authoritative decision, evidence, approval, transition, and scenario records.
                  </p>
                </div>
                <div className="grid gap-4 px-4 py-3 md:grid-cols-2">
                  <div>
                    <span className="eyebrow">Transition history</span>
                    <ul className="mt-2 space-y-1 font-mono text-[10px] text-ink-secondary">
                      {(receipt?.transitions ?? []).map((transition, index) => (
                        <li key={index}>
                          · {String(transition.to_phase ?? transition.phase ?? "transition")}
                          {transition.created_at ? ` · ${new Date(String(transition.created_at)).toLocaleString()}` : ""}
                        </li>
                      ))}
                      {(receipt?.transitions ?? []).length === 0 && <li className="text-ink-muted">No transitions recorded.</li>}
                    </ul>
                  </div>
                  <div>
                    <span className="eyebrow">Provenance</span>
                    <dl className="mt-2 space-y-1 font-mono text-[10px] text-ink-secondary">
                      {Object.entries(receipt?.provenance ?? {}).map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-3">
                          <dt className="text-ink-muted">{key}</dt>
                          <dd className="truncate">{value === null || value === undefined ? "—" : String(value)}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-2 font-mono text-[10px] text-ink-muted">
                      Scenarios linked: {(receipt?.scenarios ?? []).length} · deterministic hash {shortHash(selected.deterministic_hash)}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="border border-border bg-surface p-8 text-center text-xs text-ink-secondary">
              Select a decision to inspect its evidence and approvals.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">{label}</dt>
      <dd className="mt-1 truncate font-mono text-sm text-ink" title={value}>{value}</dd>
    </div>
  );
}

function CenteredNote({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-6 text-center">
      <div className="max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-ink-secondary">{detail}</p>
        {action && <div className="mt-6">{action}</div>}
      </div>
    </div>
  );
}
