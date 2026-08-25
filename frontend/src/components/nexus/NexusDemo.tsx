"use client";

import React, { useReducer, useMemo } from "react";
import { NexusState, NexusAction, initialNexusState, nexusReducer } from "./nexus-types";
import { deriveScenario } from "./nexus-selectors";
import { NexusControls } from "./NexusControls";
import { NexusMetrics } from "./NexusMetrics";
import { NexusExplanation } from "./NexusExplanation";
import { OperationalGraph } from "@/components/graph/OperationalGraph";

interface NexusDemoProps {
  reducedMotion?: boolean;
}

export const NexusDemo: React.FC<NexusDemoProps> = ({ reducedMotion = false }) => {
  const [state, dispatch] = useReducer(nexusReducer, initialNexusState);

  const scenario = useMemo(() => deriveScenario(state), [state]);

  return (
    <section className="nexus-demo space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">
            Nexus Operational Disruption Graph
          </h2>
          <p className="text-zinc-400 text-sm mt-1 font-mono">
            Interactive supply chain risk propagation & mitigation
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-[11px] font-mono text-zinc-400">
            <input
              type="checkbox"
              checked={reducedMotion}
              onChange={(e) => console.log("Reduced motion:", e.target.checked)}
              className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-amber-500 focus:ring-amber-500"
            />
            Reduced Motion
          </label>
        </div>
      </div>

      <NexusControls
        stage={state.stage}
        disruption={state.disruption}
        response={state.response}
        onStart={(d) => dispatch({ type: "START_DISRUPTION", disruption: d })}
        onResponse={(r) => dispatch({ type: "SET_RESPONSE", response: r })}
        onReset={() => dispatch({ type: "RESET" })}
      />

      <OperationalGraph
        scenario={scenario}
        stage={state.stage}
        selectedNodeId={state.selectedNodeId}
        onNodeSelect={(nodeId) => dispatch({ type: "SELECT_NODE", nodeId })}
        reducedMotion={reducedMotion}
        showBackground={true}
        showLegend={true}
      />

      <NexusMetrics metrics={scenario.metrics} />

      <NexusExplanation stage={state.stage} disruption={state.disruption} response={state.response} />
    </section>
  );
};