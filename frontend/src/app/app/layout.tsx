/**
 * /app segment: authenticated + onboarding acknowledged. Fresh signups land
 * on /onboarding first; direct deep links to /app redirect there until acked.
 */

"use client";

import React, { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthChecking, RequireAuth, useAuth, getOnboardingAck } from "@/lib/auth";

function AckGate({ children }: { children: React.ReactNode }): React.JSX.Element {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user && !getOnboardingAck(user.id)) {
      router.replace("/onboarding?next=%2Fapp");
    }
  }, [user, router]);

  if (user && !getOnboardingAck(user.id)) {
    return <AuthChecking label="Redirecting…" />;
  }
  return <>{children}</>;
}

export default function AppLayout({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <Suspense fallback={<AuthChecking />}>
      <RequireAuth>
        <AckGate>{children}</AckGate>
      </RequireAuth>
    </Suspense>
  );
}
