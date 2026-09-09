/**
 * Cortex Nexus — Counterfactual Scenario Simulation Typed API Client (Track X2).
 *
 * v0.8.5-B3: `fetchScenarios` / `simulateScenario` target the CANONICAL
 * persistent endpoints (`/nexus/scenarios`) — the old `/scenarios` routes
 * never existed (register §1 row 9). These two functions currently have no
 * importers; they are kept correct (not deleted) for the frontend-rewire
 * slice. Callers must bridge the AuthProvider token via
 * `setNexusAuthToken` first — canonical endpoints are authenticated.
 */

import type { RawCounterfactual } from "@/types/nexus";
import { request } from "./http";

export interface ScenarioMutation {
  mutation_id?: string;
  kind: string;
  target_entity_id: string;
  parameters?: Record<string, unknown>;
}

export interface CanonicalScenario {
  scenario_id: string;
  workspace_id: string;
  name: string;
  description: string;
  decision_id: string | null;
  parent_scenario_id: string | null;
  is_baseline: boolean;
  mutations: ScenarioMutation[];
  kpi_results: Record<string, unknown>;
  world_state_version: number;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string | null;
  completed_at: string | null;
}

export interface ScenarioKpis {
  net_expected_value: number;
  revenue_at_risk: number;
  sla_breach_pct: number;
  stockout_probability: number;
  recovery_days: number;
  increment_cost: number;
  service_level: number;
  margin_impact: number;
  working_capital_impact: number;
}

export interface ScenarioSimulation {
  scenario_id: string;
  scenario_name: string;
  success: boolean;
  kpis: ScenarioKpis;
  affected_entity_ids: string[];
  assumption_notes: string[];
  execution_time_ms: number;
  world_state_version: number;
}

export interface SimulationRequest {
  scenario_id: string;
  workspace_id: string;
  /** Explicit entity snapshot (twin runs against this; never the server singleton). */
  entities?: Array<Record<string, unknown>>;
  world_state_version?: number;
}

export interface SimulationResult {
  scenario: CanonicalScenario;
  result: ScenarioSimulation;
}

interface Envelope<T> {
  request_id: string;
  correlation_id: string | null;
  timestamp: string;
  data: T;
}

export async function fetchScenarios(
  workspaceId: string,
): Promise<{ scenarios: CanonicalScenario[]; count: number }> {
  const envelope = await request<Envelope<{ scenarios: CanonicalScenario[]; count: number }>>({
    path: `/nexus/scenarios?workspace_id=${encodeURIComponent(workspaceId)}`,
  });
  return envelope.data;
}

export async function simulateScenario(req: SimulationRequest): Promise<SimulationResult> {
  const envelope = await request<Envelope<SimulationResult>>({
    method: "POST",
    path: `/nexus/scenarios/${encodeURIComponent(req.scenario_id)}/simulate`,
    body: {
      workspace_id: req.workspace_id,
      entities: req.entities ?? [],
      world_state_version: req.world_state_version ?? 0,
    },
  });
  return envelope.data;
}

export async function fetchCounterfactuals(incidentEntityId: string): Promise<RawCounterfactual[]> {
  const data = await request<{ counterfactuals: RawCounterfactual[] }>({
    path: "/workspace/deliberate",
    method: "POST",
    body: { incident_entity_id: incidentEntityId },
  });
  return data.counterfactuals || [];
}
