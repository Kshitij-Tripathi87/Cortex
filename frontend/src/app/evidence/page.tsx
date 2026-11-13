"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiClient, useAuth } from "@/lib/auth";

type ClaimState = "pending_review" | "accepted" | "rejected" | "superseded" | "conflicted";

interface EvidenceClaim {
  claim_id: string;
  workspace_id: string;
  source_file_id: string;
  batch_id: string;
  row_number: number;
  source_column: string;
  canonical_entity: string | null;
  canonical_field: string | null;
  raw_value: string;
  normalized_value: string | null;
  confidence: number;
  claim_state: ClaimState | string;
  requires_review: boolean;
  created_at: string;
}

interface EvidenceConflict {
  conflict_id: string;
  claim_ids: string[];
  canonical_entity: string | null;
  canonical_field: string | null;
  severity: string;
  blocking: boolean;
  status: string;
  explanation: string;
}

interface ReadinessAssessment {
  assessment_id: string;
  workspace_id: string;
  batch_id: string;
  state: "ready" | "ready_with_assumptions" | "review_required" | "blocked" | string;
  blocking_conflict_count: number;
  open_conflict_count: number;
  accepted_claim_count: number;
  pending_claim_count: number;
  assumptions: string[];
  explanation: string;
}

interface PrepareResponse {
  batch_id: string;
  claims_created: number;
  conflicts_detected: number;
  blocking_conflicts: number;
  readiness: string;
  explanation: string;
}

interface PublishResponse {
  snapshot_id: string;
  version: number;
  snapshot_hash: string;
  node_count: number;
  edge_count: number;
  write_event_count: number;
  provenance_link_count: number;
  integrity_passed: boolean;
}

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed. Check the connection and try again.";
}

function stateStyle(state: string): string {
  switch (state) {
    case "accepted": return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "pending_review": return "bg-amber-50 text-amber-700 border-amber-200";
    case "rejected": return "bg-rose-50 text-rose-700 border-rose-200";
    case "superseded": return "bg-slate-100 text-slate-600 border-slate-200";
    default: return "bg-slate-100 text-slate-700 border-slate-200";
  }
}

function readinessStyle(state: string): string {
  switch (state) {
    case "ready": return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "ready_with_assumptions": return "bg-amber-50 text-amber-700 border-amber-200";
    case "blocked": return "bg-rose-50 text-rose-700 border-rose-200";
    default: return "bg-slate-100 text-slate-700 border-slate-200";
  }
}

function EvidenceContent() {
  const searchParams = useSearchParams();
  const batchId = searchParams.get("batch_id");
  const { status, workspace, user } = useAuth();
  const workspaceId = workspace?.id ?? "";
  const canReview = user?.role === "admin" || user?.role === "operator";

  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  const [conflicts, setConflicts] = useState<EvidenceConflict[]>([]);
  const [readiness, setReadiness] = useState<ReadinessAssessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<EvidenceClaim | null>(null);
  const [claimRationale, setClaimRationale] = useState("");
  const [reviewingClaim, setReviewingClaim] = useState(false);
  const [selectedConflict, setSelectedConflict] = useState<EvidenceConflict | null>(null);
  const [conflictClaimId, setConflictClaimId] = useState("");
  const [conflictAction, setConflictAction] = useState("approved");
  const [conflictRationale, setConflictRationale] = useState("");
  const [resolvingConflict, setResolvingConflict] = useState(false);
  const [publishResult, setPublishResult] = useState<PublishResponse | null>(null);

  const loadBatch = useCallback(async () => {
    if (!batchId || !workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const [claimRows, conflictRows, assessment] = await Promise.all([
        apiClient.get<EvidenceClaim[]>(
          `/sources/batches/${encodeURIComponent(batchId)}/claims`,
          { workspace_id: workspaceId },
        ),
        apiClient.get<EvidenceConflict[]>(
          `/sources/batches/${encodeURIComponent(batchId)}/conflicts`,
          { workspace_id: workspaceId },
        ),
        apiClient.post<ReadinessAssessment>(
          `/readiness/batches/${encodeURIComponent(batchId)}`,
          undefined,
          { query: { workspace_id: workspaceId } },
        ),
      ]);
      setClaims(claimRows);
      setConflicts(conflictRows);
      setReadiness(assessment);
    } catch (loadError) {
      setError(messageFor(loadError));
    } finally {
      setLoading(false);
    }
  }, [batchId, workspaceId]);

  useEffect(() => {
    if (status === "AUTHENTICATED" && batchId && workspaceId) {
      void loadBatch();
    } else if (status === "ANONYMOUS") {
      setLoading(false);
    }
  }, [status, batchId, workspaceId, loadBatch]);

  const conflictedClaimIds = useMemo(
    () => new Set(conflicts.filter((c) => c.status === "open" || c.status === "escalated").flatMap((c) => c.claim_ids)),
    [conflicts],
  );
  const pendingCount = claims.filter((claim) => claim.claim_state === "pending_review").length;
  const acceptedCount = claims.filter((claim) => claim.claim_state === "accepted").length;
  const rejectedCount = claims.filter((claim) => claim.claim_state === "rejected").length;
  const openConflicts = conflicts.filter((conflict) => conflict.status === "open" || conflict.status === "escalated");
  const canPublish =
    !!readiness &&
    (readiness.state === "ready" || readiness.state === "ready_with_assumptions") &&
    readiness.accepted_claim_count > 0 &&
    readiness.pending_claim_count === 0 &&
    readiness.open_conflict_count === 0;

  async function prepareClaims() {
    if (!batchId || !workspaceId) return;
    setPreparing(true);
    setError(null);
    setNotice(null);
    setPublishResult(null);
    try {
      const response = await apiClient.post<PrepareResponse>(
        `/sources/batches/${encodeURIComponent(batchId)}/compile`,
        undefined,
        { query: { workspace_id: workspaceId } },
      );
      setNotice(
        `Prepared batch: ${response.claims_created} new claims, ${response.conflicts_detected} new conflicts. Readiness: ${response.readiness.replaceAll("_", " ")}.`,
      );
      await loadBatch();
    } catch (prepareError) {
      setError(messageFor(prepareError));
    } finally {
      setPreparing(false);
    }
  }

  async function submitClaimReview(decision: "accepted" | "rejected") {
    if (!batchId || !workspaceId || !selectedClaim || claimRationale.trim().length < 3) return;
    setReviewingClaim(true);
    setError(null);
    try {
      await apiClient.post<EvidenceClaim>(
        `/sources/batches/${encodeURIComponent(batchId)}/claims/${encodeURIComponent(selectedClaim.claim_id)}/review`,
        { decision, rationale: claimRationale.trim() },
        { query: { workspace_id: workspaceId } },
      );
      setNotice(`Claim ${decision} and audit recorded.`);
      setSelectedClaim(null);
      setClaimRationale("");
      await loadBatch();
    } catch (reviewError) {
      setError(messageFor(reviewError));
    } finally {
      setReviewingClaim(false);
    }
  }

  async function submitConflictResolution() {
    if (!workspaceId || !selectedConflict || conflictRationale.trim().length < 3) return;
    if (conflictAction === "approved" && !conflictClaimId) {
      setError("Select the claim to approve.");
      return;
    }
    setResolvingConflict(true);
    setError(null);
    try {
      await apiClient.post(
        `/sources/conflicts/${encodeURIComponent(selectedConflict.conflict_id)}/resolve`,
        {
          selected_claim_id: conflictClaimId || null,
          action: conflictAction,
          rationale: conflictRationale.trim(),
        },
        { query: { workspace_id: workspaceId } },
      );
      setNotice(`Conflict decision recorded: ${conflictAction}.`);
      setSelectedConflict(null);
      setConflictClaimId("");
      setConflictRationale("");
      await loadBatch();
    } catch (resolveError) {
      setError(messageFor(resolveError));
    } finally {
      setResolvingConflict(false);
    }
  }

  async function publishBatch() {
    if (!batchId || !workspaceId || !canPublish) return;
    setPublishing(true);
    setError(null);
    setNotice(null);
    try {
      const published = await apiClient.post<PublishResponse>(
        `/graph/batches/${encodeURIComponent(batchId)}/compile`,
        undefined,
        { query: { workspace_id: workspaceId } },
      );
      if (!published.integrity_passed) {
        throw new Error("The graph integrity check did not pass. The batch was not accepted as published.");
      }
      setPublishResult(published);
      setNotice("Batch published to the canonical graph and persisted with an integrity-checked snapshot.");
      await loadBatch();
    } catch (publishError) {
      setError(messageFor(publishError));
    } finally {
      setPublishing(false);
    }
  }

  if (status === "UNKNOWN" || status === "CHECKING") {
    return <div className="p-8 text-sm text-gray-500">Checking your Cortex session…</div>;
  }

  if (status !== "AUTHENTICATED") {
    return (
      <div className="min-h-[50vh] flex items-center justify-center p-8 text-center">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Sign in to review source evidence</h1>
          <p className="mt-2 text-sm text-gray-600">Evidence review is scoped to your authenticated workspace.</p>
          <Link href="/auth/login?next=%2Fevidence" className="mt-4 inline-flex rounded bg-slate-900 px-4 py-2 text-white">
            Sign in
          </Link>
        </div>
      </div>
    );
  }

  if (!batchId) {
    return (
      <main className="p-8">
        <h1 className="text-2xl font-semibold text-gray-900">Evidence Review</h1>
        <p className="mt-2 text-sm text-gray-600">Open this page from a source upload so the batch ID is included.</p>
        <Link href="/upload" className="mt-4 inline-flex rounded bg-slate-900 px-4 py-2 text-white">Upload source data</Link>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 p-5 sm:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs text-slate-500">
              <Link href="/nexus/cockpit" className="font-medium text-slate-700 hover:underline">Cortex Nexus</Link>
              <span className="px-2">/</span>
              <span>Source evidence</span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Evidence review</h1>
            <p className="mt-1 text-sm text-slate-600">
              {workspace?.name ?? "Active workspace"} · batch <span className="font-mono">{batchId}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => void loadBatch()}
              disabled={loading}
              className="rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 disabled:opacity-50"
            >
              Refresh
            </button>
            <button
              onClick={() => void prepareClaims()}
              disabled={preparing || !canReview}
              className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              title={!canReview ? "Admin or operator role required" : undefined}
            >
              {preparing ? "Preparing…" : "Prepare claims"}
            </button>
          </div>
        </header>

        {error && <div role="alert" className="mb-4 border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
        {notice && <div role="status" className="mb-4 border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</div>}

        <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
          {[
            ["Claims", String(claims.length)],
            ["Pending", String(pendingCount)],
            ["Accepted", String(acceptedCount)],
            ["Rejected", String(rejectedCount)],
            ["Open conflicts", String(openConflicts.length)],
          ].map(([label, value]) => (
            <div key={label} className="border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">{value}</p>
            </div>
          ))}
        </section>

        <section className="mb-6 border border-slate-200 bg-white">
          <div className="flex flex-col gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold text-slate-950">Readiness gate</h2>
              <p className="mt-1 text-sm text-slate-600">{readiness?.explanation ?? "Readiness has not been calculated yet."}</p>
            </div>
            {readiness && (
              <span className={`inline-flex w-fit rounded border px-3 py-1 text-xs font-medium ${readinessStyle(readiness.state)}`}>
                {readiness.state.replaceAll("_", " ")}
              </span>
            )}
          </div>
          <div className="grid gap-4 p-4 md:grid-cols-3">
            <div>
              <p className="text-xs text-slate-500">Blocking conflicts</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness?.blocking_conflict_count ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Pending claims</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness?.pending_claim_count ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Accepted claims</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness?.accepted_claim_count ?? "—"}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 p-4">
            <p className="max-w-2xl text-xs text-slate-500">
              Publishing is disabled until every pending claim and open conflict is resolved. Rejected claims remain excluded from graph compilation.
            </p>
            <button
              onClick={() => void publishBatch()}
              disabled={!canPublish || publishing || !canReview}
              className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {publishing ? "Publishing…" : "Publish to World State"}
            </button>
          </div>
        </section>

        {publishResult && (
          <section className="mb-6 border border-emerald-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Published snapshot</p>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div><p className="text-xs text-slate-500">Version</p><p className="font-semibold">{publishResult.version}</p></div>
              <div><p className="text-xs text-slate-500">Nodes</p><p className="font-semibold">{publishResult.node_count}</p></div>
              <div><p className="text-xs text-slate-500">Edges</p><p className="font-semibold">{publishResult.edge_count}</p></div>
              <div><p className="text-xs text-slate-500">Provenance links</p><p className="font-semibold">{publishResult.provenance_link_count}</p></div>
            </div>
            <p className="mt-3 break-all font-mono text-[11px] text-slate-500">SHA-256: {publishResult.snapshot_hash}</p>
            <Link href="/nexus/world" className="mt-4 inline-flex rounded bg-slate-900 px-4 py-2 text-sm text-white">
              Inspect World State
            </Link>
          </section>
        )}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
          <section className="border border-slate-200 bg-white">
            <div className="border-b border-slate-200 p-4">
              <h2 className="font-semibold text-slate-950">Extracted claims</h2>
              <p className="mt-1 text-xs text-slate-500">Each column mapping is a claim. Decisions are recorded with reviewer identity and rationale.</p>
            </div>
            {loading ? (
              <div className="p-8 text-center text-sm text-slate-500">Loading claims…</div>
            ) : claims.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-sm text-slate-600">No claims have been prepared for this batch.</p>
                <button onClick={() => void prepareClaims()} disabled={preparing || !canReview} className="mt-3 rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40">
                  {preparing ? "Preparing…" : "Extract claims from profiles"}
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Source column</th>
                      <th className="px-4 py-3">Canonical field</th>
                      <th className="px-4 py-3">Confidence</th>
                      <th className="px-4 py-3">State</th>
                      <th className="px-4 py-3">Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {claims.map((claim) => (
                      <tr key={claim.claim_id} className="align-top">
                        <td className="px-4 py-3">
                          <p className="font-medium text-slate-900">{claim.source_column}</p>
                          <p className="mt-1 max-w-xs truncate font-mono text-[11px] text-slate-500">{claim.raw_value || "—"}</p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-slate-800">{claim.canonical_entity ?? "Unmapped"}</p>
                          <p className="text-xs text-slate-500">{claim.canonical_field ?? "No suggested field"}</p>
                        </td>
                        <td className="px-4 py-3 tabular-nums">{(claim.confidence * 100).toFixed(0)}%</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded border px-2 py-1 text-[11px] ${stateStyle(claim.claim_state)}`}>
                            {claim.claim_state.replaceAll("_", " ")}
                          </span>
                          {conflictedClaimIds.has(claim.claim_id) && <p className="mt-1 text-[10px] text-amber-700">Conflict requires resolution</p>}
                        </td>
                        <td className="px-4 py-3">
                          {claim.claim_state === "pending_review" && !conflictedClaimIds.has(claim.claim_id) ? (
                            <button
                              onClick={() => { setSelectedClaim(claim); setClaimRationale(""); }}
                              disabled={!canReview}
                              className="text-xs font-medium text-blue-700 hover:underline disabled:opacity-40"
                            >
                              Review
                            </button>
                          ) : <span className="text-xs text-slate-400">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="border border-slate-200 bg-white">
            <div className="border-b border-slate-200 p-4">
              <h2 className="font-semibold text-slate-950">Conflicts</h2>
              <p className="mt-1 text-xs text-slate-500">Resolve conflicting values before claim approval and graph publication.</p>
            </div>
            {openConflicts.length === 0 ? (
              <p className="p-5 text-sm text-slate-500">No open conflicts for this batch.</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {openConflicts.map((conflict) => (
                  <div key={conflict.conflict_id} className="p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-slate-900">{conflict.canonical_entity ?? "Unknown entity"} · {conflict.canonical_field ?? "Unmapped field"}</p>
                      <span className={`rounded px-2 py-1 text-[10px] ${conflict.blocking ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>
                        {conflict.status === "escalated" ? "Escalated" : conflict.blocking ? "Blocking" : conflict.severity}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-600">{conflict.explanation}</p>
                    <p className="mt-2 text-[11px] text-slate-500">{conflict.claim_ids.length} claims involved</p>
                    <button
                      onClick={() => { setSelectedConflict(conflict); setConflictClaimId(conflict.claim_ids[0] ?? ""); setConflictAction("approved"); setConflictRationale(""); }}
                      disabled={!canReview}
                      className="mt-3 text-xs font-semibold text-blue-700 hover:underline disabled:opacity-40"
                    >
                      Resolve conflict
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>

      {selectedClaim && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <section className="w-full max-w-xl border border-slate-200 bg-white shadow-xl">
            <header className="flex items-center justify-between border-b border-slate-200 p-4">
              <div>
                <h2 className="font-semibold text-slate-950">Review claim</h2>
                <p className="mt-1 font-mono text-[11px] text-slate-500">{selectedClaim.claim_id}</p>
              </div>
              <button onClick={() => setSelectedClaim(null)} className="text-sm text-slate-500">Close</button>
            </header>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><p className="text-xs text-slate-500">Source</p><p>{selectedClaim.source_column}</p></div>
                <div><p className="text-xs text-slate-500">Suggested mapping</p><p>{selectedClaim.canonical_entity ?? "—"} · {selectedClaim.canonical_field ?? "—"}</p></div>
                <div className="col-span-2"><p className="text-xs text-slate-500">Observed value</p><p className="mt-1 break-words rounded bg-slate-50 p-3 font-mono text-xs">{selectedClaim.raw_value || "—"}</p></div>
              </div>
              <div>
                <label htmlFor="claim-rationale" className="mb-1 block text-xs font-medium text-slate-700">Review rationale (required)</label>
                <textarea id="claim-rationale" value={claimRationale} onChange={(event) => setClaimRationale(event.target.value)} rows={3} minLength={3} maxLength={2000} className="w-full border border-slate-300 p-3 text-sm" placeholder="Explain why this source mapping/value is accepted or rejected." />
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <button onClick={() => setSelectedClaim(null)} className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700">Cancel</button>
                <button onClick={() => void submitClaimReview("rejected")} disabled={reviewingClaim || claimRationale.trim().length < 3} className="rounded border border-rose-300 px-3 py-2 text-sm text-rose-700 disabled:opacity-40">
                  Reject claim
                </button>
                <button onClick={() => void submitClaimReview("accepted")} disabled={reviewingClaim || claimRationale.trim().length < 3} className="rounded bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-40">
                  {reviewingClaim ? "Saving…" : "Accept claim"}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}

      {selectedConflict && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <section className="w-full max-w-xl border border-slate-200 bg-white shadow-xl">
            <header className="flex items-center justify-between border-b border-slate-200 p-4">
              <div>
                <h2 className="font-semibold text-slate-950">Resolve conflict</h2>
                <p className="mt-1 text-xs text-slate-500">{selectedConflict.canonical_entity ?? "Unknown"} · {selectedConflict.canonical_field ?? "Unmapped"}</p>
              </div>
              <button onClick={() => setSelectedConflict(null)} className="text-sm text-slate-500">Close</button>
            </header>
            <div className="space-y-4 p-4">
              <div>
                <label htmlFor="conflict-action" className="mb-1 block text-xs font-medium text-slate-700">Decision</label>
                <select id="conflict-action" value={conflictAction} onChange={(event) => setConflictAction(event.target.value)} className="w-full border border-slate-300 p-2 text-sm">
                  <option value="approved">Approve selected claim and supersede alternatives</option>
                  <option value="rejected">Reject selected claim / reject all when no claim selected</option>
                  <option value="suppressed">Suppress detector finding (claims remain pending)</option>
                  <option value="escalated">Escalate for further review</option>
                </select>
              </div>
              {conflictAction === "approved" || conflictAction === "rejected" ? (
                <div>
                  <label htmlFor="conflict-claim" className="mb-1 block text-xs font-medium text-slate-700">Claim</label>
                  <select id="conflict-claim" value={conflictClaimId} onChange={(event) => setConflictClaimId(event.target.value)} className="w-full border border-slate-300 p-2 text-sm">
                    {conflictAction === "rejected" && <option value="">Reject all claims in this conflict</option>}
                    {claims.filter((claim) => selectedConflict.claim_ids.includes(claim.claim_id)).map((claim) => (
                      <option key={claim.claim_id} value={claim.claim_id}>{claim.source_column}: {claim.raw_value}</option>
                    ))}
                  </select>
                </div>
              ) : null}
              <div>
                <label htmlFor="conflict-rationale" className="mb-1 block text-xs font-medium text-slate-700">Rationale (required)</label>
                <textarea id="conflict-rationale" value={conflictRationale} onChange={(event) => setConflictRationale(event.target.value)} rows={3} minLength={3} maxLength={2000} className="w-full border border-slate-300 p-3 text-sm" placeholder="Explain the decision or escalation." />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setSelectedConflict(null)} className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700">Cancel</button>
                <button onClick={() => void submitConflictResolution()} disabled={resolvingConflict || conflictRationale.trim().length < 3} className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40">
                  {resolvingConflict ? "Recording…" : "Record decision"}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default function EvidencePage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Loading evidence review…</div>}>
      <EvidenceContent />
    </Suspense>
  );
}
