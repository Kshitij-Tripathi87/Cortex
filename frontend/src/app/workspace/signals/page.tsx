"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { OperationalSignal } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function SignalsPage() {
  const router = useRouter();
  const { signals, setGraphMode, launchIntent, setActiveWorkflowStep } = useNexusWorkspace();

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Intent Workspace Bar */}
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Active Operational Signals & Anomalies</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Statistical and topological anomaly detection triggers across the operational graph.
          </p>
        </div>
        <Link
          href="/workspace/graph"
          onClick={() => setGraphMode("RISK")}
          className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700/80 text-xs font-mono text-zinc-300 transition"
        >
          View in Graph Risk Mode →
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {signals.map((sig) => (
          <div key={sig.signal_id} className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 space-y-4">
            <div className="flex items-center justify-between">
              <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-bold border ${
                sig.severity === "CRITICAL" ? "bg-red-950 border-red-800 text-red-400" : "bg-amber-950 border-amber-800 text-amber-400"
              }`}>
                {sig.severity} • {sig.signal_type}
              </span>
              <span className="text-xs font-mono text-zinc-400">{sig.entity_id}</span>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center bg-zinc-950 p-3 rounded-lg border border-zinc-800/80">
              <div>
                <div className="text-[10px] text-zinc-500 font-mono">OBSERVED</div>
                <div className="text-sm font-bold text-red-400 font-mono">{sig.metric_value}d</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 font-mono">BASELINE</div>
                <div className="text-sm font-bold text-zinc-300 font-mono">{sig.baseline_threshold}d</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 font-mono">DEVIATION</div>
                <div className="text-sm font-bold text-zinc-100 font-mono">+{sig.deviation_pct}%</div>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs pt-1">
              <span className="text-zinc-500 font-mono">DETECTED: {sig.detected_at}</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    launchIntent("INVESTIGATE_ENTITY", sig.entity_id);
                    setActiveWorkflowStep(1);
                    router.push("/workspace/cockpit");
                  }}
                  className="px-2.5 py-1 rounded bg-zinc-100 hover:bg-white text-zinc-950 text-[11px] font-mono font-bold transition"
                >
                  Triage in Cockpit →
                </button>
                <Link
                  href="/workspace/graph"
                  onClick={() => setGraphMode("INCIDENT")}
                  className="font-mono text-zinc-300 hover:text-white transition text-xs"
                >
                  Center in Graph →
                </Link>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
