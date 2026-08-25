"use client";

import React, { useState } from "react";
import Link from "next/link";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function AgentDeploymentsPage() {
  const [canaryPct, setCanaryPct] = useState(25);

  const deployments = [
    {
      agent_id: "capacity_booking_agent",
      name: "Capacity Booking Agent",
      active_version: "v4.1 (Stable)",
      canary_version: "v4.2 (Candidate)",
      canary_traffic_pct: canaryPct,
      replicas: 4,
      health: "100%",
      status: "CANARY_ROUTING",
    },
    {
      agent_id: "compliance_agent",
      name: "Compliance & Regulatory Agent",
      active_version: "v5.0 (Locked)",
      canary_version: "None",
      canary_traffic_pct: 0,
      replicas: 2,
      health: "100%",
      status: "PRODUCTION_ACTIVE",
    },
    {
      agent_id: "load_planning_agent",
      name: "Load Planning Agent",
      active_version: "v4.5 (Stable)",
      canary_version: "None",
      canary_traffic_pct: 0,
      replicas: 3,
      health: "100%",
      status: "PRODUCTION_ACTIVE",
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Progressive Canary Deployment & Traffic Routing</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Safely roll out specialist agent models with weighted traffic splitting, autonomous quarantine, and instant rollback.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/workspace/agents/fleet"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            ← Fleet Overview
          </Link>
        </div>
      </div>

      <div className="space-y-4 font-mono text-xs">
        {deployments.map((d) => (
          <div key={d.agent_id} className="p-4 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
              <span className="font-bold text-zinc-100 text-sm">{d.name}</span>
              <span
                className={`px-2 py-0.5 rounded font-bold text-[10px] ${
                  d.status === "CANARY_ROUTING"
                    ? "bg-amber-950 text-amber-400 border border-amber-800"
                    : "bg-emerald-950 text-emerald-400 border border-emerald-800"
                }`}
              >
                {d.status}
              </span>
            </div>

            <div className="grid grid-cols-4 gap-4 text-[11px] text-zinc-400">
              <div>
                <span>ACTIVE (STABLE):</span>
                <strong className="block text-zinc-200 mt-0.5">{d.active_version}</strong>
              </div>
              <div>
                <span>CANARY (CANDIDATE):</span>
                <strong className="block text-emerald-400 mt-0.5">{d.canary_version}</strong>
              </div>
              <div>
                <span>HEALTH / REPLICAS:</span>
                <strong className="block text-zinc-200 mt-0.5">{d.health} ({d.replicas} pods)</strong>
              </div>
              <div>
                <span>CANARY TRAFFIC:</span>
                <strong className="block text-amber-400 mt-0.5">{d.canary_traffic_pct}%</strong>
              </div>
            </div>

            {d.canary_version !== "None" && (
              <div className="pt-2 border-t border-zinc-800/80 space-y-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span>Adjust Canary Traffic Split:</span>
                  <span className="font-bold text-amber-400">{canaryPct}% to Candidate</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={canaryPct}
                  onChange={(e) => setCanaryPct(Number(e.target.value))}
                  className="w-full accent-amber-400"
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
