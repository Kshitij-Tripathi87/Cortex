/**
 * Cortex Nexus — Cryptographic Evidence DAG Typed API Client (Track X2 & X5)
 */

import { request } from "./http";
import { EvidenceNode, EvidenceVersionTuple } from "@/types/nexus";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export interface DecisionEvidenceResponse {
  decision_id: string;
  sha256_root_hash: string;
  version_tuple: EvidenceVersionTuple;
  dag_nodes: EvidenceNode[];
}

export async function fetchEvidenceForDecision(decisionId: string): Promise<DecisionEvidenceResponse> {
  return request({ path: `/decisions/${decisionId}/evidence` });
}

export async function verifyEvidenceNode(nodeId: string): Promise<{ node_id: string; is_valid: boolean; computed_hash: string }> {
  return request({ path: `/evidence/${nodeId}/verify` });
}

export async function fetchEvidenceGraph(): Promise<{ nodes: EvidenceNode[]; edges: Array<{ from: string; to: string; relation: string }> }> {
  return request({ path: "/workspace/decisions/evidence" });
}