/**
 * Device Mesh API â€” registration, presence, ownership (Day 25 Â§2).
 *
 * The phone registers like any other capability-bearing mesh node and is
 * scoped to its owner. Re-registration with the same device_id UPDATES the
 * record (no duplicate state on reconnect).
 */

import { apiGet, apiPost, unwrap } from "./client.ts";
import type { BootstrapDevice } from "./bootstrap.ts";

export interface RegisterDeviceInput {
  deviceId?: string;
  platform: string;
  agentVersion?: string;
  capabilities: string[];
  publicKey?: string;
}

export async function registerDevice(input: RegisterDeviceInput): Promise<BootstrapDevice> {
  const body = await apiPost<{ data: { device: BootstrapDevice } }>("/devices", {
    device_id: input.deviceId ?? null,
    platform: input.platform,
    agent_version: input.agentVersion ?? "v1.0",
    capabilities: input.capabilities,
    public_key: input.publicKey ?? null,
  });
  return body.data.device;
}

export async function listDevices(): Promise<BootstrapDevice[]> {
  const body = await apiGet<{ data: { devices: BootstrapDevice[]; count: number } }>(
    "/devices",
  );
  return body.data.devices;
}

export async function getDevice(deviceId: string): Promise<BootstrapDevice> {
  const body = await apiGet<{ data: { device: BootstrapDevice } }>(`/devices/${deviceId}`);
  return body.data.device;
}

export async function heartbeat(
  deviceId: string,
  status?: string,
): Promise<BootstrapDevice> {
  const body = await apiPost<{ data: { device: BootstrapDevice } }>(
    `/devices/${deviceId}/heartbeat`,
    { status: status ?? null },
  );
  return body.data.device;
}
