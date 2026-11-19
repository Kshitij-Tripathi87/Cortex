"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiClient, useAuth } from "@/lib/auth";
import { ColumnReview } from "@/components/evidence/ColumnReview";
import { UploadsList } from "@/components/evidence/UploadsList";
import {
  CLAIM_PAGE,
  CONFLICTS_SHOWN,
  LONG_ACTION_NOTE,
  LONG_ACTION_TIMEOUT_MS,
  NO_FILTERS,
  STATE_CHOICES,
  conflictsLine,
  filterQuery,
  hasFilters,
  matching,
  nextPageSize,
  pageQuery,
  reloadSize,
  rowProblem,
  sameFilters,
  showingLine,
  type ClaimFilters,
  type ClaimStateFilter,
  type ClaimSummary,
} from "@/lib/nexus/claimList";

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

/** One of the values a conflict is about, as the conflict itself carries it. */
interface ConflictValue {
  claim_id: string;
  row_number: number;
  source_column: string;
  raw_value: string;
  claim_state: ClaimState | string;
}

interface EvidenceConflict {
  conflict_id: string;
  claim_ids: string[];
  /** The values that disagree, in file order. */
  claims?: ConflictValue[];
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

// The product theme is dark with near-white body text. This page is a light
// surface, so it sets its own dark base text colour: anything without an
// explicit colour class would otherwise be near-white on white.
const PAGE_SURFACE = "min-h-screen bg-slate-50 text-slate-900";

/**
 * The competing values of a conflict, in file order. The conflict carries
 * them: the table of values holds one page, which may not include them.
 */
function conflictClaims(conflict: EvidenceConflict): ConflictValue[] {
  return conflict.claims ?? [];
}

function claimStateNote(claim: { claim_state: string }): string {
  return claim.claim_state === "accepted" || claim.claim_state === "pending_review"
    ? ""
    : ` (${String(claim.claim_state).replaceAll("_", " ")})`;
}

const formatCount = (value: number): string => value.toLocaleString("en-US");

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function EvidenceContent() {
  const searchParams = useSearchParams();
  const batchId = searchParams.get("batch_id");
  const { status, workspace, user } = useAuth();
  const workspaceId = workspace?.id ?? "";
  const canReview = [
    "admin",
    "operator",
    "system_admin",
    "workspace_admin",
    "operations_manager",
  ].includes(user?.role ?? "");

  // One page of the values, in file order; "show more" adds the next.
  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  // Counts of the whole batch, and of what the filters leave.
  const [summary, setSummary] = useState<ClaimSummary | null>(null);
  const [matchingSummary, setMatchingSummary] = useState<ClaimSummary | null>(null);
  const [filters, setFilters] = useState<ClaimFilters>(NO_FILTERS);
  // The filters the table and its counts were loaded with. While they differ
  // from what is chosen, the table still answers the earlier question.
  const [loadedFilters, setLoadedFilters] = useState<ClaimFilters>(NO_FILTERS);
  const [columnChoices, setColumnChoices] = useState<string[]>([]);
  const [loadingClaims, setLoadingClaims] = useState(false);
  const [claimsError, setClaimsError] = useState<string | null>(null);
  // What a reload of the batch asks the table for, without making the reload
  // depend on every keystroke in a filter.
  const filtersRef = useRef<ClaimFilters>(NO_FILTERS);
  const shownRef = useRef(0);
  const filtersChanged = useRef(false);
  // The latest request for values; an answer to an earlier one is dropped.
  const claimsRequest = useRef(0);
  const [conflicts, setConflicts] = useState<EvidenceConflict[]>([]);
  const [readiness, setReadiness] = useState<ReadinessAssessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<EvidenceClaim | null>(null);
  const [claimRationale, setClaimRationale] = useState("");
  const [claimCanonicalEntity, setClaimCanonicalEntity] = useState("");
  const [claimCanonicalField, setClaimCanonicalField] = useState("");
  const [reviewingClaim, setReviewingClaim] = useState(false);
  const [selectedConflict, setSelectedConflict] = useState<EvidenceConflict | null>(null);
  const [conflictClaimId, setConflictClaimId] = useState("");
  const [conflictAction, setConflictAction] = useState("approved");
  const [conflictRationale, setConflictRationale] = useState("");
  const [resolvingConflict, setResolvingConflict] = useState(false);
  const [publishResult, setPublishResult] = useState<PublishResponse | null>(null);
  // Counts the loads of the batch, so the column review reloads with it.
  const [batchLoads, setBatchLoads] = useState(0);

  const loadClaims = useCallback(
    async (use: ClaimFilters, limit: number, offset: number) => {
      if (!batchId || !workspaceId) return;
      const request = ++claimsRequest.current;
      if (rowProblem(use.row)) {
        // Not a row: nothing is asked for, and the table says why it is empty.
        setClaims([]);
        setMatchingSummary(null);
        setLoadedFilters(use);
        setClaimsError(null);
        setLoadingClaims(false);
        return;
      }
      const path = `/sources/batches/${encodeURIComponent(batchId)}/claims`;
      setLoadingClaims(true);
      setClaimsError(null);
      try {
        const [rows, counts] = await Promise.all([
          apiClient.get<EvidenceClaim[]>(path, { workspace_id: workspaceId, ...pageQuery(use, limit, offset) }),
          // The next page of the same list has the same counts.
          offset > 0
            ? Promise.resolve(null)
            : apiClient.get<ClaimSummary>(`${path}/summary`, { workspace_id: workspaceId, ...filterQuery(use) }),
        ]);
        if (request !== claimsRequest.current) return;
        if (offset > 0) {
          setClaims((current) => {
            const shown = new Set(current.map((claim) => claim.claim_id));
            return [...current, ...rows.filter((claim) => !shown.has(claim.claim_id))];
          });
        } else {
          setClaims(rows);
        }
        if (counts) setMatchingSummary(counts);
        setLoadedFilters(use);
      } catch (claimsLoadError) {
        if (request === claimsRequest.current) {
          setClaimsError(messageFor(claimsLoadError));
          if (offset === 0) {
            // What these filters leave is not known: nothing is shown as if it were.
            setClaims([]);
            setMatchingSummary(null);
            setLoadedFilters(use);
          }
        }
      } finally {
        if (request === claimsRequest.current) setLoadingClaims(false);
      }
    },
    [batchId, workspaceId],
  );

  const loadBatch = useCallback(async () => {
    if (!batchId || !workspaceId) return;
    setLoading(true);
    setError(null);
    // The table loads beside the rest and reports its own failure.
    const table = loadClaims(filtersRef.current, reloadSize(shownRef.current), 0);
    try {
      const [counts, conflictRows, assessment] = await Promise.all([
        apiClient.get<ClaimSummary>(
          `/sources/batches/${encodeURIComponent(batchId)}/claims/summary`,
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
      setSummary(counts);
      setConflicts(conflictRows);
      setReadiness(assessment);
      setBatchLoads((value) => value + 1);
    } catch (loadError) {
      setError(messageFor(loadError));
    } finally {
      await table;
      setLoading(false);
    }
  }, [batchId, workspaceId, loadClaims]);

  useEffect(() => {
    shownRef.current = claims.length;
  }, [claims.length]);

  function changeFilters(next: ClaimFilters) {
    filtersRef.current = next;
    filtersChanged.current = true;
    setFilters(next);
  }

  // A changed filter brings the first page of what it leaves, once the
  // reviewer has stopped typing.
  useEffect(() => {
    if (!filtersChanged.current) return;
    const timer = window.setTimeout(() => {
      void loadClaims(filters, CLAIM_PAGE, 0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [filters, loadClaims]);

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
  const openConflicts = conflicts.filter((conflict) => conflict.status === "open" || conflict.status === "escalated");
  const shownConflicts = openConflicts.slice(0, CONFLICTS_SHOWN);
  const rowNote = rowProblem(filters.row);
  // What is said about the table is said about what it was loaded with.
  const searching = !sameFilters(filters, loadedFilters);
  const filtered = hasFilters(loadedFilters);
  const matchingTotal = matching(matchingSummary, loadedFilters.state);
  const moreValues = searching || rowNote ? 0 : nextPageSize(claims.length, matchingTotal);
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
        { query: { workspace_id: workspaceId }, timeoutMs: LONG_ACTION_TIMEOUT_MS },
      );
      setNotice(
        `Prepared batch: ${formatCount(response.claims_created)} new claims, ${formatCount(response.conflicts_detected)} new conflicts. Readiness: ${response.readiness.replaceAll("_", " ")}.`,
      );
      // Done: the page is only being read again from here on.
      setPreparing(false);
      await loadBatch();
    } catch (prepareError) {
      setError(messageFor(prepareError));
    } finally {
      setPreparing(false);
    }
  }

  async function submitClaimReview(decision: "accepted" | "rejected") {
    if (!batchId || !workspaceId || !selectedClaim || claimRationale.trim().length < 3) return;
    const canonicalEntity = claimCanonicalEntity.trim();
    const canonicalField = claimCanonicalField.trim();
    if (decision === "accepted" && (!canonicalEntity || !canonicalField)) {
      setError("Provide a canonical entity and field before accepting this claim.");
      return;
    }
    if ((canonicalEntity && !canonicalField) || (!canonicalEntity && canonicalField)) {
      setError("Canonical entity and canonical field must be supplied together.");
      return;
    }
    setReviewingClaim(true);
    setError(null);
    try {
      await apiClient.post<EvidenceClaim>(
        `/sources/batches/${encodeURIComponent(batchId)}/claims/${encodeURIComponent(selectedClaim.claim_id)}/review`,
        {
          decision,
          rationale: claimRationale.trim(),
          ...(canonicalEntity && canonicalField
            ? { canonical_entity: canonicalEntity, canonical_field: canonicalField }
            : {}),
        },
        { query: { workspace_id: workspaceId }, timeoutMs: LONG_ACTION_TIMEOUT_MS },
      );
      setNotice(`Claim ${decision} and audit recorded.`);
      setSelectedClaim(null);
      setClaimRationale("");
      setClaimCanonicalEntity("");
      setClaimCanonicalField("");
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
        { query: { workspace_id: workspaceId }, timeoutMs: LONG_ACTION_TIMEOUT_MS },
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
        { query: { workspace_id: workspaceId }, timeoutMs: LONG_ACTION_TIMEOUT_MS },
      );
      if (!published.integrity_passed) {
        throw new Error("The graph integrity check did not pass. The batch was not accepted as published.");
      }
      setPublishResult(published);
      setNotice("Batch published to the canonical graph and persisted with an integrity-checked snapshot.");
      // Done: the page is only being read again from here on.
      setPublishing(false);
      await loadBatch();
    } catch (publishError) {
      setError(messageFor(publishError));
    } finally {
      setPublishing(false);
    }
  }

  if (status === "UNKNOWN" || status === "CHECKING") {
    return <div className={`${PAGE_SURFACE} p-8 text-sm text-slate-600`}>Checking your Cortex session…</div>;
  }

  if (status !== "AUTHENTICATED") {
    return (
      <div className={`${PAGE_SURFACE} flex items-center justify-center p-8 text-center`}>
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
      <main className={`${PAGE_SURFACE} p-5 sm:p-8`}>
        <div className="mx-auto max-w-4xl">
          <div className="text-xs text-slate-500">
            <Link href="/nexus/cockpit" className="font-medium text-slate-700 hover:underline">Cortex Nexus</Link>
            <span className="px-2">/</span>
            <span>Source evidence</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Your uploads</h1>
          <p className="mt-1 mb-6 max-w-2xl text-sm text-slate-600">
            {workspace?.name ?? "Active workspace"} · every file uploaded to this workspace and where it stands.
            A file becomes part of your data only after it is reviewed and published.
          </p>
          <UploadsList workspaceId={workspaceId} />
        </div>
      </main>
    );
  }

  return (
    <main className={`${PAGE_SURFACE} p-5 sm:p-8`}>
      <div className="mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs text-slate-500">
              <Link href="/nexus/cockpit" className="font-medium text-slate-700 hover:underline">Cortex Nexus</Link>
              <span className="px-2">/</span>
              <Link href="/evidence" className="font-medium text-slate-700 hover:underline" data-testid="evidence-all-uploads">All uploads</Link>
              <span className="px-2">/</span>
              <span>Source evidence</span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Evidence review</h1>
            <p className="mt-1 text-sm text-slate-600">
              {workspace?.name ?? "Active workspace"} · batch <span className="font-mono">{batchId}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {/* `border-solid` is needed on a button: the site-wide reset in
                globals.css (`button { border: 0 }`) sets the border style to
                none, so `border` alone draws nothing. */}
            <button
              onClick={() => void loadBatch()}
              disabled={loading}
              className="rounded border border-solid border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 disabled:opacity-50"
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

        {error && <div role="alert" className="mb-4 break-words border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
        {notice && <div role="status" className="mb-4 break-words border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</div>}
        {(preparing || publishing) && (
          <p aria-live="polite" className="mb-4 border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700" data-testid="evidence-working">
            {preparing ? "Preparing the claims of this upload." : "Publishing this upload."} {LONG_ACTION_NOTE}
          </p>
        )}

        <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
          {[
            ["Claims", summary ? formatCount(summary.total) : "—"],
            ["Pending", summary ? formatCount(summary.pending_review) : "—"],
            ["Accepted", summary ? formatCount(summary.accepted) : "—"],
            ["Rejected", summary ? formatCount(summary.rejected) : "—"],
            ["Open conflicts", formatCount(openConflicts.length)],
          ].map(([label, value]) => (
            <div key={label} className="border border-slate-200 bg-white p-4" data-testid="evidence-count">
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
          <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-3">
            <div>
              <p className="text-xs text-slate-500">Blocking conflicts</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness ? formatCount(readiness.blocking_conflict_count) : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Pending claims</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness ? formatCount(readiness.pending_claim_count) : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Accepted claims</p>
              <p className="mt-1 text-lg font-semibold text-slate-950">{readiness ? formatCount(readiness.accepted_claim_count) : "—"}</p>
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
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div><p className="text-xs text-slate-500">Version</p><p className="font-semibold">{publishResult.version}</p></div>
              <div><p className="text-xs text-slate-500">Nodes</p><p className="font-semibold">{formatCount(publishResult.node_count)}</p></div>
              <div><p className="text-xs text-slate-500">Edges</p><p className="font-semibold">{formatCount(publishResult.edge_count)}</p></div>
              <div><p className="text-xs text-slate-500">Provenance links</p><p className="font-semibold">{formatCount(publishResult.provenance_link_count)}</p></div>
            </div>
            <p className="mt-3 break-all font-mono text-[11px] text-slate-500">SHA-256: {publishResult.snapshot_hash}</p>
            <Link href="/nexus/world" className="mt-4 inline-flex rounded bg-slate-900 px-4 py-2 text-sm text-white">
              Inspect World State
            </Link>
          </section>
        )}

        {summary !== null && summary.total > 0 && (
          <ColumnReview
            batchId={batchId}
            workspaceId={workspaceId}
            canReview={canReview}
            refreshKey={batchLoads}
            onColumns={(columns) => setColumnChoices((current) => (sameList(current, columns) ? current : columns))}
            onDecided={(message) => {
              setNotice(message);
              void loadBatch();
              // The notice and the publish button are at the top of the page.
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        )}

        {/* `grid-cols-1` lets the single narrow-screen column shrink to the
            screen, so the wide claims table scrolls inside its own box. */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
          <section className="border border-slate-200 bg-white">
            <div className="border-b border-slate-200 p-4">
              <h2 className="font-semibold text-slate-950">Extracted claims</h2>
              <p className="mt-1 text-xs text-slate-500">Each cell of the file (one row, one column) is a claim. Only accepted cells are published. Whole columns are decided above; this table is for a single value that needs its own decision. Decisions are recorded with reviewer identity and rationale.</p>
            </div>
            {summary !== null && summary.total > 0 && (
              // Narrowing the table: a file can hold far more values than a
              // page shows, and a reviewer comes here for particular ones.
              <div className="border-b border-slate-200 p-4" data-testid="claims-filters">
                <div className="flex flex-wrap items-end gap-3 text-xs text-slate-600">
                  <label className="flex flex-col gap-1">
                    Show
                    <select
                      value={filters.state}
                      onChange={(event) => changeFilters({ ...filters, state: event.target.value as ClaimStateFilter })}
                      className="border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="claims-filter-state"
                    >
                      {STATE_CHOICES.map((choice) => (
                        <option key={choice.value} value={choice.value}>{choice.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="flex min-w-0 flex-col gap-1">
                    Column
                    <select
                      value={filters.column}
                      onChange={(event) => changeFilters({ ...filters, column: event.target.value })}
                      className="max-w-[14rem] border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="claims-filter-column"
                    >
                      <option value="">All columns</option>
                      {columnChoices.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    Row
                    <input
                      value={filters.row}
                      onChange={(event) => changeFilters({ ...filters, row: event.target.value })}
                      inputMode="numeric"
                      maxLength={9}
                      placeholder="Any"
                      className="w-20 border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="claims-filter-row"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    Value contains
                    <input
                      value={filters.value}
                      onChange={(event) => changeFilters({ ...filters, value: event.target.value })}
                      maxLength={200}
                      placeholder="Any"
                      className="w-40 border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="claims-filter-value"
                    />
                  </label>
                  {hasFilters(filters) && (
                    <button
                      type="button"
                      onClick={() => changeFilters(NO_FILTERS)}
                      className="rounded border border-solid border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
                      data-testid="claims-filter-clear"
                    >
                      Show all values
                    </button>
                  )}
                </div>
                {rowNote && <p role="alert" className="mt-2 text-xs text-rose-700" data-testid="claims-filter-problem">{rowNote}</p>}
              </div>
            )}
            {summary === null ? (
              <div className="p-8 text-center text-sm text-slate-500">{loading ? "Loading claims…" : "The claims could not be loaded."}</div>
            ) : summary.total === 0 ? (
              <div className="p-8 text-center">
                <p className="text-sm text-slate-600">No claims have been prepared for this batch.</p>
                <button onClick={() => void prepareClaims()} disabled={preparing || !canReview} className="mt-3 rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40">
                  {preparing ? "Preparing…" : "Extract claims from profiles"}
                </button>
              </div>
            ) : (
              <>
              {claimsError && (
                <div role="alert" className="break-words border-b border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" data-testid="claims-error">
                  The values could not be loaded: {claimsError}{" "}
                  <button type="button" onClick={() => void loadClaims(filters, reloadSize(claims.length), 0)} className="ml-1 underline">
                    Retry
                  </button>
                </div>
              )}
              <div className={`overflow-x-auto ${loadingClaims || searching ? "opacity-60" : ""}`} aria-busy={loadingClaims || searching}>
                <table className="w-full text-left text-sm" data-testid="claims-table">
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
                          <p className="font-medium text-slate-900">
                            {claim.source_column}
                            {claim.row_number > 0 && <span className="ml-2 text-xs font-normal text-slate-500">row {claim.row_number}</span>}
                          </p>
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
                              onClick={() => {
                                setSelectedClaim(claim);
                                setClaimRationale("");
                                setClaimCanonicalEntity(claim.canonical_entity ?? "");
                                setClaimCanonicalField(claim.canonical_field ?? "");
                              }}
                              disabled={!canReview}
                              className="text-xs font-medium text-blue-700 hover:underline disabled:opacity-40"
                            >
                              Review
                            </button>
                          ) : <span className="text-xs text-slate-500">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 p-4">
                <p className="text-xs text-slate-600" data-testid="claims-showing">
                  {rowNote
                    ? "Nothing was searched for."
                    : searching || (loadingClaims && claims.length === 0)
                      ? "Searching…"
                      : claimsError && matchingTotal === null
                        ? "The values are not shown: they could not be loaded."
                        : showingLine(claims.length, matchingTotal, filtered)}
                </p>
                {moreValues > 0 && (
                  <button
                    type="button"
                    onClick={() => void loadClaims(loadedFilters, moreValues, claims.length)}
                    disabled={loadingClaims}
                    className="rounded border border-solid border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 disabled:opacity-50"
                    data-testid="claims-more"
                  >
                    {loadingClaims ? "Loading…" : `Show ${formatCount(moreValues)} more`}
                  </button>
                )}
              </div>
              </>
            )}
          </section>

          <section className="border border-slate-200 bg-white">
            <div className="border-b border-slate-200 p-4">
              <h2 className="font-semibold text-slate-950">Conflicts</h2>
              <p className="mt-1 text-xs text-slate-500">Rows that give different accepted values for the same field of one record. Decide which value is published; until then publishing is blocked.</p>
            </div>
            {openConflicts.length === 0 ? (
              <p className="p-5 text-sm text-slate-500">No open conflicts for this batch.</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {conflictsLine(shownConflicts.length, openConflicts.length) && (
                  <p className="p-4 text-xs text-slate-600" data-testid="conflicts-more">
                    {conflictsLine(shownConflicts.length, openConflicts.length)}
                  </p>
                )}
                {shownConflicts.map((conflict) => (
                  <div key={conflict.conflict_id} className="p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="min-w-0 break-words text-sm font-medium text-slate-900">{conflict.canonical_entity ?? "Unknown entity"} · {conflict.canonical_field ?? "Unmapped field"}</p>
                      <span className={`rounded px-2 py-1 text-[10px] ${conflict.blocking ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>
                        {conflict.status === "escalated" ? "Escalated" : conflict.blocking ? "Blocking" : conflict.severity}
                      </span>
                    </div>
                    <p className="mt-2 break-words text-xs text-slate-600">{conflict.explanation}</p>
                    <ul className="mt-2 space-y-1 break-words text-xs text-slate-700" data-testid="conflict-values">
                      {conflictClaims(conflict).map((claim) => (
                        <li key={claim.claim_id}>
                          <span className="text-slate-500">Row {claim.row_number}:</span>{" "}
                          <span className="font-mono">{claim.raw_value}</span>
                          {claimStateNote(claim)}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[11px] text-slate-500">{conflict.claim_ids.length} claims involved</p>
                    <button
                      onClick={() => { setSelectedConflict(conflict); setConflictClaimId(conflictClaims(conflict).find((claim) => claim.claim_state === "accepted" || claim.claim_state === "pending_review")?.claim_id ?? ""); setConflictAction("approved"); setConflictRationale(""); }}
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
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="claim-canonical-entity" className="mb-1 block text-xs font-medium text-slate-700">Canonical entity</label>
                  <input
                    id="claim-canonical-entity"
                    value={claimCanonicalEntity}
                    onChange={(event) => setClaimCanonicalEntity(event.target.value)}
                    maxLength={64}
                    className="w-full border border-slate-300 p-2 text-sm"
                    placeholder="Supplier, PurchaseOrder, Shipment…"
                  />
                </div>
                <div>
                  <label htmlFor="claim-canonical-field" className="mb-1 block text-xs font-medium text-slate-700">Canonical field</label>
                  <input
                    id="claim-canonical-field"
                    value={claimCanonicalField}
                    onChange={(event) => setClaimCanonicalField(event.target.value)}
                    maxLength={128}
                    pattern="[a-z][a-z0-9_]*"
                    className="w-full border border-slate-300 p-2 font-mono text-sm"
                    placeholder="supplier_id, sku, promised_delivery_at…"
                  />
                </div>
              </div>
              <div>
                <label htmlFor="claim-rationale" className="mb-1 block text-xs font-medium text-slate-700">Review rationale (required)</label>
                <textarea id="claim-rationale" value={claimRationale} onChange={(event) => setClaimRationale(event.target.value)} rows={3} minLength={3} maxLength={2000} className="w-full border border-slate-300 p-3 text-sm" placeholder="Explain why this source mapping/value is accepted or rejected." />
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <button onClick={() => setSelectedClaim(null)} className="rounded border border-solid border-slate-300 px-3 py-2 text-sm text-slate-700">Cancel</button>
                <button onClick={() => void submitClaimReview("rejected")} disabled={reviewingClaim || claimRationale.trim().length < 3} className="rounded border border-solid border-rose-300 px-3 py-2 text-sm text-rose-700 disabled:opacity-40">
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
                  <option value="approved">Keep the selected value and withdraw the others</option>
                  <option value="rejected">Reject the selected value, or all values</option>
                  <option value="suppressed">Not a real conflict: publish the first row&apos;s value</option>
                  <option value="escalated">Escalate for further review (publishing stays blocked)</option>
                </select>
              </div>
              {conflictAction === "approved" || conflictAction === "rejected" ? (
                <div>
                  <label htmlFor="conflict-claim" className="mb-1 block text-xs font-medium text-slate-700">Claim</label>
                  <select id="conflict-claim" value={conflictClaimId} onChange={(event) => setConflictClaimId(event.target.value)} className="w-full border border-slate-300 p-2 text-sm">
                    {conflictAction === "rejected" && <option value="">Reject all claims in this conflict</option>}
                    {conflictClaims(selectedConflict)
                      .filter((claim) => claim.claim_state === "accepted" || claim.claim_state === "pending_review")
                      .map((claim) => (
                        <option key={claim.claim_id} value={claim.claim_id}>Row {claim.row_number} · {claim.source_column}: {claim.raw_value}</option>
                      ))}
                  </select>
                </div>
              ) : null}
              <div>
                <label htmlFor="conflict-rationale" className="mb-1 block text-xs font-medium text-slate-700">Rationale (required)</label>
                <textarea id="conflict-rationale" value={conflictRationale} onChange={(event) => setConflictRationale(event.target.value)} rows={3} minLength={3} maxLength={2000} className="w-full border border-slate-300 p-3 text-sm" placeholder="Explain the decision or escalation." />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setSelectedConflict(null)} className="rounded border border-solid border-slate-300 px-3 py-2 text-sm text-slate-700">Cancel</button>
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
    <Suspense fallback={<div className={`${PAGE_SURFACE} p-8 text-sm text-slate-600`}>Loading evidence review…</div>}>
      <EvidenceContent />
    </Suspense>
  );
}
