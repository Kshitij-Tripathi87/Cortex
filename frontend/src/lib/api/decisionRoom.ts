/**
 * Decision-1 — Decision Room typed API client.
 *
 * Read-only projection: GET /nexus/tasks/{task_id}/decision-room derives
 * the entire view from PostgreSQL durable records server-side. The only
 * write this client exposes is the server-enforced human approval
 * (POST /nexus/tasks/{task_id}/approvals); the durable approval row — not
 * the client — is the authority that opens EXECUTING.
 */

import { apiClient } from "@/lib/auth/client";
import type { DecisionRoomResponse, TaskApprovalResponse } from "@/types/nexus";

export async function fetchDecisionRoom(
  taskId: string,
  workspaceId: string
): Promise<DecisionRoomResponse> {
  return apiClient.get<DecisionRoomResponse>(
    `/nexus/tasks/${encodeURIComponent(taskId)}/decision-room`,
    { workspace_id: workspaceId }
  );
}

export async function decideTaskApproval(opts: {
  taskId: string;
  workspaceId: string;
  approved: boolean;
  reason?: string;
}): Promise<TaskApprovalResponse> {
  return apiClient.post<TaskApprovalResponse>(
    `/nexus/tasks/${encodeURIComponent(opts.taskId)}/approvals`,
    {
      workspace_id: opts.workspaceId,
      approved: opts.approved,
      ...(opts.reason !== undefined && opts.reason !== "" ? { reason: opts.reason } : {}),
    }
  );
}
