import type { DecisionBrief } from "./api/client";

export function formatUsd(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

export function formatHours(n: number): string {
  if (n >= 24) return `${Math.round(n / 24)}d`;
  return `${Math.round(n)}h`;
}

export function formatPct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export function severityFromScore(score: number): "low" | "medium" | "high" | "critical" {
  if (score >= 70) return "critical";
  if (score >= 40) return "high";
  if (score >= 15) return "medium";
  return "low";
}

export function severityColor(s: ReturnType<typeof severityFromScore>): string {
  return {
    low: "bg-emerald-100 text-emerald-800 border-emerald-300",
    medium: "bg-amber-100 text-amber-800 border-amber-300",
    high: "bg-orange-100 text-orange-800 border-orange-300",
    critical: "bg-red-100 text-red-800 border-red-300",
  }[s];
}

export function severityHeader(s: ReturnType<typeof severityFromScore>): string {
  return {
    low: "Routine - monitor only",
    medium: "Elevated - act within 48h",
    high: "High - act within 24h",
    critical: "Critical - act now",
  }[s];
}

export function deadlineLabel(hours: number): string {
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}

export function confidenceLabel(overall: number): { label: string; tone: string } {
  if (overall >= 0.8) return { label: "High", tone: "text-emerald-700" };
  if (overall >= 0.6) return { label: "Moderate", tone: "text-amber-700" };
  if (overall >= 0.4) return { label: "Limited", tone: "text-orange-700" };
  return { label: "Low", tone: "text-red-700" };
}

export function totalAffected(b: DecisionBrief): number {
  return (
    b.propagation.affected_components.length +
    b.propagation.affected_products.length +
    b.propagation.affected_warehouses.length +
    b.propagation.open_orders_at_risk.length
  );
}
