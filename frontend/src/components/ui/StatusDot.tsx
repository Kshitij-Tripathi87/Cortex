import React from "react";

export type StatusDotState = "live" | "reconnecting" | "syncing" | "offline" | "idle";

const COLORS: Record<StatusDotState, string> = {
  live: "bg-accent",
  reconnecting: "bg-warning",
  syncing: "bg-warning",
  offline: "bg-critical",
  idle: "bg-ink-muted",
};

interface StatusDotProps {
  state: StatusDotState;
  pulse?: boolean;
  className?: string;
}

export function StatusDot({ state, pulse = false, className = "" }: StatusDotProps) {
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full ${COLORS[state]} ${
        pulse ? "animate-pulse" : ""
      } ${className}`}
      role="presentation"
    />
  );
}
