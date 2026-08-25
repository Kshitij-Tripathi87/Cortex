"use client";

import React from "react";

interface NexusExplanationProps {
  stage: string;
  disruption: string | null;
  response: string | null;
}

const explanations: Record<string, { title: string; description: string }> = {
  baseline: {
    title: "Network Baseline",
    description:
      "All suppliers, plants, ports, and distribution centers operating normally. No active disruptions detected.",
  },
  detecting: {
    title: "Disruption Detected",
    description:
      "Supplier X has signaled a 12-day lead time variance. Risk propagates through Plant 2 → Port of LA → DC West → Customer 1. 18 orders ($4.85M exposure) now at risk.",
  },
  evaluating: {
    title: "Evaluating Responses",
    description:
      "Three mitigation options under evaluation: (1) Qualify Alternative Supplier A — 3-day lead time, $0.42M cost. (2) Activate Air Freight corridor — 48hr delivery, $2.1M cost. (3) Release regional buffer stock — immediate, limited to 8 orders. Select a response to validate.",
  },
  validated: {
    title: "Mitigation Validated",
    description:
      "Alternative Supplier A qualified and onboarded. Green path active: Supplier A → Plant 2 → Port of LA → DC West → Customer 1. Exposure reduced to $0.42M. 18 orders protected. Network resilient.",
  },
};

export const NexusExplanation: React.FC<NexusExplanationProps> = ({
  stage,
}) => {
  const { title, description } = explanations[stage] || explanations.baseline;

  return (
    <div className="mt-6 p-4 bg-zinc-950 border border-zinc-800 rounded-xl" role="region" aria-labelledby="explanation-title">
      <h3 id="explanation-title" className="text-sm font-mono font-bold text-zinc-200 mb-2">
        {title}
      </h3>
      <p className="text-zinc-400 text-sm leading-relaxed font-mono">
        {description}
      </p>
    </div>
  );
};