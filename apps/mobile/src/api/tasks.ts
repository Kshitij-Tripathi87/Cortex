/**
 * Tasks + Approvals â€” the REST API remains authoritative (Day 25 Â§9/Â§12).
 *
 * The phone only submits APPROVE or REJECT â€” it does not decide whether the
 * action is valid. The backend validates approval_id/task_id/action/target/
 * expiry and drives the governed execution:
 *
 *   PROPOSE -> POLICY -> HUMAN APPROVAL -> EXECUTE
 *
 * Voice must not create a bypass around Nexus governance.
 */

import { apiGet, apiPost, unwrap } from "./client.ts";
import type { BootstrapApproval, BootstrapTask } from "./bootstrap.ts";

export interface TaskView extends BootstrapTask {
  failure_reason: string | null;
}

export async function listActiveTasks(): Promise<BootstrapTask[]> {
  const snapshot = unwrap(await apiGet<{ data: { active_tasks: BootstrapTask[] } }>(
    "/mobile/bootstrap",
  ));
  return snapshot.active_tasks;
}

export async function getTask(taskId: string): Promise<TaskView> {
  return unwrap(await apiGet<{ data: { task: TaskView } }>(`/nexus/tasks/${taskId}`));
}

export async function createTask(input: {
  workspaceId: string;
  objective: string;
  worldStateVersion: number;
}): Promise<BootstrapTask> {
  return unwrap(
    await apiPost<{ data: BootstrapTask }>("/nexus/tasks", {
      workspace_id: input.workspaceId,
      objective: input.objective,
      world_state_version: input.worldStateVersion,
    }),
  );
}

export async function listPendingApprovals(): Promise<BootstrapApproval[]> {
  const snapshot = unwrap(
    await apiGet<{ data: { pending_approvals: BootstrapApproval[] } }>("/mobile/bootstrap"),
  );
  return snapshot.pending_approvals;
}

/** The governed decision: APPROVED is the only key into EXECUTING. */
export async function decideApproval(
  taskId: string,
  workspaceId: string,
  approved: boolean,
  reason?: string,
): Promise<{ task_id: string; status: string; approved: boolean }> {
  return unwrap(
    await apiPost<{ data: { task_id: string; status: string; approved: boolean } }>(
      `/nexus/tasks/${taskId}/approvals`,
      {
        workspace_id: workspaceId,
        approved,
        reason: reason ?? null,
      },
    ),
  );
}
