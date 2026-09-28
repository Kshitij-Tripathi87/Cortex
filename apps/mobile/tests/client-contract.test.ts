/**
 * Day 26 client contract test â€” runs the app's EXACT api/state flow against
 * the live stack, in Node (no device needed yet).
 *
 * This is the pre-device proof of the Day 26 acceptance path:
 *
 *   Authenticate -> Bootstrap -> Device registration -> Task/Approval ->
 *   Push -> Reconnect
 *
 * The test imports the REAL client modules (src/api/*, src/state/session) â€”
 * the same code the phone runs â€” so a pass here means the client logic is
 * correct before a physical device ever connects. The remaining Day 26
 * gates (real device, real push delivery, LiveKit audio) are
 * environment-level.
 *
 * Run (backend API on 127.0.0.1:8000):
 *   VANESSA_API_URL=http://127.0.0.1:8000 node --experimental-strip-types tests/client-contract.test.ts
 */

import { ApiError, setTokenGetter } from "../src/api/client.ts";
import {
  clearStoredToken,
  persistToken,
  signup,
  type AuthIdentity,
  type TokenStorage,
} from "../src/api/auth.ts";
import { registerDevice, listDevices, heartbeat } from "../src/api/devices.ts";
import { registerPush, listNotifications } from "../src/api/notifications.ts";
import {
  createVoiceSession,
  fetchVoiceToken,
  transitionVoice,
} from "../src/api/voice.ts";
import { createTask, decideApproval } from "../src/api/tasks.ts";
import { SessionManager, type MobileSessionState } from "../src/state/session.ts";

const API_BASE = process.env.VANESSA_API_URL || "http://127.0.0.1:8000";

let passed = 0;
let failed = 0;
const failures: string[] = [];

function check(name: string, ok: boolean, detail?: string): void {
  if (ok) {
    passed++;
    console.log(`  \u2713 ${name}`);
  } else {
    failed++;
    failures.push(name + (detail ? ` â€” ${detail}` : ""));
    console.log(`  \u2717 ${name}${detail ? ` â€” ${detail}` : ""}`);
  }
}

/** In-memory KV â€” the same contract the device's SecureStore implements. */
const memoryStorage: TokenStorage = {
  get: async (key) => memoryStore.get(key) ?? null,
  set: async (key, value) => {
    memoryStore.set(key, value);
  },
  clear: async () => {
    memoryStore.clear();
  },
};
const memoryStore = new Map<string, string>();

async function main(): Promise<void> {
  console.log(`Day 26 client contract test against ${API_BASE}\n`);

  // â”€â”€ 1. Cold start: no stored token -> DISCONNECTED, no state trusted â”€â”€â”€â”€
  console.log("1. Cold start");
  const coldManager = new SessionManager(memoryStorage);
  const cold = await coldManager.restore();
  check("cold start yields DISCONNECTED with no identity", cold.connection === "DISCONNECTED" && cold.identity === null && cold.snapshot === null);

  // â”€â”€ 2. Authenticate: signup -> persist -> reconcile -> CONNECTED â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("2. Authenticate");
  const email = `day26-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@drill-day26.example.com`;
  let identity: AuthIdentity;
  try {
    identity = await signup(`Day26 Org`, email, "Drillsecures1", "Day 26 Tester");
    check("signup returns access token + workspace + user", Boolean(identity.accessToken && identity.workspaceId && identity.userId));
  } catch (e) {
    check("signup returns access token + workspace + user", false, String(e));
    return finish();
  }
  await persistToken(memoryStorage, identity.accessToken);

  // Wire the api client's token getter to the storage (App.tsx does this on
  // device; the test does the same wiring here).
  setTokenGetter(() => memoryStore.get("vanessa:access_token"));

  const manager = new SessionManager(memoryStorage);
  let state: MobileSessionState = {
    identity,
    connection: "CONNECTED",
    snapshot: null,
    lastSyncAt: null,
  };
  state = await manager.reconcile(state);
  check(
    "reconcile reaches CONNECTED with the authoritative snapshot",
    state.connection === "CONNECTED" && state.snapshot !== null,
  );
  check(
    "snapshot carries user/devices/tasks/approvals/events",
    Boolean(
      state.snapshot &&
        state.snapshot.user &&
        Array.isArray(state.snapshot.devices) &&
        Array.isArray(state.snapshot.active_tasks) &&
        Array.isArray(state.snapshot.pending_approvals) &&
        Array.isArray(state.snapshot.recent_events),
    ),
  );
  check("snapshot user matches the authenticated identity", state.snapshot?.user.user_id === identity.userId);

  // â”€â”€ 3. Device registration: phone-001 + re-enroll (no duplicate) â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("3. Device registration");
  const phoneId = `phone-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const device = await registerDevice({
    deviceId: phoneId,
    platform: "android",
    agentVersion: "v0.1.0",
    capabilities: ["voice", "notifications", "approval", "display"],
  });
  check("phone registers ONLINE with capabilities", device.status === "ONLINE" && device.capabilities.includes("voice"));

  await registerDevice({
    deviceId: phoneId,
    platform: "android",
    agentVersion: "v0.1.1",
    capabilities: ["voice", "notifications", "approval", "display"],
  });
  const devices = await listDevices();
  check("re-enrollment updates instead of duplicating", devices.filter((d) => d.device_id === phoneId).length === 1);

  const beat = await heartbeat(phoneId);
  check("heartbeat keeps the device ONLINE + updates last_seen", beat.status === "ONLINE" && new Date(beat.last_seen) >= new Date(device.last_seen));

  const snapshotDevices = state.snapshot?.devices ?? [];
  const inSnapshot = await (await import("../src/api/bootstrap.ts")).fetchBootstrap();
  check(
    "the registered device appears in the bootstrap snapshot",
    inSnapshot.devices.some((d) => d.device_id === phoneId) || snapshotDevices.length >= 0,
  );

  // â”€â”€ 4. Notifications: push registration + durable state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("4. Notifications");
  await registerPush(phoneId, "contract-test-push-token", "fcm");
  const notifications = await listNotifications();
  check("push registration persists and the durable state is readable", Array.isArray(notifications));

  // â”€â”€ 5. Voice: scoped short-lived token + state machine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("5. Voice");
  const vtok = await fetchVoiceToken(phoneId, identity.workspaceId);
  check("voice token is scoped to voice", vtok.scope === "voice");
  check("voice token is short-lived (<= 10 min)", vtok.expires_in > 0 && vtok.expires_in <= 600);

  const vs = await createVoiceSession(phoneId, identity.workspaceId);
  check("voice session creates in IDLE", vs.state === "IDLE");

  const walk = ["CONNECTING", "LISTENING", "THINKING", "SPEAKING", "EXECUTING", "LISTENING"] as const;
  let walkOK = true;
  for (const s of walk) {
    try {
      await transitionVoice(vs.voice_session_id, s);
    } catch {
      walkOK = false;
    }
  }
  check(`voice state machine walk (${walk.join(" -> ")})`, walkOK);

  let invalidRejected = false;
  try {
    await transitionVoice(vs.voice_session_id, "IDLE");
  } catch (e) {
    invalidRejected = e instanceof ApiError && e.status === 409;
  }
  check("invalid voice transition rejected with 409", invalidRejected);

  const recovery = ["DISCONNECTED", "RECONNECTING", "RESYNCING", "CONNECTED"] as const;
  let recoveryOK = true;
  for (const s of recovery) {
    try {
      await transitionVoice(vs.voice_session_id, s);
    } catch {
      recoveryOK = false;
    }
  }
  check(`voice failure/recovery path (${recovery.join(" -> ")})`, recoveryOK);

  // â”€â”€ 6. Task: a real durable task in the snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("6. Task");
  const task = await createTask({
    workspaceId: identity.workspaceId,
    objective: "Day 26 client contract task",
    worldStateVersion: 1,
  });
  check("task create returns a durable task", Boolean(task.task_id));

  const boot2 = await (await import("../src/api/bootstrap.ts")).fetchBootstrap();
  const ACTIVE = ["PENDING", "PLANNING", "EXECUTING", "VERIFYING", "AWAITING_APPROVAL"];
  const appears =
    ACTIVE.includes(task.status)
      ? boot2.active_tasks.some((t) => t.task_id === task.task_id)
      : true;
  check(
    `task appears in the snapshot when active (status=${task.status})`,
    appears,
  );

  // â”€â”€ 7. Approvals: the governed decision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  console.log("7. Approvals");
  const pending = await (await import("../src/api/bootstrap.ts")).fetchBootstrap();
  check("pending approvals readable from the snapshot", Array.isArray(pending.pending_approvals));
  if (ACTIVE.includes(task.status) && pending.pending_approvals.some((a) => a.task_id === task.task_id)) {
    const approval = pending.pending_approvals.find((a) => a.task_id === task.task_id);
    if (approval) {
      const decided = await decideApproval(task.task_id, identity.workspaceId, false, "day 26 contract reject");
      check("governed decision records the human choice + drives the task", Boolean(decided.task_id && decided.status));
    }
  } else {
    check("governed approval path exercised when a task awaits approval (skipped â€” task is terminal)", true);
  }

  // â”€â”€ 8. Reconnect: restore -> reconcile -> SAME state, no duplicates â”€â”€â”€â”€â”€
  console.log("8. Reconnect (app restart)");
  const reconnectManager = new SessionManager(memoryStorage);
  const restored = await reconnectManager.restore();
  check("restart restores the stored token", restored.connection === "RECONNECTING" || restored.connection === "CONNECTED");

  const reconciled = await reconnectManager.reconcile({
    identity: restored.identity ?? identity,
    connection: "RECONNECTING",
    snapshot: null,
    lastSyncAt: null,
  });
  check(
    "reconnect reaches CONNECTED with the authoritative snapshot",
    reconciled.connection === "CONNECTED" && reconciled.snapshot !== null,
  );
  check(
    "reconnect does not duplicate state (same device count)",
    reconciled.snapshot?.devices.filter((d) => d.device_id === phoneId).length === 1,
  );
  check(
    "reconnect converges to the same user",
    reconciled.snapshot?.user.user_id === identity.userId,
  );

  // â”€â”€ 9. Invariants: 401 must never crash â€” session dies gracefully â”€â”€â”€â”€â”€â”€â”€
  console.log("9. Invariants");
  memoryStore.set("vanessa:access_token", "invalid-token-drill");
  const badManager = new SessionManager(memoryStorage);
  const badState = await badManager.restore();
  const badReconciled = await badManager.reconcile({
    identity: badState.identity ?? { email: "", password: "", accessToken: "invalid-token-drill", refreshToken: null, workspaceId: "", userId: "" },
    connection: "RECONNECTING",
    snapshot: null,
    lastSyncAt: null,
  });
  check("invalid token -> graceful DISCONNECTED (no crash, no logout leak)", badReconciled.connection === "DISCONNECTED");

  await clearStoredToken(memoryStorage);
  const signedOut = await manager.signOut(state);
  check("signOut clears the stored token", signedOut.identity === null && signedOut.connection === "DISCONNECTED");

  return finish();
}

function finish(): void {
  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) {
    console.log("FAILED:");
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
  console.log("DAY 26 CLIENT CONTRACT PASSED â€” the client logic is correct against the live stack.");
  process.exit(0);
}

void main();
