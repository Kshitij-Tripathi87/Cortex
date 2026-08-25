"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export const DemoWalkthroughGuide: React.FC = () => {
  const router = useRouter();
  const {
    worldStateVersion,
    decisionFreshnessState,
    injectStreamEvent,
    redeliberate,
    openWhyModal,
    launchIntent,
    setActiveWorkflowStep,
  } = useNexusWorkspace();

  const [isOpen, setIsOpen] = useState(false);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);

  const demoSteps = [
    {
      time: "00:00",
      title: "1. Workspace Entry & Snapshot Baseline",
      description: "Inspect active world state v101, connection status ONLINE, and authoritative 2-hop baseline.",
      actionLabel: "Go to Mission Control Cockpit →",
      action: () => router.push("/workspace/cockpit"),
    },
    {
      time: "00:15",
      title: "2. Data Ingestion & 5-Dimension Audit",
      description: "Review ingested operational tables (sellers, orders, routes) and verified 100% schema completeness.",
      actionLabel: "View Data Quality Profiler →",
      action: () => router.push("/workspace/data"),
    },
    {
      time: "01:00",
      title: "3. Operational Graph & SPOF Centrality",
      description: "Inspect focal entity seller_01a00b8e99 (PageRank: 0.042) flagged as Single Point of Failure bottleneck.",
      actionLabel: "Inspect Interactive Graph →",
      action: () => {
        launchIntent("INVESTIGATE_ENTITY", "seller_01a00b8e99", "route_SP_to_RJ");
        router.push("/workspace/graph");
      },
    },
    {
      time: "01:40",
      title: "4. Anomaly Signals & Financial Exposure",
      description: "GNN anomaly detector flagged +90% dispatch delay breach, exposing $1,746.00 USD across 12 orders.",
      actionLabel: "Why This Signal? ❓",
      action: () => openWhyModal("SIGNAL"),
    },
    {
      time: "02:00",
      title: "5. Natural Language Reasoning ('Ask Nexus')",
      description: "Query operational intent with preflight answerability report and citation lineage.",
      actionLabel: "Open Reasoning Console →",
      action: () => router.push("/workspace/reasoning"),
    },
    {
      time: "02:40",
      title: "6. Specialist Swarm Deliberation",
      description: "Logistics Routing Specialist (v4) and Risk Analyst reach 0.94 consensus proposing Candidate C air freight.",
      actionLabel: "Why These Agents? ❓",
      action: () => openWhyModal("AGENT"),
    },
    {
      time: "03:30",
      title: "7. Counterfactual Twin Simulation",
      description: "Monte Carlo simulation (1,000 runs) compares Candidates A, B, C, D; Candidate C yields +$2,900.00 Net Economic Value.",
      actionLabel: "Why Candidate C? ❓",
      action: () => openWhyModal("SCENARIO"),
    },
    {
      time: "04:40",
      title: "8. Governed Operator Approval",
      description: "Owner (Procurement) and Reviewer (COO) approve Candidate C and dispatch automated execution webhooks.",
      actionLabel: "Return to Cockpit for Sign-Off →",
      action: () => router.push("/workspace/cockpit"),
    },
    {
      time: "05:00",
      title: "9. Live Stream Mutation & Temporal Invalidation",
      description: "Simulate live telemetry delta mutating seller_01a00b8e99 (World State v101 -> v102), invalidating stale decision.",
      actionLabel: "⚡ Trigger Stream Mutation",
      action: () => {
        injectStreamEvent();
        router.push("/workspace/cockpit");
      },
    },
    {
      time: "05:30",
      title: "10. Swarm Redeliberation & Re-Approval",
      description: "Agents re-deliberate on mutated state in <600ms, restoring verified policy status against World State v102.",
      actionLabel: "Trigger Swarm Redeliberation ↺",
      action: () => {
        redeliberate();
        router.push("/workspace/cockpit");
      },
    },
  ];

  const currentStep = demoSteps[currentStepIndex];

  return (
    <>
      {/* Floating Demo Launcher Button */}
      <div className="fixed bottom-4 right-4 z-40">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="px-3 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-zinc-200 font-mono text-xs flex items-center gap-2 transition"
        >
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span className="font-bold">Working Demo Script Guide (6-Min)</span>
          <span className="text-[10px] text-zinc-500">[{currentStepIndex + 1}/{demoSteps.length}]</span>
        </button>
      </div>

      {/* Slide-Up Guide Modal / Drawer */}
      {isOpen && (
        <div className="fixed bottom-16 right-4 z-40 w-96 bg-zinc-950 border border-zinc-700 rounded-xl p-4 font-mono text-xs space-y-3 animate-fadeIn text-zinc-100">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
            <div>
              <span className="text-[9px] uppercase font-bold text-zinc-500 block">
                NEXUS 1.0 WORKING DEMO EXECUTION PACK
              </span>
              <h3 className="font-bold text-zinc-100 mt-0.5">{currentStep.title}</h3>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-500 hover:text-white text-xs w-6 h-6 rounded flex items-center justify-center bg-zinc-900"
            >
              ✕
            </button>
          </div>

          <div className="p-2.5 bg-zinc-900/60 border border-zinc-800 rounded space-y-1">
            <div className="flex items-center justify-between text-[10px] text-zinc-400">
              <span>Timestamp: <strong>{currentStep.time}</strong></span>
              <span className="text-emerald-400 font-bold">CONTROLLED DEMO</span>
            </div>
            <p className="text-[11px] text-zinc-300 font-sans leading-relaxed">
              {currentStep.description}
            </p>
          </div>

          {/* Action Trigger */}
          <button
            onClick={currentStep.action}
            className="w-full py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold text-xs transition font-sans"
          >
            {currentStep.actionLabel}
          </button>

          {/* Step Navigation Controls */}
          <div className="flex items-center justify-between pt-1 border-t border-zinc-800 text-[10px] text-zinc-400">
            <button
              onClick={() => setCurrentStepIndex((prev) => Math.max(0, prev - 1))}
              disabled={currentStepIndex === 0}
              className="px-2 py-1 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-30 rounded border border-zinc-800"
            >
              ← Previous
            </button>
            <span>Step {currentStepIndex + 1} of {demoSteps.length}</span>
            <button
              onClick={() => setCurrentStepIndex((prev) => Math.min(demoSteps.length - 1, prev + 1))}
              disabled={currentStepIndex === demoSteps.length - 1}
              className="px-2 py-1 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-30 rounded border border-zinc-800"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </>
  );
};
