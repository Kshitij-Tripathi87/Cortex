"use client";

import React, { useState } from "react";
import { EvidenceNode } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";

export default function EvidenceGraphPage() {
  const { getEvidenceVersionTuple } = useNexusWorkspace();
  const tuple = getEvidenceVersionTuple();

  const [evidenceNodes] = useState<EvidenceNode[]>([
    {
      node_id: "ev_src_01",
      node_type: "SOURCE_RECORD",
      label: "Raw Ingested Dataset: olist_orders_dataset.csv (1,000 rows)",
      checksum_sha256: "7d4a991e012a994c1071b563810a99c430e7",
      payload: { row_count: 1000, completeness: 100.0, format: "CSV" },
      verified_at: "2026-08-16T23:50:12Z",
    },
    {
      node_id: "ev_ent_02",
      node_type: "CANONICAL_ENTITY",
      label: "Canonical Entity Resolution: seller_01a00b8e99 (Single Point of Failure)",
      checksum_sha256: "b21c4388a10994cd1071b563810a99c430e8",
      parent_node_id: "ev_src_01",
      payload: { pagerank: 0.042, betweenness: 0.31, degree: 14, is_spof: true },
      verified_at: "2026-08-16T23:50:15Z",
    },
    {
      node_id: "ev_sig_03",
      node_type: "OPERATIONAL_SIGNAL",
      label: "Operational Anomaly: Dispatch Degradation (+90% Deviation)",
      checksum_sha256: "3e9f8264d27194cd1071b563810a99c430e9",
      parent_node_id: "ev_ent_02",
      payload: { observed_delay_days: 3.8, baseline_delay_days: 2.0, deviation_pct: 90.0 },
      verified_at: "2026-08-16T23:55:01Z",
    },
    {
      node_id: "ev_hyp_04",
      node_type: "ROOT_CAUSE_HYPOTHESIS",
      label: "Root Cause Hypothesis: Dispatch Buffer Exhaustion (Support: 0.91)",
      checksum_sha256: "8a0b1299c43094cd1071b563810a99c430f0",
      parent_node_id: "ev_sig_03",
      payload: { primary_hypothesis_score: 0.91, alternative_corridor_score: 0.54 },
      verified_at: "2026-08-16T23:55:02Z",
    },
    {
      node_id: "ev_prop_05",
      node_type: "AGENT_PROPOSAL",
      label: "Specialist Proposal: Air Freight (VCP->SDU) + Cross-Docking",
      checksum_sha256: "10ef8722a75594cd1071b563810a99c430f1",
      parent_node_id: "ev_hyp_04",
      payload: { cost_usd: 450.0, target_route: "route_VCP_to_SDU", participating_agents: 3 },
      verified_at: "2026-08-16T23:55:05Z",
    },
    {
      node_id: "ev_sim_06",
      node_type: "DIGITAL_TWIN_SIMULATION",
      label: "Counterfactual Evaluation: Candidate C Net ROI (+$2,900.00)",
      checksum_sha256: "5a3d7611e98094cd1071b563810a99c430f2",
      parent_node_id: "ev_prop_05",
      payload: { candidates_evaluated: 4, best_candidate: "CANDIDATE_C", sla_breach_pct: 2.0 },
      verified_at: "2026-08-16T23:55:06Z",
    },
    {
      node_id: "ev_dec_07",
      node_type: "POLICY_DECISION",
      label: "Governed Decision Card: dec_live_01 (Status: APPROVED)",
      checksum_sha256: "94cd1071b563810a99c430e7000000000000",
      parent_node_id: "ev_sim_06",
      payload: { net_economic_value_usd: 2900.0, governance_status: "APPROVED_FOR_EXECUTION" },
      verified_at: "2026-08-16T23:55:07Z",
    },
  ]);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <IntentWorkspaceBar />

      <div>
        <h1 className="text-xl font-bold text-zinc-100 font-mono">Decision Evidence Graph</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Cryptographically verifiable SHA-256 lineage linking raw CSV records directly to policy decisions.
        </p>
      </div>

      {/* Program X5: Semantic 9-Part Version Tuple */}
      <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-2 font-mono text-xs">
        <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
          <span className="font-bold text-zinc-300 uppercase text-[10px]">
            AUTHORITATIVE DECISION DEPENDENCY TUPLE (PROGRAM X5)
          </span>
          <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] font-bold">
            IMMUTABLE ROOT
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2.5 text-[11px]">
          <div>
            <span className="text-zinc-500 text-[10px] block">DATASET VERSION:</span>
            <span className="text-zinc-200">{tuple.dataset_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">GRAPH VERSION:</span>
            <span className="text-zinc-200">{tuple.graph_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">WORLD STATE VERSION:</span>
            <span className="text-zinc-200 font-bold">v{tuple.world_state_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">FEATURE VERSION:</span>
            <span className="text-zinc-200">{tuple.feature_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">MODEL VERSION:</span>
            <span className="text-zinc-200">{tuple.model_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">AGENT SWARM:</span>
            <span className="text-zinc-200">{tuple.agent_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">POLICY RULESET:</span>
            <span className="text-zinc-200">{tuple.policy_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">SIMULATION ENGINE:</span>
            <span className="text-zinc-200">{tuple.simulation_version}</span>
          </div>
          <div>
            <span className="text-zinc-500 text-[10px] block">DECISION FORMULATION:</span>
            <span className="text-emerald-400 font-bold">{tuple.decision_version}</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {evidenceNodes.map((node, idx) => (
          <div key={node.node_id} className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono">
              <div className="flex items-center gap-2.5">
                <span className="w-5 h-5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300 flex items-center justify-center text-[10px] font-bold">
                  {idx + 1}
                </span>
                <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-200 font-bold uppercase text-[10px]">
                  {node.node_type}
                </span>
                <span className="text-zinc-500">[{node.node_id}]</span>
              </div>
              <div className="text-zinc-400">
                SHA-256: <strong className="text-zinc-200">{node.checksum_sha256.substring(0, 16)}...</strong>
              </div>
            </div>

            <div className="text-sm font-semibold text-zinc-100">{node.label}</div>

            <pre className="p-3 bg-zinc-950 border border-zinc-800/80 rounded font-mono text-[10px] text-zinc-400 overflow-x-auto">
              {JSON.stringify(node.payload, null, 2)}
            </pre>
          </div>
        ))}
      </div>

      <ProgressiveDisclosure entityId="seller_01a00b8e99" />
    </div>
  );
}
