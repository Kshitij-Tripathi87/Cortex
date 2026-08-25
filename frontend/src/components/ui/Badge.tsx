import React from "react";

export type BadgeVariant =
  | "neutral"
  | "accent"
  | "warning"
  | "critical"
  | "info";

const VARIANTS: Record<BadgeVariant, string> = {
  neutral: "bg-surface-2 text-ink-secondary border-border",
  accent: "bg-accent-subtle text-accent border-accent/40",
  warning: "bg-warning-subtle text-warning border-warning/40",
  critical: "bg-critical-subtle text-critical border-critical/40",
  info: "bg-surface-2 text-ink-secondary border-border",
};

interface BadgeProps {
  variant?: BadgeVariant;
  className?: string;
  children: React.ReactNode;
}

export function Badge({ variant = "neutral", className = "", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
