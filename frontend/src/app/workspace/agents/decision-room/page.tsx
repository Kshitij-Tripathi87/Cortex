"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AgentMessageEnvelope } from "@/types/nexus";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export default function DecisionRoomFullPage() {
  const { worldStateVersion, redeliberate } = useNexusWorkspace();
  const [isDeliberating, setIsDeliberating] = useState(false);
  const [phaseFilter, setPhaseFilter] = useState<string>("ALL");

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

  const filteredMessages = phaseFilter === "ALL" ? messages : messages.filter((m) => m.phase === phaseFilter);

  const handleRunDeliberation = async () => {
    setIsDeliberating(true);
    try {
      await redeliberate();
    } finally {
      setIsDeliberating(false);
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">CTDE Protocol Deliberation Room</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Real-time Centralized Training & Decentralized Execution message stream with citations and consensus tracking.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRunDeliberation}
            disabled={isDeliberating}
            className="px-4 py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold font-mono text-xs transition shadow-lg"
          >
            {isDeliberating ? "⚡ Deliberating..." : "▶ Trigger Swarm Deliberation"}
          </button>
        </div>
      </div>

      {/* Phase Filter Bar */}
      <div className="flex items-center gap-2 border-b border-zinc-800 pb-3 text-xs font-mono">
        {["ALL", "OBSERVATION", "PROPOSAL", "CRITIQUE", "SYNTHESIS"].map((phase) => (
          <button
            key={phase}
            onClick={() => setPhaseFilter(phase)}
            className={`px-3 py-1 rounded transition ${
              phaseFilter === phase
                ? "bg-zinc-800 text-white font-bold border border-zinc-700"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {phase} {phase !== "ALL" && `(${messages.filter((m) => m.phase === phase).length})`}
          </button>
        ))}
      </div>

      {/* Message Stream */}
      <div className="space-y-3 font-mono text-xs">
        {filteredMessages.map((m) => (
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
  );
}
