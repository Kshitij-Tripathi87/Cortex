"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavGroup {
  label: string;
  items: { href: string; label: string }[];
}

const GROUPS: NavGroup[] = [
  {
    label: "OPERATIONS",
    items: [
      { href: "/workspace/cockpit", label: "Mission Control" },
      { href: "/workspace/graph", label: "Dynamic World Graph" },
      { href: "/workspace/world", label: "World State & Timeline" },
    ],
  },
  {
    label: "DATA & ENTITIES",
    items: [
      { href: "/workspace/data", label: "Datasets & Quality" },
      { href: "/workspace/data#entities", label: "Entities" },
    ],
  },
  {
    label: "INTELLIGENCE",
    items: [
      { href: "/workspace/signals", label: "Signals & Anomalies" },
      { href: "/workspace/risk", label: "Risk & Blast Radius" },
      { href: "/workspace/analysis", label: "Analysis" },
      { href: "/workspace/analysis#ask", label: "Ask Nexus" },
    ],
  },
  {
    label: "MULTI-AGENT",
    items: [
      { href: "/workspace/agents/decision-room", label: "Decision Room" },
      { href: "/workspace/agents/tasks", label: "Task Graphs & Plans" },
      { href: "/workspace/agents/fleet", label: "Specialist Fleet" },
      { href: "/workspace/agents/training", label: "Training & Evaluation" },
      { href: "/workspace/agents/deployments", label: "Canary Deployments" },
    ],
  },
  {
    label: "SIMULATION & GOVERNANCE",
    items: [
      { href: "/workspace/scenarios", label: "Counterfactual Twin" },
      { href: "/workspace/decisions", label: "Governed Decisions" },
      { href: "/workspace/evidence", label: "Evidence" },
    ],
  },
];

export const NexusSidebar: React.FC = () => {
  const pathname = usePathname();
  const active = (href: string) => {
    const base = href.split("#")[0];
    return pathname === base || pathname.startsWith(base + "/");
  };

  return (
    <aside className="w-60 shrink-0 border-r border-border bg-bg flex flex-col select-none font-sans">
      <div className="flex-1 overflow-y-auto py-4">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-5">
            <div className="px-4 mb-1 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-ink-muted">
              {group.label}
            </div>
            <div>
              {group.items.map((item) => {
                const isActive = active(item.href);
                return (
                  <Link
                    key={item.href + item.label}
                    href={item.href}
                    aria-current={isActive ? "page" : undefined}
                    className={`flex items-center justify-between border-l-2 px-4 py-1.5 text-[13px] transition-colors ${
                      isActive
                        ? "border-accent bg-surface text-ink font-medium"
                        : "border-transparent text-ink-secondary hover:text-ink hover:bg-surface/60"
                    }`}
                  >
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};
