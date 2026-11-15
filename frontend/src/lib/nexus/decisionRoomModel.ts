/**
 * Decision Room UI gating — pure, backend-derived role rules.
 *
 * The backend owns authority: the durable APPROVED row is the only key into
 * EXECUTING, and the API rejects unauthorized approvals (403). These helpers
 * only decide what the UI shows — never what executes.
 */

/** Roles allowed to submit the human approval decision. */
const APPROVAL_ROLES = new Set(["operator", "admin"]);

export function canApproveDecision(role: string | null | undefined): boolean {
  return role !== null && role !== undefined && APPROVAL_ROLES.has(role);
}

/** Tailwind badge classes for a durable task status (presentation only). */
export function taskStatusBadgeClass(status: string): string {
  switch (status) {
    case "COMPLETED":
      return "bg-emerald-950 text-emerald-400 border border-emerald-800";
    case "APPROVED":
    case "EXECUTING":
      return "bg-blue-950 text-blue-400 border border-blue-800";
    case "AWAITING_APPROVAL":
    case "PROPOSED":
      return "bg-amber-950 text-amber-400 border border-amber-800";
    case "FAILED":
    case "BLOCKED":
    case "REJECTED":
      return "bg-red-950 text-red-400 border border-red-800";
    default:
      return "bg-zinc-900 text-zinc-300 border border-zinc-800";
  }
}

/** Tailwind badge classes for a capability invocation status. */
export function invocationStatusBadgeClass(status: string): string {
  switch (status) {
    case "SUCCESS":
      return "bg-emerald-950 text-emerald-400 border border-emerald-800";
    case "BLOCKED":
      return "bg-amber-950 text-amber-400 border border-amber-800";
    case "FAILED":
      return "bg-red-950 text-red-400 border border-red-800";
    default:
      return "bg-zinc-900 text-zinc-300 border border-zinc-800";
  }
}
