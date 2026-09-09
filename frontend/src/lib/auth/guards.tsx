/**
 * Route guards (B2 §3). Render a deterministic loader while CHECKING so
 * protected content never flashes; redirect anonymous users with a
 * validated `next`, and bounce authenticated users off auth pages.
 *
 * Each guard wraps its hook-using inner component in Suspense: Next 14
 * requires a Suspense boundary above useSearchParams for prerendering,
 * and guards are mounted in layouts that cannot all add one.
 */

"use client";

import React, { Suspense, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { sanitizeNext } from "@/lib/auth/next";

export function AuthChecking({ label = "Verifying session…" }: { label?: string }): React.JSX.Element {
  return (
    <div
      data-testid="auth-checking"
      className="min-h-screen bg-bg text-ink flex items-center justify-center"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <span
          data-testid="auth-checking-spinner"
          className="inline-block w-5 h-5 border-2 border-border-strong border-t-accent rounded-full animate-spin"
          aria-hidden="true"
        />
        <span className="text-sm text-ink-secondary">{label}</span>
      </div>
    </div>
  );
}

function RequireAuthInner({ children }: { children: React.ReactNode }): React.JSX.Element {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status === "ANONYMOUS") {
      const here = searchParams?.toString() ? `${pathname}?${searchParams.toString()}` : (pathname ?? "/app");
      router.replace(`/auth/login?next=${encodeURIComponent(here)}`);
    }
  }, [status, router, pathname, searchParams]);

  if (status !== "AUTHENTICATED") {
    return <AuthChecking />;
  }
  return <>{children}</>;
}

export function RequireAuth({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <Suspense fallback={<AuthChecking />}>
      <RequireAuthInner>{children}</RequireAuthInner>
    </Suspense>
  );
}

function RequireAnonymousInner({ children }: { children: React.ReactNode }): React.JSX.Element {
  const { status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status === "AUTHENTICATED") {
      router.replace(sanitizeNext(searchParams?.get("next")));
    }
  }, [status, router, searchParams]);

  if (status === "UNKNOWN" || status === "CHECKING") {
    return <AuthChecking label="Loading…" />;
  }
  if (status === "AUTHENTICATED") {
    return <AuthChecking label="Redirecting…" />;
  }
  return <>{children}</>;
}

export function RequireAnonymous({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <Suspense fallback={<AuthChecking label="Loading…" />}>
      <RequireAnonymousInner>{children}</RequireAnonymousInner>
    </Suspense>
  );
}
