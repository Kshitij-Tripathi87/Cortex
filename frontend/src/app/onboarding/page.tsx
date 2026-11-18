/**
 * Onboarding boundary (B2 §9). Verifies the SERVER-created organization,
 * workspace, and trial from /auth/me, then acknowledges (per-user UI flag)
 * and continues. The ingestion wizard is B3's scope — not built here.
 *
 * The acknowledgement is kept per browser, so a returning user on a new
 * device sees this page again: nothing here may assume the account is new
 * or that its trial is still running.
 */

"use client";

import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { RequireAuth, useAuth, sanitizeNext, getOnboardingAck, setOnboardingAck } from "@/lib/auth";
import { planStatus } from "@/lib/auth/plan";
import { PlanPausedNotice } from "@/components/auth/PlanPausedNotice";

function OnboardingBody(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, workspace, organization } = useAuth();
  const next = sanitizeNext(searchParams?.get("next"));

  function cont(): void {
    if (user) setOnboardingAck(user.id);
    router.replace(next);
  }

  const plan = planStatus(organization);

  return (
    <div data-testid="onboarding-page" className="min-h-screen bg-bg text-ink flex items-center justify-center p-4">
      <div className="w-full max-w-lg bg-surface border border-border p-8">
        <p className="font-mono text-xs text-accent tracking-widest mb-2">NEXUS · SETUP</p>
        <h1 className="text-xl font-semibold">Your workspace is ready</h1>
        <p className="text-sm text-ink-secondary mt-1">
          Created from your signup — nothing left to configure here.
        </p>

        <dl className="mt-6 space-y-3 text-sm">
          <div className="flex justify-between border-b border-border pb-2">
            <dt className="text-ink-secondary">Organization</dt>
            <dd data-testid="onboarding-org" className="font-medium">
              {organization?.name ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between border-b border-border pb-2">
            <dt className="text-ink-secondary">Workspace</dt>
            <dd data-testid="onboarding-workspace" className="font-medium">
              {workspace?.name ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between border-b border-border pb-2">
            <dt className="text-ink-secondary">Signed in as</dt>
            <dd data-testid="onboarding-email" className="font-mono text-xs">
              {user?.email ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-secondary">Plan</dt>
            <dd data-testid="onboarding-trial" className="font-medium text-right">
              {plan ? `${plan.label}${plan.detail ? ` · ${plan.detail}` : ""}` : "—"}
            </dd>
          </div>
        </dl>
        <PlanPausedNotice testId="onboarding-plan-paused" className="mt-4" />

        <button
          onClick={cont}
          data-testid="onboarding-continue"
          className="mt-6 w-full bg-accent hover:bg-accent-hover text-white text-sm font-medium px-3 py-2.5"
        >
          Continue to Nexus
        </button>
        <p className="mt-3 text-xs text-ink-muted text-center">
          Next: open the Nexus workspace and upload your operational data.
        </p>
      </div>
    </div>
  );
}

export default function OnboardingPage(): React.JSX.Element {
  const { user, status } = useAuth();
  // Already acknowledged (e.g. deep link): skip straight through.
  if (status === "AUTHENTICATED" && user && getOnboardingAck(user.id)) {
    return (
      <RequireAuth>
        <OnboardingPassthrough />
      </RequireAuth>
    );
  }
  return (
    <RequireAuth>
      <OnboardingBody />
    </RequireAuth>
  );
}

function OnboardingPassthrough(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  React.useEffect(() => {
    router.replace(sanitizeNext(searchParams?.get("next")));
  }, [router, searchParams]);
  return (
    <div data-testid="onboarding-page" className="min-h-screen bg-bg text-ink flex items-center justify-center">
      <p className="text-sm text-ink-secondary">Setup already complete — continuing…</p>
    </div>
  );
}
