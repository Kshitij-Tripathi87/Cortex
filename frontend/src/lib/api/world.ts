/**
 * Cortex Nexus — World State API Client.
 */

import { request } from "./http";
import { WorkspaceStateResponse } from "@/types/nexus";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export async function fetchWorldState(): Promise<WorkspaceStateResponse> {
  return request<WorkspaceStateResponse>({ path: "/workspace/state" });
}