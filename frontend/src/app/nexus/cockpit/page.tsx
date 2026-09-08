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
  const [worldVersion, setWorldVersion] = useState(10482);
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

  // ── Seed demo data ──────────────────────────────────────────────

  useEffect(() => {
    // Seed with realistic demo data (the production version will pull from /api/v1/nexus/risks etc.)
    const demoRisks: RiskItem[] = [
      {
        entity_id: "S-142",
        entity_name: "S-142",
        entity_kind: "supplier",
        severity: "CRITICAL",
        risk_score: 0.71,
        gnn_risk_score: 0.88,
        title: "Supplier capacity fell 31%",
        revenue_exposure: 4500000,
        sla_risk_pct: 0.82,
        blast_radius_count: 12,
        hidden_dependencies: [
          { description: "S-142 → subcontractor X → port P-07", downstream_order_count: 12 },
        ],
        explanation: {
          what: "Revenue exposure increased ₹8.7L — Supplier S-142 capacity fell 31%.",
          why: "Port congestion at P-07 combined with a labor strike at tier-2 subcontractor X; GNN detected the hidden multi-hop dependency.",
          impact: "37 orders · 4 SKUs · 2 plants",
          confidence: 0.91,
          evidence_count: 12,
          what_next: [
            "Shift 60% to alternate supplier S-098",
            "Expedite air freight for premium orders",
            "Review Dec-2023 analogous incident",
          ],
          what_next_actions: [
            { action: "simulate", label: "SIMULATE" },
            { action: "compare", label: "COMPARE" },
            { action: "evidence", label: "EVIDENCE" },
          ],
          blocks: [
            { type: "risk_card", title: "S-142 CRITICAL", metrics: { risk_score: 0.71, gnn_risk_score: 0.88, revenue_exposure: 4500000, sla_risk_pct: 0.82 } },
          ],
        },
      },
      {
        entity_id: "S-203",
        entity_name: "S-203",
        entity_kind: "supplier",
        severity: "CRITICAL",
        risk_score: 0.68,
        title: "Lead time doubled to 21 days",
        revenue_exposure: 2800000,
        sla_risk_pct: 0.64,
        blast_radius_count: 8,
      },
      {
        entity_id: "S-077",
        entity_name: "S-077",
        entity_kind: "supplier",
        severity: "CRITICAL",
        risk_score: 0.64,
        title: "Financial health downgrade",
        revenue_exposure: 1900000,
        sla_risk_pct: 0.51,
        blast_radius_count: 5,
      },
      {
        entity_id: "P-07",
        entity_name: "Port P-07",
        entity_kind: "port",
        severity: "HIGH",
        risk_score: 0.58,
        title: "Congestion delay 5+ days",
        revenue_exposure: 3200000,
        sla_risk_pct: 0.45,
        blast_radius_count: 15,
      },
      {
        entity_id: "RT-12",
        entity_name: "Route RT-12",
        entity_kind: "route",
        severity: "HIGH",
        risk_score: 0.53,
        title: "Weather disruption projected",
        revenue_exposure: 900000,
        sla_risk_pct: 0.33,
      },
    ];
    setRisks(demoRisks);
    setSelectedRisk(demoRisks[0]);

    setCriticalNodes([
      { entity_id: "S-142", entity_kind: "supplier", name: "S-142", pagerank: 0.081, centrality_score: 1.0 },
      { entity_id: "P-07", entity_kind: "port", name: "P-07", pagerank: 0.072, centrality_score: 0.89 },
      { entity_id: "PL-01", entity_kind: "plant", name: "PL-01", pagerank: 0.065, centrality_score: 0.8 },
      { entity_id: "S-203", entity_kind: "supplier", name: "S-203", pagerank: 0.058, centrality_score: 0.72 },
    ]);

    setIntelligenceHealth({
      "Demand forecast": { accuracy: 0.91, name: "baseline-demand-forecast", version: "v1.0" },
      "ETA prediction": { accuracy: 0.87, name: "eta-xgboost", version: "v2.1" },
      "Supplier risk": { accuracy: 0.94, name: "supplier-risk-classifier", version: "v1.0" },
      "SLA prediction": { accuracy: 0.92, name: "sla-lightgbm", version: "v1.3" },
      "Scenario accuracy": { accuracy: 0.84, name: "baseline-gnn", version: "v1.0" },
      "Recommendation success": { accuracy: 0.89, name: "baseline-rl-policy", version: "v1.0" },
    });

    // Seed initial Vanessa greeting
    setVanessaMessages([
      {
        role: "assistant",
        content: "Nexus online. World state v10482. Three critical risks detected. S-142 is the highest-exposure node. Ask me anything.",
      },
    ]);
    setVanessaSessionId("VSESS-demo-session");
    setLive("live");
  }, []);

  // Simulate live world-state increments
  useEffect(() => {
    if (live !== "live") return;
    const interval = setInterval(() => {
      setWorldVersion((v) => v + Math.random() > 0.85 ? v + 1 : v);
    }, 8000);
    return () => clearInterval(interval);
  }, [live]);

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
    setVanessaMessages((m) => [...m, { role: "user", content: q }]);
    setVanessaThinking(true);

    // Simulate contextual response based on keywords + selected entity
    await new Promise((r) => setTimeout(r, 700));

    let response = "";
    let blocks: VanessaMessage["response_blocks"] = [];
    const ent = selectedRisk;
    const ql = q.toLowerCase();

    if (ql.includes("why") && ent) {
      response = `${ent.entity_name} is flagged ${ent.severity} because ${ent.title.toLowerCase()}. The GNN structural analysis elevates the traditional risk score of ${(ent.risk_score * 100).toFixed(0)}% to ${((ent.gnn_risk_score ?? ent.risk_score) * 100).toFixed(0)}% due to ${ent.hidden_dependencies?.length ?? 0} hidden multi-hop dependencies that the rules-based engine missed. Confidence: ${(ent.explanation?.confidence ?? 0.8) * 100:.0f}% across ${ent.explanation?.evidence_count ?? 0} evidence points.`;
      blocks = ent.explanation?.blocks;
    } else if (ql.includes("happen") || ql.includes("lose") || ql.includes("fail")) {
      response = `If ${ent?.entity_name ?? "this node"} fails, GNN blast-radius analysis shows ${ent?.blast_radius_count ?? 0} downstream entities affected, with ~${formatINR(ent?.revenue_exposure)} revenue exposure and ${Math.round((ent?.sla_risk_pct ?? 0) * 100)}% projected SLA breach across ${ent?.explanation?.impact ?? "multiple orders"}.`;
    } else if (ql.includes("alternate") || ql.includes("compare") || ql.includes("supplier")) {
      response = `GNN similarity analysis found 3 alternate suppliers with >60% SKU overlap. S-098 (similarity 0.78) can absorb ~45% of volume. Would you like to simulate the shift?`;
    } else if (ql.includes("last time") || ql.includes("history") || ql.includes("before")) {
      response = `Decision Memory: 3 analogous decisions in the past 18 months. Most similar: DEC-8872 (Sep 2024, Port of Rotterdam congestion) — we shifted 50% to alternate supplier, outcome: success, NEV +₹32L.`;
    } else if (ql.includes("forecast") || ql.includes("demand")) {
      response = `Demand forecast for affected SKUs shows a 12% uplift expected next 14 days (P50=14,200, P80=15,700, P95=17,900). Current WAPE 8.7%, bias -4.1%. No drift detected.`;
      blocks = [{ type: "metric", title: "Forecast Summary", metrics: { p50: 14200, p80: 15700, p95: 17900, wape: 0.087, bias: -0.041 } }];
    } else {
      response = `I see ${risks.length} open risks (${buckets.CRITICAL.length} critical, ${buckets.HIGH.length} high). World state v${worldVersion}. Select an item on the left or ask me about a specific supplier, order, or scenario.`;
    }

    setVanessaMessages((m) => [...m, { role: "assistant", content: response, response_blocks: blocks }]);
    setVanessaThinking(false);
  }, [vanessaInput, selectedRisk, risks, buckets, worldVersion]);

  // ── Render ──────────────────────────────────────────────────────

  return (
    <div className="flex h-screen flex-col bg-[#0a0a0b] font-mono text-[#e5e5e5] text-xs">
      {/* Header */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-[#26262b] px-4">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold tracking-[0.3em] text-white">NEXUS</span>
          <span className="text-[10px] uppercase tracking-widest text-[#6b7280]">Decision Cockpit</span>
        </div>
        <div className="flex items-center gap-4">
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
      <text x={cx} y={cy - 5} textAnchor="middle" fill="#06b6d4" fontSize="10" fontFamily="monospace" textTransform="uppercase">
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
  const demoSkus = [
    { sku: "SKU-102", p50: 14200, p80: 15700, p95: 17900, actual: 15100, wape: 0.087, bias: -0.041, confidence: 0.76 },
    { sku: "SKU-088", p50: 8400, p80: 9200, p95: 10100, actual: 7900, wape: 0.062, bias: 0.059, confidence: 0.82 },
    { sku: "SKU-215", p50: 3200, p80: 3800, p95: 4500, actual: 4200, wape: 0.312, bias: -0.238, confidence: 0.54 },
  ];
  const [selectedSku, setSelectedSku] = useState(demoSkus[0]);
  const errorPct = ((selectedSku.actual - selectedSku.p50) / selectedSku.p50) * 100;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-1 text-sm font-bold tracking-widest text-white">DEMAND INTELLIGENCE</h1>
      <p className="mb-6 text-[10px] uppercase tracking-widest text-[#6b7280]">Forecast vs Reality — "Where is our forecast wrong?"</p>

      <div className="mb-6 flex gap-2">
        {demoSkus.map((s) => (
          <button
            key={s.sku}
            onClick={() => setSelectedSku(s)}
            className={`border px-3 py-1.5 text-[10px] uppercase tracking-widest ${
              selectedSku.sku === s.sku ? "border-[#06b6d4] text-[#06b6d4]" : "border-[#26262b] text-[#6b7280] hover:text-white"
            }`}
          >
            {s.sku}
          </button>
        ))}
      </div>

      <div className="mb-6 grid grid-cols-4 gap-4">
        <div className="border border-[#26262b] bg-[#0f0f11] p-4">
          <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Forecast P50</div>
          <div className="mt-1 text-xl font-bold text-white">{selectedSku.p50.toLocaleString()}</div>
        </div>
        <div className="border border-[#26262b] bg-[#0f0f11] p-4">
          <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">P80 / P95</div>
          <div className="mt-1 text-xl font-bold text-white">
            {selectedSku.p80.toLocaleString()} <span className="text-sm text-[#6b7280]">/ {selectedSku.p95.toLocaleString()}</span>
          </div>
        </div>
        <div className="border border-[#26262b] bg-[#0f0f11] p-4">
          <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Actual</div>
          <div className="mt-1 text-xl font-bold text-emerald-400">{selectedSku.actual.toLocaleString()}</div>
        </div>
        <div className="border border-[#26262b] bg-[#0f0f11] p-4">
          <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">Error</div>
          <div className={`mt-1 text-xl font-bold ${errorPct > 0 ? "text-[#e5484d]" : "text-emerald-400"}`}>
            {errorPct > 0 ? "+" : ""}{errorPct.toFixed(1)}%
          </div>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-4 gap-4 text-[10px]">
        <MetricBox label="Historical WAPE" value={`${(selectedSku.wape * 100).toFixed(1)}%`} warning={selectedSku.wape > 0.15} />
        <MetricBox label="Bias" value={`${(selectedSku.bias * 100).toFixed(1)}%`} warning={Math.abs(selectedSku.bias) > 0.1} />
        <MetricBox label="Confidence" value={`${Math.round(selectedSku.confidence * 100)}%`} warning={selectedSku.confidence < 0.7} />
        <div className="flex items-center justify-center border border-[#06b6d4]/60 bg-[#06b6d4]/10">
          <button className="px-4 py-2 text-[10px] uppercase tracking-widest text-[#06b6d4]">
            Ask Vanessa →
          </button>
        </div>
      </div>

      <div className="border border-[#26262b] bg-[#0f0f11] p-4">
        <h3 className="mb-3 text-[9px] uppercase tracking-widest text-[#6b7280]">Where are we wrong?</h3>
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-[#26262b] text-left text-[9px] uppercase tracking-widest text-[#6b7280]">
              <th className="py-2">SKU</th>
              <th>WAPE</th>
              <th>Bias</th>
              <th>Direction</th>
              <th>Severity</th>
              <th>Drift</th>
            </tr>
          </thead>
          <tbody>
            {demoSkus.map((s) => {
              const err = ((s.actual - s.p50) / s.p50) * 100;
              return (
                <tr key={s.sku} className="border-b border-[#1a1a1d]">
                  <td className="py-2 font-mono text-white">{s.sku}</td>
                  <td className={s.wape > 0.15 ? "text-[#e5484d]" : ""}>{(s.wape * 100).toFixed(1)}%</td>
                  <td className={Math.abs(s.bias) > 0.1 ? "text-[#f5a623]" : ""}>{(s.bias * 100).toFixed(1)}%</td>
                  <td>{err > 0 ? "underforecast" : "overforecast"}</td>
                  <td>{s.wape > 0.2 ? <span className="text-[#e5484d]">HIGH</span> : s.wape > 0.1 ? <span className="text-[#f5a623]">MEDIUM</span> : <span className="text-emerald-400">LOW</span>}</td>
                  <td>{s.sku === "SKU-215" ? <span className="text-[#e5484d]">DETECTED</span> : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetricBox({ label, value, warning }: { label: string; value: string; warning?: boolean }) {
  return (
    <div className="border border-[#26262b] bg-[#0f0f11] p-3">
      <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">{label}</div>
      <div className={`mt-1 text-lg font-bold ${warning ? "text-[#f5a623]" : "text-white"}`}>{value}</div>
    </div>
  );
}

// ─── Supply Chain Truth dashboard (item 13) ─────────────────────────────────

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
