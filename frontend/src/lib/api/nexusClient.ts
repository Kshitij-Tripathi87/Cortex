/**
 * Cortex Nexus — Workspace API client (spec §8).
 */

import { request } from "./http";
import {
  DataAnswerabilityReport,
  DeliberationResponse,
  DemoLoadResponse,
  EvidenceAnswer,
  StreamEventResponse,
  WorkspaceStateResponse,
} from "@/types/nexus";

export { fetchActiveSignals } from "./signals";

export async function fetchWorkspaceState(): Promise<WorkspaceStateResponse> {
  return request<WorkspaceStateResponse>({ path: "/workspace/state" });
}

export async function loadDemoDataset(): Promise<DemoLoadResponse> {
  return request<DemoLoadResponse>({ method: "POST", path: "/workspace/demo/load" });
}

export async function triggerDeliberation(
  incidentEntityId?: string
): Promise<DeliberationResponse> {
  return request<DeliberationResponse>({
    method: "POST",
    path: "/workspace/deliberate",
    body: { incident_entity_id: incidentEntityId ?? null },
  });
}

export async function appendStreamEvent(
  eventType: string,
  payload: Record<string, unknown>
): Promise<StreamEventResponse> {
  return request<StreamEventResponse>({
    method: "POST",
    path: "/workspace/append-stream",
    body: { event_type: eventType, payload },
  });
}

export async function checkQueryReadiness(
  query: string
): Promise<DataAnswerabilityReport> {
  return request<DataAnswerabilityReport>({
    path: "/workspace/query/readiness",
    query: { query },
  });
}

export async function askNexusQuestion(query: string): Promise<{
  query: string;
  status: string;
  readiness_report: DataAnswerabilityReport;
  answer?: EvidenceAnswer;
}> {
  return request({
    method: "POST",
    path: "/workspace/query/ask",
    body: { query },
  });
}
