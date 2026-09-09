/**
 * Signup (B2 §5). Collects the exact B1 contract fields; the backend's
 * atomic endpoint creates organization + workspace + trial + admin user.
 * The frontend creates nothing independently.
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
  signupSchema,
  toFieldErrors,
  authFormMessage,
  type FieldErrors,
} from "@/lib/auth";

export default function SignupPage(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { signup } = useAuth();
  const [form, setForm] = useState({
    fullName: "",
    email: "",
    password: "",
    confirmPassword: "",
    organizationName: "",
    workspaceName: "",
  });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function set<K extends keyof typeof form>(key: K, value: string): void {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setFormError(null);
    const parsed = signupSchema.safeParse(form);
    if (!parsed.success) {
      setFieldErrors(toFieldErrors(parsed.error));
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      await signup({
        organization_name: parsed.data.organizationName,
        workspace_name: parsed.data.workspaceName,
        email: parsed.data.email,
        password: parsed.data.password,
        full_name: parsed.data.fullName,
      });
      setForm((prev) => ({ ...prev, password: "", confirmPassword: "" }));
      const next = sanitizeNext(searchParams?.get("next"));
      router.replace(`/onboarding?next=${encodeURIComponent(next)}`);
    } catch (error) {
      setFormError(authFormMessage(error, "signup"));
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title="Create your account" subtitle="Organization, workspace, and 7-day trial included." testId="signup-page">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <AuthField
          id="fullName"
          label="Your name"
          type="text"
          autoComplete="name"
          placeholder="Ada Operative"
          value={form.fullName}
          onChange={(e) => set("fullName", e.target.value)}
          error={fieldErrors.fullName}
          disabled={submitting}
        />
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={form.email}
          onChange={(e) => set("email", e.target.value)}
          error={fieldErrors.email}
          disabled={submitting}
        />
        <div className="grid grid-cols-2 gap-3">
          <AuthField
            id="password"
            label="Password"
            type="password"
            autoComplete="new-password"
            placeholder="••••••••••"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            error={fieldErrors.password}
            hint="10+ characters, a letter and a digit."
            disabled={submitting}
          />
          <AuthField
            id="confirmPassword"
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            placeholder="••••••••••"
            value={form.confirmPassword}
            onChange={(e) => set("confirmPassword", e.target.value)}
            error={fieldErrors.confirmPassword}
            disabled={submitting}
          />
        </div>
        <AuthField
          id="organizationName"
          label="Organization name"
          type="text"
          autoComplete="organization"
          placeholder="Acme Logistics"
          value={form.organizationName}
          onChange={(e) => set("organizationName", e.target.value)}
          error={fieldErrors.organizationName}
          disabled={submitting}
        />
        <AuthField
          id="workspaceName"
          label="Workspace name (optional)"
          type="text"
          placeholder="Defaults to your organization name"
          value={form.workspaceName}
          onChange={(e) => set("workspaceName", e.target.value)}
          error={fieldErrors.workspaceName}
          disabled={submitting}
        />
        {formError ? (
          <AuthAlert tone="error" testId="signup-error">
            {formError}
          </AuthAlert>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="signup-submit"
          className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium px-3 py-2.5"
        >
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <div className="mt-5 text-sm text-center">
        <span className="text-ink-secondary">Already have an account? </span>
        <Link href="/auth/login" className="text-ink hover:underline">
          Log in
        </Link>
      </div>
    </AuthShell>
  );
}
