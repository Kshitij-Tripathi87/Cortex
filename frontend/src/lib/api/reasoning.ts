import { request } from "./http";
import { DataAnswerabilityReport, EvidenceAnswer } from "@/types/nexus";

export interface AskResponse {
  query: string;
  status: string;
  readiness_report: DataAnswerabilityReport;
  answer?: EvidenceAnswer;
}

export async function askNexus(query: string): Promise<AskResponse> {
  return request<AskResponse>({
    method: "POST",
    path: "/workspace/query/ask",
    body: { query },
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
