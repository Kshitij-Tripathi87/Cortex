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
 *
 * Layout: the two health panels sit in a grid with an explicit single column
 * below `lg`, and their rows wrap. A health key such as
 * `worker.heartbeat.last_sweep_published` has no space to break at; as one
 * unbreakable word in an implicit grid column it made the whole page wider
 * than a phone screen, by an amount that depended on the fonts installed.
 */

/** How many audit events the page asks for at a time, newest first. */
const AUDIT_PAGE_SIZE = 100;

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
  // A full page means the log may hold older events than the ones shown.
  const [olderExist, setOlderExist] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Which feeds did not answer. A panel whose feed failed says so; it must
  // not read "no events recorded" or "not reported yet", which are claims
  // about the data.
  const [failed, setFailed] = useState({ models: false, relay: false, audit: false });

  const load = useCallback(async () => {
    if (!workspace?.id) return;
    setLoading(true);
    setError(null);
    const [modelResult, relayResult, auditResult] = await Promise.allSettled([
      apiClient.get<{ data?: { health?: Record<string, unknown> } }>("/nexus/models/health", {
        workspace_id: workspace.id,
      }),
      apiClient.get<{ data?: Record<string, unknown> }>("/nexus/realtime/health"),
      apiClient.get<AuditEvent[]>("/audit", { workspace_id: workspace.id, limit: AUDIT_PAGE_SIZE }),
    ]);
    setModelHealth(modelResult.status === "fulfilled" ? (modelResult.value.data?.health ?? null) : null);
    setRelayHealth(relayResult.status === "fulfilled" ? (relayResult.value.data ?? null) : null);
    const loadedEvents = auditResult.status === "fulfilled" ? auditResult.value : [];
    setEvents(loadedEvents);
    setOlderExist(loadedEvents.length >= AUDIT_PAGE_SIZE);
    setOlderError(null);
    setFailed({
      models: modelResult.status === "rejected",
      relay: relayResult.status === "rejected",
      audit: auditResult.status === "rejected",
    });
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

  /** Append the next page of older events. The whole log can be read this way. */
  const loadOlder = useCallback(async () => {
    if (!workspace?.id || loadingOlder) return;
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const older = await apiClient.get<AuditEvent[]>("/audit", {
        workspace_id: workspace.id,
        limit: AUDIT_PAGE_SIZE,
        offset: events.length,
      });
      // Events recorded since the first page push the older ones down, so a
      // page can start with rows that are already shown: keep each event once.
      setEvents((shown) => {
        const seen = new Set(shown.map((event) => event.event_id));
        return [...shown, ...older.filter((event) => !seen.has(event.event_id))];
      });
      setOlderExist(older.length >= AUDIT_PAGE_SIZE);
    } catch {
      setOlderError("Older events could not be loaded. Try again.");
    } finally {
      setLoadingOlder(false);
    }
  }, [workspace?.id, events.length, loadingOlder]);

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

        <section id="health" className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <div className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Model registry health</span>
              <p className="mt-1 text-[11px] text-ink-secondary">Which trained model serves each kind of prediction</p>
            </div>
            {failed.models ? <FeedFailed what="Model health" /> : <ModelRows record={modelHealth} />}
          </div>
          <div className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Event relay health</span>
              <p className="mt-1 text-[11px] text-ink-secondary">API, database, cache, event queue and the worker that sends events</p>
            </div>
            {failed.relay ? (
              <FeedFailed what="Relay health" />
            ) : (
              <HealthRows record={relayHealth} emptyNote="The relay reported nothing." />
            )}
          </div>
        </section>

        <section id="audit" className="border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-3">
            <div>
              <span className="eyebrow">Audit events</span>
              <p className="mt-1 text-[11px] text-ink-secondary">Append-only audit store, newest first</p>
            </div>
            <span className="font-mono text-[10px] text-ink-muted" data-testid="operations-audit-count">
              {/* While older events exist, this is not the total: say "latest". */}
              {failed.audit ? "Not loaded" : olderExist ? `Latest ${events.length} events` : `${events.length} events`}
            </span>
          </div>
          {failed.audit ? (
            <FeedFailed what="The audit log" testId="operations-audit-failed" />
          ) : events.length === 0 ? (
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
          {olderExist && (
            <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
              <button
                type="button"
                className="button-secondary"
                onClick={() => void loadOlder()}
                disabled={loadingOlder}
                data-testid="operations-audit-older"
              >
                {loadingOlder ? "Loading…" : "Show older events"}
              </button>
              {olderError && <span className="text-xs text-warning" role="status">{olderError}</span>}
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
        <div key={key} className="flex items-start justify-between gap-3">
          <dt className="min-w-0 text-ink-secondary [overflow-wrap:anywhere]">{key}</dt>
          <dd className="flex min-w-0 max-w-[60%] items-center gap-2">
            {typeof value === "string" && /HEALTH|OK|TRUE|DEGRADED|FAIL|BACKLOG|UNKNOWN/i.test(value) ? (
              <span className={statusBadge(value)}>{String(value).toUpperCase()}</span>
            ) : value === null || value === undefined || value === "" ? (
              // The service reported no value: say so, do not print "null".
              <span className="text-ink-muted" title="No value reported">—</span>
            ) : (
              <span className="font-mono text-[11px] text-ink [overflow-wrap:anywhere]">{String(value)}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Shown in place of a panel's content when its request failed. */
function FeedFailed({ what, testId }: { what: string; testId?: string }) {
  return (
    <p className="px-4 py-6 text-xs text-warning" role="status" data-testid={testId}>
      {what} could not be loaded. Use Refresh to try again.
    </p>
  );
}

interface ModelSlot {
  model_id?: string | null;
  name?: string | null;
  version?: string | null;
  accuracy?: number | null;
  deployed_at?: string | null;
  status?: string | null;
}

/** "91%" for 0.91; nothing when the registry holds no measured figure. */
function accuracyText(slot: ModelSlot): string | null {
  if (typeof slot.accuracy !== "number" || !Number.isFinite(slot.accuracy)) return null;
  return `${Math.round(slot.accuracy * 100)}% measured accuracy`;
}

/**
 * One line per kind of prediction: the model that serves it, or "No model
 * assigned". The registry answers with a slot for every kind whether or not
 * a model exists; printed field by field, an empty workspace showed thirty
 * rows of "null" and "accuracy 0".
 */
function ModelRows({ record }: { record: Record<string, unknown> | null }) {
  const slots = Object.entries(record ?? {}).filter(
    (entry): entry is [string, ModelSlot] => entry[1] !== null && typeof entry[1] === "object",
  );
  if (slots.length === 0) {
    return (
      <p className="px-4 py-6 text-xs text-ink-secondary">
        Model health has not been reported for this workspace yet.
      </p>
    );
  }
  const assigned = slots.filter(([, slot]) => Boolean(slot.model_id));
  return (
    <div data-testid="operations-models">
      {assigned.length === 0 && (
        <p className="px-4 pt-3 text-xs text-ink-secondary" data-testid="operations-models-none">
          No trained model is deployed in this workspace.
        </p>
      )}
      <dl className="max-h-[320px] space-y-2 overflow-y-auto px-4 py-3 text-xs">
        {slots.map(([label, slot]) => {
          const accuracy = accuracyText(slot);
          return (
            <div key={label} className="flex items-start justify-between gap-3">
              <dt className="min-w-0 text-ink-secondary">{label}</dt>
              <dd className="min-w-0 max-w-[60%] text-right">
                {slot.model_id ? (
                  <>
                    <span className="font-mono text-[11px] text-ink [overflow-wrap:anywhere]">
                      {slot.name ?? slot.model_id}
                      {slot.version ? ` ${slot.version}` : ""}
                    </span>
                    <span className="block text-[11px] text-ink-muted">
                      {accuracy ?? "No accuracy recorded"}
                      {slot.deployed_at ? `, deployed ${new Date(slot.deployed_at).toLocaleDateString()}` : ""}
                    </span>
                  </>
                ) : (
                  <span className="text-ink-muted">No model assigned</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
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
