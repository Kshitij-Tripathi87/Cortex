"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ScenarioCandidate } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";

export default function ScenariosPage() {
  const { setGraphMode, setSelectedCandidateId } = useNexusWorkspace();

  const [candidates] = useState<ScenarioCandidate[]>([
    {
      candidate_id: "CANDIDATE_A_DO_NOTHING",
      name: "Candidate A: Status Quo",
      action_type: "Do Nothing (No Intervention)",
      predicted_delay_days: 4.8,
      sla_breach_pct: 88.0,
      operational_cost_usd: 0.0,
      revenue_protected_usd: 0.0,
      net_economic_value_usd: -4200.0,
      is_optimal_choice: false,
      confidence_pct: 95.0,
    },
    {
      candidate_id: "CANDIDATE_B_GREEDY_REROUTE",
      name: "Candidate B: Dedicated Trucking",
      action_type: "Reroute via Highway BR-116 Dedicated Trucking",
      predicted_delay_days: 2.1,
      sla_breach_pct: 25.0,
      operational_cost_usd: 1200.0,
      revenue_protected_usd: 2500.0,
      net_economic_value_usd: 1300.0,
      is_optimal_choice: false,
      confidence_pct: 91.0,
    },
    {
      candidate_id: "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK",
      name: "Candidate C: Air Freight + Cross-Docking",
      action_type: "Expedited Air Freight (VCP->SDU) + Regional Cross-Dock",
      predicted_delay_days: 0.5,
      sla_breach_pct: 2.0,
      operational_cost_usd: 450.0,
      revenue_protected_usd: 3350.0,
      net_economic_value_usd: 2900.0,
      is_optimal_choice: true,
      confidence_pct: 98.0,
    },
    {
      candidate_id: "CANDIDATE_D_STOCK_TRANSFER",
      name: "Candidate D: Inter-Hub Stock Transfer",
      action_type: "Inter-Warehouse Safety Stock Transfer from Curitiba",
      predicted_delay_days: 1.2,
      sla_breach_pct: 15.0,
      operational_cost_usd: 850.0,
      revenue_protected_usd: 2800.0,
      net_economic_value_usd: 1950.0,
      is_optimal_choice: false,
      confidence_pct: 93.0,
    },
  ]);

  const handleSelectCandidate = (candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setGraphMode("SCENARIO");
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Digital Twin Scenario Studio</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Simulates competing futures under the exact same world state (Net Economic Value = Loss_without - Loss_with - Cost).
          </p>
        </div>
        <Link
          href="/workspace/graph"
          onClick={() => setGraphMode("SCENARIO")}
          className="px-3 py-1.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-mono font-bold hover:bg-emerald-900 transition"
        >
          Inspect Graph Scenario Overlay →
        </Link>
      </div>

      {/* Comparison Matrix Table */}
      <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900/30">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-zinc-900/80 border-b border-zinc-800 text-zinc-400 uppercase">
            <tr>
              <th className="px-5 py-3.5">Candidate Action</th>
              <th className="px-5 py-3.5">Predicted Delay</th>
              <th className="px-5 py-3.5">SLA Breach %</th>
              <th className="px-5 py-3.5">Cost ($USD)</th>
              <th className="px-5 py-3.5">Revenue Protected</th>
              <th className="px-5 py-3.5 text-right">Net Economic Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60 text-zinc-300">
            {candidates.map((c) => (
              <tr
                key={c.candidate_id}
                onClick={() => handleSelectCandidate(c.candidate_id)}
                className={`cursor-pointer transition ${c.is_optimal_choice ? "bg-emerald-950/20 hover:bg-emerald-950/30" : "hover:bg-zinc-900/50"}`}
              >
                <td className="px-5 py-4 font-bold">
                  <div className="flex items-center gap-2">
                    {c.is_optimal_choice && <span className="text-emerald-400">★</span>}
                    <span className={c.is_optimal_choice ? "text-emerald-400 font-bold" : "text-zinc-100"}>
                      {c.name}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400 font-normal font-sans mt-0.5">{c.action_type}</div>
                </td>
                <td className="px-5 py-4">{c.predicted_delay_days}d</td>
                <td className="px-5 py-4">{c.sla_breach_pct}%</td>
                <td className="px-5 py-4">${c.operational_cost_usd.toFixed(2)}</td>
                <td className="px-5 py-4">${c.revenue_protected_usd.toFixed(2)}</td>
                <td className={`px-5 py-4 text-right font-bold text-sm ${c.net_economic_value_usd > 0 ? "text-emerald-400" : "text-red-400"}`}>
                  ${c.net_economic_value_usd.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between items-center text-xs font-mono text-zinc-400 pt-2">
        <span>Click any candidate row to preview in Operational Graph Scenario Mode.</span>
        <Link
          href="/workspace/decisions"
          className="px-4 py-2 rounded bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs font-sans transition"
        >
          View Governed Decision Card →
        </Link>
      </div>

      <ProgressiveDisclosure entityId="seller_01a00b8e99" candidate={candidates[2]} />
    </div>
  );
}
