"use client";

import React, { useState } from "react";
import Link from "next/link";
import { RiskExposureSummary } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";

export default function RiskPage() {
  const { setGraphMode } = useNexusWorkspace();

  const [risk] = useState<RiskExposureSummary>({
    critical_entities_count: 1,
    affected_orders_count: 12,
    exposed_customers_count: 9,
    revenue_at_risk_usd: 1746.0,
    seller_concentration_gini: 0.642,
    primary_corridor: "BR-116 (São Paulo -> Rio de Janeiro)",
  });

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Intent Workspace Bar */}
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Operational Risk & Blast Radius Topology</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Downstream blast radius projection quantifying customer exposure and financial value at risk.
          </p>
        </div>
        <Link
          href="/workspace/graph"
          onClick={() => setGraphMode("RISK")}
          className="px-3 py-1.5 rounded bg-red-950 border border-red-800 text-red-400 text-xs font-mono font-bold hover:bg-red-900 transition"
        >
          View Risk Mode in Graph →
        </Link>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-1">
          <div className="text-[10px] font-mono text-zinc-500 uppercase">AFFECTED ORDERS</div>
          <div className="text-xl font-bold font-mono text-zinc-100">{risk.affected_orders_count}</div>
          <div className="text-[10px] text-red-400 font-mono">100% Pending Delivery</div>
        </div>
        <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-1">
          <div className="text-[10px] font-mono text-zinc-500 uppercase">EXPOSED CUSTOMERS</div>
          <div className="text-xl font-bold font-mono text-zinc-100">{risk.exposed_customers_count}</div>
          <div className="text-[10px] text-zinc-500 font-mono">Rio de Janeiro Hub</div>
        </div>
        <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-1">
          <div className="text-[10px] font-mono text-zinc-500 uppercase">REVENUE EXPOSURE</div>
          <div className="text-xl font-bold font-mono text-red-400">${risk.revenue_at_risk_usd.toFixed(2)}</div>
          <div className="text-[10px] text-zinc-500 font-mono">12 exposed orders, Status Quo</div>
        </div>
        <div className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl space-y-1">
          <div className="text-[10px] font-mono text-zinc-500 uppercase">SELLER CONCENTRATION</div>
          <div className="text-xl font-bold font-mono text-amber-400">{risk.seller_concentration_gini}</div>
          <div className="text-[10px] text-zinc-500 font-mono">Gini Index (High Risk)</div>
        </div>
      </div>

      <div className="border border-zinc-800 rounded-xl p-6 bg-zinc-900/30 space-y-4">
        <h3 className="text-sm font-bold text-zinc-200">Risk Propagation Path</h3>
        <div className="flex items-center gap-3 text-xs font-mono text-zinc-300 overflow-x-auto py-2">
          <div className="p-3 bg-zinc-950 border border-red-800 rounded-lg text-center shrink-0">
            <div className="text-red-400 font-bold">SELLER</div>
            <div className="text-zinc-400 text-[10px]">seller_01a00b8e99</div>
          </div>
          <span className="text-zinc-600">➔</span>
          <div className="p-3 bg-zinc-950 border border-amber-800 rounded-lg text-center shrink-0">
            <div className="text-amber-400 font-bold">CORRIDOR</div>
            <div className="text-zinc-400 text-[10px]">route_SP_to_RJ (BR-116)</div>
          </div>
          <span className="text-zinc-600">➔</span>
          <div className="p-3 bg-zinc-950 border border-zinc-800 rounded-lg text-center shrink-0">
            <div className="text-zinc-300 font-bold">12 ORDERS</div>
            <div className="text-zinc-400 text-[10px]">$1,746.00 Revenue Exposure</div>
          </div>
          <span className="text-zinc-600">➔</span>
          <div className="p-3 bg-zinc-950 border border-zinc-800 rounded-lg text-center shrink-0">
            <div className="text-zinc-300 font-bold">9 CUSTOMERS</div>
            <div className="text-zinc-400 text-[10px]">Rio de Janeiro Hub</div>
          </div>
        </div>

        <div className="pt-2 flex justify-between items-center text-xs font-mono">
          <Link
            href="/workspace/agents"
            className="text-zinc-400 hover:text-zinc-200 transition"
          >
            Inspect Graph-Aware Specialist Agent Selection →
          </Link>
          <Link
            href="/workspace/scenarios"
            className="px-4 py-2 rounded bg-zinc-100 hover:bg-white text-zinc-950 font-semibold font-sans transition"
          >
            Evaluate Counterfactual Interventions →
          </Link>
        </div>
      </div>

      <ProgressiveDisclosure entityId="seller_01a00b8e99" />
    </div>
  );
}
