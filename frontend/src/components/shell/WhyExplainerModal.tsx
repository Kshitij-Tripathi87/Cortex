"use client";

import React from "react";
import Link from "next/link";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { WhySubject } from "@/types/nexus";

interface WhyExplainerModalProps {
  isOpen: boolean;
  subject: WhySubject | null;
  onClose: () => void;
}

export const WhyExplainerModal: React.FC<WhyExplainerModalProps> = ({
  isOpen,
  subject,
  onClose,
}) => {
  const { worldStateVersion, setGraphMode } = useNexusWorkspace();

  if (!isOpen || !subject) return null;

  const explainerContent: Record<
    WhySubject,
    {
      title: string;
      subtitle: string;
      question: string;
      primaryReason: string;
      dataProof: { label: string; value: string; note: string }[];
      modelRationale: string;
      actionLink?: { href: string; label: string; mode?: string };
    }
  > = {
    SIGNAL: {
      title: "Why This Signal Was Triggered",
      subtitle: "Anomaly Threshold & Graph SPOF Detection",
      question: "Why did Nexus raise SELLER_DEGRADATION (+90%)?",
      primaryReason:
        "Observed dispatch latency of 3.8 days exceeds the 3-sigma baseline (2.0 days) by +90.0%. Because seller_01a00b8e99 is an authoritative Single Point of Failure (PageRank 0.042, Degree 14), latency propagation threatens 12 downstream customer shipments.",
      dataProof: [
        { label: "Raw Data Record", value: "olist_sellers_dataset.csv (Row #482)", note: "Canonical key: seller_id:01a00b8e99" },
        { label: "Centrality Metric", value: "PageRank: 0.042 (Top 1.2%)", note: "Betweenness: 0.31, Degree: 14" },
        { label: "Temporal Baseline", value: "2.0d SLA Normal", note: "Observed: 3.8d (+1.8d breach)" },
      ],
      modelRationale:
        "The GNN Anomaly Detector identified a topological bottleneck where 85.7% of corridor orders pass through a single warehouse dispatch queue without active failover buffers.",
      actionLink: { href: "/workspace/graph", label: "Inspect Signal in Graph Risk Mode →", mode: "RISK" },
    },
    AGENT: {
      title: "Why This Specialist Agent Was Selected",
      subtitle: "Multi-Agent Role Assignment & Context Package",
      question: "Why did the Logistics Routing Specialist (v4) lead deliberation?",
      primaryReason:
        "The incident was classified as an INTER-REGIONAL CORRIDOR BOTTLENECK (Highway BR-116). The Logistics Specialist has domain authority over air freight rate cards and multimodal handoffs between São Paulo (VCP) and Rio de Janeiro (SDU).",
      dataProof: [
        { label: "Agent Role", value: "LOGISTICS_ROUTING (v4)", note: "Specialist in multimodal carrier dispatch" },
        { label: "Context Scope", value: "14 Graph Nodes (2-hop)", note: "Pinned to World State v101" },
        { label: "Consensus Score", value: "0.94 (Multi-Agent Agreement)", note: "Supervisor + Risk Analyst verified" },
      ],
      modelRationale:
        "Agent prompt context was enriched with live rate cards ($450.00 expedited air freight) and warehouse buffer ledgers (Rio Hub: 50 units safety stock).",
      actionLink: { href: "/workspace/agents", label: "Open Agent Deliberation Room →" },
    },
    SCENARIO: {
      title: "Why This Scenario Was Formulated",
      subtitle: "Digital Twin Counterfactual Sandbox",
      question: "Why was Candidate C (Air Expedite + Cross-Dock) prioritized?",
      primaryReason:
        "Highway trucking (Candidate B) is blocked by +1.4 days of regional corridor congestion. Dedicated air transport directly bypasses Highway BR-116, dropping transit latency from 4.8 days down to 0.5 days.",
      dataProof: [
        { label: "Air Corridor Route", value: "route_VCP_to_SDU (Campinas -> Santos Dumont)", note: "Carrier capacity verified" },
        { label: "Regional Cross-Dock", value: "Rio Hub Terminal 2", note: "Cross-dock turnaround: 2.5 hours" },
        { label: "Operational Cost", value: "$450.00 USD", note: "Fixed expedited freight tariff" },
      ],
      modelRationale:
        "Digital Twin Monte Carlo simulation evaluated 1,000 potential disruptions and determined Candidate C has a 98.0% probability of preserving customer SLA commitments.",
      actionLink: { href: "/workspace/scenarios", label: "Inspect Scenario Matrix →" },
    },
    RECOMMENDATION: {
      title: "Why This Recommendation Was Approved",
      subtitle: "Net Economic Value (NEV) Dominance",
      question: "Why does Candidate C dominate all other options?",
      primaryReason:
        "Candidate C achieves a Net Economic Value of +$2,900.00 USD (Revenue Protected: $3,350.00 - Cost: $450.00). It protects 98.0% of exposed orders compared to only 12.0% protection under the Status Quo.",
      dataProof: [
        { label: "Net Economic ROI", value: "+$2,900.00 USD", note: "Protects $3,350.00 revenue at $450.00 cost" },
        { label: "SLA Protection", value: "98.0% On-Time Delivery", note: "Status Quo yields 88.0% breach" },
        { label: "Cryptographic DAG", value: "SHA-256: 5a3d7611e980...", note: "Immutable evidence root verified" },
      ],
      modelRationale:
        "All corporate governance and spend policies were validated against policy ruleset POL-LOG-2026 before recommendation formulation.",
      actionLink: { href: "/workspace/evidence", label: "Verify Evidence DAG →" },
    },
    INVALIDATION: {
      title: "Why This Decision Was Invalidated",
      subtitle: "Dynamic World State Mutation & Drift",
      question: "Why was the approved decision invalidated?",
      primaryReason:
        `World State mutated from v${worldStateVersion - 1} to v${worldStateVersion}. A real-time telemetry event modified the state of seller_01a00b8e99, breaking the freshness guarantees of the previously approved decision (dec_live_01).`,
      dataProof: [
        { label: "World State Drift", value: `v${worldStateVersion - 1} ➔ v${worldStateVersion}`, note: "Mutation event injected" },
        { label: "Dependent Entity", value: "seller_01a00b8e99", note: "State changed in graph memory" },
        { label: "Policy Guard", value: "ZERO_STALE_TOLERANCE", note: "Automated freshness invalidator" },
      ],
      modelRationale:
        "Nexus refuses to execute decisions when the underlying operational graph no longer matches the snapshot at which deliberation and simulation took place.",
      actionLink: { href: "/workspace/cockpit", label: "Trigger Swarm Redeliberation →" },
    },
  };

  const current = explainerContent[subject];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 animate-fadeIn">
      <div className="w-full max-w-2xl bg-zinc-950 border border-zinc-700/80 rounded-xl shadow-2xl overflow-hidden font-mono text-zinc-100 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-zinc-800 bg-zinc-900/60">
          <div>
            <span className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider block">
              DATA-FIRST REASONING EXPLAINER
            </span>
            <h2 className="text-sm font-bold text-zinc-100 mt-0.5">{current.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white flex items-center justify-center text-xs transition"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Question & Primary Reason */}
          <div className="p-3.5 bg-zinc-900/40 border border-zinc-800 rounded-lg space-y-1.5">
            <div className="text-xs font-bold text-emerald-400 font-sans">{current.question}</div>
            <p className="text-xs text-zinc-300 font-sans leading-relaxed">{current.primaryReason}</p>
          </div>

          {/* Hard Data Proof & Lineage */}
          <div className="space-y-2">
            <div className="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">
              AUTHORITATIVE DATA PROOF & PROVENANCE
            </div>
            <div className="grid grid-cols-3 gap-2">
              {current.dataProof.map((item, idx) => (
                <div key={idx} className="p-2.5 bg-zinc-950 border border-zinc-800 rounded text-xs space-y-1">
                  <div className="text-[9px] text-zinc-500 uppercase">{item.label}</div>
                  <div className="font-bold text-zinc-100 text-[11px] truncate">{item.value}</div>
                  <div className="text-[9px] text-zinc-400">{item.note}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Model Rationale */}
          <div className="p-3 bg-zinc-900/30 border border-zinc-800/80 rounded-lg space-y-1 text-xs">
            <div className="text-[10px] text-zinc-400 uppercase font-bold">ALGORITHMIC / POLICY RATIONALE</div>
            <p className="text-zinc-300 text-[11px] font-sans leading-tight">{current.modelRationale}</p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-zinc-800 bg-zinc-900/30 text-xs">
          <span className="text-[10px] text-zinc-500">Cryptographically verifiable proof DAG</span>
          <div className="flex items-center gap-2">
            {current.actionLink && (
              <Link
                href={current.actionLink.href}
                onClick={() => {
                  if (current.actionLink?.mode) setGraphMode(current.actionLink.mode as any);
                  onClose();
                }}
                className="px-3 py-1.5 rounded bg-zinc-100 hover:bg-white text-zinc-950 font-bold text-xs transition"
              >
                {current.actionLink.label}
              </Link>
            )}
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
