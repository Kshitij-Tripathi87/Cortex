"use client";

/**
 * Nexus v0.7 — Decision Cockpit (item 9)
 *
 * Redesigned central frontend around the operational layout:
 *
 *   ┌─────────────────────────────────────────────────────────┐
 *   │ NEXUS                         WORLD 10482      ● LIVE    │
 *   ├────────────────┬────────────────────────────────────────┤
 *   │ ATTENTION      │                                        │
 *   │                │                                        │
 *   │ 3 Critical     │             OPERATIONAL GRAPH          │
 *   │ 8 High         │                                        │
 *   │ 19 Watch       │                                        │
 *   │                │                                        │
 *   │ S-142          │                                        │
 *   │ CRITICAL       │                                        │
 *   │ ₹45L exposure  │                                        │
 *   │ 82% SLA risk   │                                        │
 *   ├────────────────┴────────────────────────────────────────┤
 *   │ VANESSA                                                  │
 *   │                                                         │
 *   │ "Why is S-142 critical?"                               │
 *   │                                                         │
 *   │ Evidence-backed explanation                            │
 *   │ + graph path                                            │
 *   │ + metrics                                               │
 *   │                                                         │
 *   │ [SIMULATE] [COMPARE] [EVIDENCE]                        │
 *   └─────────────────────────────────────────────────────────┘
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

// ─── Types ──────────────────────────────────────────────────────────────────

interface RiskItem {
  risk_id?: string;
  entity_id: string;
  entity_name: string;
  entity_kind: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "WATCH";
  risk_score: number;
  gnn_risk_score?: number;
  title: string;
  revenue_exposure?: number;
  sla_risk_pct?: number;
  blast_radius_count?: number;
  hidden_dependencies?: Array<{ description: string; downstream_order_count: number }>;
  explanation?: {
    what: string;
    why: string;
    impact: string;
    confidence: number;
    evidence_count: number;
    what_next: string[];
    what_next_actions: Array<{ action: string; label: string }>;
    blocks: Array<{ type: string; title: string; metrics?: Record<string, number> }>;
  };
}

interface VanessaMessage {
  role: "user" | "assistant";
  content: string;
  response_blocks?: Array<{ type: string; title: string; content?: string; metrics?: Record<string, unknown> }>;
  timestamp?: string;
}

interface ModelHealth {
  [system: string]: { accuracy: number; name?: string; version?: string };
}

interface CriticalNode {
  entity_id: string;
  entity_kind: string;
  name: string;
  pagerank: number;
  centrality_score: number;
}

type SeverityBucket = "CRITICAL" | "HIGH" | "WATCH";

// ─── Utilities ──────────────────────────────────────────────────────────────

function formatINR(v: number | undefined): string {
  if (v === undefined) return "—";
  const abs = Math.abs(v);
  if (abs >= 10000000) return `₹${(v / 10000000).toFixed(1)}Cr`;
  if (abs >= 100000) return `₹${(v / 100000).toFixed(0)}L`;
  if (abs >= 1000) return `₹${(v / 1000).toFixed(1)}K`;
  return `₹${Math.round(v)}`;
}

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "#e5484d",
  HIGH: "#f5a623",
  MEDIUM: "#eab308",
  LOW: "#22c55e",
  WATCH: "#6b7280",
};

// ─── Cockpit Page ───────────────────────────────────────────────────────────

export default function NexusDecisionCockpit() {
  const { status, workspace } = useAuth();
  const [worldVersion, setWorldVersion] = useState(0);
  const [live, setLive] = useState<"live" | "connecting" | "offline">("connecting");
  const [risks, setRisks] = useState<RiskItem[]>([]);
  const [selectedRisk, setSelectedRisk] = useState<RiskItem | null>(null);
  const [criticalNodes, setCriticalNodes] = useState<CriticalNode[]>([]);
  const [intelligenceHealth, setIntelligenceHealth] = useState<ModelHealth>({});
  const [vanessaInput, setVanessaInput] = useState("");
  const [vanessaMessages, setVanessaMessages] = useState<VanessaMessage[]>([]);
  const [vanessaSessionId, setVanessaSessionId] = useState<string | null>(null);
  const [vanessaThinking, setVanessaThinking] = useState(false);
  const [activeTab, setActiveTab] = useState<"cockpit" | "forecast" | "truth">("cockpit");

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Load authoritative workspace data. Empty and unavailable states stay visible;
  // the cockpit never manufactures incidents, model scores, or assistant history.
  useEffect(() => {
    if (status !== "AUTHENTICATED" || !workspace?.id) {
      setLive("offline");
      return;
    }

    let cancelled = false;
    setLive("connecting");
    const load = async () => {
      try {
        const [riskEnvelope, nodes, healthEnvelope] = await Promise.all([
          apiClient.get<{ data?: { risks?: Array<Record<string, unknown>> } }>("/nexus/risks", {
            workspace_id: workspace.id,
            status: "open",
          }),
          apiClient.get<Array<Record<string, unknown>>>("/graph/nodes", {
            workspace_id: workspace.id,
            limit: 200,
          }),
          apiClient.get<{ data?: { health?: ModelHealth } }>("/nexus/models/health", {
            workspace_id: workspace.id,
          }),
        ]);
        if (cancelled) return;

        const rawRisks = riskEnvelope.data?.risks ?? [];
        const mappedRisks: RiskItem[] = rawRisks.map((raw) => {
          const hidden = Array.isArray(raw.hidden_dependencies) ? raw.hidden_dependencies : [];
          return {
            risk_id: typeof raw.risk_id === "string" ? raw.risk_id : undefined,
            entity_id: String(raw.entity_id ?? "unknown"),
            entity_name: String(raw.entity_name ?? raw.entity_id ?? "Unknown entity"),
            entity_kind: String(raw.entity_kind ?? "entity"),
            severity: String(raw.severity ?? "WATCH").toUpperCase() as RiskItem["severity"],
            risk_score: Number(raw.risk_score ?? 0),
            gnn_risk_score: raw.gnn_risk_score == null ? undefined : Number(raw.gnn_risk_score),
            title: String(raw.title ?? "Operational risk"),
            revenue_exposure: raw.revenue_exposure == null ? undefined : Number(raw.revenue_exposure),
            sla_risk_pct: raw.sla_risk_pct == null ? undefined : Number(raw.sla_risk_pct),
            blast_radius_count: raw.blast_radius_count == null ? undefined : Number(raw.blast_radius_count),
            hidden_dependencies: hidden.map((dependency) =>
              typeof dependency === "string"
                ? { description: dependency, downstream_order_count: 0 }
                : dependency as { description: string; downstream_order_count: number },
            ),
          };
        });
        setRisks(mappedRisks);
        setSelectedRisk(mappedRisks[0] ?? null);
        setCriticalNodes(
          nodes.slice(0, 12).map((node) => ({
            entity_id: String(node.entity_id ?? node.node_id ?? "unknown"),
            entity_kind: String(node.entity_type ?? "entity"),
            name: String((node.attributes as Record<string, unknown> | undefined)?.name ?? node.entity_id ?? node.node_id ?? "Unknown entity"),
            pagerank: Number((node.attributes as Record<string, unknown> | undefined)?.pagerank ?? 0),
            centrality_score: Number((node.attributes as Record<string, unknown> | undefined)?.centrality_score ?? 0),
          })),
        );
        setIntelligenceHealth(healthEnvelope.data?.health ?? {});
        const versions = rawRisks.map((risk) => Number(risk.world_state_version ?? 0));
        setWorldVersion(versions.length ? Math.max(...versions) : 0);
        setVanessaMessages([]);
        setVanessaSessionId(null);
        setLive("live");
      } catch {
        if (!cancelled) {
          setRisks([]);
          setSelectedRisk(null);
          setCriticalNodes([]);
          setIntelligenceHealth({});
          setVanessaMessages([]);
          setVanessaSessionId(null);
          setLive("offline");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [status, workspace?.id]);

  // Auto-scroll Vanessa chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [vanessaMessages]);

  // ── Severity buckets ────────────────────────────────────────────

  const buckets = useMemo(() => {
    const b: Record<SeverityBucket, RiskItem[]> = { CRITICAL: [], HIGH: [], WATCH: [] };
    for (const r of risks) {
      if (r.severity === "CRITICAL") b.CRITICAL.push(r);
      else if (r.severity === "HIGH") b.HIGH.push(r);
      else b.WATCH.push(r);
    }
    return b;
  }, [risks]);

  // ── Vanessa ask ─────────────────────────────────────────────────

  const askVanessa = useCallback(async () => {
    const q = vanessaInput.trim();
    if (!q) return;
    setVanessaInput("");
    setVanessaMessages((messages) => [...messages, { role: "user", content: q }]);
    setVanessaThinking(true);

    if (!workspace?.id) {
      setVanessaMessages((messages) => [
        ...messages,
        { role: "assistant", content: "No authenticated workspace is available." },
      ]);
      setVanessaThinking(false);
      return;
    }

    try {
      const envelope = await apiClient.post<{
        data?: { response?: string; trace_id?: string; evidence?: Array<Record<string, unknown>> };
      }>(
        "/nexus/vanessa/ask",
        { query: q },
        { query: { workspace_id: workspace.id } },
      );
      const answer = envelope.data;
      setVanessaSessionId(answer?.trace_id ?? null);
      setVanessaMessages((messages) => [
        ...messages,
        {
          role: "assistant",
          content: answer?.response ?? "Cortex returned no grounded response for this request.",
        },
      ]);
    } catch {
      setVanessaMessages((messages) => [
        ...messages,
        { role: "assistant", content: "Cortex could not complete the grounded request." },
      ]);
    } finally {
      setVanessaThinking(false);
    }
  }, [vanessaInput, workspace?.id]);

  // ── Render ──────────────────────────────────────────────────────

  if (status !== "AUTHENTICATED") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#0a0a0b] font-mono text-xs text-[#9ca3af]">
        Authentication is required to open the Decision Cockpit.
      </main>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-[#0a0a0b] font-mono text-[#e5e5e5] text-xs">
      {/* Header */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-[#26262b] px-4">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold tracking-[0.3em] text-white">NEXUS</span>
          <span className="text-[10px] uppercase tracking-widest text-[#6b7280]">Decision Cockpit</span>
        </div>
        <div className="flex items-center gap-4">
          <a href="/nexus/decision-room" className="border border-[#26262b] px-2 py-1 text-[9px] uppercase tracking-widest text-[#9ca3af] hover:text-white">Decision Room</a>
          <nav className="flex gap-1 text-[10px] uppercase tracking-widest">
            {(["cockpit", "forecast", "truth"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setActiveTab(t)}
                className={`px-3 py-1 ${activeTab === t ? "border border-[#06b6d4] text-[#06b6d4]" : "text-[#6b7280] hover:text-[#e5e5e5]"}`}
              >
                {t === "cockpit" ? "Cockpit" : t === "forecast" ? "Forecast vs Reality" : "Truth"}
              </button>
            ))}
          </nav>
          <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                live === "live" ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" : "animate-pulse bg-amber-500"
              }`}
            />
            {live.toUpperCase()} · WORLD v{worldVersion}
          </span>
        </div>
      </header>

      {activeTab === "cockpit" && (
        <div className="flex min-h-0 flex-1">
          {/* Attention Panel */}
          <aside className="flex w-64 shrink-0 flex-col border-r border-[#26262b] overflow-y-auto">
            <div className="border-b border-[#26262b] px-3 py-2">
              <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Attention</div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-lg font-bold text-[#e5484d]">{buckets.CRITICAL.length}</div>
                  <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Critical</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-[#f5a623]">{buckets.HIGH.length}</div>
                  <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">High</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-[#6b7280]">{risks.length - buckets.CRITICAL.length - buckets.HIGH.length}</div>
                  <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Watch</div>
                </div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {risks.slice(0, 12).map((r) => {
                const selected = selectedRisk?.entity_id === r.entity_id;
                return (
                  <button
                    key={r.entity_id}
                    onClick={() => setSelectedRisk(r)}
                    className={`block w-full border-b border-[#1a1a1d] px-3 py-2.5 text-left transition-colors ${
                      selected ? "bg-[#1a1a1d]" : "hover:bg-[#111113]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-white">{r.entity_name}</span>
                      <span
                        className="text-[9px] uppercase tracking-widest"
                        style={{ color: SEVERITY_COLOR[r.severity] }}
                      >
                        {r.severity}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-[#6b7280] line-clamp-1">{r.title}</div>
                    <div className="mt-1 flex items-center gap-2 text-[10px]">
                      {r.revenue_exposure !== undefined && (
                        <span className="text-[#e5484d]">{formatINR(r.revenue_exposure)}</span>
                      )}
                      {r.sla_risk_pct !== undefined && (
                        <span className="text-[#f5a623]">{Math.round(r.sla_risk_pct * 100)}% SLA</span>
                      )}
                      {r.gnn_risk_score !== undefined && r.gnn_risk_score > r.risk_score && (
                        <span className="ml-auto rounded bg-[#e5484d]/20 px-1 text-[#e5484d]">GNN ↑</span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          {/* Operational Graph + Details */}
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            {/* Graph area */}
            <div className="relative flex-1 overflow-hidden p-4">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-[9px] uppercase tracking-widest text-[#6b7280]">
                  Operational Graph
                </h2>
                <div className="flex gap-2 text-[9px] uppercase tracking-widest text-[#6b7280]">
                  <span>{criticalNodes.length} critical nodes</span>
                  <span>· GNN-augmented</span>
                </div>
              </div>
              <CriticalNodeGraph nodes={criticalNodes} selectedId={selectedRisk?.entity_id} onSelect={(id) => {
                const r = risks.find((x) => x.entity_id === id);
                if (r) setSelectedRisk(r);
              }} />
            </div>

            {/* Selected risk detail — the WHAT/WHY/IMPACT/CONFIDENCE/EVIDENCE/WHAT NEXT panel */}
            {selectedRisk && (
              <div className="border-t border-[#26262b] bg-[#0f0f11] p-4">
                <ExplanationPanel risk={selectedRisk} />
              </div>
            )}
          </main>
        </div>
      )}

      {activeTab === "forecast" && <ForecastVsReality />}
      {activeTab === "truth" && <SupplyChainTruth health={intelligenceHealth} />}

      {/* Vanessa bar */}
      <footer className="flex h-14 shrink-0 items-center gap-3 border-t border-[#26262b] bg-[#0f0f11] px-4">
        <span className="text-[9px] uppercase tracking-widest text-[#6b7280]">
          <span className="text-[#06b6d4]">VANESSA</span> — Ask your supply chain
        </span>
        <span className="text-[#06b6d4]">&gt;</span>
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto max-h-14">
          {vanessaMessages.slice(-2).map((m, i) => (
            <div key={i} className={`text-[10px] ${m.role === "user" ? "text-[#6b7280]" : "text-[#e5e5e5]"} truncate`}>
              {m.role === "user" ? "› " : ""}{m.content}
            </div>
          ))}
        </div>
        <input
          value={vanessaInput}
          onChange={(e) => setVanessaInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void askVanessa(); }}
          placeholder={selectedRisk ? `Why is ${selectedRisk.entity_name} critical?` : "Ask about risk, forecasts, scenarios, past decisions..."}
          className="min-w-[200px] flex-1 bg-[#1a1a1d] border border-[#26262b] px-3 py-1.5 text-xs outline-none placeholder:text-[#3f3f46] focus:border-[#06b6d4]"
        />
        <button
          onClick={() => void askVanessa()}
          disabled={vanessaThinking || !vanessaInput.trim()}
          className="border border-[#06b6d4]/60 bg-[#06b6d4]/10 px-3 py-1.5 text-[10px] uppercase tracking-widest text-[#06b6d4] hover:bg-[#06b6d4]/20 disabled:opacity-40"
        >
          {vanessaThinking ? "…" : "Ask"}
        </button>
      </footer>

      {/* Vanessa conversation overlay (appears below chat area when messages > 2) */}
      {vanessaMessages.length > 1 && (
        <div className="max-h-48 shrink-0 overflow-y-auto border-t border-[#26262b] bg-[#0a0a0b] px-4 py-2">
          {vanessaMessages.slice(-4).map((m, i) => (
            <div key={i} className={`mb-1 text-[10px] ${m.role === "user" ? "text-[#6b7280]" : "text-[#e5e5e5]"}`}>
              <span className="text-[9px] uppercase tracking-widest mr-2 text-[#3f3f46]">{m.role}</span>
              {m.content}
            </div>
          ))}
          {vanessaThinking && <div className="text-[10px] text-[#06b6d4] animate-pulse">Vanessa is reasoning…</div>}
          <div ref={chatEndRef} />
        </div>
      )}
    </div>
  );
}

// ─── Critical Node Graph ────────────────────────────────────────────────────

function CriticalNodeGraph({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: CriticalNode[];
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  const width = 800;
  const height = 380;
  const cx = width / 2;
  const cy = height / 2;

  const positioned = nodes.map((n, i) => {
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2 - Math.PI / 2;
    const radius = 80 + n.centrality_score * 100;
    return {
      ...n,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      r: 6 + n.centrality_score * 14,
    };
  });

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} className="bg-[#0d0d0f] rounded border border-[#1a1a1d]">
      <defs>
        <radialGradient id="glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#06b6d4" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx={cx} cy={cy} r={160} fill="url(#glow)" />

      {/* Edges to center */}
      {positioned.map((n) => (
        <line
          key={`e-${n.entity_id}`}
          x1={cx}
          y1={cy}
          x2={n.x}
          y2={n.y}
          stroke={selectedId === n.entity_id ? "#06b6d4" : "#26262b"}
          strokeWidth={selectedId === n.entity_id ? 1.5 : 0.7}
          strokeDasharray={n.entity_kind === "port" ? "3,3" : undefined}
        />
      ))}

      {/* Nodes */}
      {positioned.map((n) => (
        <g key={n.entity_id} onClick={() => onSelect(n.entity_id)} className="cursor-pointer">
          <circle
            cx={n.x}
            cy={n.y}
            r={n.r}
            fill={n.entity_kind === "supplier" ? "#e5484d" : n.entity_kind === "port" ? "#f5a623" : n.entity_kind === "plant" ? "#22c55e" : "#6b7280"}
            stroke={selectedId === n.entity_id ? "#ffffff" : "transparent"}
            strokeWidth={selectedId === n.entity_id ? 2 : 0}
          />
          <text x={n.x} y={n.y + n.r + 12} textAnchor="middle" fill="#6b7280" fontSize="9" fontFamily="monospace">
            {n.name}
          </text>
        </g>
      ))}

      {/* Center label */}
      <text x={cx} y={cy - 5} textAnchor="middle" fill="#06b6d4" fontSize="10" fontFamily="monospace" style={{ textTransform: "uppercase" }}>
        NEXUS
      </text>
      <text x={cx} y={cy + 8} textAnchor="middle" fill="#6b7280" fontSize="8" fontFamily="monospace">
        OPERATIONAL WORLD
      </text>

      {/* Legend */}
      <g transform="translate(10, 10)">
        {[
          { color: "#e5484d", label: "Supplier" },
          { color: "#f5a623", label: "Port" },
          { color: "#22c55e", label: "Plant" },
        ].map((item, i) => (
          <g key={item.label} transform={`translate(0, ${i * 14})`}>
            <circle cx="4" cy="4" r="3" fill={item.color} />
            <text x="12" y="7" fill="#6b7280" fontSize="8" fontFamily="monospace">
              {item.label}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

// ─── Explanation Panel (WHAT/WHY/IMPACT/CONFIDENCE/EVIDENCE/WHAT NEXT) ──────

function ExplanationPanel({ risk }: { risk: RiskItem }) {
  const exp = risk.explanation;
  if (!exp) {
    return (
      <div className="text-[10px] text-[#6b7280]">
        No structured explanation for this risk. Ask Vanessa for analysis.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[1fr_1fr_1fr] gap-4 text-[10px]">
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">What</div>
        <div className="text-white">{exp.what}</div>
      </div>
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">Why</div>
        <div className="text-[#a1a1aa]">{exp.why}</div>
      </div>
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">Impact</div>
        <div className="text-[#f5a623]">{exp.impact}</div>
      </div>
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">Confidence</div>
        <div className="text-emerald-400">{Math.round(exp.confidence * 100)}%</div>
        <div className="text-[#6b7280] text-[9px]">across {exp.evidence_count} evidence points</div>
      </div>
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">Evidence</div>
        <div className="text-[#a1a1aa]">{exp.evidence_count} supporting observations</div>
        {risk.hidden_dependencies && risk.hidden_dependencies.length > 0 && (
          <div className="mt-1 text-[#e5484d]">
            {risk.hidden_dependencies.length} hidden dependencies (GNN)
          </div>
        )}
      </div>
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-widest text-[#06b6d4]">What Next</div>
        <div className="space-y-0.5">
          {exp.what_next.slice(0, 3).map((w, i) => (
            <div key={i} className="text-[#a1a1aa]">· {w}</div>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          {exp.what_next_actions.map((a) => (
            <button
              key={a.label}
              className="border border-[#06b6d4]/60 bg-[#06b6d4]/10 px-2 py-0.5 text-[9px] uppercase tracking-widest text-[#06b6d4] hover:bg-[#06b6d4]/20"
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Forecast vs Reality screen (item 12) ───────────────────────────────────

function ForecastVsReality() {
  const { workspace } = useAuth();
  const [buckets, setBuckets] = useState<Array<Record<string, unknown>>>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "offline">("loading");

  useEffect(() => {
    if (!workspace?.id) {
      setStatus("offline");
      return;
    }
    let cancelled = false;
    void apiClient
      .get<{ data?: { buckets?: Array<Record<string, unknown>> } }>("/nexus/calibration", {
        workspace_id: workspace.id,
      })
      .then((response) => {
        if (cancelled) return;
        const values = response.data?.buckets ?? [];
        setBuckets(values);
        setStatus(values.length ? "ready" : "empty");
      })
      .catch(() => {
        if (!cancelled) setStatus("offline");
      });
    return () => {
      cancelled = true;
    };
  }, [workspace?.id]);

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-1 text-sm font-bold tracking-widest text-white">FORECAST VS REALITY</h1>
      <p className="mb-6 text-[10px] uppercase tracking-widest text-[#6b7280]">
        Calibration from persisted forecasts and observations
      </p>
      {status === "loading" && <p className="text-[10px] text-[#6b7280]">Loading calibration…</p>}
      {status === "offline" && <p className="text-[10px] text-[#e5484d]">Calibration is unavailable.</p>}
      {status === "empty" && <p className="text-[10px] text-[#6b7280]">No forecast observations are available for this workspace.</p>}
      {status === "ready" && (
        <div className="border border-[#26262b] bg-[#0f0f11] p-4">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-[#26262b] text-left text-[9px] uppercase tracking-widest text-[#6b7280]">
                <th className="py-2">SKU</th>
                <th>Samples</th>
                <th>MAE</th>
                <th>Bias</th>
                <th>P80 coverage</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((bucket, index) => (
                <tr key={String(bucket.sku ?? bucket.product_id ?? index)} className="border-b border-[#1a1a1d]">
                  <td className="py-2 text-white">{String(bucket.sku ?? bucket.product_id ?? "Unknown")}</td>
                  <td>{String(bucket.sample_count ?? bucket.samples ?? "—")}</td>
                  <td>{String(bucket.mae ?? "—")}</td>
                  <td>{String(bucket.bias ?? "—")}</td>
                  <td>{String(bucket.p80_coverage ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SupplyChainTruth({ health }: { health: ModelHealth }) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-1 text-sm font-bold tracking-widest text-white">SUPPLY CHAIN TRUTH</h1>
      <p className="mb-6 text-[10px] uppercase tracking-widest text-[#6b7280]">
        How reliable is each intelligence system?
      </p>

      <div className="mb-4 rounded border border-[#06b6d4]/30 bg-[#06b6d4]/5 p-4 text-[10px] text-[#a1a1aa]">
        <span className="text-[#06b6d4]">Not:</span> "Nexus says X"
        <br />
        <span className="text-emerald-400">But:</span> "Nexus historically predicts X with 91% accuracy"
      </div>

      <div className="space-y-3">
        {Object.entries(health).map(([name, data]) => {
          const pct = Math.round(data.accuracy * 100);
          const color = data.accuracy >= 0.9 ? "#22c55e" : data.accuracy >= 0.8 ? "#f5a623" : data.accuracy > 0 ? "#e5484d" : "#6b7280";
          return (
            <div key={name} className="border border-[#26262b] bg-[#0f0f11] p-4">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-xs text-white">{name}</div>
                  <div className="text-[9px] text-[#6b7280]">
                    {data.name} {data.version}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xl font-bold" style={{ color }}>{pct}%</div>
                </div>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded bg-[#1a1a1d]">
                <div
                  className="h-full transition-all"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
