"use client";

import React, { useState } from "react";
import { AskNexusBar } from "@/components/shell/AskNexusBar";

export default function AnalysisPage() {
  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">Operational Analysis & Reasoning Studio</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Direct data interrogation and structured analytical scans across the operational world model.
        </p>
      </div>

      <div className="border border-zinc-800 rounded-xl p-6 bg-zinc-900/30">
        <AskNexusBar />
      </div>

      {/* Prebuilt Automated Analyses */}
      <div className="space-y-4">
        <h3 className="text-sm font-bold text-zinc-200">Prebuilt Operational Intelligence Scans</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-900/30 space-y-2 text-xs">
            <div className="font-bold text-zinc-100">Top Critical Single Points of Failure (SPOFs)</div>
            <p className="text-zinc-400">Identifies sellers and logistics hubs with PageRank &gt; 0.035 and zero redundancy.</p>
            <div className="text-emerald-400 font-mono font-semibold">1 Detected: seller_01a00b8e99</div>
          </div>

          <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-900/30 space-y-2 text-xs">
            <div className="font-bold text-zinc-100">Route Transit Latency Variance Scan</div>
            <p className="text-zinc-400">Scans high-volume transit corridors for highway bottlenecks and carrier delays.</p>
            <div className="text-amber-400 font-mono font-semibold">Elevated Variance: Corridor BR-116 (+1.4d)</div>
          </div>
        </div>
      </div>
    </div>
  );
}
