/**
 * Cortex Nexus — Workspace API client (spec §8).
 */

import { request } from "./http";
import {
  DataAnswerabilityReport,
  EvidenceAnswer,
} from "@/types/nexus";

export { fetchActiveSignals } from "./signals";

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
