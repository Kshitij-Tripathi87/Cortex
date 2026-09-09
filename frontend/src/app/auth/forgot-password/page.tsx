/**
 * Forgot password. Always renders the uniform message — the backend never
 * reveals whether an email exists, and neither do we. The reset token (if
 * any) is delivered out-of-band, never rendered here.
 */

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthAlert } from "@/components/auth/AuthAlert";
import { requestPasswordReset } from "@/lib/api/auth";
import { forgotPasswordSchema, toFieldErrors, type FieldErrors } from "@/lib/auth";

export default function ForgotPasswordPage(): React.JSX.Element {
  const [email, setEmail] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    const parsed = forgotPasswordSchema.safeParse({ email });
    if (!parsed.success) {
      setFieldErrors(toFieldErrors(parsed.error));
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      // Uniform outcome by design: success AND unknown-email render alike.
      await requestPasswordReset(parsed.data.email);
    } catch {
      // Even backend failures render the uniform message — no oracle.
    } finally {
      setSubmitting(false);
      setDone(true);
    }
  }

  return (
    <AuthShell title="Reset your password" subtitle="We will email you a reset link." testId="forgot-page">
      {done ? (
        <AuthAlert tone="info" testId="forgot-done">
          If an account exists for that email, a reset link is on its way. The link expires in 30
          minutes and can be used once.
        </AuthAlert>
      ) : (
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
          <button
            type="submit"
            disabled={submitting}
            data-testid="forgot-submit"
            className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium px-3 py-2.5"
          >
            {submitting ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
      <div className="mt-5 text-sm text-center">
        <Link href="/auth/login" className="text-ink-secondary hover:text-ink">
          Back to login
        </Link>
      </div>
    </AuthShell>
  );
}
