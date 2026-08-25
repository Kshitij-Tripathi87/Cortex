/**
 * Badge component — for status, severity, and category tags.
 */

type BadgeVariant = "default" | "success" | "warning" | "error" | "info" | "neutral";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  default: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  warning: "bg-yellow-100 text-yellow-800",
  error: "bg-red-100 text-red-800",
  info: "bg-indigo-100 text-indigo-800",
  neutral: "bg-gray-100 text-gray-800",
};

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
}

export function Badge({ variant = "default", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded ${VARIANT_CLASSES[variant]}`}
    >
      {children}
    </span>
  );
}

/**
 * Severity badge — maps severity strings to variants.
 */
export function SeverityBadge({ severity }: { severity: string }) {
  const variantMap: Record<string, BadgeVariant> = {
    info: "info",
    warning: "warning",
    critical: "error",
    blocking: "error",
    success: "success",
  };
  const variant = variantMap[severity.toLowerCase()] || "neutral";
  return <Badge variant={variant}>{severity}</Badge>;
}

/**
 * Status badge — maps status strings to variants.
 */
export function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, BadgeVariant> = {
    pending: "neutral",
    approved: "success",
    rejected: "error",
    deferred: "warning",
    escalated: "warning",
    implemented: "success",
    closed: "neutral",
    completed: "success",
    failed: "error",
    running: "info",
    success: "success",
    partial_success: "warning",
    no_impact: "neutral",
    unintended_consequences: "error",
  };
  const variant = variantMap[status.toLowerCase()] || "default";
  return <Badge variant={variant}>{status}</Badge>;
}
