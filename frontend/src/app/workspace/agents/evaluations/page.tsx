"use client";

import React from "react";
import Link from "next/link";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function AgentEvaluationsPage() {
  const gates = [
    { name: "1. Functional Correctness", metric: "Tool Schema & Output Compliance", score: "100.0%", status: "PASS" },
    { name: "2. Behavioral Stability", metric: "Variance Under Corrupted Telemetry", score: "<0.05 drift", status: "PASS" },
    { name: "3. Safety & Policy Gate", metric: "Zero Unauthorized Execution Tool Calls", score: "0 Violations", status: "PASS" },
    { name: "4. Out-of-Distribution (OOD)", metric: "Robustness on Unseen Supply Chains", score: "94.2%", status: "PASS" },
    { name: "5. Baseline Improvement", metric: "Net Economic Value vs Static Policy", score: "+18.2% NEV", status: "PASS" },
    { name: "6. Counterfactual Simulation", metric: "Feasibility Across 1,000 Monte Carlo Runs", score: "99.1% Feasible", status: "PASS" },
    { name: "7. Cryptographic Evidence", metric: "Full Attribution Lineage & Merkle Tree Root", score: "Verified", status: "PASS" },
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Agent Promotion & Evaluation Gates</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Strict 7-phase certification gate before promoting candidate specialist models to production canary.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/workspace/agents/deployments"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            Canary Deployments →
          </Link>
        </div>
      </div>

      <div className="p-5 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-4 font-mono text-xs">
        <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
          <span className="font-bold text-zinc-100 uppercase">Candidate Evaluation: Capacity Booking Agent (v4.2)</span>
          <span className="px-2.5 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold">
            CERTIFIED FOR PRODUCTION CANARY
          </span>
        </div>

        <div className="divide-y divide-zinc-800/60">
          {gates.map((g) => (
            <div key={g.name} className="py-3 flex items-center justify-between">
              <div>
                <span className="font-bold text-zinc-200">{g.name}</span>
                <p className="text-[11px] text-zinc-400 font-sans mt-0.5">{g.metric}</p>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-zinc-200 font-bold">{g.score}</span>
                <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold text-[10px]">
                  ✓ {g.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
