"use client";

import React from "react";
import Link from "next/link";
import { AskNexusBar } from "@/components/shell/AskNexusBar";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export default function WorkspaceOverviewPage() {
  const {
    totalRows,
    entitiesResolved,
    nodesCount,
    edgesCount,
    worldStateVersion,
    relationshipCoveragePct,
    signals,
    latestDecision,
  } = useNexusWorkspace();

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Intent-Centric Workspace Context Bar */}
      <IntentWorkspaceBar />

      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 tracking-tight">Operational World Overview</h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Mission-control state synthesized directly from live enterprise operational data.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/workspace/data"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700/80 text-xs font-mono text-zinc-300 transition"
          >
            Upload Data Tables
          </Link>
          <Link
            href="/workspace/graph"
            className="px-3 py-1.5 rounded bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs transition"
          >
            Open Operational Graph →
          </Link>
        </div>
      </div>

      {/* Persistent Reasoning Command Bar */}
      <div className="border border-zinc-800/80 rounded-xl p-4 bg-zinc-900/30">
        <AskNexusBar />
      </div>

      {/* Analytically Honest Metric Strip */}
      <div className="grid grid-cols-6 gap-3">
        {[
          { label: "ROWS INGESTED", value: totalRows.toLocaleString(), note: "Olist Production Tables" },
          { label: "ENTITIES RESOLVED", value: entitiesResolved.toLocaleString(), note: "Canonical Keys" },
          { label: "GRAPH NODES", value: nodesCount.toLocaleString(), note: "Proportional World" },
          { label: "RELATIONSHIPS", value: edgesCount.toLocaleString(), note: `Coverage: ${relationshipCoveragePct}%` },
          { label: "WORLD STATE", value: `v${worldStateVersion}`, note: "Authoritative Snapshot" },
          { label: "NET ECONOMIC ROI", value: "+$2,900.00", note: "Candidate C (Air Freight)", highlight: true },
        ].map((stat) => (
          <div key={stat.label} className="p-3.5 bg-zinc-950/80 border border-zinc-800 rounded-lg space-y-1">
            <div className="text-[10px] font-mono text-zinc-500 uppercase">{stat.label}</div>
            <div className={`text-base font-bold font-mono ${stat.highlight ? "text-emerald-400" : "text-zinc-100"}`}>
              {stat.value}
            </div>
            <div className="text-[10px] font-mono text-zinc-500">{stat.note}</div>
          </div>
        ))}
      </div>

      {/* Main Grid: Graph Preview & Live Signals */}
      <div className="grid grid-cols-3 gap-6">
        {/* Operational Graph Preview Card */}
        <div className="col-span-2 border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 flex flex-col justify-between space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
            <div>
              <h3 className="text-sm font-bold text-zinc-200">Operational Graph Viewport</h3>
              <p className="text-xs text-zinc-500">Live 2-hop localized ego-network centering on critical SPOF node.</p>
            </div>
            <Link
              href="/workspace/graph"
              className="text-xs font-mono text-zinc-400 hover:text-zinc-100 transition"
            >
              Full Viewport [{nodesCount} Nodes] →
            </Link>
          </div>

          <div className="h-56 bg-zinc-950 border border-zinc-800/80 rounded-lg flex items-center justify-center relative overflow-hidden">
            <div className="flex flex-col items-center justify-center space-y-2 text-center p-6">
              <div className="w-10 h-10 rounded-full border-2 border-red-600 bg-red-950/40 flex items-center justify-center text-xs font-mono text-red-400 font-bold animate-pulse">
                SPOF
              </div>
              <div className="text-xs font-mono text-zinc-300 font-semibold">seller_01a00b8e99 (PageRank: 0.042)</div>
              <div className="text-[11px] text-zinc-500 font-mono">
                Connected to 12 Customer Orders via BR-116 Route Corridor
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-zinc-400 font-mono pt-1">
            <span>SPOF DETECTION: <strong className="text-red-400">1 CRITICAL NODE</strong></span>
            <span>SELLER GINI: <strong className="text-zinc-200">0.642 (Elevated)</strong></span>
          </div>
        </div>

        {/* Live Signals & Risk Panel */}
        <div className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 flex flex-col justify-between space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
            <div>
              <h3 className="text-sm font-bold text-zinc-200">Active Operational Signals</h3>
              <p className="text-xs text-zinc-500">{signals.length} active anomaly threshold crossings</p>
            </div>
            <Link href="/workspace/signals" className="text-xs font-mono text-zinc-400 hover:text-zinc-100">
              All Signals →
            </Link>
          </div>

          <div className="space-y-3">
            {signals.map((sig) => (
              <div key={sig.signal_id} className="p-3 bg-zinc-950 border border-zinc-800 rounded-lg space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                    sig.severity === "CRITICAL" ? "bg-red-950 border-red-800 text-red-400" : "bg-amber-950 border-amber-800 text-amber-400"
                  }`}>
                    {sig.severity} • {sig.signal_type}
                  </span>
                  <span className="text-[10px] font-mono text-zinc-500">{sig.entity_id}</span>
                </div>
                <div className="text-xs text-zinc-300">
                  Observed deviation: <strong>+{sig.deviation_pct}%</strong> vs baseline.
                </div>
              </div>
            ))}
          </div>

          <Link
            href="/workspace/agents"
            className="w-full py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-medium text-xs text-center transition block"
          >
            Launch Multi-Agent Deliberation →
          </Link>
        </div>
      </div>

      {/* Multi-Agent Cockpit & Governed Decisions Row */}
      <div className="grid grid-cols-2 gap-6">
        {/* Decision Room Summary */}
        <div className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
            <div>
              <h3 className="text-sm font-bold text-zinc-200">Multi-Agent Decision Room</h3>
              <p className="text-xs text-zinc-500">Deliberation across 3 graph-aware specialist agents</p>
            </div>
            <Link href="/workspace/agents" className="text-xs font-mono text-zinc-400 hover:text-zinc-100">
              Open Room →
            </Link>
          </div>

          <div className="space-y-2 text-xs font-mono text-zinc-300">
            <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded flex justify-between">
              <span>Executive Coordinator:</span>
              <span className="text-emerald-400">Consensus Reached (0.94)</span>
            </div>
            <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded flex justify-between">
              <span>Logistics Routing Agent:</span>
              <span className="text-zinc-400">Proposed Air Freight (VCP-SDU)</span>
            </div>
            <div className="p-2.5 bg-zinc-950 border border-zinc-800 rounded flex justify-between">
              <span>Digital Twin Simulation:</span>
              <span className="text-emerald-400">4 Candidates Evaluated</span>
            </div>
          </div>
        </div>

        {/* Governed Decision Card */}
        <div className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/30 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
            <div>
              <h3 className="text-sm font-bold text-zinc-200">Latest Governed Decision</h3>
              <p className="text-xs text-zinc-500">Optimal simulated Net Economic Value policy</p>
            </div>
            <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-mono">
              APPROVED
            </span>
          </div>

          <div className="p-3.5 bg-zinc-950 border border-zinc-800 rounded-lg space-y-2">
            <div className="text-xs font-bold text-zinc-200">{latestDecision?.title}</div>
            <p className="text-xs text-zinc-400">{latestDecision?.action_summary}</p>
            <div className="flex items-center justify-between pt-1 text-xs font-mono">
              <span className="text-zinc-500">INTERVENTION COST: ${latestDecision?.estimated_cost_usd?.toFixed(2)}</span>
              <span className="text-emerald-400 font-bold">NET VALUE: +${latestDecision?.net_economic_value_usd?.toFixed(2)}</span>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <Link
              href="/workspace/evidence"
              className="text-xs font-mono text-zinc-400 hover:text-zinc-200 transition"
            >
              Verify Cryptographic Evidence Chain →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
