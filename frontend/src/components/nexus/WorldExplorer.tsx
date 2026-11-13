"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

/**
 * World State Explorer (demo spec §2.B).
 *
 * Interactive, read-only exploration of the workspace dependency graph as
 * persisted by the canonical World State service. All data comes from
 * `/graph/nodes` + `/graph/edges`; nothing is mocked. A tabular view and
 * per-type data-quality summary provide accessible alternatives to the
 * graph, per the accessibility requirement in the demo spec.
 */

type ViewKind = "explorer" | "graph" | "quality" | "provenance";

interface GraphNode {
  node_id?: string;
  entity_id?: string;
  entity_type?: string;
  attributes?: Record<string, unknown>;
  first_seen_version?: number;
  last_modified_version?: number;
}

interface GraphEdge {
  edge_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  relationship_type?: string;
}

interface NodePosition {
  x: number;
  y: number;
}

const VIEW_ORDER: ViewKind[] = ["explorer", "graph", "quality", "provenance"];

const VIEW_LABELS: Record<ViewKind, string> = {
  explorer: "Entity Explorer",
  graph: "Dependency Graph",
  quality: "Data Quality",
  provenance: "Source Provenance",
};

/** Band priority: the display order of entity types in the layered graph. */
const TYPE_BAND_PRIORITY = [
  "supplier", "manufacturer", "plant", "factory", "warehouse", "port", "carrier",
  "component", "material", "product", "sku", "bill_of_materials", "purchase_order",
  "shipment", "route", "inventory_position", "sales_order", "customer",
];

const MAX_GRAPH_NODES = 120;

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function nodeKey(node: GraphNode): string {
  return node.node_id ?? node.entity_id ?? "";
}

function nodeLabel(node: GraphNode): string {
  const attributes = node.attributes ?? {};
  const name = attributes.name ?? attributes.description ?? node.entity_id ?? node.node_id;
  return String(name ?? "Unnamed entity");
}

function nodeType(node: GraphNode): string {
  return String(node.entity_type ?? "entity");
}

export default function WorldExplorer() {
  const { status, workspace } = useAuth();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [view, setView] = useState<ViewKind>("explorer");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [connection, setConnection] = useState<"loading" | "live" | "offline">("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspace?.id) return;
    setConnection("loading");
    setError(null);
    try {
      const [nodeResponse, edgeResponse] = await Promise.all([
        apiClient.get<GraphNode[]>("/graph/nodes", { workspace_id: workspace.id, limit: 200 }),
        apiClient.get<GraphEdge[]>("/graph/edges", { workspace_id: workspace.id, limit: 200 }),
      ]);
      setNodes(nodeResponse);
      setEdges(edgeResponse);
      setConnection("live");
    } catch (requestError) {
      setConnection("offline");
      setError(requestError instanceof Error ? requestError.message : "The dependency graph could not be loaded.");
    }
  }, [workspace?.id]);

  useEffect(() => {
    if (status === "AUTHENTICATED") void load();
  }, [load, status]);

  // View selection from the canonical navigation (?view=…), kept in sync on
  // back/forward without requiring a Suspense boundary.
  useEffect(() => {
    const applyView = () => {
      const requested = new URLSearchParams(window.location.search).get("view");
      if (requested && (VIEW_ORDER as string[]).includes(requested)) {
        setView(requested as ViewKind);
      }
    };
    applyView();
    window.addEventListener("popstate", applyView);
    return () => window.removeEventListener("popstate", applyView);
  }, []);

  const entityTypes = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of nodes) {
      const type = nodeType(node);
      counts.set(type, (counts.get(type) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  const filteredNodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodes.filter((node) => {
      if (typeFilter !== "all" && nodeType(node) !== typeFilter) return false;
      if (!needle) return true;
      return (
        (node.entity_id ?? "").toLowerCase().includes(needle) ||
        (node.node_id ?? "").toLowerCase().includes(needle) ||
        nodeLabel(node).toLowerCase().includes(needle) ||
        nodeType(node).toLowerCase().includes(needle)
      );
    });
  }, [nodes, query, typeFilter]);

  const identifierToKey = useMemo(() => {
    const map = new Map<string, string>();
    for (const node of nodes) {
      const key = nodeKey(node);
      if (!key) continue;
      map.set(key, key);
      if (node.entity_id) map.set(node.entity_id, key);
    }
    return map;
  }, [nodes]);

  const connectionsByNode = useMemo(() => {
    const map = new Map<string, { relatedKey: string; relationship: string; direction: "in" | "out" }[]>();
    for (const edge of edges) {
      const source = identifierToKey.get(edge.source_node_id ?? "");
      const target = identifierToKey.get(edge.target_node_id ?? "");
      if (!source || !target || source === target) continue;
      const relationship = edge.relationship_type ?? "related_to";
      const list = map.get(source) ?? [];
      list.push({ relatedKey: target, relationship, direction: "out" });
      map.set(source, list);
      const reverse = map.get(target) ?? [];
      reverse.push({ relatedKey: source, relationship, direction: "in" });
      map.set(target, reverse);
    }
    return map;
  }, [edges, identifierToKey]);

  const selectedNode = useMemo(
    () => nodes.find((node) => nodeKey(node) === selectedKey) ?? null,
    [nodes, selectedKey],
  );

  const worldVersion = useMemo(
    () =>
      nodes.reduce(
        (max, node) => Math.max(max, node.last_modified_version ?? 0, node.first_seen_version ?? 0),
        0,
      ),
    [nodes],
  );

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <CenteredNote title="Opening Cortex" detail="Checking your workspace session…" />;
  }
  if (status !== "AUTHENTICATED") {
    return (
      <CenteredNote
        title="Sign in to Cortex"
        detail="The World State Explorer is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Fworld" className="button-primary">Sign in</Link>}
      />
    );
  }

  return (
    <div className="min-w-0">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-4 border-b border-border px-5 py-3 sm:px-8">
        <div>
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span className="font-semibold text-ink">Cortex</span>
            <span>/</span>
            <span>World State</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">
            Canonical entities and dependencies persisted by the World State service
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`badge ${connection === "live" ? "badge-positive" : "badge-neutral"}`}>
            {connection === "live" ? "CONNECTED" : connection.toUpperCase()}
          </span>
          <span className="font-mono text-[10px] text-ink-muted">
            {workspace?.name ?? "Workspace"} · {nodes.length} nodes · {edges.length} edges
            {worldVersion ? ` · v${worldVersion}` : ""}
          </span>
        </div>
      </header>

      <div className="space-y-5 px-5 py-6 sm:px-8">
        {error && (
          <div className="notice-error" role="alert">
            {error} <button type="button" onClick={() => void load()} className="ml-2 underline">Retry</button>
          </div>
        )}

        <div className="flex flex-wrap gap-px border border-border bg-border" role="tablist" aria-label="World State views">
          {VIEW_ORDER.map((kind) => (
            <button
              key={kind}
              type="button"
              role="tab"
              aria-selected={view === kind}
              onClick={() => setView(kind)}
              className={`px-4 py-2 text-xs font-medium transition-colors ${
                view === kind ? "bg-surface-2 text-ink" : "bg-surface text-ink-secondary hover:text-ink"
              }`}
            >
              {VIEW_LABELS[kind]}
            </button>
          ))}
        </div>

        {(view === "explorer" || view === "graph") && (
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search entities by id, name, or type…"
              className="field min-w-[240px] flex-1"
              aria-label="Search entities"
            />
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              className="field"
              aria-label="Filter by entity type"
            >
              <option value="all">All types ({nodes.length})</option>
              {entityTypes.map(([type, count]) => (
                <option key={type} value={type}>
                  {titleCase(type)} ({count})
                </option>
              ))}
            </select>
          </div>
        )}

        {view === "explorer" && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <NodeTable nodes={filteredNodes} onSelect={setSelectedKey} selectedKey={selectedKey} total={nodes.length} />
            <EntityDetail
              node={selectedNode}
              connections={selectedKey ? connectionsByNode.get(selectedKey) ?? [] : []}
              labelFor={(key) => {
                const related = nodes.find((candidate) => nodeKey(candidate) === key);
                return related ? nodeLabel(related) : key;
              }}
            />
          </div>
        )}

        {view === "graph" && (
          <div className="border border-border bg-surface">
            <DependencyGraphView
              nodes={filteredNodes}
              edges={edges}
              identifierToKey={identifierToKey}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
            />
            <div className="border-t border-border p-4">
              <EntityDetailInline
                node={selectedNode}
                connections={selectedKey ? connectionsByNode.get(selectedKey) ?? [] : []}
                labelFor={(key) => {
                  const related = nodes.find((candidate) => nodeKey(candidate) === key);
                  return related ? nodeLabel(related) : key;
                }}
              />
            </div>
          </div>
        )}

        {view === "quality" && <QualityView nodes={nodes} edges={edges} worldVersion={worldVersion} />}

        {view === "provenance" && <ProvenanceView nodes={filteredNodes} total={nodes.length} />}
      </div>
    </div>
  );
}

function CenteredNote({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-6 text-center">
      <div className="max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-ink-secondary">{detail}</p>
        {action && <div className="mt-6">{action}</div>}
      </div>
    </div>
  );
}

function NodeTable({
  nodes,
  onSelect,
  selectedKey,
  total,
}: {
  nodes: GraphNode[];
  onSelect: (key: string) => void;
  selectedKey: string | null;
  total: number;
}) {
  if (total === 0) {
    return (
      <div className="border border-border bg-surface px-5 py-12 text-center">
        <div className="text-sm font-medium">No operational graph loaded</div>
        <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-ink-secondary">
          Upload and validate the supported data contract to build the canonical World State.
        </p>
        <Link href="/upload" className="mt-4 inline-block text-xs text-accent hover:underline">
          Open data readiness →
        </Link>
      </div>
    );
  }
  return (
    <div className="border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="eyebrow">Entities ({nodes.length}{nodes.length !== total ? ` of ${total}` : ""})</span>
        <span className="font-mono text-[10px] text-ink-muted">click a row for detail</span>
      </div>
      <div className="max-h-[560px] overflow-y-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-surface-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Entity</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Entity ID</th>
              <th className="px-4 py-2 font-medium">Version</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node) => {
              const key = nodeKey(node);
              const selected = key === selectedKey;
              return (
                <tr
                  key={key || node.entity_id}
                  onClick={() => onSelect(key)}
                  className={`cursor-pointer border-t border-border transition-colors ${
                    selected ? "bg-accent-subtle" : "hover:bg-surface-2"
                  }`}
                >
                  <td className="px-4 py-2 text-ink">{nodeLabel(node)}</td>
                  <td className="px-4 py-2 text-ink-secondary">{titleCase(nodeType(node))}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">{node.entity_id ?? node.node_id ?? "—"}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">
                    {node.last_modified_version ? `v${node.last_modified_version}` : "—"}
                  </td>
                </tr>
              );
            })}
            {nodes.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-ink-secondary">
                  No entities match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EntityDetail({
  node,
  connections,
  labelFor,
}: {
  node: GraphNode | null;
  connections: Array<{ relatedKey: string; relationship: string; direction: "in" | "out" }>;
  labelFor: (key: string) => string;
}) {
  if (!node) {
    return (
      <div className="border border-border bg-surface px-5 py-10 text-center">
        <p className="text-xs text-ink-secondary">Select an entity to inspect its attributes, versions, and dependencies.</p>
      </div>
    );
  }
  const attributes = Object.entries(node.attributes ?? {});
  return (
    <div className="border border-border bg-surface">
      <div className="border-b border-border px-4 py-3">
        <span className="eyebrow">Entity detail</span>
        <h2 className="mt-1 text-sm font-semibold">{nodeLabel(node)}</h2>
        <p className="mt-0.5 font-mono text-[10px] text-ink-muted">{nodeType(node)} · {node.entity_id ?? node.node_id}</p>
      </div>
      <dl className="space-y-2 border-b border-border px-4 py-3 text-xs">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-secondary">First seen</dt>
          <dd className="font-mono text-[11px]">{node.first_seen_version ? `v${node.first_seen_version}` : "—"}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-secondary">Last modified</dt>
          <dd className="font-mono text-[11px]">{node.last_modified_version ? `v${node.last_modified_version}` : "—"}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-secondary">Connections</dt>
          <dd className="font-mono text-[11px]">{connections.length}</dd>
        </div>
      </dl>
      <div className="border-b border-border px-4 py-3">
        <span className="eyebrow">Attributes</span>
        {attributes.length === 0 ? (
          <p className="mt-2 text-xs text-ink-secondary">No attributes recorded for this entity.</p>
        ) : (
          <dl className="mt-2 max-h-48 space-y-1.5 overflow-y-auto text-xs">
            {attributes.map(([key, value]) => (
              <div key={key} className="flex justify-between gap-3">
                <dt className="text-ink-secondary">{key}</dt>
                <dd className="max-w-[55%] truncate text-right font-mono text-[10px] text-ink" title={String(value)}>
                  {String(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div className="px-4 py-3">
        <span className="eyebrow">Dependencies</span>
        {connections.length === 0 ? (
          <p className="mt-2 text-xs text-ink-secondary">No relationships recorded for this entity.</p>
        ) : (
          <ul className="mt-2 max-h-48 space-y-1.5 overflow-y-auto text-xs">
            {connections.slice(0, 12).map((connection, index) => (
              <li key={`${connection.relatedKey}-${index}`} className="flex items-baseline justify-between gap-3">
                <span className="truncate text-ink">{labelFor(connection.relatedKey)}</span>
                <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.08em] text-ink-muted">
                  {connection.direction === "in" ? "←" : "→"} {connection.relationship.replace(/_/g, " ")}
                </span>
              </li>
            ))}
            {connections.length > 12 && (
              <li className="font-mono text-[9px] text-ink-muted">+{connections.length - 12} more</li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}

function EntityDetailInline({
  node,
  connections,
  labelFor,
}: {
  node: GraphNode | null;
  connections: Array<{ relatedKey: string; relationship: string; direction: "in" | "out" }>;
  labelFor: (key: string) => string;
}) {
  if (!node) {
    return <p className="text-xs text-ink-secondary">Select a node to inspect its record.</p>;
  }
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <div>
        <span className="eyebrow">Selected entity</span>
        <p className="mt-1 text-sm font-medium">{nodeLabel(node)}</p>
        <p className="font-mono text-[10px] text-ink-muted">{nodeType(node)}</p>
      </div>
      <div>
        <span className="eyebrow">Attribute count</span>
        <p className="mt-1 font-mono text-sm">{Object.keys(node.attributes ?? {}).length}</p>
      </div>
      <div>
        <span className="eyebrow">Top dependencies</span>
        {connections.length === 0 ? (
          <p className="mt-1 text-xs text-ink-secondary">None recorded.</p>
        ) : (
          <p className="mt-1 truncate text-xs text-ink-secondary" title={connections.slice(0, 4).map((c) => labelFor(c.relatedKey)).join(", ")}>
            {connections.slice(0, 4).map((c) => labelFor(c.relatedKey)).join(", ")}
            {connections.length > 4 ? ` +${connections.length - 4}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

function DependencyGraphView({
  nodes,
  edges,
  identifierToKey,
  selectedKey,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  identifierToKey: Map<string, string>;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  if (nodes.length === 0) {
    return (
      <div className="flex min-h-[280px] items-center justify-center px-5 text-center">
        <p className="text-xs text-ink-secondary">No entities match the current filters.</p>
      </div>
    );
  }

  const visibleNodes = nodes.slice(0, MAX_GRAPH_NODES);

  // Layered layout: entity types form horizontal bands in dependency order.
  const typeOrder = new Map<string, number>();
  [...new Set(visibleNodes.map(nodeType))].forEach((type) => {
    const priority = TYPE_BAND_PRIORITY.indexOf(type);
    typeOrder.set(type, priority === -1 ? TYPE_BAND_PRIORITY.length : priority);
  });
  const bands = [...typeOrder.entries()].sort((a, b) => a[1] - b[1]).map(([type]) => type);

  const positions = new Map<string, NodePosition>();
  const nodesByType = new Map<string, GraphNode[]>();
  for (const node of visibleNodes) {
    const type = nodeType(node);
    const list = nodesByType.get(type) ?? [];
    list.push(node);
    nodesByType.set(type, list);
  }
  const rowHeight = 84;
  const columnWidth = 118;
  const widest = Math.max(...bands.map((type) => Math.min(nodesByType.get(type)?.length ?? 0, 12)));
  const width = Math.max(widest * columnWidth + 80, 760);
  const height = bands.length * rowHeight + 70;

  bands.forEach((type, bandIndex) => {
    const list = (nodesByType.get(type) ?? []).slice(0, 12);
    list.forEach((node, index) => {
      const key = nodeKey(node);
      positions.set(key, {
        x: 60 + index * columnWidth,
        y: 46 + bandIndex * rowHeight,
      });
    });
  });

  const drawnEdges: Array<{ edge: GraphEdge; source: NodePosition; target: NodePosition; highlighted: boolean }> = [];
  for (const edge of edges) {
    const source = positions.get(identifierToKey.get(edge.source_node_id ?? "") ?? "");
    const target = positions.get(identifierToKey.get(edge.target_node_id ?? "") ?? "");
    if (!source || !target) continue;
    const highlighted =
      selectedKey !== null &&
      (identifierToKey.get(edge.source_node_id ?? "") === selectedKey ||
        identifierToKey.get(edge.target_node_id ?? "") === selectedKey);
    drawnEdges.push({ edge, source, target, highlighted });
  }

  return (
    <div className="overflow-x-auto p-4">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="min-w-[720px]"
        role="img"
        aria-label="Interactive dependency graph; a tabular entity list is available under Entity Explorer"
      >
        <g stroke="#27272a" strokeWidth="1">
          {drawnEdges.map((entry, index) => (
            <line
              key={entry.edge.edge_id ?? index}
              x1={entry.source.x}
              y1={entry.source.y}
              x2={entry.target.x}
              y2={entry.target.y}
              stroke={entry.highlighted ? "#16a34a" : undefined}
              strokeWidth={entry.highlighted ? 1.6 : undefined}
            />
          ))}
        </g>
        {visibleNodes.map((node) => {
          const key = nodeKey(node);
          const position = positions.get(key);
          if (!position) return null;
          const selected = key === selectedKey;
          return (
            <g
              key={key}
              onClick={() => onSelect(key)}
              className="cursor-pointer"
              role="button"
              aria-label={`Select ${nodeLabel(node)}`}
            >
              <circle
                cx={position.x}
                cy={position.y}
                r={selected ? 9 : 6}
                fill={selected ? "#16a34a" : "#8b938b"}
              />
              <text x={position.x} y={position.y + 22} textAnchor="middle" fill={selected ? "#fafafa" : "#a1a1aa"} fontSize="9">
                {nodeLabel(node).slice(0, 18)}
              </text>
              <text x={position.x} y={position.y - 12} textAnchor="middle" fill="#71717a" fontSize="8">
                {titleCase(nodeType(node)).slice(0, 16)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 px-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />Selected</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-[#8b938b]" />Entity</span>
        <span className="ml-auto">
          Showing {visibleNodes.length} of {nodes.length} nodes
          {nodes.length > visibleNodes.length ? " — narrow the filters to see more" : ""}
        </span>
      </div>
    </div>
  );
}

function QualityView({ nodes, edges, worldVersion }: { nodes: GraphNode[]; edges: GraphEdge[]; worldVersion: number }) {
  const byType = new Map<string, { count: number; withAttributes: number; versioned: number }>();
  for (const node of nodes) {
    const type = nodeType(node);
    const entry = byType.get(type) ?? { count: 0, withAttributes: 0, versioned: 0 };
    entry.count += 1;
    if (Object.keys(node.attributes ?? {}).length > 0) entry.withAttributes += 1;
    if ((node.last_modified_version ?? 0) > 0) entry.versioned += 1;
    byType.set(type, entry);
  }
  const rows = [...byType.entries()].sort((a, b) => b[1].count - a[1].count);

  if (nodes.length === 0) {
    return (
      <div className="border border-border bg-surface px-5 py-12 text-center">
        <div className="text-sm font-medium">No data quality summary available</div>
        <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-ink-secondary">
          Quality indicators appear after the workspace has ingested and validated operational data.
        </p>
        <Link href="/upload" className="mt-4 inline-block text-xs text-accent hover:underline">Open data readiness →</Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
        <Metric label="Canonical entities" value={nodes.length.toLocaleString()} detail="Distinct graph nodes" />
        <Metric label="Relationships" value={edges.length.toLocaleString()} detail="Persisted graph edges" />
        <Metric label="Entity types" value={String(rows.length)} detail="Distinct operational kinds" />
        <Metric label="World state" value={worldVersion ? `v${worldVersion}` : "—"} detail="Highest version marker" />
      </div>
      <div className="border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <span className="eyebrow">Per-type completeness</span>
        </div>
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Entity type</th>
              <th className="px-4 py-2 font-medium">Count</th>
              <th className="px-4 py-2 font-medium">With attributes</th>
              <th className="px-4 py-2 font-medium">Versioned</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([type, entry]) => (
              <tr key={type} className="border-t border-border">
                <td className="px-4 py-2 text-ink">{titleCase(type)}</td>
                <td className="px-4 py-2 font-mono text-[11px]">{entry.count}</td>
                <td className="px-4 py-2 font-mono text-[11px]">
                  {entry.withAttributes}/{entry.count}
                  {entry.withAttributes < entry.count && (
                    <span className="ml-2 font-mono text-[9px] uppercase text-warning">incomplete</span>
                  )}
                </td>
                <td className="px-4 py-2 font-mono text-[11px]">
                  {entry.versioned}/{entry.count}
                  {entry.versioned < entry.count && (
                    <span className="ml-2 font-mono text-[9px] uppercase text-warning">stale marker</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ProvenanceView({ nodes, total }: { nodes: GraphNode[]; total: number }) {
  if (total === 0) {
    return (
      <div className="border border-border bg-surface px-5 py-12 text-center">
        <div className="text-sm font-medium">No provenance records available</div>
        <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-ink-secondary">
          Source provenance appears after operational data has been ingested into the World State.
        </p>
        <Link href="/upload" className="mt-4 inline-block text-xs text-accent hover:underline">Open data readiness →</Link>
      </div>
    );
  }
  return (
    <div className="border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="eyebrow">Source provenance ({nodes.length}{nodes.length !== total ? ` of ${total}` : ""})</span>
        <span className="font-mono text-[10px] text-ink-muted">as recorded at ingestion</span>
      </div>
      <div className="max-h-[560px] overflow-y-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-surface-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Entity</th>
              <th className="px-4 py-2 font-medium">Source system</th>
              <th className="px-4 py-2 font-medium">Entity ID</th>
              <th className="px-4 py-2 font-medium">First seen</th>
              <th className="px-4 py-2 font-medium">Last modified</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node) => {
              const attributes = node.attributes ?? {};
              const source = attributes.source ?? attributes.source_system;
              return (
                <tr key={nodeKey(node) || node.entity_id} className="border-t border-border">
                  <td className="px-4 py-2 text-ink">{nodeLabel(node)}</td>
                  <td className="px-4 py-2 text-ink-secondary">{source ? String(source) : <span className="text-ink-muted">not recorded</span>}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">{node.entity_id ?? node.node_id ?? "—"}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">{node.first_seen_version ? `v${node.first_seen_version}` : "—"}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">{node.last_modified_version ? `v${node.last_modified_version}` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="bg-surface px-4 py-4">
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-[11px] text-ink-muted">{detail}</div>
    </div>
  );
}
