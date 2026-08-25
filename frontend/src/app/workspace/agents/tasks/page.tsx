"use client";

import React, { useState } from "react";
import Link from "next/link";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function AgentTasksPage() {
  const [selectedTask, setSelectedTask] = useState<string>("TASK_2026_001");

  const tasks = [
    {
      task_id: "TASK_2026_001",
      title: "Resolve SLA Corridor Disruption on seller_01a00b8e99",
      target_entity: "seller_01a00b8e99",
      world_state_version: 101,
      status: "COMPLETED",
      consensus_score: 0.94,
      steps_count: 5,
      completed_steps: 5,
      runtime_ms: 680,
      created_at: "23:55:01Z",
      steps: [
        { id: "s1", name: "Supplier Discovery via GNN Embeddings", domain: "PROCUREMENT", agent: "Supplier Discovery Agent (v4.2)", status: "COMPLETED", time: "120ms", output: "Found alternate seller_bb99112233 (0.94 similarity)" },
        { id: "s2", name: "3D Volumetric Cubing & Co-Loading", domain: "OPTIMIZATION", agent: "Load Planning Agent (v4.5)", status: "COMPLETED", time: "180ms", output: "12 orders cubed at 35% utilization (FEASIBLE)" },
        { id: "s3", name: "Multimodal Capacity & Rate Negotiation", domain: "BOOKING", agent: "Capacity Booking Agent (v4.2)", status: "COMPLETED", time: "210ms", output: "Reserved Lane VCP-SDU ($450.00 / 0.5d transit)" },
        { id: "s4", name: "Trade Sanctions & Spend Authorization", domain: "COMPLIANCE", agent: "Compliance Agent (v5.0)", status: "COMPLETED", time: "90ms", output: "APPROVED (Budget within $1,500 limit, Sanctions Clear)" },
        { id: "s5", name: "Consensus Synthesis & Twin Dispatch", domain: "SUPERVISOR", agent: "Nexus Swarm Supervisor (v5.0)", status: "COMPLETED", time: "80ms", output: "Consensus 0.94 • Candidate C dispatched to Digital Twin" },
      ],
    },
    {
      task_id: "TASK_2026_002",
      title: "Safety Stock Rebalance: Campinas (VCP) to Rio Hub",
      target_entity: "hub_campinas_vcp",
      world_state_version: 101,
      status: "IN_PROGRESS",
      consensus_score: 0.88,
      steps_count: 4,
      completed_steps: 3,
      runtime_ms: 450,
      created_at: "23:58:14Z",
      steps: [
        { id: "s1", name: "Corridor Flow Imbalance Scan", domain: "OPTIMIZATION", agent: "Network Rebalancing Agent (v4.1)", status: "COMPLETED", time: "110ms", output: "50 buffer units allocated for shuttle" },
        { id: "s2", name: "Carrier Rate Validation", domain: "BOOKING", agent: "Carrier Negotiation Agent (v4.0)", status: "COMPLETED", time: "140ms", output: "Contracted $320.00 dedicated shuttle" },
        { id: "s3", name: "Transport Compliance Clearance", domain: "COMPLIANCE", agent: "Compliance Agent (v5.0)", status: "COMPLETED", time: "90ms", output: "Inter-state ICMS tax permit cleared" },
        { id: "s4", name: "Executive Synthesis & PO Dispatch", domain: "SUPERVISOR", agent: "Nexus Swarm Supervisor (v5.0)", status: "IN_PROGRESS", time: "110ms", output: "Awaiting final operator quorum" },
      ],
    },
  ];

  const currentTask = tasks.find((t) => t.task_id === selectedTask) || tasks[0];

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Multi-Agent Task Graphs & Execution Plans</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Structured directed acyclic task graphs (DAGs) decomposing operational disruptions across domain ensembles.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/workspace/agents"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            ← Decision Room
          </Link>
          <Link
            href="/workspace/agents/fleet"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            Fleet Replicas →
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* Left Column: Task List */}
        <div className="space-y-3">
          <div className="text-xs font-bold text-zinc-400 font-mono uppercase tracking-wider">Active Task Graphs</div>
          {tasks.map((t) => (
            <div
              key={t.task_id}
              onClick={() => setSelectedTask(t.task_id)}
              className={`p-4 rounded-xl border transition cursor-pointer font-mono ${
                selectedTask === t.task_id
                  ? "bg-zinc-900/90 border-emerald-500 shadow-md"
                  : "bg-zinc-950/60 border-zinc-800 hover:border-zinc-700"
              }`}
            >
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-zinc-100">{t.task_id}</span>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    t.status === "COMPLETED"
                      ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                      : "bg-amber-950 text-amber-400 border border-amber-800 animate-pulse"
                  }`}
                >
                  {t.status}
                </span>
              </div>
              <p className="text-xs text-zinc-300 font-sans mt-2 line-clamp-2">{t.title}</p>
              <div className="flex items-center justify-between text-[10px] text-zinc-500 mt-3 pt-2 border-t border-zinc-800/80">
                <span>Steps: <strong className="text-zinc-300">{t.completed_steps}/{t.steps_count}</strong></span>
                <span>Consensus: <strong className="text-emerald-400">{t.consensus_score}</strong></span>
              </div>
            </div>
          ))}
        </div>

        {/* Right 2 Columns: Task Execution Trace DAG */}
        <div className="col-span-2 space-y-4">
          <div className="p-5 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-4 font-mono text-xs">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-zinc-100 text-sm">{currentTask.title}</span>
                </div>
                <div className="text-[11px] text-zinc-400 mt-1">
                  Entity: <strong className="text-zinc-200">{currentTask.target_entity}</strong> • World State: <strong className="text-zinc-200">v{currentTask.world_state_version}</strong> • Runtime: <strong className="text-emerald-400">{currentTask.runtime_ms}ms</strong>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold text-xs">
                {currentTask.status}
              </span>
            </div>

            {/* Step Trace */}
            <div className="space-y-3">
              {currentTask.steps.map((s, idx) => (
                <div key={s.id} className="p-3.5 bg-zinc-900/60 border border-zinc-800/80 rounded-lg flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <span className="w-6 h-6 rounded-full bg-zinc-950 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-300 font-bold mt-0.5">
                      {idx + 1}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-zinc-200">{s.name}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                          {s.domain}
                        </span>
                      </div>
                      <div className="text-[11px] text-zinc-400 mt-1 font-sans">
                        Assigned: <span className="text-zinc-300 font-mono">{s.agent}</span>
                      </div>
                      <div className="text-xs text-emerald-400 font-sans mt-1">
                        ↳ Output: {s.output}
                      </div>
                    </div>
                  </div>
                  <div className="text-right whitespace-nowrap">
                    <span className="text-[10px] text-zinc-500 block">{s.time}</span>
                    <span className="text-emerald-400 font-bold text-[10px] block mt-1">
                      {s.status === "COMPLETED" ? "✓ COMPLETE" : "● RUNNING"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
