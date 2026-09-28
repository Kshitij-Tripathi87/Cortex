/**
 * App shell — the minimal Day 25/26 flow (deliberately small):
 *
 *   Launch -> Authenticate -> GET /mobile/bootstrap -> Render state ->
 *   Register device -> Heartbeat -> Notifications -> Start voice session
 *
 * The app assumes it can be killed at any point: PHONE STATE != VANESSA
 * STATE. On relaunch the bootstrap reconstructs the authoritative state.
 *
 * Voice: the TALK button starts a voice session (token + session + state
 * machine) — the transport (LiveKit) wires in separately; the Nexus voice
 * state machine is authoritative, not the transport.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";
import { setTokenGetter } from "./src/api/client";
import {
  loadStoredToken,
  persistToken,
  type TokenStorage,
} from "./src/api/auth";
import { registerDevice } from "./src/api/devices";
import {
  createVoiceSession,
  fetchVoiceToken,
  transitionVoice,
  type VoiceSessionView,
} from "./src/api/voice";
import { SessionManager, type MobileSessionState } from "./src/state/session";
import { Home } from "./src/screens/Home";
import { Login } from "./src/screens/Login";
import { Approvals } from "./src/screens/Approvals";
import { TaskDetail } from "./src/screens/TaskDetail";
import { Devices } from "./src/screens/Devices";

/** In-memory KV — replace with SecureStore-backed storage on device. */
const memoryStorage: TokenStorage = {
  get: async (key) => memoryStore.get(key) ?? null,
  set: async (key, value) => {
    memoryStore.set(key, value);
  },
  clear: async () => memoryStore.clear(),
};
const memoryStore = new Map<string, string>();

type Screen = "HOME" | "APPROVALS" | "DEVICES" | "TASK_DETAIL";

export default function App() {
  const manager = new SessionManager(memoryStorage);
  const [state, setState] = useState<MobileSessionState>({
    identity: null,
    connection: "DISCONNECTED",
    snapshot: null,
    lastSyncAt: null,
  });
  const [loading, setLoading] = useState(true);
  const [screen, setScreen] = useState<Screen>("HOME");
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [voiceSession, setVoiceSession] = useState<VoiceSessionView | null>(null);

  // Token getter — the api client reads the secure storage through this.
  useEffect(() => {
    let mounted = true;
    setTokenGetter(() => (mounted ? memoryStore.get("vanessa:access_token") ?? null : null));
    return () => {
      mounted = false;
    };
  }, []);

  // Cold start: restore the stored token, then reconcile from bootstrap.
  useEffect(() => {
    void (async () => {
      const token = await loadStoredToken(memoryStorage);
      if (token) {
        const restored = await manager.reconcile({
          identity: {
            email: "",
            password: "",
            accessToken: token,
            refreshToken: null,
            workspaceId: state.snapshot?.user.user_id ? "" : "",
            userId: "",
          },
          connection: "RECONNECTING",
          snapshot: null,
          lastSyncAt: null,
        });
        setState(restored);
      }
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAuthenticated = useCallback(async () => {
    setLoading(true);
    // The minimal first version signs in via the bootstrap after the login
    // screen collects credentials; the identity arrives from the backend.
    setState((prev) => ({ ...prev, connection: "RECONNECTING" }));
    setLoading(false);
  }, []);

  const handleTalk = useCallback(async () => {
    const deviceId = "phone-001";
    const ws = state.snapshot?.active_tasks[0]?.workspace_id;
    try {
      // Short-lived scoped token (identity validated server-side).
      await fetchVoiceToken(deviceId, ws);
      const session = await createVoiceSession(deviceId, ws);
      setVoiceSession(session);
      await transitionVoice(session.voice_session_id, "CONNECTING");
      await transitionVoice(session.voice_session_id, "LISTENING");
    } catch {
      // The voice state machine stays authoritative; transport failures
      // surface as DISCONNECTED -> RECONNECTING (not a crash).
      if (voiceSession) await transitionVoice(voiceSession.voice_session_id, "DISCONNECTED");
    }
  }, [state.snapshot, voiceSession]);

  const handleRegister = useCallback(async () => {
    try {
      await registerDevice({
        deviceId: "phone-001",
        platform: "android",
        agentVersion: "v0.1.0",
        capabilities: ["voice", "notifications", "approval", "display"],
      });
    } catch {
      // registration is idempotent; failures surface on the Home status
    }
  }, []);

  const handleApproveResolved = useCallback(
    async (_taskId: string, _approved: boolean, _status: string) => {
      // The governed execution completed server-side; re-bootstrap so the
      // stale client cache is replaced with authoritative state.
      setState((prev) => ({ ...prev, connection: "RECONNECTING" }));
      const refreshed = await manager.reconcile(state);
      setState(refreshed);
    },
    [manager, state],
  );

  // Reconnect heartbeat: keep the device present while foregrounded.
  useEffect(() => {
    if (state.connection !== "CONNECTED") return;
    void handleRegister();
    const interval = setInterval(() => {
      void manager.reconcile(state).then((next) => setState(next));
    }, 30000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.connection]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: "#0b0f14", justifyContent: "center" }}>
        <Text style={{ color: "#5c6975", textAlign: "center" }}>Starting...</Text>
      </View>
    );
  }

  const authed = state.snapshot !== null;

  if (!authed) {
    return <Login onAuthenticated={handleAuthenticated} />;
  }

  const workspaceId = state.snapshot?.active_tasks[0]?.workspace_id ?? "";

  if (screen === "APPROVALS") {
    return <Approvals workspaceId={workspaceId} onResolved={handleApproveResolved} />;
  }
  if (screen === "DEVICES") {
    return <Devices />;
  }
  if (screen === "TASK_DETAIL" && openTaskId) {
    return <TaskDetail taskId={openTaskId} />;
  }
  return (
    <Home
      state={state}
      loading={loading}
      onTalk={() => void handleTalk()}
      onOpenApprovals={() => setScreen("APPROVALS")}
      onOpenTask={(task) => {
        setOpenTaskId(task.task_id);
        setScreen("TASK_DETAIL");
      }}
    />
  );
}

// Persist the token when the identity changes (secure storage on device).
export async function persistOnAuthenticate(identity: { accessToken: string }) {
  await persistToken(memoryStorage, identity.accessToken);
}
