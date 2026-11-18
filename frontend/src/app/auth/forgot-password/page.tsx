/**
 * Forgot password.
 *
 * Cortex sends no email. Submitting records the request on the server; a
 * member of the team then sends a single-use reset link to the address on
 * the account by hand (backend/scripts/admin_users.py). The page says exactly
 * that: it must never promise a message that nothing will send.
 *
 * The outcome is the same for a known and an unknown email (the backend never
 * reveals whether an account exists, and neither do we). A request that could
 * not be recorded at all is different: nobody will ever see it, so the user is
 * told and can try again.
 */

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthAlert } from "@/components/auth/AuthAlert";
import { requestPasswordReset } from "@/lib/api/auth";
import { isApiClientError } from "@/lib/auth/errors";
import { forgotPasswordSchema, toFieldErrors, type FieldErrors } from "@/lib/auth";

const CONTACT_HREF = "/contact?topic=general#write";

function failureMessage(error: unknown): string {
  if (isApiClientError(error) && error.kind === "rate_limited") {
    return "Too many reset requests from your network for now, so this one was not recorded. Wait an hour and try again.";
  }
  if (isApiClientError(error) && error.kind === "network") {
    return "Cortex could not be reached, so your request was not recorded. Check your connection and try again.";
  }
  return "Your request could not be recorded. Nothing was sent. Try again in a moment.";
}

export default function ForgotPasswordPage(): React.JSX.Element {
  const [email, setEmail] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
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
    setFailure(null);
    setSubmitting(true);
    try {
      // Uniform outcome by design: a known and an unknown email render alike.
      await requestPasswordReset(parsed.data.email);
      setDone(true);
    } catch (error) {
      // Not recorded: no one on the team will see it. Saying "done" here would
      // leave the user waiting for a link that cannot come.
      setFailure(failureMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="A member of the Cortex team sends the reset link."
      testId="forgot-page"
    >
      {done ? (
        <AuthAlert tone="info" testId="forgot-done">
          <p>
            Your request is recorded. If an account exists for that email, a member of the Cortex
            team will send a single-use reset link to it.
          </p>
          <p className="mt-2">
            Nothing was emailed automatically: a person sends the link, so it will not arrive within
            minutes.{" "}
            <Link href={CONTACT_HREF} className="underline underline-offset-2 hover:text-ink">
              Heard nothing? Write to us
            </Link>
            .
          </p>
        </AuthAlert>
      ) : (
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <p className="text-sm text-ink-secondary" data-testid="forgot-how">
            Cortex does not send automatic emails yet. Enter the email of your account: the request
            is recorded, and a member of the team sends a single-use reset link to that address by
            hand. It is not instant.
          </p>
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
          {failure ? (
            <AuthAlert tone="error" testId="forgot-error">
              {failure}{" "}
              <Link href={CONTACT_HREF} className="underline underline-offset-2">
                Or write to us
              </Link>
              .
            </AuthAlert>
          ) : null}
          <button
            type="submit"
            disabled={submitting}
            data-testid="forgot-submit"
            className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium px-3 py-2.5"
          >
            {submitting ? "Recording…" : "Request a reset link"}
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
