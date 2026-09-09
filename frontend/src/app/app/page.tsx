/**
 * Authenticated home (B2). Server-derived identity summary + a live call to
 * the canonical Nexus API (proves end-to-end authenticated access per the
 * B2 acceptance gate) + password change + logout.
 */

"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";
import { isApiClientError } from "@/lib/auth/errors";
import { changePassword } from "@/lib/api/auth";
import { AuthField } from "@/components/auth/AuthField";
import { AuthAlert } from "@/components/auth/AuthAlert";
import { changePasswordSchema, toFieldErrors, type FieldErrors } from "@/lib/auth/validation";

type NexusStatus =
  | { state: "loading" }
  | { state: "ok"; count: number }
  | { state: "forbidden" }
  | { state: "error"; message: string };

function NexusStatusCard({ workspaceId }: { workspaceId: string }): React.JSX.Element {
  const [status, setStatus] = useState<NexusStatus>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await apiClient.get<{ decisions: unknown[]; count: number }>(
          "/nexus/decisions",
          { workspace_id: workspaceId, limit: 1 },
        );
        if (!cancelled) setStatus({ state: "ok", count: data.count });
      } catch (error) {
        if (cancelled) return;
        // 403 here means "authenticated but not permitted" — the session
        // stays valid (the client only invalidates on 401).
        if (isApiClientError(error) && error.kind === "forbidden") {
          setStatus({ state: "forbidden" });
        } else if (isApiClientError(error) && error.kind === "network") {
          setStatus({ state: "error", message: "Nexus API unreachable." });
        } else {
          setStatus({ state: "error", message: "Nexus API returned an error." });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return (
    <div data-testid="nexus-status" className="bg-surface border border-border p-5">
      <h2 className="text-sm font-medium mb-1">Nexus API</h2>
      {status.state === "loading" && (
        <p data-testid="nexus-status-loading" className="text-sm text-ink-secondary">
          Checking authenticated access…
        </p>
      )}
      {status.state === "ok" && (
        <p data-testid="nexus-status-ok" className="text-sm">
          <span className="text-accent font-medium">Connected.</span>{" "}
          <span className="text-ink-secondary">
            {status.count} decision{status.count === 1 ? "" : "s"} in this workspace.
          </span>
        </p>
      )}
      {status.state === "forbidden" && (
        <p data-testid="nexus-status-forbidden" className="text-sm text-warning">
          Authenticated, but this workspace is not shared with you.
        </p>
      )}
      {status.state === "error" && (
        <p data-testid="nexus-status-error" className="text-sm text-critical">
          {status.message}
        </p>
      )}
    </div>
  );
}

function ChangePasswordCard(): React.JSX.Element {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [notice, setNotice] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setNotice(null);
    const parsed = changePasswordSchema.safeParse({ currentPassword, newPassword, confirmPassword });
    if (!parsed.success) {
      setFieldErrors(toFieldErrors(parsed.error));
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      await changePassword(parsed.data.currentPassword, parsed.data.newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice({ tone: "success", text: "Password changed." });
    } catch {
      setNotice({ tone: "error", text: "Could not change the password. Check the current one and try again." });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div data-testid="change-password-card" className="bg-surface border border-border p-5">
      <h2 className="text-sm font-medium mb-3">Change password</h2>
      <form onSubmit={onSubmit} noValidate className="space-y-3">
        <AuthField
          id="currentPassword"
          label="Current password"
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          error={fieldErrors.currentPassword}
          disabled={submitting}
        />
        <div className="grid grid-cols-2 gap-3">
          <AuthField
            id="newPassword"
            label="New password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            error={fieldErrors.newPassword}
            disabled={submitting}
          />
          <AuthField
            id="confirmPassword"
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            error={fieldErrors.confirmPassword}
            disabled={submitting}
          />
        </div>
        {notice ? (
          <AuthAlert tone={notice.tone} testId="change-password-notice">
            {notice.text}
          </AuthAlert>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="change-password-submit"
          className="bg-surface-2 hover:bg-border-strong border border-border-strong disabled:opacity-50 text-sm px-4 py-2"
        >
          {submitting ? "Changing…" : "Change password"}
        </button>
      </form>
    </div>
  );
}

export default function AppHomePage(): React.JSX.Element {
  const { user, workspace, organization, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  async function onLogout(): Promise<void> {
    if (loggingOut) return;
    setLoggingOut(true);
    await logout();
  }

  return (
    <div data-testid="app-page" className="min-h-screen bg-bg text-ink">
      <header className="border-b border-border">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <p className="font-mono text-xs text-accent tracking-widest">NEXUS</p>
            <h1 className="text-lg font-semibold" data-testid="app-workspace-name">
              {workspace?.name ?? "Workspace"}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <span data-testid="app-user-email" className="font-mono text-xs text-ink-secondary">
              {user?.email}
            </span>
            <button
              onClick={onLogout}
              disabled={loggingOut}
              data-testid="logout-button"
              className="bg-surface-2 hover:bg-border-strong border border-border-strong disabled:opacity-50 text-sm px-3 py-1.5"
            >
              {loggingOut ? "Logging out…" : "Log out"}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6 space-y-4">
        <div className="bg-surface border border-border p-5">
          <h2 className="text-sm font-medium mb-2">Organization</h2>
          <p className="text-sm" data-testid="app-org-line">
            <span className="font-medium">{organization?.name}</span>{" "}
            <span className="text-ink-secondary">
              · {organization?.plan} trial
              {organization?.trial_ends_at
                ? ` · ends ${new Date(organization.trial_ends_at).toLocaleDateString()}`
                : ""}
            </span>
          </p>
          <div className="mt-4">
            <Link
              href="/workspace/cockpit"
              data-testid="open-workspace-link"
              className="inline-block bg-accent hover:bg-accent-hover text-white text-sm font-medium px-4 py-2"
            >
              Open Nexus workspace
            </Link>
          </div>
        </div>

        {workspace ? <NexusStatusCard workspaceId={workspace.id} /> : null}
        <ChangePasswordCard />
      </main>
    </div>
  );
}
