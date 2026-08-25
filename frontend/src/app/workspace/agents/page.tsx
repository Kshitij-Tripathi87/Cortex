"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AgentMessageEnvelope } from "@/types/nexus";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export default function AgentOperationsCenterPage() {
  const { worldStateVersion, redeliberate } = useNexusWorkspace();

  const [isDeliberating, setIsDeliberating] = useState(false);
  const [activeTab, setActiveTab] = useState<"TASK_GRAPH" | "DELIBERATION" | "TOPOLOGY" | "MANIFESTS">("TASK_GRAPH");
  const [selectedDomain, setSelectedDomain] = useState<string>("ALL");

  const [taskGraph] = useState({
    task_id: "TASK_2026_001",
    title: "Resolve SLA Corridor Disruption on seller_01a00b8e99",
    status: "COMPLETED",
    consensus_score: 0.94,
    created_at: "23:55:01Z",
    steps: [
      { id: "s1", domain: "PROCUREMENT", title: "Supplier Discovery via GNN Embeddings", agent: "Supplier Discovery Agent (v4.2)", status: "COMPLETED", time: "120ms", verdict: "Discovered seller_bb99112233 (0.94 similarity)" },
      { id: "s2", domain: "OPTIMIZATION", title: "3D Volumetric Cubing & Co-Loading", agent: "Load Planning Agent (v4.5)", status: "COMPLETED", time: "180ms", verdict: "12 orders cubed at 35% utilization (FEASIBLE)" },
      { id: "s3", domain: "BOOKING", title: "Multimodal Capacity & Rate Negotiation", agent: "Capacity Booking Agent (v4.2)", status: "COMPLETED", time: "210ms", verdict: "Reserved Lane VCP-SDU ($450.00 / 0.5d transit)" },
      { id: "s4", domain: "COMPLIANCE", title: "Trade Sanctions & Spend Authorization", agent: "Compliance Agent (v5.0)", status: "COMPLETED", time: "90ms", verdict: "APPROVED (Budget within $1,500 limit, Sanctions Clear)" },
      { id: "s5", domain: "SUPERVISOR", title: "Consensus Synthesis & Twin Dispatch", agent: "Nexus Swarm Supervisor (v5.0)", status: "COMPLETED", time: "80ms", verdict: "Consensus 0.94 • Candidate C dispatched to Digital Twin" },
    ],
  });

  const domainFamilies = [
    {
      group: "BOOKING",
      name: "Booking & Negotiation Family",
      color: "border-blue-800 bg-blue-950/20 text-blue-400",
      agents: [
        { id: "capacity_booking_agent", name: "Capacity Booking Agent", version: "v4.2", role: "Capacity & Lane Availability", status: "ACTIVE" },
        { id: "carrier_negotiation_agent", name: "Carrier Negotiation Agent", version: "v4.0", role: "Pricing Bands & Discounts", status: "ACTIVE" },
        { id: "freight_tender_agent", name: "Freight Tender Agent", version: "v4.1", role: "Tender Documentation", status: "ACTIVE" },
        { id: "booking_exception_agent", name: "Booking Exception Agent", version: "v4.0", role: "Rejection & Cutoff Recovery", status: "ACTIVE" },
      ],
    },
    {
      group: "COMPLIANCE",
      name: "Back-Office & Compliance (Control Plane)",
      color: "border-red-800 bg-red-950/20 text-red-400",
      agents: [
        { id: "compliance_agent", name: "Compliance Agent", version: "v5.0", role: "Trade Rules & Veto Authority", status: "ACTIVE (VETO POWER)" },
        { id: "finance_validation_agent", name: "Finance Validation Agent", version: "v4.1", role: "Spend Limits & Budget Audit", status: "ACTIVE" },
        { id: "documentation_agent", name: "Documentation Agent", version: "v4.0", role: "Invoice & Customs Verification", status: "ACTIVE" },
        { id: "audit_agent", name: "Audit & Provenance Agent", version: "v4.2", role: "Merkle Evidence DAG Verification", status: "ACTIVE" },
      ],
    },
    {
      group: "OPTIMIZATION",
      name: "Load Planning & Optimization Family",
      color: "border-emerald-800 bg-emerald-950/20 text-emerald-400",
      agents: [
        { id: "load_planning_agent", name: "Load Planning Agent", version: "v4.5", role: "3D Cubing & Weight Balancing", status: "ACTIVE" },
        { id: "route_optimization_agent", name: "Route Optimization Agent", version: "v4.3", role: "Topological Delay Minimization", status: "ACTIVE" },
        { id: "consolidation_agent", name: "Consolidation Agent", version: "v4.0", role: "Co-Loading & LTL Consolidation", status: "ACTIVE" },
        { id: "network_rebalancing_agent", name: "Network Rebalancing Agent", version: "v4.1", role: "Inter-Hub Inventory Flow", status: "ACTIVE" },
      ],
    },
    {
      group: "PROCUREMENT",
      name: "Procurement & Sourcing Family",
      color: "border-purple-800 bg-purple-950/20 text-purple-400",
      agents: [
        { id: "supplier_discovery_agent", name: "Supplier Discovery Agent", version: "v4.2", role: "GNN Embedding Similarity", status: "ACTIVE" },
        { id: "supplier_evaluation_agent", name: "Supplier Evaluation Agent", version: "v4.0", role: "Multi-Factor Risk Scorecard", status: "ACTIVE" },
        { id: "strategic_sourcing_agent", name: "Strategic Sourcing Agent", version: "v4.4", role: "Expedite vs Sourcing Trade-Offs", status: "ACTIVE" },
        { id: "purchase_reorder_agent", name: "Purchase Reorder Agent", version: "v4.1", role: "Gated Purchase Orders", status: "ACTIVE" },
      ],
    },
  ];

  const [messages, setMessages] = useState<AgentMessageEnvelope[]>([
    {
      message_id: "msg_01",
      sender_role: "SUPERVISOR",
      sender_name: "Nexus Swarm Supervisor",
      sender_version: "v5.0",
      content: "Task TASK_2026_001 created: Severe dispatch latency (+90%) detected on seller_01a00b8e99. Routing task graph to Procurement, Optimization, Booking, and Compliance families.",
      evidence_refs: ["sig_seller_deg_01", "olist_sellers_dataset.csv:#482"],
      phase: "OBSERVATION",
      timestamp: "23:55:02",
      context_package: { world_state_version: 101, domain: "SUPERVISOR" },
    },
    {
      message_id: "msg_02",
      sender_role: "PROCUREMENT",
      sender_name: "Supplier Discovery Agent",
      sender_version: "v4.2",
      content: "GNN embedding similarity query identified alternative qualified supplier seller_bb99112233 in Rio de Janeiro (Similarity: 0.94, OTIF: 96.5%).",
      evidence_refs: ["gnn_supplier_embeddings_v4.1"],
      phase: "PROPOSAL",
      timestamp: "23:55:03",
      context_package: { world_state_version: 101, domain: "PROCUREMENT" },
    },
    {
      message_id: "msg_03",
      sender_role: "OPTIMIZATION",
      sender_name: "Load Planning Agent",
      sender_version: "v4.5",
      content: "12 exposed orders cubed at 4.2m3 total volume (35% container utilization). Feasibility verdict: FEASIBLE for Air Cargo Pallet PAG.",
      evidence_refs: ["load_manifest_3d_engine"],
      phase: "PROPOSAL",
      timestamp: "23:55:04",
      context_package: { world_state_version: 101, domain: "OPTIMIZATION" },
    },
    {
      message_id: "msg_04",
      sender_role: "BOOKING",
      sender_name: "Capacity Booking Agent",
      sender_version: "v4.2",
      content: "Capacity locked on Lane VCP-SDU (Air Cargo) at $450.00 rate card. Transit time projected at 0.5 days with 98% SLA protection.",
      evidence_refs: ["rate_card_latam_2026", "corridor_vcp_sdu"],
      phase: "PROPOSAL",
      timestamp: "23:55:05",
      context_package: { world_state_version: 101, domain: "BOOKING" },
    },
    {
      message_id: "msg_05",
      sender_role: "COMPLIANCE",
      sender_name: "Compliance Agent (Control Plane)",
      sender_version: "v5.0",
      content: "Trade rule validation and sanctions checks passed. Spend authorization verified within $1,500 limit. Veto not exercised (APPROVED).",
      evidence_refs: ["sanctions_registry_2026", "finance_policy_sop"],
      phase: "CRITIQUE",
      timestamp: "23:55:06",
      context_package: { world_state_version: 101, domain: "COMPLIANCE" },
    },
    {
      message_id: "msg_06",
      sender_role: "SUPERVISOR",
      sender_name: "Nexus Swarm Supervisor",
      sender_version: "v5.0",
      content: "Multi-Agent Consensus synthesized (Consensus Score: 0.94). Candidate C (Air Expedite + Cross-Dock) formulated and dispatched to Digital Twin Simulator.",
      evidence_refs: ["consensus_score_0.94", "merkle_dag_5a3d76"],
      phase: "SYNTHESIS",
      timestamp: "23:55:07",
      context_package: { world_state_version: 101, domain: "SUPERVISOR" },
    },
  ]);

  const handleRunSwarm = async () => {
    setIsDeliberating(true);
    try {
      await redeliberate();
      const newMsg: AgentMessageEnvelope = {
        message_id: `msg_${Date.now()}`,
        sender_role: "SUPERVISOR",
        sender_name: "Nexus Swarm Supervisor",
        sender_version: "v5.0",
        content: `Live Swarm re-executed Task Graph against World State v${worldStateVersion}. Compliance cleared, Consensus 0.94 confirmed.`,
        evidence_refs: [`world_state_v${worldStateVersion}`, "policy_pass"],
        phase: "SYNTHESIS",
        timestamp: new Date().toLocaleTimeString(),
        context_package: { world_state_version: worldStateVersion, domain: "SUPERVISOR" },
      };
      setMessages((prev) => [...prev, newMsg]);
    } finally {
      setIsDeliberating(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      {/* Header & Main Trigger */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Agent Operations Center & Swarm Runtime</h1>
          <p className="text-xs text-zinc-400 mt-1">
            4 Domain Specialist Families (Booking, Compliance, Optimization, Procurement) orchestrated by Nexus Supervisor.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRunSwarm}
            disabled={isDeliberating}
            className="px-4 py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold font-mono text-xs transition shadow-lg flex items-center gap-2"
          >
            <span>{isDeliberating ? "⚡ Executing Swarm Task Graph..." : "▶ Execute 4-Family Swarm Task"}</span>
          </button>
          <Link
            href="/workspace/agents/fleet"
            className="px-3 py-2 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            Fleet & Lifecycle Replicas →
          </Link>
        </div>
      </div>

      {/* Primary Sub-Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-zinc-800 pb-2 text-xs font-mono">
        <button
          onClick={() => setActiveTab("TASK_GRAPH")}
          className={`px-3 py-1.5 rounded-t transition ${activeTab === "TASK_GRAPH" ? "bg-zinc-800 text-white font-bold border-b-2 border-emerald-400" : "text-zinc-400 hover:text-zinc-200"}`}
        >
          Active Task Graph ({taskGraph.task_id})
        </button>
        <button
          onClick={() => setActiveTab("DELIBERATION")}
          className={`px-3 py-1.5 rounded-t transition ${activeTab === "DELIBERATION" ? "bg-zinc-800 text-white font-bold border-b-2 border-emerald-400" : "text-zinc-400 hover:text-zinc-200"}`}
        >
          CTDE Deliberation Stream
        </button>
        <button
          onClick={() => setActiveTab("TOPOLOGY")}
          className={`px-3 py-1.5 rounded-t transition ${activeTab === "TOPOLOGY" ? "bg-zinc-800 text-white font-bold border-b-2 border-emerald-400" : "text-zinc-400 hover:text-zinc-200"}`}
        >
          4-Family Domain Hierarchy
        </button>
        <button
          onClick={() => setActiveTab("MANIFESTS")}
          className={`px-3 py-1.5 rounded-t transition ${activeTab === "MANIFESTS" ? "bg-zinc-800 text-white font-bold border-b-2 border-emerald-400" : "text-zinc-400 hover:text-zinc-200"}`}
        >
          Capability Manifests & Veto Rules
        </button>
      </div>

      {/* TAB 1: ACTIVE TASK GRAPH */}
      {activeTab === "TASK_GRAPH" && (
        <div className="space-y-4 font-mono text-xs">
          <div className="p-4 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <span className="font-bold text-zinc-100 uppercase">{taskGraph.title}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-zinc-400">Consensus: <strong className="text-emerald-400">{taskGraph.consensus_score}</strong></span>
                <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold text-[10px]">
                  {taskGraph.status}
                </span>
              </div>
            </div>

            {/* Step Progression Trace */}
            <div className="divide-y divide-zinc-800/60">
              {taskGraph.steps.map((s, idx) => (
                <div key={s.id} className="py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-zinc-900 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-300 font-bold">
                      {idx + 1}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-zinc-200">{s.title}</span>
                        <span className="text-zinc-500 text-[10px]">[{s.domain} • {s.agent}]</span>
                      </div>
                      <div className="text-[11px] text-zinc-400 mt-0.5 font-sans">{s.verdict}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] text-zinc-500">{s.time}</span>
                    <span className="text-emerald-400 font-bold text-[10px]">✓ PASS</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: DELIBERATION STREAM */}
      {activeTab === "DELIBERATION" && (
        <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900/30 font-mono text-xs">
          <div className="px-5 py-3 border-b border-zinc-800 bg-zinc-900/50 flex items-center justify-between">
            <span>STRUCTURED CTDE MESSAGE PASSING PROTOCOL</span>
            <span className="text-emerald-400 font-bold">CONSENSUS SCORE: 0.94</span>
          </div>
          <div className="p-5 space-y-3">
            {messages.map((m) => (
              <div
                key={m.message_id}
                className={`border rounded-xl p-4 transition ${
                  m.phase === "SYNTHESIS"
                    ? "border-emerald-800/80 bg-emerald-950/20"
                    : "border-zinc-800/80 bg-zinc-950/90"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-zinc-100">{m.sender_name}</span>
                    <span className="text-zinc-500">[{m.sender_role} • {m.sender_version}]</span>
                    <span
                      className={`px-2 py-0.2 rounded text-[10px] font-bold ${
                        m.phase === "OBSERVATION"
                          ? "bg-blue-950 text-blue-400 border border-blue-800"
                          : m.phase === "CRITIQUE"
                          ? "bg-amber-950 text-amber-400 border border-amber-800"
                          : m.phase === "PROPOSAL"
                          ? "bg-purple-950 text-purple-400 border border-purple-800"
                          : "bg-emerald-950 text-emerald-400 border border-emerald-800"
                      }`}
                    >
                      {m.phase}
                    </span>
                  </div>
                  <span className="text-zinc-500">{m.timestamp}</span>
                </div>
                <p className="text-sm text-zinc-200 font-sans mt-2 leading-relaxed">{m.content}</p>
                <div className="flex items-center gap-2 text-[10px] text-zinc-500 mt-2.5 pt-2 border-t border-zinc-800/60">
                  <span className="font-bold text-zinc-400">EVIDENCE CITED:</span>
                  {m.evidence_refs.map((ref) => (
                    <span key={ref} className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800">
                      {ref}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: 4-FAMILY DOMAIN HIERARCHY */}
      {activeTab === "TOPOLOGY" && (
        <div className="grid grid-cols-2 gap-4 font-mono text-xs">
          {domainFamilies.map((f) => (
            <div key={f.group} className={`p-4 border rounded-xl space-y-3 ${f.color}`}>
              <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
                <span className="font-bold uppercase tracking-wider">{f.name}</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 font-bold">
                  {f.agents.length} SPECIALISTS
                </span>
              </div>
              <div className="space-y-2">
                {f.agents.map((a) => (
                  <div key={a.id} className="p-2.5 bg-zinc-900/60 border border-zinc-800/60 rounded flex items-center justify-between">
                    <div>
                      <div className="font-bold text-zinc-200">{a.name}</div>
                      <div className="text-[10px] text-zinc-400 mt-0.5">{a.role}</div>
                    </div>
                    <span className="text-[10px] font-bold text-emerald-400">{a.status}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TAB 4: CAPABILITY MANIFESTS & VETO RULES */}
      {activeTab === "MANIFESTS" && (
        <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900/30 font-mono text-xs">
          <div className="px-5 py-3 border-b border-zinc-800 bg-zinc-900/50 flex items-center justify-between">
            <span>AGENT CAPABILITY MANIFESTS & EXECUTION BOUNDARIES</span>
            <span className="text-zinc-400 text-[10px]">17 ACTIVE SPECIFICATIONS</span>
          </div>
          <div className="p-4 divide-y divide-zinc-800/60">
            <div className="py-2.5 flex items-center justify-between">
              <div>
                <strong className="text-zinc-200">Compliance Agent (Group B2)</strong>
                <p className="text-zinc-400 text-[11px] font-sans">Holds authoritative VETO power over execution on sanctions or blacklist violations.</p>
              </div>
              <span className="px-2 py-0.5 rounded bg-red-950 border border-red-800 text-red-400 text-[10px] font-bold">
                HARD VETO AUTHORITY: YES
              </span>
            </div>
            <div className="py-2.5 flex items-center justify-between">
              <div>
                <strong className="text-zinc-200">Finance Validation Agent (Group B3)</strong>
                <p className="text-zinc-400 text-[11px] font-sans">Blocks actions exceeding departmental budget limits ($1,500 auto-approval ceiling).</p>
              </div>
              <span className="px-2 py-0.5 rounded bg-amber-950 border border-amber-800 text-amber-400 text-[10px] font-bold">
                BUDGET GATE: ENFORCED
              </span>
            </div>
            <div className="py-2.5 flex items-center justify-between">
              <div>
                <strong className="text-zinc-200">All Analytical & Specialist Agents (Groups A, C, D)</strong>
                <p className="text-zinc-400 text-[11px] font-sans">Proposal and simulation permissions only. Zero direct execution access.</p>
              </div>
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 text-[10px] font-bold">
                DIRECT EXECUTE: FALSE
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
