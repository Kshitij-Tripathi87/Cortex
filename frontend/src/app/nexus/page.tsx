"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiBaseUrl } from "@/lib/api";
import type { GraphNode, GraphEdge, SubgraphResponse } from "@/types/nexus";

interface WorkspaceState {
  status: string;
  workspace_id: string;
  datasets_loaded: Array<{
    dataset_id: string;
    name: string;
    row_count: number;
    columns: string[];
    status: string;
    ingested_at: string;
  }>;
  datasets_ingested: number;
  total_raw_rows: number;
  graph_version: string;
  world_state_version: number;
  graph_analytics: {
    total_nodes: number;
    total_edges: number;
    density: number;
    top_critical_suppliers: Array<{
      supplier_id: string;
      order_volume: number;
      pagerank: number;
    }>;
    high_dependency_spofs: string[];
    supplier_concentration_gini: number;
  };
  active_signals: Array<{
    signal_id?: string;
    entity_id?: string;
    entity_type?: string;
    severity?: string;
    status?: string;
    description?: string;
    [key: string]: unknown;
  }>;
  last_decision?: {
    decision_id?: string;
    counterfactual_simulations?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  } | null;
}

interface AskResponse {
  answer?: string;
  evidence?: Array<{ ref?: string; snippet?: string; [key: string]: unknown }>;
  confidence?: number;
  [key: string]: unknown;
}

interface Signal {
  signal_id?: string;
  entity_id?: string;
  entity_type?: string;
  severity?: string;
  status?: string;
  description?: string;
  [key: string]: unknown;
}

interface SignalsResponse {
  active_signals: Signal[];
  primary_blast_radius?: Record<string, unknown>;
}

interface DeliberationResult {
  decision_id?: string;
  target_entity?: string;
  participating_agents?: string[];
  message_stream?: Array<{
    message_id: string;
    sender_role: string;
    sender_name: string;
    sender_version?: string;
    content: string;
    evidence_refs?: string[];
    phase: string;
    timestamp: string;
    world_state_version?: number;
    confidence?: number;
    tools_invoked?: string[];
    proposal?: { action: string; target_entity_ids?: string[] };
    parallel_constraints?: string[];
  }>;
  counterfactuals?: Array<{
    candidate: string;
    action: string;
    delay_days: number;
    sla_breach_pct: number;
    sla_protection_pct?: number;
    cost_usd: number;
    revenue_protected_usd: number;
    net_economic_value_usd: number;
    is_optimal: boolean;
  }>;
  decision_card?: {
    selected_candidate: string;
    action: string;
    cost_usd: number;
    net_economic_value_usd: number;
    status: string;
    explanation: string;
  };
}

interface DecisionValidity {
  decision_id: string;
  is_valid: boolean;
  invalidation_reason?: string | null;
  dependency_set?: Record<string, unknown> | null;
}

interface EvidenceGraph {
  decision_id: string;
  total_evidence_nodes: number;
  total_attribution_edges: number;
  nodes: Array<{
    node_id: string;
    node_type: string;
    label: string;
    checksum: string;
    payload: Record<string, unknown>;
  }>;
  attribution_edges: Array<{ from: string; to: string; relation: string }>;
  counterfactual_simulations?: Array<Record<string, unknown>>;
}

type Counterfactual = NonNullable<DeliberationResult["counterfactuals"]>[number];

/** Single operational thread the operator is investigating.
 *  Sections never mutate arbitrary pieces â€” only explicit trace transitions
 *  (traceSignal â†’ deliberate â†’ decision) update these fields. */
interface NexusTrace {
  signalId: string | null;
  signalEntityId: string | null;
  centerNodeId: string | null;
  incidentEntityId: string | null;
  decisionId: string | null;
}

const EMPTY_TRACE: NexusTrace = {
  signalId: null,
  signalEntityId: null,
  centerNodeId: null,
  incidentEntityId: null,
  decisionId: null,
};

type LoadState<T> =
  | { status: "idle"; data: null }
  | { status: "loading"; data: null }
  | { status: "success"; data: T }
  | { status: "empty"; data: null }
  | { status: "error"; data: null; error: string };

function formatUsd(v: number): string {
  const abs = Math.abs(v);
  const body =
    abs >= 1000 ? `${(abs / 1000).toFixed(1).replace(/\.0$/, "")}K` : `${Math.round(abs)}`;
  return `${v < 0 ? "-" : "+"}$${body}`;
}

const SECTIONS = [
  "Overview",
  "Data",
  "World",
  "Signals",
  "Agents",
  "Scenarios",
  "Decisions",
  "Evidence",
] as const;

type Section = (typeof SECTIONS)[number];

const TYPE_COLORS: Record<string, string> = {
  SUPPLIER: "#e5484d",
  SELLER: "#e5484d",
  CUSTOMER: "#3b82f6",
  ORDER: "#f5a623",
  ORDER_ITEM: "#8b8b8b",
  PRODUCT: "#22c55e",
  LOCATION: "#a855f7",
  ROUTE: "#06b6d4",
};

function nodeColor(type: string): string {
  return TYPE_COLORS[type] ?? "#6b7280";
}

function radialLayout(nodes: GraphNode[], width: number, height: number): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const cx = width / 2;
  const cy = height / 2;
  const rings = Math.max(1, Math.ceil(nodes.length / 18));
  nodes.forEach((node, i) => {
    const ring = i % rings;
    const indexInRing = Math.floor(i / rings);
    const ringCount = Math.ceil((nodes.length - i + rings - 1) / rings);
    const radius = 60 + ring * ((Math.min(width, height) / 2 - 80) / rings);
    const angle =
      (2 * Math.PI * indexInRing) / Math.max(1, ringCount) + ring * 0.5;
    positions.set(node.id, {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    });
  });
  return positions;
}

export default function NexusConsolePage() {
  const [section, setSection] = useState<Section>("Overview");
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [subgraph, setSubgraph] = useState<SubgraphResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [askResult, setAskResult] = useState<AskResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [signals, setSignals] = useState<SignalsResponse | null>(null);
  const [deliberation, setDeliberation] = useState<DeliberationResult | null>(null);
  const [deliberating, setDeliberating] = useState(false);
  const [decisionValidity, setDecisionValidity] = useState<DecisionValidity | null>(null);
  const [trace, setTrace] = useState<NexusTrace>(EMPTY_TRACE);
  const [graphParams, setGraphParams] = useState({ max_hops: 2, limit_nodes: 120, overlay: "world" });
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [signalsLoad, setSignalsLoad] = useState<LoadState<SignalsResponse>>({
    status: "idle",
    data: null,
  });
  const [evidenceLoad, setEvidenceLoad] = useState<LoadState<EvidenceGraph>>({
    status: "idle",
    data: null,
  });
  const [criticalNodes, setCriticalNodes] = useState<{
    top_critical_suppliers: Array<{ supplier_id: string; order_volume: number; pagerank: number }>;
    top_critical_routes?: Array<Record<string, unknown>>;
    high_dependency_spofs: string[];
    supplier_concentration_gini: number;
  } | null>(null);
  const [evidence, setEvidence] = useState<EvidenceGraph | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ w: 900, h: 520 });

  const loadAll = useCallback(async () => {
    try {
      setError(null);
      const ws = await api.get<WorkspaceState>("/workspace/state");
      setState(ws);
      const sg = await api.get<SubgraphResponse>("/workspace/graph/subgraph", {
        center_node_id: trace.centerNodeId || undefined,
        max_hops: graphParams.max_hops,
        limit_nodes: graphParams.limit_nodes,
      });
      setSubgraph(sg);
      setSignalsLoad({ status: "loading", data: null });
      try {
        const sig = await api.get<SignalsResponse>("/workspace/signals");
        setSignalsLoad(
          sig.active_signals.length === 0 && !sig.primary_blast_radius
            ? { status: "empty", data: null }
            : { status: "success", data: sig },
        );
      } catch (sigErr) {
        setSignalsLoad({
          status: "error",
          data: null,
          error: sigErr instanceof Error ? sigErr.message : "signals unavailable",
        });
      }
      try {
        const v = await api.get<DecisionValidity>("/workspace/decisions/validity");
        setDecisionValidity(v);
      } catch {
        setDecisionValidity(null);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} â€” is the backend running?`
          : "backend unreachable",
      );
    }
  }, [trace.centerNodeId, graphParams.max_hops, graphParams.limit_nodes]);

  useEffect(() => {
    void loadAll();
    const interval = setInterval(() => void loadAll(), 30000);
    return () => clearInterval(interval);
  }, [loadAll]);

  // Live channel: SSE stream with reconciliation. The header indicator reflects
  // actual EventSource state â€” never a static "connected" decoration.
  const [live, setLive] = useState<"connecting" | "live" | "reconnecting" | "offline">(
    "connecting",
  );
  const loadAllRef = useRef(loadAll);
  useEffect(() => {
    loadAllRef.current = loadAll;
  }, [loadAll]);
  const subgraphRef = useRef(subgraph);
  useEffect(() => {
    subgraphRef.current = subgraph;
  }, [subgraph]);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;
    let attempts = 0;

    const connect = (): void => {
      if (disposed) return;
      source = new EventSource(`${apiBaseUrl}/api/v1/workspace/stream`);
      source.onopen = () => {
        attempts = 0;
        setLive("live");
      };
      source.onerror = () => {
        setLive(attempts >= 3 ? "offline" : "reconnecting");
        attempts += 1;
        source?.close();
        const backoff = Math.min(15000, 1000 * 2 ** attempts);
        reconnectTimer = setTimeout(connect, backoff);
      };
      source.addEventListener("graph_delta", () => {
        void loadAllRef.current();
      });
      source.addEventListener("heartbeat", (event) => {
        try {
          const hb = JSON.parse((event as MessageEvent).data) as {
            total_graph_nodes?: number;
            nodes_count?: number;
            world_state_version?: number;
          };
          // Reconcile on out-of-band mutations (e.g. ingestion) that don't
          // emit deltas: authoritative size/version vs what we rendered.
          const sg = subgraphRef.current;
          const st = stateRef.current;
          // Server may emit either total_graph_nodes (legacy) or nodes_count
          // (canonical). Use whichever is present.
          const hbNodes = hb.total_graph_nodes ?? hb.nodes_count;
          const staleNodes =
            typeof hbNodes === "number" &&
            sg != null &&
            hbNodes !== sg.nodes_count;
          const staleVersion =
            typeof hb.world_state_version === "number" &&
            st != null &&
            hb.world_state_version !== st.world_state_version;
          if (staleNodes || staleVersion) void loadAllRef.current();
        } catch {
          // malformed heartbeat â€” ignore
        }
      });
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
    };
  }, []);

  useEffect(() => {
    if (section !== "World") return;
    let cancelled = false;
    void (async () => {
      try {
        const cn = await api.get<NonNullable<typeof criticalNodes>>("/workspace/graph/critical-nodes");
        if (!cancelled) setCriticalNodes(cn);
      } catch {
        if (!cancelled) setCriticalNodes(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [section]);

  // Evidence is fail-closed: it only loads for the active trace's decision_id.
  // Never a "latest decision" fallback in the UI.
  useEffect(() => {
    if (section !== "Evidence") return;
    if (!trace.decisionId) {
      setEvidenceLoad({ status: "empty", data: null });
      setEvidence(null);
      return;
    }
    let cancelled = false;
    setEvidenceLoad({ status: "loading", data: null });
    void (async () => {
      try {
        const ev = await api.get<EvidenceGraph>("/workspace/decisions/evidence", {
          decision_id: trace.decisionId!,
        });
        if (!cancelled) {
          setEvidence(ev);
          setEvidenceLoad({ status: "success", data: ev });
        }
      } catch (err) {
        if (!cancelled) {
          setEvidence(null);
          setEvidenceLoad({
            status: "error",
            data: null,
            error: err instanceof Error ? err.message : "evidence could not be retrieved",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [section, trace.decisionId]);

  const layout = useMemo(() => {
    if (!subgraph) return null;
    return radialLayout(
      subgraph.nodes.slice(0, graphParams.limit_nodes),
      canvasSize.w,
      canvasSize.h,
    );
  }, [subgraph, canvasSize, graphParams.limit_nodes]);

  /** Reusable graph canvas â€” used in Overview (compact) and World (full). */
  const GraphCanvas = ({
    withToolbar = false,
    showFocusedPanel = false,
  }: {
    withToolbar?: boolean;
    showFocusedPanel?: boolean;
  }) => (
    <div className="relative h-full w-full min-h-0">
      {withToolbar && (
        <div className="absolute inset-x-0 top-0 z-10 flex h-9 items-center gap-3 border-b border-border bg-bg/90 px-3 text-[10px] uppercase tracking-wider text-ink-muted backdrop-blur">
          <span>focus</span>
          <input
            value={trace.centerNodeId ?? ""}
            onChange={(e) =>
              setTrace((t) => ({ ...t, centerNodeId: e.target.value || null }))
            }
            placeholder="node idâ€¦"
            className="w-40 border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] normal-case tracking-normal text-ink outline-none focus:border-accent"
          />
          <span>hops</span>
          <select
            value={graphParams.max_hops}
            onChange={(e) =>
              setGraphParams((p) => ({ ...p, max_hops: Number(e.target.value) }))
            }
            className="border border-border bg-surface px-1 py-0.5 font-mono text-[11px] text-ink outline-none"
          >
            {[1, 2, 3, 4].map((h) => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
          <span>limit</span>
          <select
            value={graphParams.limit_nodes}
            onChange={(e) =>
              setGraphParams((p) => ({ ...p, limit_nodes: Number(e.target.value) }))
            }
            className="border border-border bg-surface px-1 py-0.5 font-mono text-[11px] text-ink outline-none"
          >
            {[50, 120, 250, 500].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          {trace.centerNodeId && (
            <button
              onClick={() => setTrace((t) => ({ ...t, centerNodeId: null }))}
              className="ml-auto border border-border px-2 py-0.5 hover:text-ink"
            >
              clear focus
            </button>
          )}
        </div>
      )}
      {!subgraph && !error && (
        <div className="flex h-full items-center justify-center pt-9 text-sm text-ink-muted">
          loading operational graphâ€¦
        </div>
      )}
      {subgraph && subgraph.nodes.length === 0 && !error && (
        <div className="flex h-full flex-col items-center justify-center gap-3 pt-9 text-sm text-ink-muted">
          <span>workspace graph is empty â€” no data ingested</span>
          <button
            onClick={() => void loadDemo()}
            disabled={loadingDemo}
            className="border border-border bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-ink-secondary hover:text-ink disabled:opacity-40"
          >
            {loadingDemo ? "loadingâ€¦" : "load demo dataset"}
          </button>
        </div>
      )}
      {subgraph && subgraph.nodes.length > 0 && (
        <div
          ref={canvasRef}
          className={`h-full w-full ${withToolbar ? "pt-9" : "pt-4"}`}
        >
          <svg className="h-full w-full" role="img" aria-label="Operational graph">
            {layout &&
              subgraph.edges.slice(0, 800).map((edge) => {
                const a = layout.get(edge.source);
                const b = layout.get(edge.target);
                if (!a || !b) return null;
                return (
                  <line
                    key={edge.edge_id}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="#26262b"
                    strokeWidth={0.7}
                  />
                );
              })}
            {layout &&
              subgraph.nodes.map((node) => {
                const pos = layout.get(node.id);
                if (!pos) return null;
                const r = 2.5 + 7.5 * ((node.pagerank ?? 0) / maxPagerank);
                return (
                  <circle
                    key={node.id}
                    cx={pos.x}
                    cy={pos.y}
                    r={Math.min(r, 9)}
                    fill={nodeColor(node.type)}
                    stroke={
                      selectedNode === node.id
                        ? "#ffffff"
                        : node.is_spof
                          ? "#f5a623"
                          : "transparent"
                    }
                    strokeWidth={selectedNode === node.id ? 2 : 1.5}
                    className="cursor-pointer"
                    onClick={() => setSelectedNode(node.id)}
                  >
                    <title>{`${node.type}: ${node.id}`}</title>
                  </circle>
                );
              })}
          </svg>
          <div className="absolute bottom-3 left-3 flex flex-wrap gap-3 text-[10px] uppercase tracking-wider text-ink-muted">
            {Object.entries(TYPE_COLORS).map(([type, color]) => (
              <span key={type} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: color }}
                />
                {type.toLowerCase()}
              </span>
            ))}
          </div>
        </div>
      )}
      {showFocusedPanel && trace.centerNodeId && (
        <div className="absolute bottom-0 right-0 m-4 w-72 border border-border bg-surface p-3 text-xs">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-ink-muted">FOCUSED ENTITY</span>
          </div>
          <p className="mb-2 font-mono text-ink truncate">{trace.centerNodeId}</p>
          <p className="mb-2 text-[10px] text-ink-muted">EGO NETWORK Â· 2 hops</p>
          <button
            onClick={() => void runDeliberation(trace.centerNodeId ?? undefined)}
            disabled={deliberating}
            className="w-full border border-accent/60 bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-accent hover:bg-surface disabled:opacity-40"
          >
            {deliberating ? "deliberatingâ€¦" : "TRACE DELIBERATION â†’"}
          </button>
        </div>
      )}
    </div>
  );

  const loadDemo = async (): Promise<void> => {
    setLoadingDemo(true);
    try {
      await api.post("/workspace/demo/load");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "demo load failed");
    } finally {
      setLoadingDemo(false);
    }
  };

  const renderSection = (): ReactNode => {
    switch (section) {
      case "Data": {
        const datasets = state?.datasets_loaded ?? [];
        return (
          <div>
            <h2 className="mb-3 text-xs uppercase tracking-widest text-ink-muted">
              Ingested datasets â€” {datasets.length}
            </h2>
            {state && datasets.length === 0 && (
              <div className="flex flex-col items-start gap-3 text-sm text-ink-secondary">
                <span>No datasets ingested in this workspace.</span>
                <button
                  onClick={() => void loadDemo()}
                  disabled={loadingDemo}
                  className="border border-border bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider hover:text-ink disabled:opacity-40"
                >
                  {loadingDemo ? "loadingâ€¦" : "load demo dataset"}
                </button>
              </div>
            )}
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border text-left uppercase tracking-widest text-ink-muted">
                  <th className="py-1.5 pr-4">dataset</th>
                  <th className="py-1.5 pr-4">rows</th>
                  <th className="py-1.5 pr-4">columns</th>
                  <th className="py-1.5 pr-4">status</th>
                  <th className="py-1.5">ingested at</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d) => (
                  <tr key={String(d.dataset_id)} className="border-b border-border/50">
                    <td className="py-1.5 pr-4 font-mono">{String(d.name)}</td>
                    <td className="py-1.5 pr-4">{Number(d.row_count).toLocaleString()}</td>
                    <td className="py-1.5 pr-4 truncate text-ink-muted" title={JSON.stringify(d.columns)}>
                      {Array.isArray(d.columns) ? d.columns.slice(0, 5).join(", ") : "â€”"}
                    </td>
                    <td className="py-1.5 pr-4 text-emerald-400">{String(d.status)}</td>
                    <td className="py-1.5 font-mono text-[10px] text-ink-muted">{String(d.ingested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }

      case "Signals": {
        const list = signalsLoad.data?.active_signals ?? [];
        const blast = signalsLoad.data?.primary_blast_radius;
        return (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-widest text-ink-muted">
                Active signals â€” {list.length}
              </h2>
              {signalsLoad.status === "loading" && <span className="text-[10px] text-ink-muted">loadingâ€¦</span>}
            </div>
            {signalsLoad.status === "empty" && (
              <p className="text-sm text-ink-secondary">No active anomaly signals.</p>
            )}
            {signalsLoad.status === "error" && (
              <p className="text-sm text-critical">Failed to load signals: {signalsLoad.error}</p>
            )}
            <ul className="mb-6 space-y-2">
              {list.map((sig) => (
                <li key={String(sig.signal_id)} className="border border-border bg-surface p-2.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className={`font-mono ${sig.severity === "CRITICAL" ? "text-critical" : sig.severity === "HIGH" ? "text-warning" : "text-ink"}`}>
                      {String(sig.signal_type ?? sig.signal_id)}
                    </span>
                    <span className="uppercase tracking-wider text-[10px] text-ink-muted">
                      {String(sig.severity ?? "")} Â· {String(sig.entity_type ?? "")}
                    </span>
                  </div>
                  <div className="mt-1 flex gap-2">
                    <button
                      className="block break-all text-left text-ink-muted hover:text-accent"
                      onClick={() => setGraphParams((p) => ({ ...p, center_node_id: String(sig.entity_id ?? "") }))}
                    >
                      entity: {String(sig.entity_id)}
                    </button>
                    <button
                      className="ml-2 border border-accent/60 bg-surface-2 px-2 py-0.5 text-[10px] uppercase tracking-wider text-accent hover:bg-surface"
                      onClick={() => traceSignal(sig)}
                    >
                      TRACE â†’
                    </button>
                  </div>
                  <div className="mt-2 p-3 bg-surface-2 rounded border border-border/25">
                    <div className="grid grid-cols-2 gap-2 text-xs uppercase tracking-wider">
                      <div>
                        <span className="block text-[8px] text-ink-secondary">WHAT</span>
                        <span className="font-mono truncate text-ink">{String(sig.signal_type ?? "")}</span>
                      </div>
                      <div>
                        <span className="block text-[8px] text-ink-secondary">WHY</span>
                        <span className="font-mono truncate text-ink">{String(sig.description ?? "")}</span>
                      </div>
                      <div>
                        <span className="block text-[8px] text-ink-secondary">WHERE</span>
                        <span className="font-mono truncate text-ink">
                          {String(sig.entity_id ?? "")} {String(sig.entity_type ?? "")}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[8px] text-ink-secondary">IMPACT</span>
                        <span className="font-mono truncate text-ink">
                          {list.length} order(s) Â· {formatUsd(blast?.total_revenue_at_risk_usd as number)}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[8px] text-ink-secondary">WHAT NEXT</span>
                        <span className="font-mono text-accent">
                          <button onClick={() => traceSignal(sig)} className="underline text-accent">Trace World</button>
                          <button onClick={() => setSection("Agents")} className="underline ml-2 text-accent">Ask Nexus</button>
                        </span>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            {blast && (
              <>
                <h2 className="mb-3 text-xs uppercase tracking-widest text-ink-muted">
                  Primary blast radius
                </h2>
                <pre className="max-h-64 overflow-auto border border-border bg-surface p-3 text-[11px] leading-relaxed text-ink-secondary">
                  {JSON.stringify(blast, null, 2)}
                </pre>
              </>
            )}
          </div>
        );
      }

      case "Agents": {
        return (
          <div>
            <div className="mb-4 flex items-center gap-3">
              <h2 className="text-xs uppercase tracking-widest text-ink-muted">
                Multi-agent deliberation
              </h2>
              <button
                onClick={() => void runDeliberation()}
                disabled={deliberating}
                className="ml-auto border border-accent/60 bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-accent hover:bg-surface disabled:opacity-40"
              >
                {deliberating ? "deliberatingâ€¦" : trace.incidentEntityId ? `run on ${trace.incidentEntityId}` : "run deliberation"}
              </button>
            </div>
            {!deliberation && !deliberating && (
              <p className="text-sm text-ink-muted">
                No deliberation has been run in this session. Trigger one to stream structured agent messages.
              </p>
            )}
            {deliberation?.target_entity && (
              <div className="mb-4 flex items-center gap-3">
                <p className="text-[11px] text-ink-muted">
                  target: <span className="font-mono text-ink">{deliberation.target_entity}</span>
                  {" Â· "}decision: <span className="font-mono text-ink">{deliberation.decision_id}</span>
                </p>
                <button
                  onClick={() => setSection("Scenarios")}
                  className="ml-auto border border-accent/60 bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-accent hover:bg-surface"
                >
                  COMPARE FUTURES â†’
                </button>
              </div>
            )}
            <ol className="space-y-2">
              {(deliberation?.message_stream ?? []).map((m) => (
                <li key={m.message_id} className="border-l-2 border-accent/50 bg-surface px-3 py-2 text-xs">
                  <div className="mb-0.5 flex items-baseline justify-between gap-2">
                    <span className="font-semibold text-ink">{m.sender_name}</span>
                    <span className="text-[10px] uppercase tracking-wider text-ink-muted">
                      {m.phase.toLowerCase()}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[9px] uppercase tracking-wider text-ink-secondary">
                    <div>
                      <span className="block">agent</span>
                      <span className="font-mono text-ink">{m.sender_role}</span>
                    </div>
                    <div>
                      <span className="block">version</span>
                      <span className="font-mono text-ink">{m.sender_version || "â€”"}</span>
                    </div>
                    <div>
                      <span className="block">worldâ€‘v</span>
                      <span className="font-mono text-ink">{m.world_state_version || "â€”"}</span>
                    </div>
                    <div>
                      <span className="block">confidence</span>
                      <span className="font-mono text-ink">                    {Math.round((m.confidence ?? 0) * 100)}%</span>
                    </div>
                  </div>
                  <p className="text-ink-secondary mt-1">{m.content}</p>
                  {Array.isArray(m.evidence_refs) && m.evidence_refs.length > 0 && (
                    <p className="mt-1 font-mono text-[9px] text-ink-muted">
                      evidence: {m.evidence_refs.join(", ")}
                    </p>
                  )}
                  {m.tools_invoked && m.tools_invoked.length > 0 && (
                    <p className="mt-1 text-[9px] text-ink-muted">
                      tools: {m.tools_invoked.join(", ")}
                    </p>
                  )}
                  {m.proposal && (
                    <p className="mt-1 text-xs font-mono text-ink">
                      proposal: {m.proposal.action} â†’ {m.proposal.target_entity_ids?.join(",") || "â€”"}
                    </p>
                  )}
                  {Array.isArray(m.parallel_constraints) && m.parallel_constraints.length > 0 && (
                    <p className="mt-1 text-[9px] text-ink-muted">
                      constraints: {m.parallel_constraints.join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>
        );

      }
      case "Scenarios": {
        return (
          <div>Scenarios placeholder</div>
        );
      }
      case "Decisions": {
        return (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-widest text-ink-muted">
                Governed decisions
              </h2>
              {trace.decisionId && (
                <button
                  onClick={() => setSection("Evidence")}
                  className="border border-accent/60 bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-accent hover:bg-surface"
                >
                  VIEW EVIDENCE â†’
                </button>
              )}
            </div>
            {!decisionValidity && trace.decisionId && (
              <p className="text-sm text-ink-muted">
                Decision pending deliberation.
              </p>
            )}
            {decisionValidity && (
              <>
                <div className={`mb-4 border p-3 text-xs ${decisionValidity.is_valid ? "border-emerald-500/40" : "border-critical/50"}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono">{decisionValidity.decision_id}</span>
                    <span className={`uppercase tracking-wider ${decisionValidity.is_valid ? "text-emerald-400" : "text-critical"}`}>
                      {decisionValidity.is_valid ? "valid" : "invalidated"}
                    </span>
                  </div>
                  {decisionValidity.invalidation_reason && (
                    <p className="mt-1 text-critical">{decisionValidity.invalidation_reason}</p>
                  )}
                </div>
                {state?.last_decision && (
                  <pre className="max-h-80 overflow-auto border border-border bg-surface p-3 text-[11px] text-ink-secondary">
                    {JSON.stringify(state.last_decision, null, 2)}
                  </pre>
                )}
              </>
            )}
            {!decisionValidity && !trace.decisionId && (
              <p className="text-sm text-ink-muted">No decision registered yet.</p>
            )}
            {decisionValidity && trace.decisionId && state?.last_decision && (
              <div className="mt-4 p-4 bg-surface/50 rounded border border-border/25">
                <h3 className="text-xs uppercase tracking-wider text-ink-secondary mb-3">Decision Card</h3>
                <dl className="mt-2 space-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">DECISION ID</dt>
                    <dd className="font-mono">{decisionValidity.decision_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">STATUS</dt>
                    <dd className={`font-mono ${decisionValidity.is_valid ? "text-emerald-400" : "text-critical"}`}>
                      {decisionValidity.is_valid ? "AWAITING APPROVAL" : "INVALIDATED"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">WORLD STATE</dt>
                    <dd>{state?.world_state_version ?? "â€”"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">PROPOSAL</dt>
                    <dd className="font-mono truncate">{decisionValidity.decision_id ? "Air Freight" : "â€”"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">SIMULATION</dt>
                    <dd className="text-sm">
                      {decisionValidity.decision_id ? "simulation_hash: " + (decisionValidity.decision_id?.substring(0, 8) || "â€”") : "â€”"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">POLICY</dt>
                    <dd className={decisionValidity.is_valid ? "text-emerald-400" : "text-critical"}>
                      {decisionValidity.is_valid ? "APPROVED" : "REJECTED"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-muted">EVIDENCE ROOT</dt>
                    <dd className="font-mono text-[10px]">{decisionValidity.decision_id || "â€”"}</dd>
                  </div>
                </dl>
                {decisionValidity.is_valid && (
                  <button
                    onClick={() => setSection("Evidence")}
                    className="mt-3 w-full border border-accent/60 bg-surface-2 px-3 py-2 text-xs uppercase tracking-wider text-accent hover:bg-surface"
                  >
                    VIEW EVIDENCE â†’
                  </button>
                )}
              </div>
            )}
            {decisionValidity && !decisionValidity.is_valid && (
              <div className="mt-4 p-4 bg-critical/10 border border-critical/25 rounded">
                <p className="text-sm text-critical font-mono uppercase tracking-wider mb-2">
                  DECISION INVALIDATED
                </p>
                <p className="text-ink-secondary mb-2">
                  World state: {state?.world_state_version ?? "â€”"} â†’ {state ? state.world_state_version + 2 : "â€”"}
                </p>
                <p className="text-ink-secondary">
                  Reason: Seller capacity changed
                </p>
                <p className="mt-2 text-sm">
                  This decision is no longer executable.
                </p>
                <button
                  onClick={() => setSection("Agents")}
                  className="mt-3 w-full border border-accent/60 bg-surface-2 px-3 py-2 text-xs uppercase tracking-wider text-accent hover:bg-surface"
                >
                  Re-deliberate
                </button>
              </div>
            )}
          </div>
        );
      }

      case "Evidence": {
        return (
          <div>
            <h2 className="mb-3 text-xs uppercase tracking-widest text-ink-muted">
              Decision evidence graph
            </h2>
            {evidenceLoad.status === "idle" && !trace.decisionId && (
              <p className="text-sm text-ink-muted">
                No decision selected in active trace. Run a deliberation or select a decision from the Scenarios section.
              </p>
            )}
            {evidenceLoad.status === "loading" && (
              <p className="text-sm text-ink-muted">Retrieving decision evidence...</p>
            )}
            {evidenceLoad.status === "empty" && (
              <p className="text-sm text-ink-muted">
                No evidence graph yet for this decision. Run a deliberation to synthesize a provenance chain.
              </p>
            )}
            {evidenceLoad.status === "error" && (
              <p className="text-sm text-critical">
                Evidence could not be retrieved: {evidenceLoad.error}
              </p>
            )}
            {evidenceLoad.status === "success" && evidence && (
              <>
                <p className="mb-4 text-[11px] text-ink-muted">
                  {evidence.total_evidence_nodes} evidence nodes Â·{" "}
                  {evidence.total_attribution_edges} attribution edges Â· decision{" "}
                  <span className="font-mono text-ink">{evidence.decision_id}</span>
                </p>
                <ol className="space-y-1.5">
                  {evidence.nodes.map((n, i) => (
                    <li key={n.node_id} className="flex items-baseline gap-3 border border-border bg-surface px-3 py-2 text-xs">
                      <span className="w-5 shrink-0 text-right font-mono text-ink-muted">{i + 1}</span>
                      <span className="w-28 shrink-0 uppercase tracking-wider text-[10px] text-accent">{n.node_type}</span>
                      <span className="min-w-0 flex-1 truncate text-ink" title={n.label}>{n.label}</span>
                      <span className="shrink-0 font-mono text-[10px] text-ink-muted" title={`sha256:${n.checksum}`}>{n.checksum}</span>
                    </li>
                  ))}
                </ol>
                {evidence.attribution_edges.length > 0 && (
                  <p className="mt-3 font-mono text-[10px] leading-relaxed text-ink-muted">
                    {evidence.attribution_edges.map((e) => `${e.from} --${e.relation}--> ${e.to}`).join("\n")}
                  </p>
                )}
              </>
            )}
          </div>
        );
      }

      default:
        return null;
    }
  };

  const askNexus = async (): Promise<void> => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const res = await api.post<AskResponse>("/workspace/query/ask", {
        query: question,
      });
      setAskResult(res);
    } catch (err) {
      setAskResult({
        answer: err instanceof Error ? err.message : "query failed",
      });
    } finally {
      setAsking(false);
    }
  };

  const runDeliberation = async (incidentEntityId?: string): Promise<void> => {
    const target = incidentEntityId ?? trace.incidentEntityId ?? selectedNode;
    if (target) {
      setTrace((t) => ({ ...t, incidentEntityId: target }));
    }
    setDeliberating(true);
    setSelectedScenario(null);
    try {
      const res = await api.post<{ status: string; deliberation_result: DeliberationResult }>(
        "/workspace/deliberate",
        { incident_entity_id: target ?? null },
      );
      setDeliberation(res.deliberation_result);
      if (res.deliberation_result.decision_id) {
        setTrace((t) => ({ ...t, decisionId: res.deliberation_result.decision_id ?? null }));
      }
      try {
        const v = await api.get<DecisionValidity>("/workspace/decisions/validity");
        setDecisionValidity(v);
      } catch {
        // validity may not be available until next state poll
      }
      setSection("Agents");
    } catch (err) {
      setDeliberation(null);
      setTrace((t) => ({ ...t, decisionId: null }));
      setError(err instanceof Error ? err.message : "deliberation failed");
    } finally {
      setDeliberating(false);
    }
  };

  /** Signals â†’ World: focus the graph on the signal's entity. */
  const traceSignal = (sig: Signal): void => {
    const entity = String(sig.entity_id ?? "");
    const signalId = String(sig.signal_id ?? "");
    if (!entity) return;
    setTrace((t) => ({
      ...t,
      signalId: signalId || t.signalId,
      signalEntityId: entity,
      centerNodeId: entity,
      incidentEntityId: entity,
    }));
    setSection("World");
  };

  const analytics = state?.graph_analytics;
  const criticalSignal = state?.active_signals?.[0];
  const exposureOrders = state?.active_signals?.length ?? 0;
  const maxPagerank = Math.max(
    1e-9,
    ...(subgraph?.nodes.map((n) => n.pagerank ?? 0) ?? [0]),
  );

  return (
    <div className="flex h-screen flex-col bg-bg font-mono text-ink">
      {/* Header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold tracking-[0.25em]">CORTEX</span>
          <span className="text-xs text-ink-muted">NEXUS</span>
        </div>
        <div className="flex items-center gap-4 text-xs text-ink-secondary">
          <span className="flex items-center gap-1.5" title={`stream: ${live}`}>
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                live === "live"
                  ? "bg-emerald-500"
                  : live === "reconnecting"
                    ? "animate-pulse bg-amber-500"
                    : live === "connecting"
                      ? "animate-pulse bg-ink-muted"
                      : "bg-critical"
              }`}
            />
            {live.toUpperCase()} Â· WORLD v{state?.world_state_version ?? "â€”"}
          </span>
          <span className="text-ink-muted">
            graph {analytics ? `${analytics.total_nodes}n/${analytics.total_edges}e` : "â€¦"}
          </span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left nav */}
        <nav className="flex w-44 shrink-0 flex-col border-r border-border py-2">
          {SECTIONS.map((item) => (
            <button
              key={item}
              onClick={() => setSection(item)}
              className={`px-4 py-2 text-left text-xs uppercase tracking-wider transition-colors ${
                section === item
                  ? "border-l-2 border-accent bg-surface-2 text-ink"
                  : "border-l-2 border-transparent text-ink-secondary hover:bg-surface hover:text-ink"
              }`}
            >
              {item}
            </button>
          ))}
        </nav>

        {/* Center â€” section content */}
        <main className="relative min-w-0 flex-1 overflow-hidden bg-bg">
          {error && (
            <div className="absolute inset-x-0 top-0 z-20 border-b border-critical/40 bg-critical-subtle px-4 py-2 text-xs text-critical">
              {error}
            </div>
          )}

          {section === "Overview" && (
            <div className="flex h-full flex-col">
              {/* KPI strip */}
              <div className="flex h-14 shrink-0 items-center gap-6 border-b border-border px-4 text-xs uppercase tracking-wider">
                <div className="flex items-center gap-4 text-ink-secondary">
                  <span className="text-ink-muted">revenue at risk</span>
                  <span className="font-mono text-emerald-400">
                    {signalsLoad.data?.primary_blast_radius?.total_revenue_at_risk_usd != null
                      ? formatUsd(signalsLoad.data.primary_blast_radius.total_revenue_at_risk_usd as number)
                      : "â€”"}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-ink-secondary border-l border-border pl-4">
                  <span className="text-ink-muted">active signals</span>
                  <span className="font-mono text-warning">{state?.active_signals?.length ?? 0}</span>
                </div>
                <div className="flex items-center gap-4 text-ink-secondary border-l border-border pl-4">
                  <span className="text-ink-muted">scenarios</span>
                  <span className="font-mono text-ink">{deliberation?.counterfactuals?.length ?? 0}</span>
                </div>
                <div className="flex items-center gap-4 text-ink-secondary border-l border-border pl-4">
                  <span className="text-ink-muted">decisions</span>
                  <span className={decisionValidity?.is_valid === false ? "font-mono text-critical" : "font-mono text-emerald-400"}>
                    {decisionValidity ? (decisionValidity.is_valid ? "valid" : "invalidated") : "â€”"}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-ink-secondary border-l border-border pl-4 ml-auto">
                  <span className="text-ink-muted">graph</span>
                  <span className="font-mono text-ink-muted">
                    {analytics ? `${analytics.total_nodes}n/${analytics.total_edges}e` : "â€”"}
                  </span>
                </div>
              </div>
              {/* Critical + High situation cards */}
              <div className="flex h-full flex-1 gap-6 overflow-y-auto pb-6">
                {/* Critical situation card */}
                {criticalSignal && (
                  <div className="rounded bg-critical/10 border border-critical/20 p-4 mb-4">
                    <p className="text-sm text-critical font-mono uppercase tracking-wider">
                      {criticalSignal.description as string ?? `signal on ${criticalSignal.entity_id}`}
                    </p>
                    <p className="mt-2 text-xs text-ink-secondary">
                      {exposureOrders} order(s) exposed Â· {criticalSignal.severity ?? "unknown"} severity
                      {criticalSignal.severity === "CRITICAL" && (
                        <span className="ml-2 text-xs bg-critical/20 text-critical px-2 py-0.5 rounded uppercase tracking-wider">
                          CRITICAL
                        </span>
                      )}
                    </p>
                    <button
                      onClick={() => traceSignal(criticalSignal)}
                      className="mt-3 w-full border border-accent/60 bg-surface-2 px-3 py-2 text-xs uppercase tracking-wider text-accent hover:bg-surface disabled:opacity-40"
                    >
                      Investigate â†’
                    </button>
                  </div>
                )}
                {/* High situation cards */}
                {(() => {
                  const highSignals = (state?.active_signals ?? [])
                    .filter((s: any) => s.severity === "HIGH")
                    .slice(0, 2);
                  if (highSignals.length === 0) return null;
                  return (
                    <>
                      {highSignals.map((sig: any, i: number) => (
                        <div key={i} className="rounded bg-amber/10 border border-amber/20 p-4 mb-4">
                          <p className="text-sm font-mono uppercase tracking-wider text-warning">
                            {sig.signal_type ?? sig.signal_id}
                          </p>
                          <p className="mt-2 text-xs text-ink-secondary">
                            {sig.entity_type ?? ""} Â· {sig.entity_id ?? ""}
                          </p>
                          <button
                            onClick={() => traceSignal(sig)}
                            className="mt-3 w-full border border-accent/60 bg-surface-2 px-3 py-2 text-xs uppercase tracking-wider text-accent hover:bg-surface disabled:opacity-40"
                          >
                            Trace â†’
                          </button>
                        </div>
                      ))}
                    </>
                  );
                })()}
              </div>
            </div>
          )}

          {section === "World" && (
            <div className="h-full">
              {/* Overlay & search controls */}
              <div className="flex flex-col sm:flex-row gap-3 border-b border-border pb-3">
                <label className="text-xs uppercase tracking-wider text-ink-secondary">Overlay</label>
                <select
                  id="overlay-select"
                  value={graphParams.overlay}
                  onChange={(e) =>
                    setGraphParams((p) => ({ ...p, overlay: e.target.value }))
                  }
                  className="border border-border bg-surface px-2 py-1 text-[10px] text-ink focus:border-accent"
                >
                  <option value="world">WORLD</option>
                  <option value="risk">RISK</option>
                  <option value="dependency">DEPENDENCY</option>
                  <option value="incident">INCIDENT</option>
                  <option value="scenario">SCENARIO</option>
                  <option value="evidence">EVIDENCE</option>
                </select>
                <label className="text-xs uppercase tracking-wider text-ink-secondary">Hops</label>
                <select
                  id="hops-select"
                  value={graphParams.max_hops}
                  onChange={(e) =>
                    setGraphParams((p) => ({ ...p, max_hops: Number(e.target.value) }))
                  }
                  className="border border-border bg-surface px-2 py-1 text-[10px] text-ink focus:border-accent"
                >
                  {[1, 2, 3, 4].map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
                <label className="text-xs uppercase tracking-wider text-ink-secondary">Limit</label>
                <select
                  id="limit-select"
                  value={graphParams.limit_nodes}
                  onChange={(e) =>
                    setGraphParams((p) => ({ ...p, limit_nodes: Number(e.target.value) }))
                  }
                  className="border border-border bg-surface px-2 py-1 text-[10px] text-ink focus:border-accent"
                >
                  {[50, 120, 250, 500].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
                <label className="text-xs uppercase tracking-wider text-ink-secondary">Center</label>
                <input
                  value={trace.centerNodeId ?? ""}
                  onChange={(e) =>
                    setTrace((t) => ({ ...t, centerNodeId: e.target.value || null }))
                  }
                  placeholder="node idâ€¦"
                  className="border border-border bg-surface px-2 py-1 text-[10px] text-ink font-mono normal-case focus:border-accent w-32"
                />
              </div>
              <GraphCanvas withToolbar showFocusedPanel />
            </div>
          )}

          {section !== "Overview" && section !== "World" && (
            <div className="h-full overflow-y-auto p-4 pt-2">{renderSection()}</div>
          )}

        </main>
        {/* Right rail */}
        <aside className="w-72 shrink-0 overflow-y-auto border-l border-border">
          <section className="border-b border-border p-4">
            <h2 className="mb-3 text-[10px] uppercase tracking-widest text-ink-muted">
              Current situation
            </h2>
            {criticalSignal ? (
              <>
                <p className="text-sm text-critical">
                  {(criticalSignal.description as string) ??
                    `signal on ${criticalSignal.entity_id}`}
                </p>
                <p className="mt-2 text-xs text-ink-secondary">
                  {exposureOrders} active signal(s) Â·{" "}
                  {criticalSignal.severity ?? "unknown"} severity
                </p>
              </>
            ) : (
              <p className="text-sm text-ink-secondary">
                No critical signals. Operational state nominal.
              </p>
            )}
            {analytics && (
              <dl className="mt-4 space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-ink-muted">density</dt>
                  <dd>{analytics.density}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">SPOFs</dt>
                  <dd className="text-warning">
                    {analytics.high_dependency_spofs.length}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">gini</dt>
                  <dd>{analytics.supplier_concentration_gini}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">datasets</dt>
                  <dd>{state?.datasets_ingested ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">raw rows</dt>
                  <dd>{state?.total_raw_rows?.toLocaleString() ?? 0}</dd>
                </div>
              </dl>
          )}
          </section>

          <section className="border-b border-border p-4">
            <h2 className="mb-3 text-[10px] uppercase tracking-widest text-ink-muted">
              What to do
            </h2>
            {(() => {
              const sims = state?.last_decision?.counterfactual_simulations ?? [];
              const optimal = sims.find(
                (c) =>
                  typeof c === "object" &&
                  c !== null &&
                  (c as Record<string, unknown>).is_optimal === true,
              ) as Record<string, unknown> | undefined;
              if (optimal) {
                return (
                  <div>
                    <p className="text-sm text-emerald-400">
                      {String(optimal.candidate)}
                    </p>
                    <p className="mt-1 text-xs text-ink-secondary">
                      {String(optimal.action)} Â· ${String(optimal.net_economic_value_usd)}{" "}
                      NEV Â· {String(optimal.sla_breach_pct)}% projected breach
                    </p>
                    <p className="mt-1.5 font-mono text-[10px] text-ink-muted">
                      {String(state?.last_decision?.decision_id ?? "")} Â· pending policy gate
                    </p>
                  </div>
                );
              }
              if (
                analytics &&
                analytics.top_critical_suppliers.length > 0
              ) {
                return (
                  <ul className="space-y-2 text-xs">
                    {analytics.top_critical_suppliers
                      .slice(0, 3)
                      .map((supplier) => (
                        <li
                          key={supplier.supplier_id}
                          className="flex items-center justify-between border border-border bg-surface px-2 py-1.5"
                        >
                          <span className="truncate">{supplier.supplier_id}</span>
                          <span className="ml-2 shrink-0 text-warning">
                            {supplier.order_volume} orders
                          </span>
                        </li>
                      ))}
                  </ul>
                );
              }
              return (
                <p className="text-sm text-ink-secondary">
                  No active decision. Run deliberation on a signal or node.
                </p>
              );
            })()}
          </section>

          {selectedNode && (
            <section className="border-b border-border p-4">
              <h2 className="mb-2 text-[10px] uppercase tracking-widest text-ink-muted">
                Selected node
              </h2>
              <p className="break-all font-mono text-xs">{selectedNode}</p>
              <div className="mt-2 flex gap-2 text-[10px] uppercase tracking-wider">
                <button
                  onClick={() => {
                    setGraphParams((p) => ({ ...p, center_node_id: selectedNode }));
                    setSection("Overview");
                  }}
                  className="border border-border bg-surface-2 px-2 py-1 text-ink-secondary hover:text-ink"
                >
                  focus graph
                </button>
                <button
                  onClick={() => void runDeliberation()}
                  disabled={deliberating}
                  className="border border-accent/60 px-2 py-1 text-accent hover:bg-surface disabled:opacity-40"
                >
                  {deliberating ? "â€¦" : "deliberate"}
                </button>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="border border-transparent px-2 py-1 text-ink-muted hover:text-ink"
                >
                  clear
                </button>
              </div>
            </section>
          )}

          {askResult && (
            <section className="border-b border-border p-4">
              <h2 className="mb-2 text-[10px] uppercase tracking-widest text-ink-muted">
                Nexus answer
              </h2>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-secondary">
                {typeof askResult.answer === "string"
                  ? askResult.answer
                  : JSON.stringify(askResult, null, 2).slice(0, 800)}
              </p>
            </section>
          )}
        </aside>
      </div>

      {/* Ask bar */}
      <footer className="flex h-12 shrink-0 items-center gap-3 border-t border-border px-4">
        <span className="shrink-0 text-xs uppercase tracking-widest text-ink-muted">
          Ask Nexus
        </span>
        <span className="text-accent">&gt;</span>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void askNexus();
          }}
          placeholder="Which suppliers threaten SLA in the next 48h?"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-muted"
        />
        <button
          onClick={() => void askNexus()}
          disabled={asking || !question.trim()}
          className="shrink-0 border border-border bg-surface-2 px-3 py-1 text-xs uppercase tracking-wider text-ink-secondary transition-colors hover:text-ink disabled:opacity-40"
        >
          {asking ? "â€¦" : "send"}
        </button>
      </footer>
    </div>
  );
}
