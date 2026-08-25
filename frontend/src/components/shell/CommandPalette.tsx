"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export const CommandPalette: React.FC = () => {
  const router = useRouter();
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    launchIntent,
    setGraphMode,
    setProgressiveLevel,
    injectStreamEvent,
    redeliberate,
    setActiveWorkflowStep,
    setBenchmarkScale,
    setHistoricalVersion,
    openWhyModal,
  } = useNexusWorkspace();

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Keyboard shortcut listener: Cmd+K or Ctrl+K or /
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if (e.key === "Escape" && commandPaletteOpen) {
        setCommandPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  if (!commandPaletteOpen) return null;

  const operationalCommands = [
    // 1. Primary Operator Intents
    {
      id: "cmd_investigate_seller",
      category: "OPERATOR ACTIONS",
      title: "Investigate Seller 01a00b8e99",
      subtitle: "Lock workspace context to 2-hop ego network & degradation signals",
      icon: "🔍",
      action: () => {
        launchIntent("INVESTIGATE_ENTITY", "seller_01a00b8e99", "route_SP_to_RJ");
        setActiveWorkflowStep(1);
        router.push("/workspace/cockpit");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_high_risk_routes",
      category: "OPERATOR ACTIONS",
      title: "Show high-risk routes (Corridor BR-116)",
      subtitle: "Filter graph to risk transit corridors with SLA breach > 50%",
      icon: "🎯",
      action: () => {
        setGraphMode("RISK");
        router.push("/workspace/graph");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_open_incident",
      category: "OPERATOR ACTIONS",
      title: "Open current incident (INC-2026-0899)",
      subtitle: "Jump to 3-column Mission Control Cockpit (Why | Affected | To Do)",
      icon: "⚡",
      action: () => {
        router.push("/workspace/cockpit");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_simulate_failure",
      category: "OPERATOR ACTIONS",
      title: "Simulate Seller 01a00b8e99 failure",
      subtitle: "Run digital twin disruption scenario with 100% capacity loss",
      icon: "🔮",
      action: () => {
        launchIntent("SIMULATE_DISRUPTION", "seller_01a00b8e99", "scenario_seller_loss");
        setActiveWorkflowStep(5);
        router.push("/workspace/cockpit");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_invalidated_decisions",
      category: "OPERATOR ACTIONS",
      title: "Show invalidated decisions & state drift",
      subtitle: "Review policy decisions invalidated by live world state mutation",
      icon: "⚠️",
      action: () => {
        router.push("/workspace/decisions");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_agent_fleet",
      category: "OPERATOR ACTIONS",
      title: "Open agent fleet & replica metrics",
      subtitle: "Inspect multi-agent consensus, canary splits, and p95 latency",
      icon: "🤖",
      action: () => {
        router.push("/workspace/agents/fleet");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "cmd_jump_v101",
      category: "OPERATOR ACTIONS",
      title: "Jump to World State v101 (Authoritative Snapshot)",
      subtitle: "Reconstruct graph and decisions at historical baseline snapshot",
      icon: "⏱️",
      action: () => {
        setHistoricalVersion(101);
        router.push("/workspace/world");
        setCommandPaletteOpen(false);
      },
    },

    // 2. Data-First "Why am I seeing this?"
    {
      id: "why_signal",
      category: "DATA REASONING",
      title: "Why this signal? (SELLER_DEGRADATION +90%)",
      subtitle: "Explain statistical baseline 2.0d -> 3.8d and raw CSV row #482",
      icon: "❓",
      action: () => {
        openWhyModal("SIGNAL");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "why_agent",
      category: "DATA REASONING",
      title: "Why this agent? (Logistics Specialist v4)",
      subtitle: "Explain domain assignment for BR-116 multimodal dispatch",
      icon: "❓",
      action: () => {
        openWhyModal("AGENT");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "why_recommendation",
      category: "DATA REASONING",
      title: "Why this recommendation? (Candidate C Air Freight)",
      subtitle: "Explain +$2,900.00 Net Economic Value and 98% SLA protection",
      icon: "❓",
      action: () => {
        openWhyModal("RECOMMENDATION");
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "why_invalidation",
      category: "DATA REASONING",
      title: "Why is this decision invalid? (State Drift)",
      subtitle: "Explain real-time telemetry mutation breaking decision freshness",
      icon: "❓",
      action: () => {
        openWhyModal("INVALIDATION");
        setCommandPaletteOpen(false);
      },
    },

    // 3. Execution & Telemetry
    {
      id: "act_mutate",
      category: "STREAM SIMULATION",
      title: "Inject Live Real-Time Event (World State Mutation)",
      subtitle: "Simulate live telemetry stream delta to test invalidation guard",
      icon: "⚡",
      action: () => {
        injectStreamEvent();
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "act_redeliberate",
      category: "STREAM SIMULATION",
      title: "Trigger Multi-Agent Swarm Redeliberation",
      subtitle: "Re-run agent swarm on mutated world state and re-validate policy",
      icon: "🤖",
      action: () => {
        redeliberate();
        setCommandPaletteOpen(false);
      },
    },
    {
      id: "act_bench_10k",
      category: "PERFORMANCE BENCHMARK",
      title: "Benchmark Scale: 10,000 Nodes (Stress Test)",
      subtitle: "Stress test browser canvas rendering and WebWorker layout at 60 FPS",
      icon: "🚀",
      action: () => {
        setBenchmarkScale(10000);
        router.push("/workspace/graph");
        setCommandPaletteOpen(false);
      },
    },
  ];

  const filteredCommands = operationalCommands.filter(
    (c) =>
      c.title.toLowerCase().includes(query.toLowerCase()) ||
      c.subtitle.toLowerCase().includes(query.toLowerCase()) ||
      c.category.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/70 animate-fadeIn">
      <div className="w-full max-w-2xl bg-zinc-950 border border-zinc-700/80 rounded-xl shadow-2xl overflow-hidden font-mono text-zinc-100 flex flex-col">
        {/* Input Bar */}
        <div className="flex items-center px-4 py-3 border-b border-zinc-800 bg-zinc-900/60">
          <span className="text-emerald-400 mr-3 text-sm font-bold">❯</span>
          <input
            type="text"
            autoFocus
            placeholder="Operator command (e.g. 'Investigate Seller', 'High-risk routes', 'Why this signal')..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            className="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none"
          />
          <kbd className="text-[10px] text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded border border-zinc-700">ESC</kbd>
        </div>

        {/* Results List */}
        <div className="max-h-96 overflow-y-auto p-2 divide-y divide-zinc-900">
          {filteredCommands.length === 0 ? (
            <div className="py-8 text-center text-xs text-zinc-500">
              No matching operator command for &quot;{query}&quot;
            </div>
          ) : (
            filteredCommands.map((item, idx) => (
              <button
                key={item.id}
                onClick={item.action}
                onMouseEnter={() => setSelectedIndex(idx)}
                className={`w-full flex items-center justify-between p-2.5 rounded-lg text-left transition ${
                  selectedIndex === idx ? "bg-zinc-800 text-white" : "text-zinc-300 hover:bg-zinc-900"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="text-base">{item.icon}</span>
                  <div>
                    <div className="text-xs font-semibold text-zinc-100">{item.title}</div>
                    <div className="text-[11px] text-zinc-400">{item.subtitle}</div>
                  </div>
                </div>
                <span className="text-[9px] uppercase tracking-wider text-zinc-500 font-bold px-2 py-0.5 bg-zinc-900 rounded border border-zinc-800">
                  {item.category}
                </span>
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-zinc-800/80 bg-zinc-900/40 text-[10px] text-zinc-500">
          <div className="flex items-center gap-3">
            <span>↑↓ Select</span>
            <span>↵ Execute</span>
            <span>ESC Dismiss</span>
          </div>
          <span className="text-zinc-400">Nexus Operator Console</span>
        </div>
      </div>
    </div>
  );
};
