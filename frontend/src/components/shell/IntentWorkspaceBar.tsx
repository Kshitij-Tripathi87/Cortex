"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentType } from "@/types/nexus";

export const IntentWorkspaceBar: React.FC = () => {
  const { currentIntent, launchIntent, clearIntent, setActiveWorkflowStep } = useNexusWorkspace();
  const [showLauncher, setShowLauncher] = useState(false);

  const predefinedIntents: {
    type: IntentType;
    label: string;
    targetId: string;
    secondaryId?: string;
    description: string;
    icon: string;
  }[] = [
    {
      type: "INVESTIGATE_ENTITY",
      label: "Investigate Seller 01a00b8e99",
      targetId: "seller_01a00b8e99",
      secondaryId: "route_SP_to_RJ",
      description: "Assemble 2-hop ego-graph, active degradation signals, and affected customer orders.",
      icon: "🔍",
    },
    {
      type: "INVESTIGATE_INCIDENT",
      label: "Triage Incident: BR-116 Route Congestion",
      targetId: "route_SP_to_RJ",
      secondaryId: "sig_route_cong_02",
      description: "Center on corridor bottleneck, compute blast radius across 14 transit corridors.",
      icon: "⚡",
    },
    {
      type: "EVALUATE_DECISION",
      label: "Evaluate Decision: Candidate C (Air Expedite)",
      targetId: "dec_live_01",
      secondaryId: "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK",
      description: "Inspect causal DAG, Monte Carlo simulation intervals, and cryptographic policy compliance.",
      icon: "📋",
    },
    {
      type: "SIMULATE_DISRUPTION",
      label: "Simulate Disruption: Campinas Hub Failure",
      targetId: "loc_SP_HUB",
      secondaryId: "scenario_hub_outage",
      description: "Inject 48h terminal outage overlay and calculate customer SLA risk distribution.",
      icon: "🔮",
    },
  ];

  return (
    <div className="w-full">
      {currentIntent ? (
        <div className="flex items-center justify-between px-3.5 py-2 bg-zinc-900/90 border border-zinc-800 rounded-lg text-xs font-mono">
          <div className="flex items-center gap-2.5">
            <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-bold uppercase tracking-wider text-[10px] border border-zinc-700">
              INTENT: {currentIntent.intent_type.replace("_", " ")}
            </span>
            <span className="text-zinc-100 font-semibold">{currentIntent.title}</span>
            <span className="text-zinc-500">•</span>
            <span className="text-zinc-400">
              Ego-Graph: <strong className="text-zinc-200">{currentIntent.ego_nodes_count} nodes</strong>
            </span>
            <span className="text-zinc-500">•</span>
            <span className="text-zinc-400">
              Active Signals: <strong className="text-red-400">{currentIntent.active_signals_count} Critical</strong>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/workspace/cockpit"
              onClick={() => setActiveWorkflowStep(6)}
              className="px-2.5 py-1 rounded bg-zinc-100 text-zinc-950 font-bold hover:bg-white transition text-[11px]"
            >
              Open Unified Canvas →
            </Link>
            <button
              onClick={() => setShowLauncher(!showLauncher)}
              className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition text-[11px]"
            >
              Switch Intent
            </button>
            <button
              onClick={clearIntent}
              className="px-2 py-1 rounded text-zinc-500 hover:text-zinc-300 transition text-[11px]"
              title="Clear Intent Scope"
            >
              ✕
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between px-3.5 py-2 bg-zinc-950/60 border border-zinc-800/80 rounded-lg text-xs">
          <div className="flex items-center gap-2 text-zinc-400 font-mono">
            <span>🎯</span>
            <span>No intent workspace locked. Assemble context around an operational objective:</span>
          </div>
          <button
            onClick={() => setShowLauncher(!showLauncher)}
            className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-mono text-[11px] border border-zinc-700 transition"
          >
            Launch Intent Workspace ▾
          </button>
        </div>
      )}

      {/* Dropdown Launcher */}
      {showLauncher && (
        <div className="mt-2 p-3 bg-zinc-950 border border-zinc-700/80 rounded-lg shadow-2xl grid grid-cols-2 gap-2 z-30 relative animate-fadeIn">
          {predefinedIntents.map((intent) => (
            <button
              key={intent.label}
              onClick={() => {
                launchIntent(intent.type, intent.targetId, intent.secondaryId);
                setShowLauncher(false);
              }}
              className="p-2.5 rounded border border-zinc-800/80 hover:border-zinc-600 bg-zinc-900/40 hover:bg-zinc-900 text-left transition flex flex-col justify-between space-y-1 group"
            >
              <div className="flex items-center justify-between w-full">
                <div className="flex items-center gap-2 font-mono text-xs font-semibold text-zinc-200 group-hover:text-white">
                  <span>{intent.icon}</span>
                  <span>{intent.label}</span>
                </div>
                <span className="text-[10px] font-mono text-zinc-500 uppercase">{intent.type.split("_")[1]}</span>
              </div>
              <p className="text-[11px] text-zinc-400 leading-tight">{intent.description}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
