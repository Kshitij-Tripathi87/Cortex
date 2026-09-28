/**
 * Mobile bootstrap â€” the authoritative snapshot (Day 25 Â§4).
 *
 * On first launch / login / reconnect / app resume the phone reconstructs
 * its state from GET /mobile/bootstrap. The phone never treats a local UI
 * state as authoritative; server state wins.
 */

import { apiGet, unwrap } from "./client.ts";

export interface BootstrapUser {
  user_id: string;
  email: string | null;
  roles: string[];
}

export interface BootstrapDevice {
  device_id: string;
  owner_id: string;
  platform: string;
  agent_version: string;
  capabilities: string[];
  status: string;
  last_seen: string;
}

export interface BootstrapTask {
  task_id: string;
  status: string;
  objective: string;
  workspace_id: string;
  world_state_version: number;
  requires_approval: boolean;
  blocked_reason: string | null;
  created_at: string;
}

export interface BootstrapApproval {
  approval_id: string;
  task_id: string;
  task_status: string;
  reason: string | null;
  created_at: string;
}

export interface BootstrapEvent {
  workspace_id: string;
  seq: number;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
}

export interface BootstrapSnapshot {
  user: BootstrapUser;
  devices: BootstrapDevice[];
  active_tasks: BootstrapTask[];
  pending_approvals: BootstrapApproval[];
  recent_events: BootstrapEvent[];
  bootstrap_at: string;
}

export async function fetchBootstrap(): Promise<BootstrapSnapshot> {
  return unwrap(await apiGet<{ data: BootstrapSnapshot }>("/mobile/bootstrap"));
}
