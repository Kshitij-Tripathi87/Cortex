/**
 * /auth/* segment: anonymous-only. Authenticated visitors bounce to `next`
 * (validated) or /app. Suspense boundary for useSearchParams (static export safe).
 */

"use client";

import React, { Suspense } from "react";
import { AuthChecking, RequireAnonymous } from "@/lib/auth";

export default function AuthLayout({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <Suspense fallback={<AuthChecking label="Loading…" />}>
      <RequireAnonymous>{children}</RequireAnonymous>
    </Suspense>
  );
}
