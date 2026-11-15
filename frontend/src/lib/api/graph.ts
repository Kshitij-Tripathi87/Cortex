/**
 * Cortex Nexus — Operational Graph API Client.
 */

import { request } from "./http";
import { GraphNode, SubgraphResponse, CriticalNodesResponse } from "@/types/nexus";

export async function fetchOperationalSubgraph(
  workspaceId: string,
  centerNodeId?: string,
  maxHops: number = 2,
  limitNodes: number = 100
): Promise<SubgraphResponse> {
  const [nodes, edges] = await Promise.all([
    request<Array<Record<string, any>>>({
      path: "/graph/nodes",
      query: { workspace_id: workspaceId, limit: limitNodes },
    }),
    request<Array<Record<string, any>>>({
      path: "/graph/edges",
      query: { workspace_id: workspaceId, limit: limitNodes },
    }),
  ]);
  const mappedNodes = nodes.map((node) => ({
    id: String(node.node_id),
    type: String(node.entity_type).toUpperCase() as GraphNode["type"],
    attributes: node.attributes ?? {},
    pagerank: Number(node.attributes?.pagerank ?? 0),
    degree: Number(node.attributes?.degree ?? 0),
    is_spof: Boolean(node.attributes?.is_spof ?? node.attributes?.spof ?? false),
  }));
  const mappedEdges = edges.map((edge) => ({
    edge_id: String(edge.edge_id),
    source: String(edge.source_node_id),
    target: String(edge.target_node_id),
    relation_type: String(edge.relationship_type),
    weight: Number(edge.attributes?.weight ?? 1),
  }));
  return {
    center_node_id: centerNodeId,
    max_hops: maxHops,
    nodes_count: mappedNodes.length,
    edges_count: mappedEdges.length,
    nodes: mappedNodes,
    edges: mappedEdges,
  };
}

export async function fetchCriticalNodes(workspaceId: string): Promise<CriticalNodesResponse> {
  const graph = await fetchOperationalSubgraph(workspaceId, undefined, 2, 200);
  return {
    top_critical_sellers: [],
    top_critical_routes: [],
    high_dependency_spofs: graph.nodes.filter((node) => node.is_spof).map((node) => node.id),
    seller_concentration_gini: 0,
  };
}

export async function fetchGraphDeltas(workspaceId: string, sinceVersion: number = 0) {
  return request<{ events: unknown[]; latest_seq: number }>({
    path: "/realtime/events",
    query: { workspace_id: workspaceId, after_seq: sinceVersion },
  });
}
