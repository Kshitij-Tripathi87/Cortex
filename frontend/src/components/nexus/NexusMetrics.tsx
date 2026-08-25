"use client";

import React from "react";
import { NexusMetrics as NexusMetricsType } from "./nexus-types";

interface NexusMetricsProps {
  metrics: NexusMetricsType;
}

export const NexusMetrics: React.FC<NexusMetricsProps> = ({ metrics }) => {
  const items = [
    { label: "Exposure", value: metrics.exposure, className: "text-amber-400" },
    { label: "Time to Impact", value: metrics.timeToImpact, className: "text-blue-400" },
    { label: "Orders at Risk", value: metrics.ordersAtRisk.toString(), className: "text-red-400" },
    { label: "Validated Options", value: metrics.validatedOptions.toString(), className: "text-emerald-400" },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3" role="region" aria-label="Key metrics">
      {items.map((item) => (
        <div
          key={item.label}
          className="p-4 bg-zinc-950 border border-zinc-800 rounded-xl"
        >
          <div className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider mb-1">
            {item.label}
          </div>
          <div className={`text-xl font-mono font-bold ${item.className}`}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
};