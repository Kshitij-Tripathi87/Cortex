/**
 * Reset password (?token=...). Redeems the single-use backend token. Invalid,
 * expired, and already-used tokens all render the same message (no oracle).
 */

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthAlert } from "@/components/auth/AuthAlert";
import { confirmPasswordReset } from "@/lib/api/auth";
import { resetPasswordSchema, toFieldErrors, authFormMessage, type FieldErrors } from "@/lib/auth";

export default function ResetPasswordPage(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams?.get("token") ?? "";
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setFormError(null);
    const parsed = resetPasswordSchema.safeParse({ token, newPassword, confirmPassword });
    if (!parsed.success) {
      setFieldErrors(toFieldErrors(parsed.error));
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      await confirmPasswordReset(parsed.data.token, parsed.data.newPassword);
      router.replace("/auth/login?reset=1");
    } catch (error) {
      // Uniform: the backend does not distinguish invalid/expired/used.
      setFormError(authFormMessage(error, "login"));
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <AuthShell title="Reset your password" subtitle="This reset link is incomplete." testId="reset-page">
        <AuthAlert tone="error" testId="reset-error">
          This reset link is missing its token. Request a new one to continue.
        </AuthAlert>
        <div className="mt-5 text-sm text-center">
          <Link href="/auth/forgot-password" className="text-ink-secondary hover:text-ink">
            Request a new link
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Choose a new password" subtitle="The link expires 30 minutes after issue." testId="reset-page">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <AuthField
          id="newPassword"
          label="New password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••••"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          error={fieldErrors.newPassword}
          hint="10+ characters, a letter and a digit."
          disabled={submitting}
        />
        <AuthField
          id="confirmPassword"
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••••"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          error={fieldErrors.confirmPassword}
          disabled={submitting}
        />
        {formError ? (
          <AuthAlert tone="error" testId="reset-error">
            {formError}
          </AuthAlert>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="reset-submit"
          className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium px-3 py-2.5"
        >
          {submitting ? "Resetting…" : "Reset password"}
        </button>
      </form>
    </AuthShell>
  );
}
