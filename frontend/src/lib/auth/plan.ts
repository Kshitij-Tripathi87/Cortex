/**
 * What the site says about an organization's plan.
 *
 * Whether a plan is active is the server's verdict
 * (`organization.subscription_active` from GET /auth/me, computed by the same
 * rule as the billing gate). Nothing here decides it from the browser's
 * clock; the clock is only used to say how many days of a running trial are
 * left.
 */

import type { AuthOrganization } from "./types";

/** Where a user asks for more time or a paid plan. Cortex has no self-serve billing. */
export const PLAN_CONTACT_HREF = "/contact?topic=sales#write";

/**
 * What an ended plan pauses, in the site's words. The server states the same
 * facts in its own sentence (PAUSED_ACTIONS in
 * backend/app/modules/billing/plans.py): change both when the gate changes.
 */
export const PAUSED_ACTIONS =
  "You can still sign in and see your data. Creating, running and approving tasks is paused.";

export interface PlanStatus {
  /** "Trial", "Trial ended", "Pro plan" … */
  label: string;
  /** "5 days left, ends 25 Nov 2026", "on 10 Nov 2026" …; empty when there is nothing to add. */
  detail: string;
  /** The server says the plan is not active. */
  paused: boolean;
  /** First sentence of the paused notice; null unless paused. */
  pausedReason: string | null;
}

type PlanFields = Pick<AuthOrganization, "plan" | "trial_ends_at" | "subscription_active">;

const DAY_MS = 86_400_000;

const PLAN_NAMES: Record<string, string> = {
  free: "Free plan",
  pro: "Pro plan",
  enterprise: "Enterprise plan",
};

/** "10 Nov 2026": unambiguous in every country, same form as the API's refusal text. */
export function formatDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function planStatus(
  organization: PlanFields | null | undefined,
  now: Date = new Date(),
): PlanStatus | null {
  if (!organization) return null;
  // Only an explicit "false" pauses: an API that does not send the field yet
  // must not make the site announce an ended plan.
  const paused = organization.subscription_active === false;
  const day = formatDay(organization.trial_ends_at);

  if (organization.plan === "trial") {
    if (paused) {
      return {
        label: "Trial ended",
        detail: day ? `on ${day}` : "",
        paused,
        pausedReason: day ? `Your trial ended on ${day}.` : "Your trial has ended.",
      };
    }
    if (!day || !organization.trial_ends_at) {
      return { label: "Trial", detail: "no end date", paused, pausedReason: null };
    }
    const remaining = new Date(organization.trial_ends_at).getTime() - now.getTime();
    let left = "";
    if (remaining >= DAY_MS) {
      // A started day counts as a day; the exact end day follows anyway.
      const days = Math.ceil(remaining / DAY_MS);
      left = `${days} day${days === 1 ? "" : "s"} left, `;
    } else if (remaining > 0) {
      left = "less than a day left, ";
    }
    return { label: "Trial", detail: `${left}ends ${day}`, paused, pausedReason: null };
  }

  const name = PLAN_NAMES[organization.plan] ?? `Plan "${organization.plan}"`;
  if (paused) {
    return {
      label: name,
      detail: "not active",
      paused,
      pausedReason: "Your plan is not active.",
    };
  }
  return { label: name, detail: "", paused, pausedReason: null };
}
