/**
 * Session state â€” the reconnection + reconciliation contract (Day 25 Â§16/Â§17).
 *
 * Mobile network behavior cannot be trusted; the app assumes it can be
 * killed at any point. Therefore:
 *
 *     PHONE STATE != VANESSA STATE
 *
 * The phone is disposable; Vanessa's backend state is durable. On
 * reconnect the phone:
 *   1. refreshes the token if required
 *   2. reconnects realtime (transport-specific)
 *   3. fetches the authoritative snapshot (bootstrap)
 *   4. replaces the stale client cache
 *
 * Session separation (do not collapse these):
 *   user session   the authenticated principal
 *   voice session  a voice-session record (reconnecting it never creates
 *                  a task)
 *   task session   a task-session record (ref = task_id)
 */

import { ApiError } from "../api/client.ts";
import {
  clearStoredToken,
  loadStoredToken,
  persistToken,
  refreshAuth,
  type AuthIdentity,
  type TokenStorage,
} from "../api/auth.ts";
import { fetchBootstrap, type BootstrapSnapshot } from "../api/bootstrap.ts";

export type ConnectionState =
  | "CONNECTED"
  | "DISCONNECTED"
  | "RECONNECTING"
  | "AUTH_REFRESH"
  | "BOOTSTRAP";

export interface MobileSessionState {
  identity: AuthIdentity | null;
  connection: ConnectionState;
  snapshot: BootstrapSnapshot | null;
  lastSyncAt: string | null;
}

export class SessionManager {
  storage: TokenStorage;

  constructor(storage: TokenStorage) {
    this.storage = storage;
  }

  /** Cold start: restore the stored token (if any) â€” no state is trusted. */
  async restore(): Promise<MobileSessionState> {
    const token = await loadStoredToken(this.storage);
    if (!token) {
      return { identity: null, connection: "DISCONNECTED", snapshot: null, lastSyncAt: null };
    }
    return {
      identity: null, // identity is only trusted after a successful bootstrap
      connection: "RECONNECTING",
      snapshot: null,
      lastSyncAt: null,
      // The token is carried until bootstrap confirms it is still valid.
      ...(await this.withToken(token)),
    } as MobileSessionState;
  }

  private async withToken(token: string): Promise<Partial<MobileSessionState>> {
    return { identity: { email: "", password: "", accessToken: token, refreshToken: null, workspaceId: "", userId: "" } };
  }

  /** Authenticate and persist the token to secure storage. */
  async authenticate(
    identity: AuthIdentity,
  ): Promise<MobileSessionState> {
    await persistToken(this.storage, identity.accessToken);
    return this.reconcile({ identity, connection: "CONNECTED", snapshot: null, lastSyncAt: null });
  }

  /** Reconnection: refresh -> bootstrap -> replace the stale cache. */
  async reconcile(state: MobileSessionState): Promise<MobileSessionState> {
    let identity = state.identity;
    if (!identity) {
      return { ...state, connection: "DISCONNECTED" };
    }

    try {
      const snapshot = await fetchBootstrap();
      return {
        identity,
        connection: "CONNECTED",
        snapshot,
        lastSyncAt: snapshot.bootstrap_at,
      };
    } catch (error) {
      // 401 must never log the user out silently â€” refresh once, retry.
      if (error instanceof ApiError && (error.status === 401 || error.status === 4401)) {
        try {
          identity = await refreshAuth(identity);
          await persistToken(this.storage, identity.accessToken);
          const snapshot = await fetchBootstrap();
          return {
            identity,
            connection: "CONNECTED",
            snapshot,
            lastSyncAt: snapshot.bootstrap_at,
          };
        } catch {
          // refresh failed â€” the session is genuinely dead
        }
      }
      return { ...state, identity, connection: "DISCONNECTED" };
    }
  }

  /** App lifecycle: terminated/killed â€” the durable state is the backend's. */
  async signOut(state: MobileSessionState): Promise<MobileSessionState> {
    await clearStoredToken(this.storage);
    return { identity: null, connection: "DISCONNECTED", snapshot: null, lastSyncAt: null };
  }
}

/** Voice sessions never create tasks (session separation invariant). */
export function isVoiceReconnect(state: MobileSessionState): boolean {
  return (
    state.connection === "RECONNECTING" || state.connection === "CONNECTED"
  );
}
