"use client";

import React, { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ApiClientError } from "@/lib/auth/errors";
import { decideTaskApproval, fetchDecisionRoom } from "@/lib/api/decisionRoom";
import {
  canApproveDecision,
  invocationStatusBadgeClass,
  taskStatusBadgeClass,
} from "@/lib/nexus/decisionRoomModel";
import type { DecisionRoomView } from "@/types/nexus";

/**
 * Decision-1 — Decision Room as a read-only projection of the durable
 * runtime (GET /nexus/tasks/{task_id}/decision-room).
 *
 * CRITICAL CONSTRAINT: this page owns NO state machine, NO approval logic,
 * NO execution logic, and NO World State mutation. Every field is rendered
 * verbatim from the backend projection (PostgreSQL durable records). The
 * approve/reject buttons submit the human decision to the server; the
 * durable APPROVED row — not this UI — is the authority that opens
 * EXECUTING, and the UI state after any action is always re-derived from a
 * fresh read of the projection.
 */
function DecisionRoomProjection() {
  const { user, workspace } = useAuth();
  const searchParams = useSearchParams();
  const taskId = searchParams.get("task_id");

  const [view, setView] = useState<DecisionRoomView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const workspaceId = workspace?.id ?? null;
  const mayApprove = canApproveDecision(user?.role);

  const load = useCallback(async () => {
    if (!taskId || !workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchDecisionRoom(taskId, workspaceId);
      setView(response.data.decision_room);
    } catch (err) {
      setView(null);
      if (err instanceof ApiClientError && err.status === 404) {
        setError("Task not found in this workspace.");
      } else if (err instanceof ApiClientError && err.status === 403) {
        setError("You do not have access to this task's workspace.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to load the Decision Room.");
      }
    } finally {
      setLoading(false);
    }
  }, [taskId, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = useCallback(
    async (approved: boolean) => {
      if (!taskId || !workspaceId) return;
      setDeciding(true);
      setActionError(null);
      try {
        await decideTaskApproval({ taskId, workspaceId, approved });
        // State is always re-derived from the durable projection — never
        // from a client-side guess about what the decision caused.
        const response = await fetchDecisionRoom(taskId, workspaceId);
        setView(response.data.decision_room);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 403) {
          setActionError("Your role cannot approve or reject this decision.");
        } else {
          setActionError(err instanceof Error ? err.message : "Decision failed.");
        }
      } finally {
        setDeciding(false);
      }
    },
    [taskId, workspaceId]
  );

  if (!taskId) {
    return (
      <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
        <IntentWorkspaceBar />
        <div className="border border-zinc-800 rounded-xl p-8 text-center bg-zinc-950/90">
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Decision Room</h1>
          <p className="text-sm text-zinc-400 mt-2">
            No task selected. Open a task from the{" "}
            <Link href="/workspace/agents/tasks" className="text-emerald-400 hover:underline">
              agent tasks
            </Link>{" "}
            view or pass <code className="font-mono text-xs text-zinc-300">?task_id=</code> in the
            URL to project its durable runtime here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between" data-testid="decision-room-header">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Decision Room</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Read-only projection of the durable task runtime. Every field is derived from
            PostgreSQL; the backend is the only authority.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          data-testid="decision-room-refresh"
          className="px-4 py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100 font-bold font-mono text-xs transition border border-zinc-700"
        >
          {loading ? "Loading..." : "⟳ Refresh"}
        </button>
      </div>

      {error !== null && (
        <div
          className="border border-red-800 bg-red-950/40 rounded-xl p-4 text-sm text-red-300"
          data-testid="decision-room-error"
        >
          {error}
        </div>
      )}

      {loading && view === null && (
        <div className="border border-zinc-800 rounded-xl p-8 text-center text-sm text-zinc-400 bg-zinc-950/90">
          Loading durable task state...
        </div>
      )}

      {view !== null && <Projection view={view} mayApprove={mayApprove} deciding={deciding} onDecide={decide} actionError={actionError} />}
    </div>
  );
}

function Projection({
  view,
  mayApprove,
  deciding,
  onDecide,
  actionError,
}: {
  view: DecisionRoomView;
  mayApprove: boolean;
  deciding: boolean;
  onDecide: (approved: boolean) => void;
  actionError: string | null;
}) {
  const { task, pending_decision: pending } = view;
  return (
    <div className="space-y-6 font-mono text-xs">
      {/* Task state */}
      <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-task">
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-zinc-100">TASK STATE</h2>
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${taskStatusBadgeClass(task.status)}`} data-testid="task-status-badge">
            {task.status}
          </span>
        </div>
        <p className="text-sm text-zinc-200 font-sans mt-2 leading-relaxed">{task.objective}</p>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-zinc-500 mt-2.5 pt-2 border-t border-zinc-800/60">
          <span className="font-mono">task_id: {task.task_id}</span>
          <span className="font-mono">trace_id: {task.trace_id}</span>
          <span className="font-mono">world_state_version: {task.world_state_version}</span>
          <span className="font-mono">requires_approval: {String(task.requires_approval)}</span>
        </div>
      </section>

      {/* Pending decision + server-enforced approve/reject */}
      {pending !== null && (
        <section className="border border-amber-800/80 rounded-xl p-4 bg-amber-950/20" data-testid="decision-room-pending">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-amber-300">PENDING DECISION</h2>
            {pending.awaited_since !== null && (
              <span className="text-[10px] text-amber-500">awaited since {pending.awaited_since}</span>
            )}
          </div>
          {pending.reason !== null && <p className="text-sm text-zinc-200 font-sans mt-2">{pending.reason}</p>}
          {pending.approval_required_for.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 mt-2 text-[10px] text-zinc-400">
              <span className="font-bold">APPROVAL REQUIRED FOR:</span>
              {pending.approval_required_for.map((capability) => (
                <span key={capability} className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800">
                  {capability}
                </span>
              ))}
            </div>
          )}
          {mayApprove ? (
            <div className="flex items-center gap-3 mt-3 pt-3 border-t border-amber-900/60">
              <button
                onClick={() => onDecide(true)}
                disabled={deciding}
                data-testid="decision-approve"
                className="px-4 py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold font-mono text-xs transition disabled:opacity-50"
              >
                {deciding ? "Submitting..." : "✓ Approve"}
              </button>
              <button
                onClick={() => onDecide(false)}
                disabled={deciding}
                data-testid="decision-reject"
                className="px-4 py-2 rounded bg-red-500 hover:bg-red-400 text-zinc-950 font-bold font-mono text-xs transition disabled:opacity-50"
              >
                {deciding ? "Submitting..." : "✗ Reject"}
              </button>
            </div>
          ) : (
            <p className="text-[10px] text-zinc-400 mt-3 pt-3 border-t border-amber-900/60">
              Read-only: your role can review this decision, but approval is an operator action.
            </p>
          )}
          {actionError !== null && (
            <p className="text-[10px] text-red-400 mt-2" data-testid="decision-action-error">
              {actionError}
            </p>
          )}
        </section>
      )}

      {/* Recommendation */}
      {view.recommendation !== null && (
        <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-recommendation">
          <h2 className="font-bold text-zinc-100">RECOMMENDATION ({view.recommendation.source})</h2>
          <p className="text-sm text-zinc-200 font-sans mt-2 leading-relaxed">{view.recommendation.statement}</p>
          <EvidenceRow refs={view.recommendation.evidence_refs} label="EVIDENCE" />
        </section>
      )}

      {/* Plan */}
      {view.plan !== null && (
        <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-plan">
          <h2 className="font-bold text-zinc-100">PLAN</h2>
          <div className="mt-2 space-y-2">
            {view.plan.steps.map((step, index) => (
              <div key={step.step_id} className="flex items-start gap-2">
                <span className="w-5 h-5 rounded-full bg-zinc-800 text-zinc-300 flex items-center justify-center text-[10px] shrink-0">
                  {index + 1}
                </span>
                <div>
                  <span className="text-zinc-200">{step.title}</span>
                  <span className="text-zinc-500"> [{step.agent_role}]</span>
                  <div className="flex flex-wrap gap-1 mt-0.5">
                    {step.required_capabilities.map((capability) => (
                      <span key={capability} className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-800 text-[10px]">
                        {capability}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Capability invocations + policy results */}
      <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-invocations">
        <h2 className="font-bold text-zinc-100">CAPABILITY INVOCATIONS</h2>
        {view.invocations.length === 0 ? (
          <p className="text-zinc-500 mt-2">No capability invocations recorded.</p>
        ) : (
          <div className="mt-2 space-y-2">
            {view.invocations.map((invocation) => (
              <div key={invocation.invocation_id} className="border border-zinc-800/60 rounded p-2">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-200">{invocation.capability_id}</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${invocationStatusBadgeClass(invocation.status)}`}>
                    {invocation.status}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-[10px] text-zinc-500 mt-1">
                  <span>v{invocation.capability_version}</span>
                  <span>{invocation.side_effect}</span>
                  <span>wsv {invocation.world_state_version}</span>
                  <span className="font-mono">sha256:{invocation.arguments_sha256.slice(0, 12)}</span>
                </div>
                {invocation.error !== null && <p className="text-[10px] text-amber-400 mt-1">error: {invocation.error}</p>}
                <p className="text-[10px] text-zinc-500 mt-1">
                  policy: {invocation.authorization.allowed === true ? "allowed" : invocation.authorization.allowed === false ? "denied" : "n/a"}
                  {invocation.authorization.policy_id !== null && ` (${invocation.authorization.policy_id})`}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Approvals trail */}
      {view.approvals.length > 0 && (
        <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-approvals">
          <h2 className="font-bold text-zinc-100">APPROVAL TRAIL</h2>
          <div className="mt-2 space-y-2">
            {view.approvals.map((approval, index) => (
              <div key={`${approval.decision}-${approval.decided_at}-${index}`} className="flex items-center justify-between border border-zinc-800/60 rounded p-2">
                <div>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${approval.decision === "APPROVED" ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : approval.decision === "REJECTED" ? "bg-red-950 text-red-400 border border-red-800" : "bg-zinc-900 text-zinc-300 border border-zinc-800"}`}>
                    {approval.decision}
                  </span>
                  {approval.reason !== null && <span className="text-zinc-400 ml-2">{approval.reason}</span>}
                </div>
                <div className="text-right text-[10px] text-zinc-500">
                  {approval.approver_id !== null && <div className="font-mono">approver: {approval.approver_id}</div>}
                  <div>{approval.decided_at}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Execution + outcome */}
      {view.execution !== null && (
        <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-execution">
          <h2 className="font-bold text-zinc-100">EXECUTION</h2>
          <p className="mt-2 text-zinc-200">
            status: {view.execution.status} · attempts: {view.execution.attempts}
          </p>
          {view.execution.failure_reason !== null && (
            <p className="text-[10px] text-red-400 mt-1">{view.execution.failure_reason}</p>
          )}
        </section>
      )}

      {view.outcome !== null && (
        <section className="border border-emerald-800/80 rounded-xl p-4 bg-emerald-950/20" data-testid="decision-room-outcome">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-emerald-300">OUTCOME</h2>
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${taskStatusBadgeClass(view.outcome.status)}`}>
              {view.outcome.status}
            </span>
          </div>
          <p className="mt-2 text-[10px] text-zinc-500">{view.outcome.completed_at}</p>
        </section>
      )}

      {/* Evidence ledger */}
      <section className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90" data-testid="decision-room-evidence">
        <h2 className="font-bold text-zinc-100">EVIDENCE LEDGER</h2>
        {view.evidence.length === 0 ? (
          <p className="text-zinc-500 mt-2">No evidence established.</p>
        ) : (
          <div className="flex flex-wrap gap-2 mt-2">
            {view.evidence.map((record) => (
              <span key={record.ref} className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800">
                {record.ref}
              </span>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function EvidenceRow({ refs, label }: { refs: string[]; label: string }) {
  if (refs.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[10px] text-zinc-500 mt-2 pt-2 border-t border-zinc-800/60">
      <span className="font-bold text-zinc-400">{label}:</span>
      {refs.map((ref) => (
        <span key={ref} className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800">
          {ref}
        </span>
      ))}
    </div>
  );
}

export default function DecisionRoomPage() {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-400">Loading Decision Room...</div>}>
      <DecisionRoomProjection />
    </Suspense>
  );
}
