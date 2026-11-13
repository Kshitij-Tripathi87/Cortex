"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "WATCH";

interface Risk {
  risk_id?: string;
  entity_id: string;
  entity_name: string;
  entity_kind: string;
  severity: Severity;
  risk_score: number;
  title: string;
  revenue_exposure?: number;
  sla_risk_pct?: number;
  blast_radius_count?: number;
  world_state_version?: number;
  root_causes?: string[];
  hidden_dependencies?: Array<{ description?: string; downstream_order_count?: number } | string>;
}

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

interface VanessaMessage {
  role: "operator" | "cortex";
  content: string;
}

type RiskEnvelope = { data?: { risks?: Risk[] } };

const severityStyles: Record<Severity, string> = {
  CRITICAL: "border-critical/50 bg-critical-subtle text-critical",
  HIGH: "border-warning/50 bg-warning-subtle text-warning",
  MEDIUM: "border-warning/40 bg-warning-subtle text-warning",
  LOW: "border-accent/40 bg-accent-subtle text-accent",
  WATCH: "border-border bg-surface text-ink-secondary",
};

function formatINR(value?: number): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 10_000_000) return `₹${(value / 10_000_000).toFixed(1)}Cr`;
  if (Math.abs(value) >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (Math.abs(value) >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function nodeLabel(node: GraphNode): string {
  const attributes = node.attributes ?? {};
  const name = attributes.name ?? attributes.description ?? node.entity_id ?? node.node_id;
  return String(name ?? "Unnamed entity");
}

function riskLabel(risk: Risk): string {
  return risk.entity_name || risk.entity_id;
}

export default function DisruptionCockpit() {
  const { status, workspace } = useAuth();
  const [risks, setRisks] = useState<Risk[]>([]);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);
  const [connection, setConnection] = useState<"loading" | "live" | "offline">("loading");
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<VanessaMessage[]>([]);
  const [asking, setAsking] = useState(false);

  const loadWorkspace = useCallback(async () => {
    if (!workspace?.id) return;
    setConnection("loading");
    setError(null);
    try {
      const [riskResponse, nodeResponse, edgeResponse] = await Promise.all([
        apiClient.get<RiskEnvelope>("/nexus/risks", { workspace_id: workspace.id, status: "open" }),
        apiClient.get<GraphNode[]>("/graph/nodes", { workspace_id: workspace.id, limit: 200 }),
        apiClient.get<GraphEdge[]>("/graph/edges", { workspace_id: workspace.id, limit: 200 }),
      ]);
      const nextRisks = riskResponse.data?.risks ?? [];
      setRisks(nextRisks);
      setNodes(nodeResponse);
      setEdges(edgeResponse);
      setSelectedRiskId((current) => current && nextRisks.some((risk) => risk.entity_id === current)
        ? current
        : nextRisks[0]?.entity_id ?? null);
      setConnection("live");
    } catch (requestError) {
      setConnection("offline");
      setError(requestError instanceof Error ? requestError.message : "The workspace could not be loaded.");
    }
  }, [workspace?.id]);

  useEffect(() => {
    if (status === "AUTHENTICATED") void loadWorkspace();
  }, [loadWorkspace, status]);

  const selectedRisk = useMemo(
    () => risks.find((risk) => risk.entity_id === selectedRiskId) ?? risks[0] ?? null,
    [risks, selectedRiskId],
  );

  const summary = useMemo(() => {
    const exposure = risks.reduce((largest, risk) => Math.max(largest, risk.revenue_exposure ?? 0), 0);
    const orders = risks.reduce((largest, risk) => Math.max(largest, risk.blast_radius_count ?? 0), 0);
    return {
      critical: risks.filter((risk) => risk.severity === "CRITICAL").length,
      high: risks.filter((risk) => risk.severity === "HIGH").length,
      exposure,
      orders,
      worldVersion: risks.reduce((latest, risk) => Math.max(latest, risk.world_state_version ?? 0), 0),
    };
  }, [risks]);

  const askCortex = async () => {
    const trimmed = query.trim();
    if (!trimmed || !workspace?.id || asking) return;
    setQuery("");
    setMessages((current) => [...current, { role: "operator", content: trimmed }]);
    setAsking(true);
    try {
      const response = await apiClient.post<{ data?: { response?: string } }>(
        "/nexus/vanessa/ask",
        { query: trimmed },
        { query: { workspace_id: workspace.id } },
      );
      setMessages((current) => [...current, {
        role: "cortex",
        content: response.data?.response ?? "No grounded response was returned for this question.",
      }]);
    } catch (requestError) {
      setMessages((current) => [...current, {
        role: "cortex",
        content: requestError instanceof Error ? requestError.message : "The grounded question could not be completed.",
      }]);
    } finally {
      setAsking(false);
    }
  };

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <StatusPanel title="Opening Cortex" detail="Checking your workspace session…" />;
  }

  if (status !== "AUTHENTICATED") {
    return (
      <StatusPanel
        title="Sign in to Cortex"
        detail="The disruption workspace is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Fcockpit" className="button-primary">Sign in</Link>}
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
                <span>Disruption Intelligence</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Supplier disruption &amp; component shortage recovery</p>
            </div>
            <div className="flex items-center gap-3">
              <div className="hidden text-right sm:block">
                <div className="text-[11px] text-ink">{workspace?.name ?? "Workspace"}</div>
                <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted">{connection === "live" ? "Live state" : "Connection unavailable"}</div>
              </div>
              <Link href="/nexus/decision-room" className="button-secondary">Open decision room</Link>
            </div>
          </header>

          <div className="space-y-6 px-5 py-6 sm:px-8">
            {error && <div className="notice-error" role="alert">{error} <button type="button" onClick={() => void loadWorkspace()} className="ml-2 underline">Retry</button></div>}

            <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div>
                <p className="eyebrow">Operational decision workspace</p>
                <h1 className="mt-2 max-w-3xl text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Turn a supplier delay into a recovery decision.</h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-secondary">Cortex connects your operational data, traces component dependencies, and keeps the recommendation reviewable before anyone acts.</p>
              </div>
              <div className="border border-border bg-surface p-4">
                <div className="flex items-center justify-between border-b border-border pb-3">
                  <span className="eyebrow">Workspace state</span>
                  <span className={`badge ${connection === "live" ? "badge-positive" : "badge-neutral"}`}>{connection === "live" ? "CONNECTED" : connection.toUpperCase()}</span>
                </div>
                <dl className="mt-3 space-y-3 text-xs">
                  <DataPoint label="World state" value={summary.worldVersion ? `v${summary.worldVersion}` : "Not available"} />
                  <DataPoint label="Operational nodes" value={nodes.length ? nodes.length.toLocaleString("en-IN") : "Not loaded"} />
                  <DataPoint label="Relationships" value={edges.length ? edges.length.toLocaleString("en-IN") : "Not loaded"} />
                </dl>
              </div>
            </section>

            <section className="grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
              <Metric label="Open disruptions" value={risks.length.toString()} detail={`${summary.critical} critical · ${summary.high} high`} />
              <Metric label="Largest exposure" value={formatINR(summary.exposure)} detail="Highest persisted risk record" />
              <Metric label="Largest blast radius" value={summary.orders ? summary.orders.toLocaleString("en-IN") : "—"} detail="Highest recorded order count" />
              <Metric label="Data posture" value={nodes.length && edges.length ? "Traceable" : "Incomplete"} detail={nodes.length && edges.length ? "Graph records available" : "Upload or reconcile data"} />
            </section>

            <section className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
              <div className="border border-border bg-surface">
                <div className="flex items-start justify-between border-b border-border px-4 py-4">
                  <div><p className="eyebrow">Attention queue</p><h2 className="mt-1 text-base font-semibold">Open disruptions</h2></div>
                  <span className="font-mono text-xs text-ink-muted">{risks.length.toString().padStart(2, "0")}</span>
                </div>
                {risks.length === 0 ? (
                  <EmptyState title="No open disruptions" detail="Cortex will show a risk here after the workspace has validated operational data." action={<Link href="/upload" className="text-accent hover:underline">Review data readiness →</Link>} />
                ) : (
                  <div className="divide-y divide-border">
                    {risks.slice(0, 10).map((risk) => (
                      <button key={risk.entity_id} type="button" onClick={() => setSelectedRiskId(risk.entity_id)} className={`w-full px-4 py-4 text-left transition-colors hover:bg-surface-2 ${selectedRisk?.entity_id === risk.entity_id ? "border-l-2 border-accent bg-surface-2" : "border-l-2 border-transparent"}`}>
                        <div className="flex items-start justify-between gap-2"><span className="text-sm font-medium text-ink">{riskLabel(risk)}</span><span className={`badge ${severityStyles[risk.severity]}`}>{risk.severity}</span></div>
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink-secondary">{risk.title}</p>
                        <div className="mt-3 flex gap-3 font-mono text-[10px] text-ink-muted"><span>{formatINR(risk.revenue_exposure)} exposure</span><span>{risk.blast_radius_count ?? "—"} orders</span></div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="min-w-0 border border-border bg-surface">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
                  <div><p className="eyebrow">Impact assessment</p><h2 className="mt-1 text-base font-semibold">Dependency view</h2><p className="mt-1 text-xs text-ink-secondary">Relationships loaded from the current workspace graph.</p></div>
                  <Link href="/nexus/world" className="button-secondary">Inspect full graph</Link>
                </div>
                <DependencyMap nodes={nodes} edges={edges} selectedRisk={selectedRisk} />
                {selectedRisk && <RiskSummary risk={selectedRisk} />}
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="border border-border bg-surface p-5">
                <div className="flex items-start justify-between gap-4"><div><p className="eyebrow">Recovery workflow</p><h2 className="mt-1 text-base font-semibold">Compare before you commit</h2></div><span className="badge badge-neutral">HUMAN APPROVAL</span></div>
                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <WorkflowStep number="01" title="Assess" detail="Trace affected material and orders." active />
                  <WorkflowStep number="02" title="Simulate" detail="Compare feasible recovery options." />
                  <WorkflowStep number="03" title="Approve" detail="Record the decision and outcome." />
                </div>
                <div className="mt-5 flex flex-wrap gap-3 border-t border-border pt-4"><Link href="/nexus/scenarios" className="button-primary">Open scenario lab</Link><Link href="/nexus/decision-room" className="button-secondary">Review decisions</Link></div>
              </div>
              <div className="border border-border bg-surface p-5">
                <div className="flex items-start justify-between gap-4"><div><p className="eyebrow">Grounded investigation</p><h2 className="mt-1 text-base font-semibold">Ask about this workspace</h2></div><span className="font-mono text-[10px] text-ink-muted">EVIDENCE-BOUND</span></div>
                <div className="mt-4 min-h-16 space-y-2 text-xs">{messages.length === 0 ? <p className="text-ink-secondary">Ask what changed, which orders are exposed, or what evidence supports the selected disruption.</p> : messages.slice(-3).map((message, index) => <div key={`${message.role}-${index}`} className={message.role === "operator" ? "text-ink-muted" : "border-l-2 border-accent pl-3 text-ink-secondary"}><span className="mr-2 font-mono text-[9px] uppercase tracking-[0.12em]">{message.role === "operator" ? "You" : "Cortex"}</span>{message.content}</div>)}</div>
                <div className="mt-4 flex gap-2 border-t border-border pt-4"><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void askCortex(); }} placeholder={selectedRisk ? `Why is ${riskLabel(selectedRisk)} affected?` : "Ask about the current workspace"} className="field min-w-0 flex-1" /><button type="button" onClick={() => void askCortex()} disabled={asking || !query.trim()} className="button-secondary disabled:cursor-not-allowed disabled:opacity-50">{asking ? "Asking…" : "Ask"}</button></div>
              </div>
            </section>
          </div>
    </div>
  );
}

function StatusPanel({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return <div className="flex min-h-[70vh] items-center justify-center px-6 text-center"><div className="max-w-md"><div className="mx-auto mb-5 flex h-10 w-10 items-center justify-center bg-accent text-lg font-bold text-white">C</div><h1 className="text-2xl font-semibold tracking-tight">{title}</h1><p className="mt-2 text-sm text-ink-secondary">{detail}</p>{action && <div className="mt-6">{action}</div>}</div></div>;
}

function DataPoint({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-3"><dt className="text-ink-secondary">{label}</dt><dd className="font-mono text-[11px] text-ink">{value}</dd></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="bg-surface px-4 py-4"><div className="eyebrow">{label}</div><div className="mt-2 text-xl font-semibold tracking-tight">{value}</div><div className="mt-1 text-[11px] text-ink-muted">{detail}</div></div>;
}

function EmptyState({ title, detail, action }: { title: string; detail: string; action: React.ReactNode }) {
  return <div className="px-4 py-10"><div className="text-sm font-medium">{title}</div><p className="mt-2 max-w-xs text-xs leading-5 text-ink-secondary">{detail}</p><div className="mt-4 text-xs">{action}</div></div>;
}

function RiskSummary({ risk }: { risk: Risk }) {
  return <div className="grid gap-4 border-t border-border px-5 py-4 sm:grid-cols-4"><div><div className="eyebrow">Selected signal</div><div className="mt-1 text-sm font-medium">{risk.title}</div></div><div><div className="eyebrow">Risk score</div><div className="mt-1 font-mono text-sm">{Math.round(risk.risk_score * 100)}%</div></div><div><div className="eyebrow">SLA risk</div><div className="mt-1 font-mono text-sm">{risk.sla_risk_pct === undefined ? "—" : `${Math.round(risk.sla_risk_pct * 100)}%`}</div></div><div><div className="eyebrow">Entity type</div><div className="mt-1 text-sm">{titleCase(risk.entity_kind)}</div></div></div>;
}

function WorkflowStep({ number, title, detail, active = false }: { number: string; title: string; detail: string; active?: boolean }) {
  return <div className={`border p-3 ${active ? "border-accent/60 bg-accent-subtle" : "border-border"}`}><div className="font-mono text-[10px] text-accent">{number}</div><div className="mt-3 text-sm font-medium">{title}</div><div className="mt-1 text-xs leading-5 text-ink-secondary">{detail}</div></div>;
}

function DependencyMap({ nodes, edges, selectedRisk }: { nodes: GraphNode[]; edges: GraphEdge[]; selectedRisk: Risk | null }) {
  if (nodes.length === 0) return <div className="flex min-h-[270px] items-center justify-center px-5 text-center"><div><div className="text-sm font-medium">No operational graph loaded</div><p className="mt-2 max-w-sm text-xs leading-5 text-ink-secondary">Upload and validate the supported data contract to build the dependency view.</p><Link href="/upload" className="mt-4 inline-block text-xs text-accent hover:underline">Open data readiness →</Link></div></div>;
  const visibleNodes = nodes.slice(0, 18);
  const width = 920;
  const height = 270;
  const positions = new Map(visibleNodes.map((node, index) => [node.node_id ?? node.entity_id ?? String(index), { x: 52 + (index % 6) * 160, y: 65 + Math.floor(index / 6) * 80 }]));
  const selectedId = selectedRisk?.entity_id;
  const nodeKey = (node: GraphNode) => node.node_id ?? node.entity_id ?? "";
  const matchingEdges = edges.filter((edge) => positions.has(edge.source_node_id ?? "") && positions.has(edge.target_node_id ?? ""));
  return <div className="relative overflow-x-auto bg-[#0b0d0c] p-4"><svg viewBox={`0 0 ${width} ${height}`} className="min-w-[680px]" role="img" aria-label="Operational dependency map"><g stroke="#343a35" strokeWidth="1">{matchingEdges.map((edge, index) => { const source = positions.get(edge.source_node_id ?? ""); const target = positions.get(edge.target_node_id ?? ""); if (!source || !target) return null; return <line key={edge.edge_id ?? index} x1={source.x} y1={source.y} x2={target.x} y2={target.y} />; })}</g>{visibleNodes.map((node, index) => { const key = nodeKey(node); const position = positions.get(key); if (!position) return null; const selected = node.entity_id === selectedId; const type = String(node.entity_type ?? "entity"); return <g key={key || index}><circle cx={position.x} cy={position.y} r={selected ? 9 : 6} fill={selected ? "#16a34a" : type.toLowerCase().includes("supplier") ? "#dc2626" : "#8b938b"} /><text x={position.x} y={position.y + 24} textAnchor="middle" fill={selected ? "#f5f7f5" : "#9ba39b"} fontSize="10">{nodeLabel(node).slice(0, 20)}</text><text x={position.x} y={position.y - 14} textAnchor="middle" fill="#687168" fontSize="8">{titleCase(type)}</text></g>; })}</svg><div className="mt-2 flex flex-wrap gap-4 px-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-critical" />Supplier</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />Selected</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-[#8b938b]" />Entity</span><span className="ml-auto">Showing {visibleNodes.length} of {nodes.length} nodes</span></div></div>;
}
