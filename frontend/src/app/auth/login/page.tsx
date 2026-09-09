/**
 * Login (B2 §4). Email + password only — the backend resolves the workspace
 * from the globally-unique email (B2 contract change). Every credential
 * failure renders the generic message; email is preserved, password stays
 * in the form only, and double-submit is disabled while pending.
 */

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthAlert } from "@/components/auth/AuthAlert";
import {
  useAuth,
  sanitizeNext,
  getOnboardingAck,
  loginSchema,
  toFieldErrors,
  authFormMessage,
  isApiClientError,
  type FieldErrors,
} from "@/lib/auth";

export default function LoginPage(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setFormError(null);
    const parsed = loginSchema.safeParse({ email, password });
    if (!parsed.success) {
      setFieldErrors(toFieldErrors(parsed.error));
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      const data = await login({ email: parsed.data.email, password: parsed.data.password });
      // Password must not outlive the submitted form.
      setPassword("");
      const next = sanitizeNext(searchParams?.get("next"));
      if (!getOnboardingAck(data.user.id)) {
        router.replace(`/onboarding?next=${encodeURIComponent(next)}`);
      } else {
        router.replace(next);
      }
    } catch (error) {
      // 422 from the server maps to field-level; everything else is generic.
      if (isApiClientError(error) && error.kind === "validation" && error.details) {
        setFormError(String(error.details));
      } else {
        setFormError(authFormMessage(error, "login"));
      }
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title="Log in to Nexus" subtitle="Operational decision intelligence." testId="login-page">
      {searchParams?.get("reset") === "1" ? (
        <div className="mb-4">
          <AuthAlert tone="success" testId="login-reset-notice">
            Password reset. Log in with your new password.
          </AuthAlert>
        </div>
      ) : null}
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          disabled={submitting}
        />
        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          disabled={submitting}
        />
        {formError ? (
          <AuthAlert tone="error" testId="login-error">
            {formError}
          </AuthAlert>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="login-submit"
          className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium px-3 py-2.5"
        >
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
      <div className="mt-5 flex items-center justify-between text-sm">
        <Link href="/auth/signup" className="text-ink-secondary hover:text-ink">
          Create account
        </Link>
        <Link href="/auth/forgot-password" className="text-ink-secondary hover:text-ink">
          Forgot password?
        </Link>
      </div>
    </AuthShell>
  );
}
