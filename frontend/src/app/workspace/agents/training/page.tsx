"use client";

import React, { useState } from "react";
import Link from "next/link";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function AgentTrainingPlanePage() {
  const [selectedAgent, setSelectedAgent] = useState("capacity_booking_agent");
  const [epochs, setEpochs] = useState(15);
  const [computeBudget, setComputeBudget] = useState(25.0);
  const [isTraining, setIsTraining] = useState(false);

  const trainingHistory = [
    {
      run_id: "RUN_2026_08_14",
      agent: "capacity_booking_agent (v4.2)",
      dataset: "ds_logistics_2026_08 (14,200 episodes)",
      loss: "0.042 (-18.2%)",
      status: "QUALIFIED",
      epochs: 15,
      cost_usd: 18.5,
    },
    {
      run_id: "RUN_2026_08_11",
      agent: "load_planning_agent (v4.5)",
      dataset: "ds_3d_cubing_2026 (22,000 pallets)",
      loss: "0.019 (-24.1%)",
      status: "QUALIFIED",
      epochs: 20,
      cost_usd: 24.0,
    },
  ];

  const handleStartTraining = () => {
    setIsTraining(true);
    setTimeout(() => {
      setIsTraining(false);
    }, 2000);
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Centralized Training Plane & Offline Replay</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Train specialized domain agents using Centralized Training & Decentralized Execution (CTDE) with counterfactual loss.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/workspace/agents/evaluations"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            Promotion Gates →
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Left: Configuration Form */}
        <div className="p-5 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-4 font-mono text-xs">
          <div className="font-bold text-zinc-100 uppercase border-b border-zinc-800 pb-2">
            Configure Training Run
          </div>

          <div className="space-y-1.5">
            <label className="text-zinc-400">Target Domain Specialist</label>
            <select
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-200"
            >
              <option value="capacity_booking_agent">Capacity Booking Agent (Group A1)</option>
              <option value="carrier_negotiation_agent">Carrier Negotiation Agent (Group A2)</option>
              <option value="load_planning_agent">Load Planning Agent (Group C1)</option>
              <option value="supplier_discovery_agent">Supplier Discovery Agent (Group D1)</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-zinc-400">Training Epochs</label>
            <input
              type="number"
              value={epochs}
              onChange={(e) => setEpochs(Number(e.target.value))}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-200"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-zinc-400">Max Compute Budget (USD)</label>
            <input
              type="number"
              value={computeBudget}
              onChange={(e) => setComputeBudget(Number(e.target.value))}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-2.5 py-1.5 text-zinc-200"
            />
          </div>

          <button
            onClick={handleStartTraining}
            disabled={isTraining}
            className="w-full mt-2 py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold transition flex items-center justify-center gap-2"
          >
            <span>{isTraining ? "⚡ Training in Progress..." : "▶ Launch Centralized Training Run"}</span>
          </button>
        </div>

        {/* Right 2 Columns: Training Run History */}
        <div className="col-span-2 space-y-3 font-mono text-xs">
          <div className="font-bold text-zinc-400 uppercase tracking-wider">Historical Training Runs & Loss Curves</div>
          {trainingHistory.map((r) => (
            <div key={r.run_id} className="p-4 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-zinc-100">{r.run_id} • {r.agent}</span>
                <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold text-[10px]">
                  {r.status}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400 font-sans">{r.dataset}</div>
              <div className="flex items-center justify-between text-[11px] pt-2 border-t border-zinc-800/80 text-zinc-400">
                <span>Loss: <strong className="text-emerald-400">{r.loss}</strong></span>
                <span>Epochs: <strong className="text-zinc-200">{r.epochs}</strong></span>
                <span>Cost: <strong className="text-zinc-200">${r.cost_usd.toFixed(2)}</strong></span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
