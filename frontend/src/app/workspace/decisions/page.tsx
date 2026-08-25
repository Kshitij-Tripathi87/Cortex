"use client";

import React, { useState } from "react";
import Link from "next/link";
import { DecisionCard } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";

export default function DecisionsPage() {
  const { isDecisionValid, invalidationReason, latestDecision } = useNexusWorkspace();

  const [decisions] = useState<DecisionCard[]>([
    {
      decision_id: "dec_live_01",
      title: "Expedited Air Freight + Cross-Docking (Candidate C)",
      target_entity_id: "seller_01a00b8e99",
      selected_candidate: "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK",
      action_summary: "Reroute 12 exposed orders via Campinas (VCP) to Santos Dumont (SDU) air corridor with Rio Hub cross-docking.",
      estimated_cost_usd: 450.0,
      net_economic_value_usd: 2900.0,
      sla_protection_pct: 98.0,
      governance_status: "APPROVED_FOR_EXECUTION",
      created_at: "2026-08-16T23:55:07Z",
      world_state_version: 101,
      graph_version: "graph_v1",
      is_valid: true,
      dependency_set: {
        dependent_entity_ids: ["seller_01a00b8e99", "route_SP_to_RJ", "order_9901", "order_9902"],
        dependent_signals: ["SELLER_DEGRADATION", "SLA_BREACH_RISK"],
        created_at_world_version: 101,
      },
    },
  ]);

  const lifecycleStages = [
    { id: "DRAFT", label: "1. Draft" },
    { id: "SIMULATED", label: "2. Simulated" },
    { id: "AWAITING_REVIEW", label: "3. Review" },
    { id: "APPROVED", label: "4. Approved" },
    { id: "EXECUTING", label: "5. Executing" },
    { id: "COMPLETED", label: "6. Verified" },
  ];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <IntentWorkspaceBar />

      <div>
        <h1 className="text-xl font-bold text-zinc-100 font-mono">Governed Decision Cards & Policy Lifecycle</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Synthesized operational policy decisions with active dependency tracking, lifecycle audit, and automatic freshness invalidation.
        </p>
      </div>

      <div className="space-y-4">
        {decisions.map((dec) => (
          <div key={dec.decision_id} className="border border-zinc-800 rounded-xl p-6 bg-zinc-900/30 space-y-5">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <div className="text-[10px] font-mono text-zinc-500 uppercase">{dec.decision_id} • TARGET: {dec.target_entity_id}</div>
                <h3 className="text-base font-bold text-zinc-100 mt-0.5">{dec.title}</h3>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold border ${
                  isDecisionValid
                    ? "bg-emerald-950 border-emerald-800 text-emerald-400"
                    : "bg-red-950 border-red-800 text-red-400 animate-pulse"
                }`}>
                  {isDecisionValid ? dec.governance_status : "INVALIDATED"}
                </span>
                <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 text-xs font-mono">
                  {isDecisionValid ? `VALID (v${dec.world_state_version})` : "MUTATION DRIFT"}
                </span>
              </div>
            </div>

            {/* W6: Visual Decision Lifecycle Pipeline */}
            <div className="p-3 bg-zinc-950 border border-zinc-800/80 rounded-lg space-y-1.5 font-mono text-xs">
              <div className="text-[10px] text-zinc-500 uppercase font-bold">LIFECYCLE STATE PIPELINE:</div>
              <div className="flex items-center gap-2">
                {lifecycleStages.map((stage, idx) => {
                  const isCurrent = isDecisionValid && stage.id === "APPROVED";
                  const isPast = ["DRAFT", "SIMULATED", "AWAITING_REVIEW"].includes(stage.id);
                  return (
                    <React.Fragment key={stage.id}>
                      <span
                        className={`px-2.5 py-1 rounded text-[10px] ${
                          isCurrent
                            ? "bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold"
                            : isPast
                            ? "bg-zinc-900 text-zinc-300 border border-zinc-800"
                            : "text-zinc-600 bg-zinc-950"
                        }`}
                      >
                        {stage.label}
                      </span>
                      {idx < lifecycleStages.length - 1 && <span className="text-zinc-700">→</span>}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>

            <p className="text-sm text-zinc-300">{dec.action_summary}</p>

            <div className="grid grid-cols-3 gap-3 p-3.5 bg-zinc-950 border border-zinc-800 rounded-lg text-center font-mono text-xs">
              <div>
                <div className="text-[10px] text-zinc-500">INTERVENTION COST</div>
                <div className="text-sm font-bold text-zinc-200 mt-0.5">${dec.estimated_cost_usd.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-500">SLA COMPLIANCE</div>
                <div className="text-sm font-bold text-emerald-400 mt-0.5">{dec.sla_protection_pct}%</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-500">NET ECONOMIC VALUE</div>
                <div className="text-sm font-bold text-emerald-400 mt-0.5">+${dec.net_economic_value_usd.toFixed(2)}</div>
              </div>
            </div>

            {/* Dependency Set */}
            <div className="text-[11px] font-mono text-zinc-500 space-y-1">
              <div>DECISION DEPENDENCY SET:</div>
              <div className="text-zinc-400">
                Entities: [{dec.dependency_set?.dependent_entity_ids.join(", ")}] • Signals: [{dec.dependency_set?.dependent_signals.join(", ")}]
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <Link
                href="/workspace/cockpit"
                className="text-xs font-mono text-zinc-400 hover:text-zinc-200 transition"
              >
                ← Open in Incident Cockpit
              </Link>
              <Link
                href="/workspace/evidence"
                className="px-3.5 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-mono transition"
              >
                Inspect Cryptographic Evidence Tree →
              </Link>
            </div>
          </div>
        ))}
      </div>

      <ProgressiveDisclosure entityId="seller_01a00b8e99" decision={decisions[0]} />
    </div>
  );
}
