/**
 * Voice â€” provider-agnostic sessions + short-lived scoped tokens (Day 25 Â§6/Â§7).
 *
 * The token endpoint validates identity server-side and issues a SHORT-LIVED
 * (5 min), scoped (`voice`) token. LiveKit transport state stays SEPARATE
 * from the authoritative Nexus voice state machine â€” LiveKit is not the
 * source of truth.
 *
 * Voice state machine (user-visible):
 *   IDLE -> CONNECTING -> LISTENING -> THINKING -> SPEAKING -> EXECUTING -> LISTENING
 *   Failure: DISCONNECTED -> RECONNECTING -> RESYNCING -> CONNECTED
 */

import { apiGet, apiPost, unwrap } from "./client.ts";

export const VOICE_STATES = [
  "IDLE",
  "CONNECTING",
  "LISTENING",
  "THINKING",
  "SPEAKING",
  "EXECUTING",
  "DISCONNECTED",
  "RECONNECTING",
  "RESYNCING",
  "CONNECTED",
] as const;

export type VoiceState = (typeof VOICE_STATES)[number];

export interface VoiceToken {
  token: string;
  expires_in: number;
  provider: string;
  scope: string;
  device_id: string;
}

export interface VoiceSessionView {
  voice_session_id: string;
  state: VoiceState;
  device_id: string;
  workspace_id: string | null;
  provider: string;
}

export async function fetchVoiceToken(deviceId: string, workspaceId?: string): Promise<VoiceToken> {
  return unwrap(
    await apiPost<{ data: VoiceToken }>("/voice/token", {
      device_id: deviceId,
      workspace_id: workspaceId ?? null,
    }),
  );
}

export async function createVoiceSession(
  deviceId: string,
  workspaceId?: string,
): Promise<VoiceSessionView> {
  return unwrap(
    await apiPost<{ data: VoiceSessionView }>("/voice/sessions", {
      device_id: deviceId,
      workspace_id: workspaceId ?? null,
    }),
  );
}

export async function getVoiceSession(voiceSessionId: string): Promise<VoiceSessionView> {
  return unwrap(
    await apiGet<{ data: VoiceSessionView }>(`/voice/sessions/${voiceSessionId}`),
  );
}

export async function transitionVoice(
  voiceSessionId: string,
  state: VoiceState,
): Promise<VoiceSessionView> {
  return unwrap(
    await apiPost<{ data: VoiceSessionView }>(
      `/voice/sessions/${voiceSessionId}/state`,
      { state },
    ),
  );
}
