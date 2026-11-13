"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";
import {
  createScenario,
  fetchScenarios,
  simulateScenario,
  type CanonicalScenario,
  type ScenarioKpis,
  type SimulationResult,
} from "@/lib/api/scenarios";
import { buildTwinSnapshot, entityUuid, graphWorldStateVersion, type GraphNode } from "@/lib/nexus/snapshot";

/**
 * Scenario Studio (demo spec §2.D).
 *
 * Recovery alternatives are created as real persisted scenarios
 * (`POST /nexus/scenarios`) against a selected entity from the workspace
 * dependency graph, then simulated through the canonical deterministic twin
 * (`POST /nexus/scenarios/{id}/simulate`) using a snapshot built from the
 * same graph records. Every KPI shown is returned by the backend; nothing
 * is fabricated client-side (spec invariant 4).
 */

interface GraphEdge {
  edge_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  relationship_type?: string;
}

type LeverKind = "supplier_failure" | "capacity_shock" | "lead_time_increase";

const LEVER_LABELS: Record<LeverKind, string> = {
  supplier_failure: "Restore supplier capacity",
  capacity_shock: "Set facility capacity",
  lead_time_increase: "Adjust supplier lead time",
};

const KPI_ROWS: Array<{ key: keyof ScenarioKpis; label: string; format: (value: number) => string; lowerIsBetter: boolean }> = [
  { key: "net_expected_value", label: "Net expected value", format: formatINR, lowerIsBetter: false },
  { key: "revenue_at_risk", label: "Revenue at risk", format: formatINR, lowerIsBetter: true },
  { key: "increment_cost", label: "Incremental cost", format: formatINR, lowerIsBetter: true },
  { key: "service_level", label: "Service level", format: pct, lowerIsBetter: false },
  { key: "sla_breach_pct", label: "SLA breach", format: pct, lowerIsBetter: true },
  { key: "stockout_probability", label: "Stockout probability", format: pct, lowerIsBetter: true },
  { key: "recovery_days", label: "Recovery days", format: (value) => `${value}`, lowerIsBetter: true },
];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function formatINR(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10_000_000) return `₹${(value / 10_000_000).toFixed(1)}Cr`;
  if (Math.abs(value) >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (Math.abs(value) >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

function pct(value: number): string {
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
}

function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

export default function ScenarioStudioPage() {
  const { status, workspace, organization, user } = useAuth();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [scenarios, setScenarios] = useState<CanonicalScenario[]>([]);
  const [results, setResults] = useState<Record<string, SimulationResult>>({});
  const [selectedEntityId, setSelectedEntityId] = useState<string>("");
  const [lever, setLever] = useState<LeverKind>("supplier_failure");
  const [amount, setAmount] = useState<number>(100);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const tenantId = useMemo(() => {
    for (const candidate of [organization?.id, user?.id, workspace?.id]) {
      if (candidate && UUID_PATTERN.test(candidate)) return candidate;
    }
    return workspace?.id ?? "";
  }, [organization?.id, user?.id, workspace?.id]);

  const load = useCallback(async () => {
    if (!workspace?.id) return;
    setLoading(true);
    setError(null);
    try {
      const [nodeResponse, scenarioResponse] = await Promise.all([
        apiClient.get<GraphNode[]>("/graph/nodes", { workspace_id: workspace.id, limit: 200 }),
        fetchScenarios(workspace.id),
      ]);
      setNodes(nodeResponse);
      setScenarios(scenarioResponse.scenarios);
      setSelectedEntityId((current) => {
        if (current && nodeResponse.some((node) => node.entity_id === current)) return current;
        const supplier = nodeResponse.find((node) => node.entity_type === "supplier");
        return supplier?.entity_id ?? "";
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Scenario data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [workspace?.id]);

  useEffect(() => {
    if (status === "AUTHENTICATED") void load();
  }, [load, status]);

  const worldVersion = useMemo(() => graphWorldStateVersion(nodes), [nodes]);

  const snapshot = useMemo(() => {
    if (!workspace?.id || !tenantId) return null;
    return buildTwinSnapshot(nodes, { tenantId, workspaceId: workspace.id });
  }, [nodes, tenantId, workspace?.id]);

  const candidateEntities = useMemo(() => {
    const priority = ["supplier", "manufacturer", "plant", "factory", "warehouse", "port"];
    return [...nodes]
      .filter((node) => node.entity_id)
      .sort((a, b) => {
        const rank = (node: GraphNode) => {
          const index = priority.indexOf(String(node.entity_type ?? ""));
          return index === -1 ? priority.length : index;
        };
        return rank(a) - rank(b);
      })
      .slice(0, 200);
  }, [nodes]);

  const selectedEntity = useMemo(
    () => nodes.find((node) => node.entity_id === selectedEntityId) ?? null,
    [nodes, selectedEntityId],
  );

  const sortedScenarios = useMemo(
    () =>
      [...scenarios].sort((a, b) => {
        if (a.is_baseline !== b.is_baseline) return a.is_baseline ? -1 : 1;
        return (a.created_at ?? "").localeCompare(b.created_at ?? "");
      }),
    [scenarios],
  );

  const baseline = sortedScenarios.find((scenario) => scenario.is_baseline) ?? null;
  const alternatives = sortedScenarios.filter((scenario) => !scenario.is_baseline);

  const kpisFor = (scenario: CanonicalScenario): ScenarioKpis | null => {
    const live = results[scenario.scenario_id]?.result.kpis;
    if (live) return live;
    const persisted = scenario.kpi_results;
    if (persisted && Object.keys(persisted).length > 0) return persisted as unknown as ScenarioKpis;
    return null;
  };

  const mutationFor = (scenario: CanonicalScenario) => scenario.mutations?.[0] ?? null;

  const refreshScenarios = useCallback(async () => {
    if (!workspace?.id) return;
    const response = await fetchScenarios(workspace.id);
    setScenarios(response.scenarios);
  }, [workspace?.id]);

  const createBaseline = async () => {
    if (!workspace?.id) return;
    setBusy("baseline");
    setError(null);
    setNotice(null);
    try {
      const { scenario } = await createScenario({
        workspace_id: workspace.id,
        name: "Baseline — current operational state",
        description: "No mutations; KPIs reflect the world state as persisted.",
        world_state_version: worldVersion,
        is_baseline: true,
      });
      setScenarios((current) => [...current, scenario]);
      setNotice(`Baseline scenario ${scenario.scenario_id} created.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Baseline creation failed.");
    } finally {
      setBusy(null);
    }
  };

  const addAlternative = async () => {
    if (!workspace?.id || !selectedEntityId) return;
    setBusy("alternative");
    setError(null);
    setNotice(null);
    const parameters =
      lever === "supplier_failure"
        ? { availability_pct: amount }
        : lever === "capacity_shock"
          ? { capacity_pct: amount }
          : { extra_days: amount };
    const leverNote =
      lever === "lead_time_increase"
        ? `${amount >= 0 ? "+" : ""}${amount} days`
        : `${amount}%`;
    try {
      const { scenario } = await createScenario({
        workspace_id: workspace.id,
        name: `${LEVER_LABELS[lever]} — ${selectedEntity ? String(selectedEntity.attributes?.name ?? selectedEntity.entity_id) : selectedEntityId} (${leverNote})`,
        description: `Recovery alternative targeting ${selectedEntityId} at world state v${worldVersion}.`,
        world_state_version: worldVersion,
        mutations: [
          {
            kind: lever,
            target_entity_id: entityUuid(selectedEntityId),
            parameters,
          },
        ],
      });
      setScenarios((current) => [...current, scenario]);
      setNotice(`Recovery alternative ${scenario.scenario_id} created.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Alternative creation failed.");
    } finally {
      setBusy(null);
    }
  };

  const simulatePending = async () => {
    if (!workspace?.id || !snapshot) return;
    if (snapshot.entities.length === 0) {
      setError("The workspace graph contains no entities the twin can simulate. Upload operational data first.");
      return;
    }
    setBusy("simulate");
    setError(null);
    setNotice(null);
    const pending = sortedScenarios.filter((scenario) => !results[scenario.scenario_id]);
    const nextResults: Record<string, SimulationResult> = {};
    try {
      for (const scenario of pending) {
        const outcome = await simulateScenario({
          scenario_id: scenario.scenario_id,
          workspace_id: workspace.id,
          entities: snapshot.entities,
          world_state_version: worldVersion,
        });
        nextResults[outcome.result.scenario_id] = outcome;
      }
      setResults((current) => ({ ...current, ...nextResults }));
      await refreshScenarios();
      setNotice(`${Object.keys(nextResults).length} scenario(s) simulated against ${snapshot.entities.length} canonical entities.`);
    } catch (requestError) {
      setResults((current) => ({ ...current, ...nextResults }));
      setError(requestError instanceof Error ? requestError.message : "Simulation failed.");
      await refreshScenarios();
    } finally {
      setBusy(null);
    }
  };

  if (status === "CHECKING" || status === "UNKNOWN") {
    return <CenteredNote title="Opening Cortex" detail="Checking your workspace session…" />;
  }
  if (status !== "AUTHENTICATED") {
    return (
      <CenteredNote
        title="Sign in to Cortex"
        detail="Scenario Studio is available to authenticated operators."
        action={<Link href="/auth/login?next=%2Fnexus%2Fscenarios" className="button-primary">Sign in</Link>}
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
            <span>Scenario Studio</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">
            Recovery alternatives simulated against the canonical world state — never production data
          </p>
        </div>
        <span className="font-mono text-[10px] text-ink-muted">
          {workspace?.name ?? "Workspace"} · world state {worldVersion ? `v${worldVersion}` : "not loaded"}
        </span>
      </header>

      <div className="space-y-5 px-5 py-6 sm:px-8">
        {error && <div className="notice-error" role="alert">{error}</div>}
        {notice && (
          <div className="border border-border bg-surface px-4 py-3 text-xs text-ink-secondary" role="status">
            {notice}
          </div>
        )}

        <section id="options" className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="border border-border bg-surface p-5">
            <p className="eyebrow">Recovery options</p>
            <h2 className="mt-1 text-base font-semibold">Model a recovery lever</h2>
            <p className="mt-1 text-xs text-ink-secondary">
              Each alternative is a persisted scenario with explicit mutations against one canonical entity.
            </p>
            <div className="mt-4 space-y-3">
              <label className="block text-xs text-ink-secondary">
                Target entity
                <select
                  value={selectedEntityId}
                  onChange={(event) => setSelectedEntityId(event.target.value)}
                  className="field mt-1 w-full"
                  aria-label="Target entity for the recovery alternative"
                >
                  <option value="">Select an entity…</option>
                  {candidateEntities.map((node) => (
                    <option key={node.entity_id} value={node.entity_id ?? ""}>
                      {titleCase(String(node.entity_type ?? "entity"))} — {String(node.attributes?.name ?? node.entity_id)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-ink-secondary">
                Lever
                <select
                  value={lever}
                  onChange={(event) => {
                    const next = event.target.value as LeverKind;
                    setLever(next);
                    setAmount(next === "lead_time_increase" ? 2 : 100);
                  }}
                  className="field mt-1 w-full"
                  aria-label="Recovery lever"
                >
                  {(Object.keys(LEVER_LABELS) as LeverKind[]).map((kind) => (
                    <option key={kind} value={kind}>{LEVER_LABELS[kind]}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-ink-secondary">
                {lever === "lead_time_increase" ? "Lead-time delta (days; negative = expedited)" : "Capacity (%)"}
                <input
                  type="number"
                  value={amount}
                  onChange={(event) => setAmount(Number(event.target.value))}
                  className="field mt-1 w-full"
                  aria-label="Lever amount"
                />
              </label>
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => void addAlternative()}
                  disabled={busy !== null || !selectedEntityId}
                  className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy === "alternative" ? "Creating…" : "Add recovery alternative"}
                </button>
                <button
                  type="button"
                  onClick={() => void createBaseline()}
                  disabled={busy !== null || baseline !== null}
                  className="button-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy === "baseline" ? "Creating…" : baseline ? "Baseline exists" : "Create baseline"}
                </button>
              </div>
            </div>
          </div>

          <div className="border border-border bg-surface p-5">
            <p className="eyebrow">Simulation basis</p>
            <h2 className="mt-1 text-base font-semibold">Deterministic twin snapshot</h2>
            <p className="mt-1 text-xs text-ink-secondary">
              Scenarios run against an explicit snapshot of the workspace graph — the twin never mutates
              production World State.
            </p>
            <dl className="mt-4 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-secondary">Snapshot entities</dt>
                <dd className="font-mono text-[11px]">{snapshot?.entities.length ?? 0}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-secondary">Unmapped graph nodes</dt>
                <dd className="font-mono text-[11px]">{snapshot?.excluded.length ?? 0}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-secondary">World state version</dt>
                <dd className="font-mono text-[11px]">{worldVersion ? `v${worldVersion}` : "—"}</dd>
              </div>
            </dl>
            <button
              type="button"
              onClick={() => void simulatePending()}
              disabled={busy !== null || scenarios.length === 0}
              className="button-primary mt-4 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy === "simulate" ? "Simulating…" : "Simulate pending scenarios"}
            </button>
            {snapshot && snapshot.excluded.length > 0 && (
              <p className="mt-3 border-t border-border pt-3 font-mono text-[10px] leading-5 text-ink-muted">
                {snapshot.excluded.length} graph node(s) could not be represented as twin entities
                (unsupported type or missing identifier) and are excluded — reported explicitly, not hidden.
              </p>
            )}
          </div>
        </section>

        <section className="border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="eyebrow">Scenarios ({scenarios.length})</span>
            {loading && <span className="font-mono text-[10px] text-ink-muted">loading…</span>}
          </div>
          {scenarios.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-ink-secondary">
              No scenarios yet. Create a baseline, then add recovery alternatives.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {sortedScenarios.map((scenario) => {
                const mutation = mutationFor(scenario);
                const kpis = kpisFor(scenario);
                return (
                  <li key={scenario.scenario_id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{scenario.name}</span>
                        {scenario.is_baseline && <span className="badge badge-neutral">BASELINE</span>}
                        <span className={`badge ${scenario.status === "completed" ? "badge-positive" : "badge-neutral"}`}>
                          {scenario.status.toUpperCase()}
                        </span>
                      </div>
                      <p className="mt-1 font-mono text-[10px] text-ink-muted">
                        {scenario.scenario_id} · v{scenario.world_state_version}
                        {mutation ? ` · ${mutation.kind} → ${mutation.target_entity_id.slice(0, 13)}…` : " · no mutations"}
                      </p>
                    </div>
                    <div className="text-right">
                      {kpis ? (
                        <span className="font-mono text-xs text-ink">NEV {formatINR(kpis.net_expected_value)}</span>
                      ) : (
                        <span className="font-mono text-[10px] text-ink-muted">not simulated</span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {alternatives.length > 0 && (
          <section id="comparison" className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Scenario comparison</span>
              <p className="mt-1 text-xs text-ink-secondary">
                Side-by-side KPIs as returned by the deterministic twin. Deltas are relative to the baseline
                {baseline ? "" : " — no baseline scenario exists yet, so only absolute values are shown"}.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-xs">
                <thead className="bg-surface-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Metric</th>
                    <th className="px-4 py-2 font-medium">{baseline?.name ?? "Baseline (missing)"}</th>
                    {alternatives.map((scenario) => (
                      <th key={scenario.scenario_id} className="px-4 py-2 font-medium">{scenario.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {KPI_ROWS.map((row) => {
                    const baselineKpis = baseline ? kpisFor(baseline) : null;
                    return (
                      <tr key={row.key} className="border-t border-border">
                        <td className="px-4 py-2 text-ink-secondary">{row.label}</td>
                        <td className="px-4 py-2 font-mono text-[11px] text-ink">
                          {baselineKpis ? row.format(baselineKpis[row.key]) : "—"}
                        </td>
                        {alternatives.map((scenario) => {
                          const kpis = kpisFor(scenario);
                          const value = kpis ? kpis[row.key] : null;
                          const delta = kpis && baselineKpis ? kpis[row.key] - baselineKpis[row.key] : null;
                          const good = delta === null ? false : row.lowerIsBetter ? delta < 0 : delta > 0;
                          return (
                            <td key={scenario.scenario_id} className="px-4 py-2">
                              <span className="font-mono text-[11px] text-ink">{value === null ? "—" : row.format(value)}</span>
                              {delta !== null && Math.abs(delta) > 1e-9 && (
                                <span className={`ml-2 font-mono text-[9px] ${good ? "text-accent" : "text-warning"}`}>
                                  {delta > 0 ? "+" : ""}{row.format(delta)}
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {Object.keys(results).length > 0 && (
          <section id="results" className="border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <span className="eyebrow">Simulation results</span>
              <p className="mt-1 text-xs text-ink-secondary">
                Persisted twin output: KPIs, affected entities, and the assumptions the engine recorded.
              </p>
            </div>
            <ul className="divide-y divide-border">
              {sortedScenarios
                .filter((scenario) => results[scenario.scenario_id])
                .map((scenario) => {
                  const result = results[scenario.scenario_id].result;
                  return (
                    <li key={scenario.scenario_id} className="px-4 py-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-medium text-ink">{scenario.name}</span>
                        <span className="font-mono text-[10px] text-ink-muted">
                          {result.execution_time_ms}ms · v{result.world_state_version}
                        </span>
                      </div>
                      <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-4">
                        <div><dt className="text-ink-secondary">NEV</dt><dd className="font-mono text-[11px]">{formatINR(result.kpis.net_expected_value)}</dd></div>
                        <div><dt className="text-ink-secondary">Revenue at risk</dt><dd className="font-mono text-[11px]">{formatINR(result.kpis.revenue_at_risk)}</dd></div>
                        <div><dt className="text-ink-secondary">Service level</dt><dd className="font-mono text-[11px]">{pct(result.kpis.service_level)}</dd></div>
                        <div><dt className="text-ink-secondary">Recovery days</dt><dd className="font-mono text-[11px]">{result.kpis.recovery_days}</dd></div>
                      </dl>
                      <p className="mt-2 font-mono text-[10px] text-ink-muted">
                        Affected entities: {result.affected_entity_ids.length === 0 ? "none" : result.affected_entity_ids.join(", ")}
                      </p>
                      {result.assumption_notes.length > 0 && (
                        <div className="mt-2 border border-border bg-surface-2 px-3 py-2">
                          <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-warning">Assumptions recorded</span>
                          <ul className="mt-1 space-y-0.5 font-mono text-[10px] leading-5 text-ink-secondary">
                            {result.assumption_notes.map((note, index) => (
                              <li key={index}>· {note}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </li>
                  );
                })}
            </ul>
          </section>
        )}
      </div>
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
