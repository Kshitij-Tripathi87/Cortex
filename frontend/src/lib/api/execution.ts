/**
 * Cortex Nexus — Policy Execution & Automated Dispatch Typed API Client (Track X2)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

export interface ExecutionRequest {
  decision_id: string;
  target_candidate_id: string;
  execution_mode: "AUTOMATED_WEBHOOK" | "MANUAL_DISPATCH";
  idempotency_key: string;
}

export interface ExecutionResponse {
  execution_id: string;
  decision_id: string;
  status: "QUEUED" | "IN_TRANSIT" | "COMPLETED" | "FAILED";
  dispatched_at: string;
  adapter_target: string;
}

export async function executeDecision(req: ExecutionRequest): Promise<ExecutionResponse> {
  const resp = await fetch(`${API_BASE}/executions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) throw new Error("Decision execution dispatch failed");
  return resp.json();
}

export async function fetchExecutionStatus(executionId: string): Promise<ExecutionResponse> {
  const resp = await fetch(`${API_BASE}/executions/${executionId}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`Failed to fetch execution status for ${executionId}`);
  return resp.json();
}
