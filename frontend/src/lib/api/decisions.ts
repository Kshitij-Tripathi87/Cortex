import { request } from "./http";
import {
  DecisionValidityResponse,
  EvidenceNode,
} from "@/types/nexus";

export interface DecisionApprovalRequest {
  decision_id: string;
  reviewer: string;
  comments?: string;
}

export async function fetchDecisionValidity(): Promise<DecisionValidityResponse> {
  return request<DecisionValidityResponse>({ path: "/workspace/decisions/validity" });
}

export async function fetchDecisionEvidence(): Promise<{
  decision_id: string;
  total_evidence_nodes: number;
  total_attribution_edges: number;
  nodes: EvidenceNode[];
  attribution_edges: Array<{ from: string; to: string; relation: string }>;
}> {
  return request({ path: "/workspace/decisions/evidence" });
}

/** Governance approval mutation (spec §32: no fake optimistic success). */
export async function approveDecision(
  req: DecisionApprovalRequest
): Promise<{ decision_id: string; status: string }> {
  return request<{ decision_id: string; status: string }>({
    method: "POST",
    path: `/workspace/decisions/${req.decision_id}/approve`,
    body: { reviewer: req.reviewer, comments: req.comments },
  });
}
