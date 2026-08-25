import { request } from "./http";
import { OperationalSignal, SignalListResponse } from "@/types/nexus";

export async function fetchActiveSignals(): Promise<OperationalSignal[]> {
  const data = await request<SignalListResponse>({ path: "/workspace/signals" });
  return data.active_signals || [];
}

export async function fetchPrimaryBlastRadius(): Promise<Record<string, unknown> | null> {
  const data = await request<SignalListResponse>({ path: "/workspace/signals" });
  return data.primary_blast_radius ?? null;
}
