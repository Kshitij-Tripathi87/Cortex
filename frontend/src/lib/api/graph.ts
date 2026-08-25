/**
 * Cortex Nexus — Operational Graph API Client.
 */

import { request } from "./http";
import { SubgraphResponse, CriticalNodesResponse } from "@/types/nexus";

export async function fetchOperationalSubgraph(
  centerNodeId?: string,
  maxHops: number = 2,
  limitNodes: number = 100
): Promise<SubgraphResponse> {
  return request<SubgraphResponse>({
    path: "/workspace/graph/subgraph",
    query: {
      center_node_id: centerNodeId,
      max_hops: maxHops,
      limit_nodes: limitNodes,
    },
  });
}

export async function fetchCriticalNodes(): Promise<CriticalNodesResponse> {
  return request<CriticalNodesResponse>({ path: "/workspace/graph/critical-nodes" });
}

export async function fetchGraphDeltas(sinceVersion: string = "") {
  return request<{ deltas_count: number; deltas: unknown[] }>({
    path: "/workspace/graph/delta",
    query: { since_version: sinceVersion },
  });
}
