"use client";

import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api, ApiError } from "@/lib/api";

interface Node { node_id: string; entity_type: string; entity_id: string; attributes: Record<string, any>; first_seen_version: number; last_modified_version: number; }
interface Edge { edge_id: string; source_node_id: string; target_node_id: string; relationship_type: string; attributes: Record<string, any>; first_seen_version: number; last_modified_version: number; }
interface Snapshot { snapshot_id: string; version: number; snapshot_hash: string; prev_snapshot_hash: string | null; node_count: number; edge_count: number; source_batch_id: string | null; sealed_at: string; }
interface Integrity { no_orphan_edges: boolean; all_nodes_have_provenance: boolean; all_edges_have_provenance: boolean; chain_verified: boolean; }

type Tab = "nodes" | "edges" | "snapshots";
const ENTITY_TYPES = ["All", "Supplier", "Facility", "Product", "Customer", "Shipment", "Route", "Carrier", "Inventory", "PurchaseOrder", "PurchaseOrderLine"];
const RELATIONSHIP_TYPES = ["All", "SHIPS_TO", "CONNECTS_TO", "SUPPLIES_TO", "MANAGES", "OWNS"];

export default function GraphExplorerPage() {
  const [workspaceId] = useWorkspace();
  const [activeTab, setActiveTab] = useState<Tab>("nodes");
  const [entityType, setEntityType] = useState("All");
  const [relationshipType, setRelationshipType] = useState("All");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | unknown>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const fetchIntegrity = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const data = await api.get<Integrity>("/api/v1/graph/integrity", { workspace_id: workspaceId });
      setIntegrity(data);
    } catch (e) { /* ignore integrity errors */ }
  }, [workspaceId]);

  const fetchNodes = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, any> = { workspace_id: workspaceId, limit: pageSize, offset: (page - 1) * pageSize };
      if (entityType && entityType !== "All") params.entity_type = entityType;
      const data = await api.get<Node[]>("/api/v1/graph/nodes", params);
      setNodes(data);
    } catch (e) { setError(e); }
    finally { setLoading(false); }
  }, [workspaceId, entityType, page]);

  const fetchEdges = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, any> = { workspace_id: workspaceId, limit: pageSize, offset: (page - 1) * pageSize };
      if (relationshipType && relationshipType !== "All") params.relationship_type = relationshipType;
      const data = await api.get<Edge[]>("/api/v1/graph/edges", params);
      setEdges(data);
    } catch (e) { setError(e); }
    finally { setLoading(false); }
  }, [workspaceId, relationshipType, page]);

  const fetchSnapshots = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Snapshot[]>("/api/v1/graph/snapshots", { workspace_id: workspaceId });
      setSnapshots(data);
    } catch (e) { setError(e); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { fetchIntegrity(); }, [fetchIntegrity]);
  useEffect(() => { if (activeTab === "nodes") fetchNodes(); }, [activeTab, fetchNodes]);
  useEffect(() => { if (activeTab === "edges") fetchEdges(); }, [activeTab, fetchEdges]);
  useEffect(() => { if (activeTab === "snapshots") fetchSnapshots(); }, [activeTab, fetchSnapshots]);

  const retry = () => { if (activeTab === "nodes") fetchNodes(); else if (activeTab === "edges") fetchEdges(); else fetchSnapshots(); };

  const integrityFailed = integrity && (!integrity.no_orphan_edges || !integrity.all_nodes_have_provenance || !integrity.all_edges_have_provenance || !integrity.chain_verified);

  return (
    <div>
      <PageHeader title="Graph Explorer" description="Inspect the operational graph compiled from evidence" />
      {integrityFailed && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
          ⚠️ Integrity checks failed. Some graph elements may be incomplete.
        </div>
      )}
      {integrity && (
        <div className="mb-6 bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Integrity Status</h3>
          <div className="flex gap-4 flex-wrap">
            <div className="flex items-center gap-2"><span className={integrity.no_orphan_edges ? "text-green-500" : "text-red-500"}>{integrity.no_orphan_edges ? "✓" : "✗"}</span><span className="text-sm">No Orphan Edges</span></div>
            <div className="flex items-center gap-2"><span className={integrity.all_nodes_have_provenance ? "text-green-500" : "text-red-500"}>{integrity.all_nodes_have_provenance ? "✓" : "✗"}</span><span className="text-sm">All Nodes Have Provenance</span></div>
            <div className="flex items-center gap-2"><span className={integrity.all_edges_have_provenance ? "text-green-500" : "text-red-500"}>{integrity.all_edges_have_provenance ? "✓" : "✗"}</span><span className="text-sm">All Edges Have Provenance</span></div>
            <div className="flex items-center gap-2"><span className={integrity.chain_verified ? "text-green-500" : "text-red-500"}>{integrity.chain_verified ? "✓" : "✗"}</span><span className="text-sm">Chain Verified</span></div>
          </div>
        </div>
      )}
      <div className="mb-4 border-b border-gray-200">
        <nav className="flex gap-4">
          {(["nodes", "edges", "snapshots"] as Tab[]).map((tab) => (
            <button key={tab} onClick={() => { setActiveTab(tab); setPage(1); }} className={`px-4 py-2 text-sm font-medium ${activeTab === tab ? "border-b-2 border-blue-500 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}>{tab.charAt(0).toUpperCase() + tab.slice(1)}</button>
          ))}
        </nav>
      </div>
      {activeTab === "nodes" && (
        <div>
          <div className="mb-4 flex gap-2 items-center">
            <label className="text-sm text-gray-600">Entity Type:</label>
            <select value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1); }} className="border border-gray-300 rounded px-3 py-1.5 text-sm">
              {ENTITY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {loading ? <LoadingState message="Loading nodes..." /> : error ? <ErrorState error={error} onRetry={retry} /> : nodes.length === 0 ? <EmptyState title="No nodes" description="No graph nodes found for this workspace" /> : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entity Type</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entity ID</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Attributes</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">First Seen</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Modified</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th></tr></thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {nodes.map((n) => (
                    <tr key={n.node_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm"><Badge>{n.entity_type}</Badge></td>
                      <td className="px-4 py-3 text-sm font-mono">{n.entity_id}</td>
                      <td className="px-4 py-3 text-sm">{Object.keys(n.attributes).slice(0, 3).map((k) => <Badge key={k} variant="neutral">{k}</Badge>)}</td>
                      <td className="px-4 py-3 text-sm">{n.first_seen_version}</td>
                      <td className="px-4 py-3 text-sm">{n.last_modified_version}</td>
                      <td className="px-4 py-3 text-sm"><button onClick={() => setSelectedNode(n)} className="text-blue-600 hover:text-blue-800">View</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 py-3 flex gap-2"><button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-3 py-1 text-sm border rounded disabled:opacity-50">Prev</button><span className="px-3 py-1 text-sm">Page {page}</span><button onClick={() => setPage((p) => p + 1)} disabled={nodes.length < pageSize} className="px-3 py-1 text-sm border rounded disabled:opacity-50">Next</button></div>
            </div>
          )}
        </div>
      )}
      {activeTab === "edges" && (
        <div>
          <div className="mb-4 flex gap-2 items-center">
            <label className="text-sm text-gray-600">Relationship:</label>
            <select value={relationshipType} onChange={(e) => { setRelationshipType(e.target.value); setPage(1); }} className="border border-gray-300 rounded px-3 py-1.5 text-sm">
              {RELATIONSHIP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {loading ? <LoadingState message="Loading edges..." /> : error ? <ErrorState error={error} onRetry={retry} /> : edges.length === 0 ? <EmptyState title="No edges" description="No graph edges found for this workspace" /> : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">First Seen</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Modified</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th></tr></thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {edges.map((e) => (
                    <tr key={e.edge_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono">{e.source_node_id}</td>
                      <td className="px-4 py-3 text-sm font-mono">{e.target_node_id}</td>
                      <td className="px-4 py-3 text-sm"><Badge>{e.relationship_type}</Badge></td>
                      <td className="px-4 py-3 text-sm">{e.first_seen_version}</td>
                      <td className="px-4 py-3 text-sm">{e.last_modified_version}</td>
                      <td className="px-4 py-3 text-sm"><button onClick={() => setSelectedEdge(e)} className="text-blue-600 hover:text-blue-800">View</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 py-3 flex gap-2"><button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-3 py-1 text-sm border rounded disabled:opacity-50">Prev</button><span className="px-3 py-1 text-sm">Page {page}</span><button onClick={() => setPage((p) => p + 1)} disabled={edges.length < pageSize} className="px-3 py-1 text-sm border rounded disabled:opacity-50">Next</button></div>
            </div>
          )}
        </div>
      )}
      {activeTab === "snapshots" && (
        <div>
          {loading ? <LoadingState message="Loading snapshots..." /> : error ? <ErrorState error={error} onRetry={retry} /> : snapshots.length === 0 ? <EmptyState title="No snapshots" description="No graph snapshots found. Compile evidence first." /> : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Hash</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Prev Hash</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Nodes</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Edges</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Batch ID</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Sealed At</th></tr></thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {snapshots.map((s) => (
                    <tr key={s.snapshot_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-semibold">{s.version}</td>
                      <td className="px-4 py-3 text-sm font-mono text-xs">{s.snapshot_hash.slice(0, 16)}...</td>
                      <td className="px-4 py-3 text-sm font-mono text-xs">{s.prev_snapshot_hash ? s.prev_snapshot_hash.slice(0, 16) + "..." : "—"}</td>
                      <td className="px-4 py-3 text-sm">{s.node_count}</td>
                      <td className="px-4 py-3 text-sm">{s.edge_count}</td>
                      <td className="px-4 py-3 text-sm font-mono text-xs">{s.source_batch_id || "—"}</td>
                      <td className="px-4 py-3 text-sm">{new Date(s.sealed_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {selectedNode && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setSelectedNode(null)}>
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Node Details</h3>
            <div className="space-y-2 text-sm">
              <div><span className="font-medium">Node ID:</span> <span className="font-mono">{selectedNode.node_id}</span></div>
              <div><span className="font-medium">Entity Type:</span> <Badge>{selectedNode.entity_type}</Badge></div>
              <div><span className="font-medium">Entity ID:</span> <span className="font-mono">{selectedNode.entity_id}</span></div>
              <div><span className="font-medium">First Seen Version:</span> {selectedNode.first_seen_version}</div>
              <div><span className="font-medium">Last Modified Version:</span> {selectedNode.last_modified_version}</div>
              <div className="mt-4"><h4 className="font-semibold mb-2">Attributes</h4><pre className="bg-gray-50 p-3 rounded text-xs overflow-auto max-h-64">{JSON.stringify(selectedNode.attributes, null, 2)}</pre></div>
            </div>
            <div className="flex justify-end mt-4"><button onClick={() => setSelectedNode(null)} className="px-4 py-2 bg-gray-200 rounded text-sm hover:bg-gray-300">Close</button></div>
          </div>
        </div>
      )}
      {selectedEdge && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setSelectedEdge(null)}>
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Edge Details</h3>
            <div className="space-y-2 text-sm">
              <div><span className="font-medium">Edge ID:</span> <span className="font-mono">{selectedEdge.edge_id}</span></div>
              <div><span className="font-medium">Source:</span> <span className="font-mono">{selectedEdge.source_node_id}</span></div>
              <div><span className="font-medium">Target:</span> <span className="font-mono">{selectedEdge.target_node_id}</span></div>
              <div><span className="font-medium">Relationship:</span> <Badge>{selectedEdge.relationship_type}</Badge></div>
              <div><span className="font-medium">First Seen Version:</span> {selectedEdge.first_seen_version}</div>
              <div><span className="font-medium">Last Modified Version:</span> {selectedEdge.last_modified_version}</div>
              <div className="mt-4"><h4 className="font-semibold mb-2">Attributes</h4><pre className="bg-gray-50 p-3 rounded text-xs overflow-auto max-h-64">{JSON.stringify(selectedEdge.attributes, null, 2)}</pre></div>
            </div>
            <div className="flex justify-end mt-4"><button onClick={() => setSelectedEdge(null)} className="px-4 py-2 bg-gray-200 rounded text-sm hover:bg-gray-300">Close</button></div>
          </div>
        </div>
      )}
    </div>
  );
}