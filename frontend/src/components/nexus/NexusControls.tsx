"use client";

import React from "react";

interface NexusControlsProps {
  stage: string;
  disruption: string | null;
  response: string | null;
  onStart: (disruption: string) => void;
  onResponse: (response: string) => void;
  onReset: () => void;
}

export const NexusControls: React.FC<NexusControlsProps> = ({
  stage,
  disruption,
  response,
  onStart,
  onResponse,
  onReset,
}) => {
  const isActive = stage !== "baseline";

  return (
    <div className="flex flex-wrap items-center gap-4 mb-6 p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
      <div className="flex items-center gap-3">
        <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">
          Stage:
        </span>
        <span
          className={`px-3 py-1 rounded-full text-[10px] font-mono font-bold uppercase ${
            stage === "baseline"
              ? "bg-zinc-800 text-zinc-400"
              : stage === "detecting"
              ? "bg-amber-900/30 text-amber-400"
              : stage === "evaluating"
              ? "bg-blue-900/30 text-blue-400"
              : "bg-emerald-900/30 text-emerald-400"
          }`}
        >
          {stage}
        </span>
      </div>

      <div className="flex-1 flex flex-wrap items-center gap-3" role="group" aria-label="Disruption controls">
        {!isActive ? (
          <button
            type="button"
            onClick={() => onStart("supplier-delay")}
            className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-zinc-950 font-mono font-bold text-[11px] transition-colors"
            aria-label="Start supplier delay disruption simulation"
          >
            Start Disruption
          </button>
        ) : (
          <>
            <span className="text-[11px] font-mono text-zinc-400 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" aria-hidden="true" />
              Active: Supplier Delay
            </span>

            {stage === "evaluating" && response === null && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-zinc-500">Response:</span>
                <button
                  type="button"
                  onClick={() => onResponse("alt-supplier-a")}
                  className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-[10px] font-mono text-zinc-300 transition"
                >
                  Qualify Alt Supplier A
                </button>
                <button
                  type="button"
                  onClick={() => onResponse("air-freight")}
                  className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-[10px] font-mono text-zinc-300 transition"
                >
                  Activate Air Freight
                </button>
                <button
                  type="button"
                  onClick={() => onResponse("inventory-buffer")}
                  className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-[10px] font-mono text-zinc-300 transition"
                >
                  Release Buffer Stock
                </button>
              </div>
            )}

            {stage === "validated" && (
              <span className="text-[11px] font-mono text-emerald-400 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400" aria-hidden="true" />
                Mitigation Validated
              </span>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        onClick={onReset}
        className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-[11px] font-mono text-zinc-300 transition"
        aria-label="Reset simulation to baseline"
      >
        Reset
      </button>
    </div>
  );
};