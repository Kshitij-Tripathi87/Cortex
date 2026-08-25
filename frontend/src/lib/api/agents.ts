/**
 * Cortex Nexus — Multi-Agent Swarm Typed API Client (Track X2 & X6)
 */

import { request } from "./http";
import { AgentMessageEnvelope, AgentLifecycleState } from "@/types/nexus";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export interface AgentDescriptor {
  agent_id: string;
  role: string;
  name: string;
  version: string;
  state: AgentLifecycleState;
  model: string;
  policy: string;
  health: number;
  consensus_contribution: number;
}

export interface DeliberationRequest {
  incident_entity_id: string;
  workspace_id?: string;
  participating_roles?: string[];
}

export interface DeliberationResponse {
  deliberation_id: string;
  incident_entity_id: string;
  consensus_score: number;
  participating_agents: AgentDescriptor[];
  messages: AgentMessageEnvelope[];
  recommended_candidate_id: string;
}

export async function fetchAgents(): Promise<AgentDescriptor[]> {
  return request({ path: "/agents" });
}

export async function fetchAgentMessages(agentId: string): Promise<AgentMessageEnvelope[]> {
  return request({ path: `/agents/${agentId}/messages` });
}

export async function deliberate(req: DeliberationRequest): Promise<DeliberationResponse> {
  return request({
    method: "POST",
    path: "/agents/deliberate",
    body: req,
  });
}

export async function trainAgent(agentId: string, trainingDataRef: string): Promise<{ job_id: string; status: string }> {
  return request({
    method: "POST",
    path: "/agents/train",
    body: { agent_id: agentId, training_data_ref: trainingDataRef },
  });
}

export async function deployAgent(agentId: string, targetState: AgentLifecycleState): Promise<{ agent_id: string; new_state: AgentLifecycleState }> {
  return request({
    method: "POST",
    path: "/agents/deploy",
    body: { agent_id: agentId, target_state: targetState },
  });
}

export async function createAgentTask(incidentEntityId: string, worldStateVersion: number = 101): Promise<any> {
  return request({
    method: "POST",
    path: "/agents/tasks",
    body: { incident_entity_id: incidentEntityId, world_state_version: worldStateVersion },
  });
}

export async function fetchTaskGraph(taskId: string): Promise<any> {
  return request({ path: `/agents/tasks/${taskId}` });
}

export async function fetchAgentManifests(): Promise<any> {
  return request({ path: "/agents/manifests" });
}