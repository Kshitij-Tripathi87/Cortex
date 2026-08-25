"use client";

import React from "react";
import Link from "next/link";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { StatusDot } from "@/components/ui";

interface NexusHeaderProps {
  onInjectEvent?: () => void;
  onOpenQueryModal?: () => void;
}

const LIVE_LABEL: Record<string, { state: "live" | "reconnecting" | "offline"; text: string }> = {
  LIVE: { state: "live", text: "LIVE" },
  RECONNECTING: { state: "reconnecting", text: "RECONNECTING" },
  OFFLINE: { state: "offline", text: "OFFLINE" },
};

export const NexusHeader: React.FC<NexusHeaderProps> = ({
  onInjectEvent,
  onOpenQueryModal,
}) => {
  const { realtimeStatus, workspaceName, environmentLabel } = useNexusWorkspace();
  const live = LIVE_LABEL[realtimeStatus] ?? LIVE_LABEL.OFFLINE;

  return (
    <header className="h-12 shrink-0 border-b border-border bg-bg px-4 flex items-center justify-between font-sans">
      {/* Brand + workspace + environment */}
      <div className="flex items-center gap-3">
        <Link href="/workspace/cockpit" className="text-[13px] font-bold tracking-tight text-ink hover:text-ink">
          CORTEX NEXUS
        </Link>
        <span className="text-ink-muted text-xs">/</span>
        <button
          type="button"
          className="flex items-center gap-1.5 h-7 px-2 border border-border bg-surface text-[11px] text-ink-secondary hover:bg-surface-2"
          title="Workspace"
        >
          <span className="font-mono text-[9px] uppercase text-ink-muted">WS</span>
          <span className="text-ink">{workspaceName}</span>
          <span className="text-ink-muted text-[9px]">▾</span>
        </button>
        <span className="flex items-center h-7 px-2 border border-border bg-surface text-[10px] font-mono uppercase tracking-wider text-ink-secondary">
          ENV: <span className="ml-1 text-ink">{environmentLabel}</span>
        </span>
      </div>

      {/* Live connection + ask + user */}
      <div className="flex items-center gap-2">
        <span
          className="flex items-center gap-1.5 h-7 px-2 border border-border bg-surface text-[10px] font-mono"
          title={
            live.state === "live"
              ? "Realtime connection established and authoritative state synchronized"
              : "Realtime not synchronized"
          }
        >
          <StatusDot state={live.state} pulse={live.state === "live"} />
          <span className={live.state === "live" ? "text-accent font-semibold" : live.state === "reconnecting" ? "text-warning" : "text-critical"}>
            {live.text}
          </span>
        </span>

        {onInjectEvent && (
          <button
            type="button"
            onClick={onInjectEvent}
            className="h-7 px-2.5 border border-border bg-surface text-[11px] text-ink-secondary hover:bg-surface-2"
            title="Inject live operational event"
          >
            + Event
          </button>
        )}

        <button
          type="button"
          onClick={onOpenQueryModal}
          className="h-7 px-2.5 bg-ink text-bg text-[11px] font-semibold hover:bg-zinc-200"
        >
          Ask Nexus
          <span className="ml-1.5 font-mono text-[9px] bg-bg/20 px-1 py-0.5">⌘K</span>
        </button>

        <button
          type="button"
          className="h-7 px-2 border border-border bg-surface text-[11px] text-ink-secondary hover:bg-surface-2"
          title="Account"
        >
          User <span className="text-ink-muted text-[9px]">▾</span>
        </button>
      </div>
    </header>
  );
};
