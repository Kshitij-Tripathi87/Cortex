"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AgentFleetReplica } from "@/types/nexus";

export default function AgentFleetPage() {
  const [fleet] = useState<AgentFleetReplica[]>([
    {
      agent_id: "agent_shipment_tracking",
      role: "SHIPMENT_TRACKING",
      name: "Shipment Tracking Agent",
      version: "v9_olist",
      replica_count: 12,
      canary_pct: 10,
      status: "HEALTHY",
      latency_p95_ms: 18.4,
      error_rate_pct: 0.0,
      last_heartbeat: "Just now",
    },
    {
      agent_id: "agent_logistics_routing",
      role: "LOGISTICS_ROUTING",
      name: "Logistics Routing Agent",
      version: "v4",
      replica_count: 8,
      canary_pct: 0,
      status: "HEALTHY",
      latency_p95_ms: 24.1,
      error_rate_pct: 0.0,
      last_heartbeat: "Just now",
    },
    {
      agent_id: "agent_inventory_allocation",
      role: "INVENTORY_ALLOCATION",
      name: "Inventory Allocation Agent",
      version: "v6",
      replica_count: 6,
      canary_pct: 0,
      status: "HEALTHY",
      latency_p95_ms: 15.8,
      error_rate_pct: 0.0,
      last_heartbeat: "Just now",
    },
  ]);

  const lifecycleStages = [
    { id: "TRAIN", label: "1. Centralized Train" },
    { id: "VALIDATE", label: "2. Certified" },
    { id: "SHADOW", label: "3. Shadow Run" },
    { id: "CANARY", label: "4. Canary (10%)" },
    { id: "ACTIVE", label: "5. Active Fleet" },
    { id: "SUPERVISED", label: "6. Supervised" },
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">Decentralized Agent Fleet & CTDE Lifecycle</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Cluster-wide replica health, progressive canary rollout quotas, and automated drift replacement.
        </p>
      </div>

      {/* W7: Agent Platform Lifecycle Pipeline */}
      <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-2 font-mono text-xs">
        <div className="text-[10px] text-zinc-500 uppercase font-bold">CTDE AGENT LIFECYCLE PIPELINE:</div>
        <div className="flex items-center gap-2 overflow-x-auto py-1">
          {lifecycleStages.map((stage, idx) => (
            <React.Fragment key={stage.id}>
              <span className="px-3 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-300 text-[10px]">
                {stage.label}
              </span>
              {idx < lifecycleStages.length - 1 && <span className="text-zinc-700">→</span>}
            </React.Fragment>
          ))}
        </div>
      </div>

      <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900/30">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-zinc-900/80 border-b border-zinc-800 text-zinc-400 uppercase">
            <tr>
              <th className="px-5 py-3.5">Agent Role & Name</th>
              <th className="px-5 py-3.5">Version</th>
              <th className="px-5 py-3.5">Active Replicas</th>
              <th className="px-5 py-3.5">Canary Quota</th>
              <th className="px-5 py-3.5">P95 Latency</th>
              <th className="px-5 py-3.5">Health Status</th>
              <th className="px-5 py-3.5 text-right">Controls</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60 text-zinc-300">
            {fleet.map((agent) => (
              <tr key={agent.agent_id}>
                <td className="px-5 py-3.5 font-bold text-zinc-100">
                  <div>{agent.name}</div>
                  <div className="text-[10px] text-zinc-500 font-normal">{agent.role}</div>
                </td>
                <td className="px-5 py-3.5">{agent.version}</td>
                <td className="px-5 py-3.5">{agent.replica_count} nodes</td>
                <td className="px-5 py-3.5">
                  <span className={agent.canary_pct > 0 ? "text-emerald-400 font-bold" : "text-zinc-400"}>
                    {agent.canary_pct}% canary
                  </span>
                </td>
                <td className="px-5 py-3.5">{agent.latency_p95_ms}ms</td>
                <td className="px-5 py-3.5">
                  <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-[10px] font-bold">
                    {agent.status}
                  </span>
                </td>
                <td className="px-5 py-3.5 text-right space-x-2">
                  <button className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[11px] transition">
                    Scale
                  </button>
                  <button className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[11px] transition">
                    Rollback
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
