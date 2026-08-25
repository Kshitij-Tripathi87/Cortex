"use client";

import React, { useState } from "react";
import Link from "next/link";
import { WorldStateEvent } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export default function WorldStateTimelinePage() {
  const { worldStateVersion, setHistoricalVersion } = useNexusWorkspace();

  const [events] = useState<WorldStateEvent[]>([
    {
      event_id: "evt_101",
      version: 101,
      event_type: "SELLER_STATUS_CHANGED",
      entity_id: "seller_01a00b8e99",
      timestamp: "2026-08-16T23:55:01Z",
      payload: { old_status: "NOMINAL", new_status: "DEGRADED", delay_days: 3.8 },
      state_summary: "Seller seller_01a00b8e99 dispatch latency increased from 2.0d to 3.8d (+90%).",
    },
    {
      event_id: "evt_100",
      version: 100,
      event_type: "ROUTE_CORRIDOR_CONGESTION",
      entity_id: "route_SP_to_RJ",
      timestamp: "2026-08-16T23:52:14Z",
      payload: { corridor: "BR-116", delay_variance: 1.4 },
      state_summary: "Corridor BR-116 detected +1.4 days transit variance.",
    },
    {
      event_id: "evt_099",
      version: 99,
      event_type: "BATCH_ORDERS_INGESTED",
      entity_id: "olist_orders_batch_01",
      timestamp: "2026-08-16T23:50:00Z",
      payload: { count: 1000, coverage_pct: 98.6 },
      state_summary: "1,000 orders ingested, resolving 784 nodes and 942 relationships.",
    },
  ]);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100">World State Timeline & Version Time-Travel</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Immutable event log enabling point-in-time state reconstruction, historical diffs, and replay.
          </p>
        </div>

        {/* V4: Time Travel Version Selector */}
        <div className="flex items-center gap-2 bg-zinc-950 p-1.5 rounded-lg border border-zinc-800 text-xs font-mono">
          <span className="text-zinc-500 text-[10px]">TIME TRAVEL:</span>
          {[99, 100, 101, 102].map((v) => (
            <button
              key={v}
              onClick={() => setHistoricalVersion(v)}
              className={`px-2.5 py-1 rounded transition ${
                worldStateVersion === v
                  ? "bg-zinc-800 text-zinc-100 font-bold border border-zinc-700"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              v{v}
            </button>
          ))}
        </div>
      </div>

      <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900/30">
        <div className="px-5 py-3 border-b border-zinc-800 bg-zinc-900/50 text-xs font-semibold text-zinc-300 font-mono flex items-center justify-between">
          <span>EVENT SOURCING LEDGER</span>
          <span className="text-emerald-400 font-bold">ACTIVE WORLD STATE: v{worldStateVersion}</span>
        </div>
        <div className="divide-y divide-zinc-800/60">
          {events.map((evt) => (
            <div key={evt.event_id} className="p-5 space-y-2 text-xs">
              <div className="flex items-center justify-between font-mono">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded font-bold ${
                    worldStateVersion >= evt.version ? "bg-zinc-800 text-zinc-200" : "bg-zinc-950 text-zinc-600 border border-zinc-800"
                  }`}>
                    v{evt.version}
                  </span>
                  <span className="font-bold text-zinc-300">{evt.event_type}</span>
                  <span className="text-zinc-500">[{evt.entity_id}]</span>
                </div>
                <span className="text-zinc-500">{evt.timestamp}</span>
              </div>
              <p className="text-zinc-300">{evt.state_summary}</p>
              <pre className="p-2.5 bg-zinc-950 border border-zinc-800/80 rounded font-mono text-[10px] text-zinc-400 overflow-x-auto">
                {JSON.stringify(evt.payload, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
