/**
 * Cortex Nexus — Counterfactual Scenario Simulation Typed API Client (Track X2)
 */

import { request } from "./http";
import { ScenarioCandidate, RawCounterfactual } from "@/types/nexus";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export interface SimulationRequest {
  scenario_id: string;
  disruption_entity_id: string;
  disruption_type: string;
  monte_carlo_runs?: number;
}

export interface SimulationResult {
  simulation_id: string;
  scenario_id: string;
  candidates: ScenarioCandidate[];
  optimal_candidate_id: string;
  execution_time_ms: number;
}

export async function fetchScenarios(): Promise<{ scenarios: { id: string; name: string; description: string }[] }> {
  return request({ path: "/scenarios" });
}

export async function simulateScenario(req: SimulationRequest): Promise<SimulationResult> {
  return request({
    method: "POST",
    path: `/scenarios/${req.scenario_id}/simulate`,
    body: req,
  });
}

export async function fetchCounterfactuals(incidentEntityId: string): Promise<RawCounterfactual[]> {
  const data = await request<{ counterfactuals: RawCounterfactual[] }>({
    path: "/workspace/deliberate",
    method: "POST",
    body: { incident_entity_id: incidentEntityId },
  });
  return data.counterfactuals || [];
}