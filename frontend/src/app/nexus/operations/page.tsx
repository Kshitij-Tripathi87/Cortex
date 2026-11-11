"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

/**
 * Operations (demo spec §3 — Ingestion, Audit Events, System Health).
 *
 * System health reads the canonical model and relay health endpoints; audit
 * events read the append-only audit store. Everything shown is reported by
 * the services themselves — the UI never synthesizes a status.
 */

interface AuditEvent {
  event_id: string;
  event_type: string;
  event_category: string;
  subject_type?: string | null;
  subject_id?: string | null;
  message?: string | null;
  occurred_at: string;
  correlation_id?: string | null;
}

function statusBadge(status: unknown): string {
  const value = String(status ?? "").toUpperCase();
  if (value.includes("HEALTHY") || value.includes("OK") || value === "TRUE") return "badge badge-positive";
  if (value.includes("DEGRADED") || value.includes("BACKLOG") || value.includes("WARN") || value === "UNKNOWN") return "badge badge-neutral border-warning/50 text-warning";
  if (value.includes("FAIL") || value === "FALSE") return "badge border-critical/50 bg-critical-subtle text-critical";
  return "badge badge-neutral";
}

function flattenHealth(record: Record<string, unknown>, prefix = ""): Array<{ key: string; value: unknown }> {
  const rows: Array<{ key: string; value: unknown }> = [];
  for (const [key, value] of Object.entries(record)) {
    const composite = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      rows.push(...flattenHealth(value as Record<string, unknown>, composite));
    } else {
      rows.push({ key: composite, value });
    }
  }
  return rows;
}

export default function OperationsPage() {
  const { status, workspace } = useAuth();
  const [modelHealth, setModelHealth] = useState<Record<string, unknown> | null>(null);
  const [relayHealth, setRelayHealth] = useState<Record<string, unknown> | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspace?.id) return;
    setLoading(true);
    setError(null);
    const [modelResult, relayResult, auditResult] = await Promise.allSettled([
      apiClient.get<{ data?: { health?: Record<string, unknown> } }>("/nexus/models/health", {
        workspace_id: workspace.id,
      }),
      apiClient.get<{ data?: Record<string, unknown> }>("/nexus/realtime/health"),
      apiClient.get<AuditEvent[]>("/audit", { workspace_id: workspace.id, limit: 100 }),
    ]);
    if (modelResult.status === "fulfilled") setModelHealth(modelResult.value.data?.health ?? null);
    if (relayResult.status === "fulfilled") setRelayHealth(relayResult.value.data ?? null);
    if (auditResult.status === "fulfilled") setEvents(auditResult.value);
    const failures = [modelResult, relayResult, auditResult].filter((result) => result.status === "rejected");
    setError(
      failures.length === 0
        ? null
        : `${failures.length} of 3 operational feeds unavailable — shown feeds are live, missing ones are reported rather than simulated.`,
    );
    setLoading(false);
  }, [workspace?.id]);

  useEffect(() => {
    if (status === "AUTHENTICATED") void load();
  }, [load, status]);

  useEffect(() => {
    if (window.location.hash === "#audit" || window.location.hash === "#health") {
      document.querySelector(window.location.hash)?.scrollIntoView({ behavior: "smooth" });
    }
  }, [modelHealth, relayHealth, events]);

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <CenteredNote title="Opening Cortex" detail="Checking your workspace session…" />;
  }
  if (status !== "AUTHENTICATED") {
    return (
      <CenteredNote
        title="Sign in to Cortex"
        detail="Operational telemetry is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Foperations" className="button-primary">Sign in</Link>}
      />
    );
  }

  return (
    <div className="min-w-0">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-4 border-b border-border px-5 py-3 sm:px-8">
        <div>
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span className="font-semibold text-ink">Cortex</span>
            <span>/</span>
            <span>Operations</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">System health, audit trail, and data operations</p>
        </div>
        <div className="flex gap-2">
          <Link href="/upload" className="button-secondary">Ingestion</Link>
          <button type="button" onClick={() => void load()} className="button-secondary" disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="space-y-5 px-5 py-6 sm:px-8">
        {error && <div className="border border-border bg-surface px-4 py-3 text-xs text-warning" role="status">{error}</div>}

        <section id="health" className="grid gap-5 lg:grid-cols-2">
          <div className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Model registry health</span>
              <p className="mt-1 text-[11px] text-ink-secondary">GET /nexus/models/health</p>
            </div>
            <HealthRows record={modelHealth} emptyNote="Model health has not been reported for this workspace yet." />
          </div>
          <div className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Event relay health</span>
              <p className="mt-1 text-[11px] text-ink-secondary">GET /nexus/realtime/health — API / DB / Redis / Outbox / Worker</p>
            </div>
            <HealthRows record={relayHealth} emptyNote="Relay health is unavailable." />
          </div>
        </section>

        <section id="audit" className="border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <span className="eyebrow">Audit events</span>
              <p className="mt-1 text-[11px] text-ink-secondary">Append-only audit store, newest first</p>
            </div>
            <span className="font-mono text-[10px] text-ink-muted">{events.length} events</span>
          </div>
          {events.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-ink-secondary">No audit events recorded yet.</p>
          ) : (
            <div className="max-h-[520px] overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-surface-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Occurred</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Event</th>
                    <th className="px-4 py-2 font-medium">Subject</th>
                    <th className="px-4 py-2 font-medium">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.event_id} className="border-t border-border">
                      <td className="whitespace-nowrap px-4 py-2 font-mono text-[10px] text-ink-muted">
                        {event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-2 text-ink-secondary">{event.event_category}</td>
                      <td className="px-4 py-2 font-mono text-[10px] text-ink">{event.event_type}</td>
                      <td className="px-4 py-2 font-mono text-[10px] text-ink-muted">
                        {event.subject_type ? `${event.subject_type}:${(event.subject_id ?? "").slice(0, 12)}` : "—"}
                      </td>
                      <td className="max-w-[280px] truncate px-4 py-2 text-ink-secondary" title={event.message ?? ""}>
                        {event.message ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function HealthRows({ record, emptyNote }: { record: Record<string, unknown> | null; emptyNote: string }) {
  if (!record || Object.keys(record).length === 0) {
    return <p className="px-4 py-6 text-xs text-ink-secondary">{emptyNote}</p>;
  }
  const rows = flattenHealth(record);
  return (
    <dl className="max-h-[320px] space-y-2 overflow-y-auto px-4 py-3 text-xs">
      {rows.map(({ key, value }) => (
        <div key={key} className="flex items-center justify-between gap-3">
          <dt className="text-ink-secondary">{key}</dt>
          <dd className="flex items-center gap-2">
            {typeof value === "string" && /HEALTH|OK|TRUE|DEGRADED|FAIL|BACKLOG|UNKNOWN/i.test(value) ? (
              <span className={statusBadge(value)}>{String(value).toUpperCase()}</span>
            ) : (
              <span className="font-mono text-[11px] text-ink">{String(value)}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function CenteredNote({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-6 text-center">
      <div className="max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-ink-secondary">{detail}</p>
        {action && <div className="mt-6">{action}</div>}
      </div>
    </div>
  );
}
