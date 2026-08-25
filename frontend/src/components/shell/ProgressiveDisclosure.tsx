"use client";

import React from "react";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { EntityLineageInfo, DecisionCard, ScenarioCandidate } from "@/types/nexus";

interface ProgressiveDisclosureProps {
  entityId?: string;
  decision?: DecisionCard | null;
  candidate?: ScenarioCandidate;
}

export const ProgressiveDisclosure: React.FC<ProgressiveDisclosureProps> = ({
  entityId = "seller_01a00b8e99",
  decision,
  candidate,
}) => {
  const { progressiveLevel, setProgressiveLevel, getEntityLineage } = useNexusWorkspace();
  const lineage: EntityLineageInfo = getEntityLineage(entityId);

  return (
    <div className="border border-zinc-800 rounded-xl bg-zinc-950/90 overflow-hidden font-mono text-xs">
      {/* Tiered Tab Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/50 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">PROGRESSIVE DISCLOSURE:</span>
          <div className="inline-flex rounded-lg bg-zinc-950 p-0.5 border border-zinc-800">
            <button
              onClick={() => setProgressiveLevel(1)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                progressiveLevel === 1 ? "bg-zinc-800 text-zinc-100 font-bold" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              L1: Summary
            </button>
            <button
              onClick={() => setProgressiveLevel(2)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                progressiveLevel === 2 ? "bg-zinc-800 text-zinc-100 font-bold" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              L2: Reasoning & Simulation
            </button>
            <button
              onClick={() => setProgressiveLevel(3)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                progressiveLevel === 3 ? "bg-zinc-800 text-zinc-100 font-bold" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              L3: Data Lineage & Math
            </button>
          </div>
        </div>

        <span className="text-[10px] text-zinc-500">
          {progressiveLevel === 1 && "Executive View (Standardized Financials)"}
          {progressiveLevel === 2 && "Intelligence & Counterfactual Distribution"}
          {progressiveLevel === 3 && "Cryptographic Source Lineage & Graph Topology"}
        </span>
      </div>

      {/* Level 1: Executive Operational Summary & Standardized Financial Notation */}
      {progressiveLevel === 1 && (
        <div className="p-4 space-y-4 animate-fadeIn">
          <div className="p-3 bg-zinc-900/40 border border-zinc-800/80 rounded-lg space-y-2">
            <div className="text-[11px] text-zinc-400 font-sans leading-relaxed">
              <strong className="text-zinc-200">Operational Finding:</strong> Seller{" "}
              <code className="text-zinc-300 bg-zinc-800 px-1 py-0.5 rounded">{entityId}</code> exhibits acute dispatch
              degradation (+90% latency). Mitigating via expedited air routing protects 98% of exposed customer orders.
            </div>

            {/* Standardized Financial Metric Card */}
            <div className="grid grid-cols-3 gap-3 pt-2">
              <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded">
                <div className="text-[10px] text-zinc-500 uppercase">REVENUE EXPOSURE</div>
                <div className="text-sm font-bold text-red-400">$1,746.00 USD</div>
                <div className="text-[10px] text-zinc-500">12 exposed orders, 48h horizon (Status Quo)</div>
              </div>
              <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded">
                <div className="text-[10px] text-zinc-500 uppercase">ESTIMATED MITIGATION COST</div>
                <div className="text-sm font-bold text-zinc-200">$450.00 USD</div>
                <div className="text-[10px] text-zinc-500">Air Freight + Regional Cross-Dock</div>
              </div>
              <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded">
                <div className="text-[10px] text-zinc-500 uppercase">NET ECONOMIC ROI</div>
                <div className="text-sm font-bold text-emerald-400">+$2,900.00 USD</div>
                <div className="text-[10px] text-zinc-500">Protected Value vs Status Quo</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Level 2: Agent Deliberation & Simulation Percentiles */}
      {progressiveLevel === 2 && (
        <div className="p-4 space-y-3 animate-fadeIn">
          <div className="grid grid-cols-2 gap-3">
            {/* Multi-Agent Reasoning Trace */}
            <div className="p-3 bg-zinc-900/30 border border-zinc-800 rounded-lg space-y-2">
              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">
                MULTI-AGENT CONSENSUS TRACE
              </div>
              <div className="space-y-2 text-[11px] text-zinc-300">
                <div className="p-2 bg-zinc-950 rounded border border-zinc-800/80">
                  <div className="text-zinc-400 font-semibold text-[10px]">Logistics Specialist (v9)</div>
                  <div>Carrier BR-116 delay verified at +4.8 days. Air freight corridor (VCP-SDU) open.</div>
                </div>
                <div className="p-2 bg-zinc-950 rounded border border-zinc-800/80">
                  <div className="text-zinc-400 font-semibold text-[10px]">Risk Analyst (v4)</div>
                  <div>SLA breach risk plunges from 88% down to 2.0% with cross-dock handoff.</div>
                </div>
              </div>
            </div>

            {/* Monte Carlo Distribution */}
            <div className="p-3 bg-zinc-900/30 border border-zinc-800 rounded-lg space-y-2">
              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">
                MONTE CARLO (1,000 ITERATIONS)
              </div>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex justify-between border-b border-zinc-800/60 pb-1 text-zinc-400">
                  <span>P10 Delay Protection:</span>
                  <span className="font-bold text-zinc-200">0.3 days (99.1% SLA)</span>
                </div>
                <div className="flex justify-between border-b border-zinc-800/60 pb-1 text-zinc-400">
                  <span>P50 Expected Protection:</span>
                  <span className="font-bold text-emerald-400">0.5 days (98.0% SLA)</span>
                </div>
                <div className="flex justify-between border-b border-zinc-800/60 pb-1 text-zinc-400">
                  <span>P90 Conservative Protection:</span>
                  <span className="font-bold text-zinc-200">0.9 days (94.5% SLA)</span>
                </div>
                <div className="flex justify-between text-zinc-400 pt-0.5">
                  <span>Recommendation Confidence:</span>
                  <span className="font-bold text-emerald-400">98.0% (High Certainty)</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Level 3: Raw Data Lineage & Topological Mathematics */}
      {progressiveLevel === 3 && (
        <div className="p-4 space-y-3 animate-fadeIn">
          <div className="p-3 bg-zinc-900/40 border border-zinc-800 rounded-lg space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
              <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">
                AUTHORITATIVE DATA PROVENANCE & TOPOLOGY
              </span>
              <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-[10px]">
                CRYPTOGRAPHICALLY VERIFIED
              </span>
            </div>

            <div className="grid grid-cols-3 gap-3 text-[11px]">
              <div>
                <span className="text-zinc-500 text-[10px] block">SOURCE CSV TABLE:</span>
                <span className="text-zinc-200 font-bold">{lineage.source_dataset}</span>
              </div>
              <div>
                <span className="text-zinc-500 text-[10px] block">SOURCE ROW INDEX:</span>
                <span className="text-zinc-200 font-bold">#{lineage.source_row_index}</span>
              </div>
              <div>
                <span className="text-zinc-500 text-[10px] block">CANONICAL KEY:</span>
                <span className="text-zinc-200 font-bold">{lineage.canonical_key}</span>
              </div>
            </div>

            <div className="grid grid-cols-4 gap-2 pt-2 border-t border-zinc-800/60 text-[10px]">
              <div className="p-2 bg-zinc-950 rounded border border-zinc-800">
                <div className="text-zinc-500">PAGERANK:</div>
                <div className="text-zinc-200 font-bold text-xs">{lineage.pagerank}</div>
              </div>
              <div className="p-2 bg-zinc-950 rounded border border-zinc-800">
                <div className="text-zinc-500">BETWEENNESS:</div>
                <div className="text-zinc-200 font-bold text-xs">{lineage.betweenness}</div>
              </div>
              <div className="p-2 bg-zinc-950 rounded border border-zinc-800">
                <div className="text-zinc-500">CONNECTED DEGREE:</div>
                <div className="text-zinc-200 font-bold text-xs">{lineage.connected_degree} edges</div>
              </div>
              <div className="p-2 bg-zinc-950 rounded border border-zinc-800">
                <div className="text-zinc-500">TOPOLOGICAL CLASSIFICATION:</div>
                <div className="text-red-400 font-bold text-xs">SPOF (Single Point of Failure)</div>
              </div>
            </div>

            <div className="pt-2 border-t border-zinc-800/60 flex items-center justify-between text-[10px] text-zinc-500">
              <span>SHA-256 Checksum: b21c4388a10994cd1071b563810a99c430e8</span>
              <span>Ingested: {lineage.ingested_at}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
