"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

/**
 * Disruption & Impact Analysis (demo spec §2.C).
 *
 * Renders the persisted risk registry (root causes, hidden dependencies,
 * exposure, SLA risk, blast radius) and derives upstream/downstream
 * dependency paths by traversing the same persisted graph the World State
 * Explorer shows. Where a value is absent (e.g. no GNN score recorded) the
 * UI says so instead of inventing one (spec invariant 4).
 */

type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "WATCH";

interface Risk {
  risk_id?: string;
  entity_id: string;
  entity_name?: string;
  entity_kind: string;
  severity: Severity;
  risk_score: number;
  gnn_risk_score?: number | null;
  title: string;
  description?: string | null;
  revenue_exposure?: number | null;
  sla_risk_pct?: number | null;
  blast_radius_count?: number | null;
  world_state_version?: number | null;
  root_causes?: string[] | null;
  hidden_dependencies?: Array<{ description?: string; downstream_order_count?: number } | string> | null;
  status?: string;
  created_at?: string | null;
}

interface GraphNode {
  node_id?: string;
  entity_id?: string;
  entity_type?: string;
  attributes?: Record<string, unknown>;
}

interface GraphEdge {
  edge_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  relationship_type?: string;
}

const severityStyles: Record<Severity, string> = {
  CRITICAL: "border-critical/50 bg-critical-subtle text-critical",
  HIGH: "border-warning/50 bg-warning-subtle text-warning",
  MEDIUM: "border-warning/40 bg-warning-subtle text-warning",
  LOW: "border-accent/40 bg-accent-subtle text-accent",
  WATCH: "border-border bg-surface text-ink-secondary",
};

function formatINR(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 10_000_000) return `₹${(value / 10_000_000).toFixed(1)}Cr`;
  if (Math.abs(value) >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (Math.abs(value) >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function nodeKey(node: GraphNode): string {
  return node.node_id ?? node.entity_id ?? "";
}

function nodeLabel(node: GraphNode): string {
  const attributes = node.attributes ?? {};
  const name = attributes.name ?? attributes.description ?? node.entity_id ?? node.node_id;
  return String(name ?? "Unnamed entity");
}

/** Simple paths from a start entity across persisted graph edges (BFS, depth-limited). */
function dependencyPaths(
  startEntityId: string,
  edges: GraphEdge[],
  identifierToKey: Map<string, string>,
  labelFor: (key: string) => string,
  maxDepth = 3,
  maxPaths = 8,
): Array<{ steps: string[]; relationships: string[] }> {
  const adjacency = new Map<string, Array<{ other: string; relationship: string }>>();
  for (const edge of edges) {
    const source = identifierToKey.get(edge.source_node_id ?? "");
    const target = identifierToKey.get(edge.target_node_id ?? "");
    if (!source || !target || source === target) continue;
    const relationship = (edge.relationship_type ?? "related_to").replace(/_/g, " ");
    const outList = adjacency.get(source) ?? [];
    outList.push({ other: target, relationship });
    adjacency.set(source, outList);
    const inList = adjacency.get(target) ?? [];
    inList.push({ other: source, relationship });
    adjacency.set(target, inList);
  }

  const startKey = identifierToKey.get(startEntityId);
  if (!startKey) return [];

  const paths: Array<{ steps: string[]; relationships: string[] }> = [];
  const visited = new Set<string>([startKey]);

  const walk = (currentKey: string, steps: string[], relationships: string[]) => {
    if (paths.length >= maxPaths) return;
    if (steps.length > 1) paths.push({ steps: [...steps], relationships: [...relationships] });
    if (steps.length > maxDepth) return;
    for (const { other, relationship } of adjacency.get(currentKey) ?? []) {
      if (visited.has(other)) continue;
      visited.add(other);
      walk(other, [...steps, labelFor(other)], [...relationships, relationship]);
      visited.delete(other);
      if (paths.length >= maxPaths) return;
    }
  };

  walk(startKey, [labelFor(startKey)], []);
  return paths.sort((a, b) => b.steps.length - a.steps.length);
}

export default function ImpactAnalysisPage() {
  const { status, workspace } = useAuth();
  const [risks, setRisks] = useState<Risk[]>([]);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);
  const [view, setView] = useState<"detail" | "paths">("detail");
  const [connection, setConnection] = useState<"loading" | "live" | "offline">("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspace?.id) return;
    setConnection("loading");
    setError(null);
    try {
      const [riskResponse, nodeResponse, edgeResponse] = await Promise.all([
        apiClient.get<{ data?: { risks?: Risk[] } }>("/nexus/risks", {
          workspace_id: workspace.id,
          status: "all",
        }),
        apiClient.get<GraphNode[]>("/graph/nodes", { workspace_id: workspace.id, limit: 500 }),
        apiClient.get<GraphEdge[]>("/graph/edges", { workspace_id: workspace.id, limit: 800 }),
      ]);
      const nextRisks = riskResponse.data?.risks ?? [];
      setRisks(nextRisks);
      setNodes(nodeResponse);
      setEdges(edgeResponse);
      setSelectedRiskId((current) =>
        current && nextRisks.some((risk) => risk.entity_id === current)
          ? current
          : nextRisks[0]?.entity_id ?? null,
      );
      setConnection("live");
    } catch (requestError) {
      setConnection("offline");
      setError(requestError instanceof Error ? requestError.message : "Impact data could not be loaded.");
    }
  }, [workspace?.id]);

  useEffect(() => {
    if (status === "AUTHENTICATED") void load();
  }, [load, status]);

  useEffect(() => {
    const applyView = () => {
      const requested = new URLSearchParams(window.location.search).get("view");
      if (requested === "detail" || requested === "paths") setView(requested);
    };
    applyView();
    window.addEventListener("popstate", applyView);
    return () => window.removeEventListener("popstate", applyView);
  }, []);

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

  const selectedRisk = useMemo(
    () => risks.find((risk) => risk.entity_id === selectedRiskId) ?? risks[0] ?? null,
    [risks, selectedRiskId],
  );

  const inGraph = Boolean(selectedRisk && identifierToKey.has(selectedRisk.entity_id));

  const paths = useMemo(() => {
    if (!selectedRisk) return [];
    return dependencyPaths(selectedRisk.entity_id, edges, identifierToKey, (key) => {
      const node = nodes.find((candidate) => nodeKey(candidate) === key);
      return node ? nodeLabel(node) : key;
    });
  }, [selectedRisk, edges, identifierToKey, nodes]);

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <CenteredNote title="Opening Cortex" detail="Checking your workspace session…" />;
  }
  if (status !== "AUTHENTICATED") {
    return (
      <CenteredNote
        title="Sign in to Cortex"
        detail="Impact analysis is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Fimpact" className="button-primary">Sign in</Link>}
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
            <span>Intelligence</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">Disruption impact, dependency paths, and confidence</p>
        </div>
        <span className={`badge ${connection === "live" ? "badge-positive" : "badge-neutral"}`}>
          {connection === "live" ? "CONNECTED" : connection.toUpperCase()}
        </span>
      </header>

      <div className="space-y-5 px-5 py-6 sm:px-8">
        {error && (
          <div className="notice-error" role="alert">
            {error} <button type="button" onClick={() => void load()} className="ml-2 underline">Retry</button>
          </div>
        )}

        <div className="flex flex-wrap gap-px border border-border bg-border" role="tablist" aria-label="Intelligence views">
          {(["detail", "paths"] as const).map((kind) => (
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
              {kind === "detail" ? "Disruption detail" : "Risk & blast radius"}
            </button>
          ))}
        </div>

        {risks.length === 0 ? (
          <div className="border border-border bg-surface px-5 py-12 text-center">
            <div className="text-sm font-medium">No risk records</div>
            <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-ink-secondary">
              Risks appear here after operational data has been ingested and analyzed. Cortex does not
              fabricate disruptions.
            </p>
            <Link href="/upload" className="mt-4 inline-block text-xs text-accent hover:underline">Open data readiness →</Link>
          </div>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div className="border border-border bg-surface">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <span className="eyebrow">Disruptions ({risks.length})</span>
              </div>
              <div className="max-h-[620px] divide-y divide-border overflow-y-auto">
                {risks.map((risk) => (
                  <button
                    key={risk.risk_id ?? risk.entity_id}
                    type="button"
                    onClick={() => setSelectedRiskId(risk.entity_id)}
                    className={`w-full px-4 py-3 text-left transition-colors hover:bg-surface-2 ${
                      selectedRisk?.entity_id === risk.entity_id ? "border-l-2 border-accent bg-surface-2" : "border-l-2 border-transparent"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-medium text-ink">{risk.entity_name || risk.title}</span>
                      <span className={`badge ${severityStyles[risk.severity] ?? severityStyles.WATCH}`}>{risk.severity}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink-secondary">{risk.title}</p>
                    <div className="mt-2 flex gap-3 font-mono text-[10px] text-ink-muted">
                      <span>{formatINR(risk.revenue_exposure)} exposure</span>
                      <span>{risk.blast_radius_count ?? "—"} orders</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {selectedRisk && (
              <div className="min-w-0 space-y-5">
                <div className="border border-border bg-surface">
                  <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
                    <div>
                      <span className="eyebrow">Disruption</span>
                      <h2 className="mt-1 text-base font-semibold">{selectedRisk.title}</h2>
                      <p className="mt-0.5 font-mono text-[10px] text-ink-muted">
                        {selectedRisk.entity_name || selectedRisk.entity_id} · {titleCase(selectedRisk.entity_kind)}
                        {selectedRisk.status ? ` · ${selectedRisk.status}` : ""}
                      </p>
                    </div>
                    <span className={`badge ${severityStyles[selectedRisk.severity] ?? severityStyles.WATCH}`}>
                      {selectedRisk.severity}
                    </span>
                  </div>
                  {selectedRisk.description && (
                    <p className="border-b border-border px-5 py-3 text-xs leading-5 text-ink-secondary">
                      {selectedRisk.description}
                    </p>
                  )}
                  <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-3">
                    <Detail label="Risk score" value={`${Math.round(selectedRisk.risk_score * 100)}%`} />
                    <Detail
                      label="GNN risk score"
                      value={selectedRisk.gnn_risk_score === null || selectedRisk.gnn_risk_score === undefined ? "not recorded" : `${Math.round(selectedRisk.gnn_risk_score * 100)}%`}
                    />
                    <Detail label="Revenue exposure" value={formatINR(selectedRisk.revenue_exposure)} />
                    <Detail
                      label="SLA risk"
                      value={selectedRisk.sla_risk_pct === null || selectedRisk.sla_risk_pct === undefined ? "—" : `${Math.round(selectedRisk.sla_risk_pct * 100)}%`}
                    />
                    <Detail label="Blast radius (orders)" value={selectedRisk.blast_radius_count === null || selectedRisk.blast_radius_count === undefined ? "—" : String(selectedRisk.blast_radius_count)} />
                    <Detail label="World state" value={selectedRisk.world_state_version ? `v${selectedRisk.world_state_version}` : "—"} />
                  </dl>
                </div>

                <div className="grid gap-5 md:grid-cols-2">
                  <div className="border border-border bg-surface p-4">
                    <span className="eyebrow">Root causes</span>
                    {(selectedRisk.root_causes ?? []).length === 0 ? (
                      <p className="mt-2 text-xs text-ink-secondary">No root causes recorded for this risk.</p>
                    ) : (
                      <ul className="mt-2 space-y-1.5 text-xs leading-5 text-ink-secondary">
                        {(selectedRisk.root_causes ?? []).map((cause, index) => (
                          <li key={index} className="border-l-2 border-critical/50 pl-3">{cause}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="border border-border bg-surface p-4">
                    <span className="eyebrow">Hidden dependencies</span>
                    {(selectedRisk.hidden_dependencies ?? []).length === 0 ? (
                      <p className="mt-2 text-xs text-ink-secondary">No hidden dependencies recorded for this risk.</p>
                    ) : (
                      <ul className="mt-2 space-y-1.5 text-xs leading-5 text-ink-secondary">
                        {(selectedRisk.hidden_dependencies ?? []).map((dependency, index) => {
                          const text = typeof dependency === "string" ? dependency : dependency.description ?? "";
                          const orders = typeof dependency === "object" && dependency !== null ? dependency.downstream_order_count : undefined;
                          return (
                            <li key={index} className="border-l-2 border-warning/50 pl-3">
                              {text || "Dependency recorded without a description"}
                              {orders !== undefined && orders !== null && (
                                <span className="ml-2 font-mono text-[10px] text-ink-muted">{orders} downstream orders</span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                </div>

                <div className="border border-border bg-surface p-4">
                  <span className="eyebrow">Methodology & confidence</span>
                  <ul className="mt-2 space-y-1.5 text-xs leading-5 text-ink-secondary">
                    <li>· Risk figures come from the persisted risk registry at world state {selectedRisk.world_state_version ? `v${selectedRisk.world_state_version}` : "(version not recorded)"}.</li>
                    <li>· Exposure, SLA risk, and blast radius are computed by the deterministic impact engine at detection time; every component traces to graph rows and a documented formula.</li>
                    <li>· {selectedRisk.gnn_risk_score === null || selectedRisk.gnn_risk_score === undefined ? "No GNN-derived score was recorded — deterministic path only." : `A GNN-derived score (${Math.round(selectedRisk.gnn_risk_score * 100)}%) supplements the deterministic score.`}</li>
                    <li>· Dependency paths are traversed from the live persisted graph, depth-limited to 3 hops.</li>
                  </ul>
                </div>

                <div className="border border-border bg-surface">
                  <div className="border-b border-border px-4 py-3">
                    <span className="eyebrow">Dependency paths from this entity</span>
                  </div>
                  <div className="px-4 py-3">
                    {!inGraph ? (
                      <p className="text-xs text-ink-secondary">
                        This entity is not present in the currently loaded graph — it may be stale or not yet
                        resolved. The discrepancy is surfaced rather than hidden.
                      </p>
                    ) : paths.length === 0 ? (
                      <p className="text-xs text-ink-secondary">No dependency paths traverse this entity in the loaded graph.</p>
                    ) : (
                      <ol className="space-y-2">
                        {paths.map((path, index) => (
                          <li key={index} className="border border-border bg-surface-2 px-3 py-2 text-xs leading-5">
                            {path.steps.map((step, stepIndex) => (
                              <span key={stepIndex}>
                                {stepIndex > 0 && (
                                  <span className="mx-2 font-mono text-[9px] uppercase tracking-[0.08em] text-ink-muted">
                                    —{path.relationships[stepIndex - 1]}→
                                  </span>
                                )}
                                <span className="text-ink">{step}</span>
                              </span>
                            ))}
                            <span className="ml-2 font-mono text-[9px] text-ink-muted">({path.steps.length - 1} hop{path.steps.length > 2 ? "s" : ""})</span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">{label}</dt>
      <dd className="mt-1 font-mono text-sm text-ink">{value}</dd>
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
