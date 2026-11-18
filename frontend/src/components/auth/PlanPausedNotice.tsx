/**
 * Shown to a signed-in user whose plan is not active (a trial that ended).
 *
 * Without it the only sign was a refused action. It says what ended, what
 * still works, what is paused, and where to ask for more time: the contact
 * form, because Cortex has no self-serve billing. A member of the team then
 * extends the trial or sets a plan (backend/scripts/admin_orgs.py).
 */

"use client";

import React from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { PAUSED_ACTIONS, PLAN_CONTACT_HREF, planStatus } from "@/lib/auth/plan";

export function PlanPausedMessage({
  reason,
  testId,
  className = "",
}: {
  reason: string;
  testId: string;
  className?: string;
}): React.JSX.Element {
  return (
    <div
      role="status"
      data-testid={testId}
      className={`border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-ink ${className}`}
    >
      <span className="font-medium">{reason}</span> {PAUSED_ACTIONS}{" "}
      <Link
        href={PLAN_CONTACT_HREF}
        data-testid={`${testId}-contact`}
        className="font-medium underline underline-offset-2 hover:text-accent"
      >
        Write to us to continue
      </Link>
      .
    </div>
  );
}

/** The notice for the signed-in user's own organization; renders nothing while the plan is active. */
export function PlanPausedNotice({
  testId = "plan-paused",
  className,
}: {
  testId?: string;
  className?: string;
}): React.JSX.Element | null {
  const { status, organization } = useAuth();
  if (status !== "AUTHENTICATED") return null;
  const plan = planStatus(organization);
  if (!plan?.paused || !plan.pausedReason) return null;
  return <PlanPausedMessage reason={plan.pausedReason} testId={testId} className={className} />;
}
