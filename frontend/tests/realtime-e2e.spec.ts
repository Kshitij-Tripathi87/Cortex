/**
 * B4 realtime acceptance (Playwright, runs against the real stack in CI e2e).
 *
 * Proves the B4 durable-realtime wire contract end-to-end on the canonical
 * path: PG commit → outbox → relay → Redis → SSE/WS → sequence gate. Every
 * event under test is produced by a REAL mutation of the canonical
 * `/api/v1/nexus/decisions` API — no demo data, no hand-crafted frames.
 *
 * Protocol under test (docs/NEXUS_v0.8.5_B4_LAUNCH_RELIABILITY.md):
 *   - GET /api/v1/nexus/realtime/events?workspace_id&after_seq   durable replay
 *   - GET /api/v1/nexus/realtime/stream?workspace_id&after_seq&token  SSE
 *   - WS  /api/v1/realtime/ws?token&workspace_id&after_seq       live + catch-up
 *
 * Auth boundaries are exercised explicitly (foreign workspace → 403, bad
 * token → 401/4401) because "403 must never log out" is a launch invariant.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = process.env.NEXUS_WS_URL || 'ws://localhost:8000/api/v1/realtime/ws';

interface Identity {
  email: string;
  password: string;
  accessToken: string;
  workspaceId: string;
  userId: string;
}

function uniqueEmail(tag: string): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `b4-${tag}-${Date.now()}-${rand}@example.com`;
}

async function signupViaApi(request: APIRequestContext, tag: string): Promise<Identity> {
  const email = uniqueEmail(tag);
  const password = 'E2esecures1';
  const resp = await request.post(`${BACKEND}/api/v1/auth/signup`, {
    data: { organization_name: `B4 Org ${tag}`, email, password, full_name: 'B4 Realtime Tester' },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  return {
    email,
    password,
    accessToken: body.access_token as string,
    workspaceId: body.workspace_id as string,
    userId: body.user_id as string,
  };
}

async function createDecisionViaApi(
  request: APIRequestContext,
  id: Identity,
): Promise<string> {
  const resp = await request.post(`${BACKEND}/api/v1/nexus/decisions`, {
    headers: { Authorization: `Bearer ${id.accessToken}` },
    data: { workspace_id: id.workspaceId, situation: 'B4 realtime e2e' },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  const decisionId = body?.data?.decision?.decision_id as string;
  expect(decisionId).toBeTruthy();
  return decisionId;
}

test.describe('B4 durable realtime', () => {
  // Two identities, shared across the suite: orgA is the subject; orgB is a
  // foreign workspace used to prove the tenant boundary.
  let orgA: Identity;
  let orgB: Identity;

  test.beforeAll(async ({ request }) => {
    orgA = await signupViaApi(request, 'a');
    orgB = await signupViaApi(request, 'b');
  });

  test('durable replay serves a committed decision_created with contiguous seqs', async ({
    request,
  }) => {
    const decisionId = await createDecisionViaApi(request, orgA);

    const resp = await request.get(`${BACKEND}/api/v1/nexus/realtime/events`, {
      headers: { Authorization: `Bearer ${orgA.accessToken}` },
      params: { workspace_id: orgA.workspaceId, after_seq: '0', limit: '100' },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    const envelope = body.data;
    const events: Array<Record<string, unknown>> = envelope.events ?? [];
    expect(events.length).toBeGreaterThan(0);

    // The committed decision must be replayable from the durable outbox.
    const mine = events.find((e) => e.entity_id === decisionId);
    expect(mine).toBeTruthy();
    expect(mine!.type).toBe('decision_created');
    expect(mine!.entity_type).toBe('decision');
    expect(mine!.event_id).toBeTruthy();
    expect(mine!.correlation_id).toBeTruthy();
    expect(typeof mine!.seq).toBe('number');

    // Wire contract: contiguous, strictly-increasing per-workspace seqs.
    const seqs = events.map((e) => e.seq as number);
    for (let i = 1; i < seqs.length; i += 1) {
      expect(seqs[i]).toBe(seqs[i - 1] + 1);
    }

    // Replay envelope sanity.
    expect(envelope.resync_required).toBe(false);
    expect(envelope.latest_seq).toBeGreaterThanOrEqual(mine!.seq as number);
  });

  test('WebSocket delivers a live decision_created after catch-up completes', async ({
    request,
    page,
  }) => {
    // Give the page a real origin, then open a native WS with ?token= auth.
    // Resolve only once catch-up completes: the live bridge subscribes after
    // catch-up, so a mutation created before catchup_complete could otherwise
    // race the subscription and be missed (correctly surfaced as a gap).
    await page.goto('/company');
    const wsUrl =
      `${WS_URL}?token=${encodeURIComponent(orgA.accessToken)}` +
      `&workspace_id=${encodeURIComponent(orgA.workspaceId)}&after_seq=0`;

    await page.evaluate(
      ({ url }) => {
        const w = window as unknown as Record<string, unknown>;
        const frames: Array<Record<string, unknown>> = [];
        w.__b4_frames = frames;
        return new Promise<void>((resolve, reject) => {
          const ws = new WebSocket(url);
          w.__b4_ws = ws;
          ws.onmessage = (ev: MessageEvent) => {
            let msg: Record<string, unknown>;
            try {
              msg = JSON.parse(ev.data as string);
            } catch {
              return;
            }
            frames.push(msg);
            if (msg.type === 'catchup_complete') resolve();
          };
          ws.onerror = () => reject(new Error('WS connection failed'));
          setTimeout(() => reject(new Error('WS catchup_complete timeout')), 8000);
        });
      },
      { url: wsUrl },
    );

    // Now mutate: the canonical API commits a decision → outbox → live frame.
    const decisionId = await createDecisionViaApi(request, orgA);

    const live = await page.evaluate(
      ({ decisionId }) =>
        new Promise<Record<string, unknown>>((resolve, reject) => {
          const w = window as unknown as { __b4_frames: Array<Record<string, unknown>> };
          const deadline = Date.now() + 20000;
          const poll = () => {
            const hit = w.__b4_frames.find(
              (f) => f.type === 'decision_created' && f.entity_id === decisionId,
            );
            if (hit) return resolve(hit);
            if (Date.now() > deadline) {
              return reject(new Error('live decision_created not delivered within 20s'));
            }
            setTimeout(poll, 200);
          };
          poll();
        }),
      { decisionId },
    );

    expect(live.entity_id).toBe(decisionId);
    expect(live.type).toBe('decision_created');
    expect(typeof live.seq).toBe('number');
    expect((live.seq as number) > 0).toBe(true);

    // Clean up the socket we left open on the page.
    await page.evaluate(() => {
      const w = window as unknown as { __b4_ws?: WebSocket };
      w.__b4_ws?.close();
    });
  });

  test('SSE stream replays the committed event after the connected handshake', async ({
    request,
    page,
  }) => {
    const decisionId = await createDecisionViaApi(request, orgA);

    await page.goto('/company');
    const streamUrl =
      `${BACKEND}/api/v1/nexus/realtime/stream?workspace_id=${encodeURIComponent(orgA.workspaceId)}` +
      `&after_seq=0&token=${encodeURIComponent(orgA.accessToken)}`;

    const result = await page.evaluate(
      ({ url, decisionId }) =>
        new Promise<{ connected: Record<string, unknown>; event: Record<string, unknown> }>(
          (resolve, reject) => {
            const es = new EventSource(url);
            let connected: Record<string, unknown> | null = null;
            const deadline = Date.now() + 20000;
            es.addEventListener('connected', (ev: MessageEvent) => {
              connected = JSON.parse(ev.data as string);
            });
            es.addEventListener('decision_created', (ev: MessageEvent) => {
              const data = JSON.parse(ev.data as string);
              if (data.entity_id === decisionId && connected) {
                es.close();
                resolve({ connected, event: data });
              }
            });
            es.onerror = () => {
              if (Date.now() > deadline) {
                es.close();
                reject(new Error('SSE connected/replay not received within 20s'));
              }
            };
            setTimeout(() => {
              es.close();
              reject(new Error('SSE connected/replay timeout'));
            }, 20000);
          },
        ),
      { url: streamUrl, decisionId },
    );

    // Handshake is server-side authoritative: the streamed workspace comes
    // from the verified token, never the (possibly forged) query value.
    expect(result.connected.workspace_id).toBe(orgA.workspaceId);
    expect(result.event.entity_id).toBe(decisionId);
    expect(result.event.type).toBe('decision_created');
    expect(typeof result.event.seq).toBe('number');
  });

  test('realtime boundaries: foreign workspace → 403, bad token → 401/4401', async ({
    request,
    page,
  }) => {
    // 1. Valid token, foreign workspace: the server must 403 (never leak).
    const foreign = await request.get(`${BACKEND}/api/v1/nexus/realtime/events`, {
      headers: { Authorization: `Bearer ${orgA.accessToken}` },
      params: { workspace_id: orgB.workspaceId, after_seq: '0' },
    });
    expect(foreign.status()).toBe(403);

    // 2. Garbage token on the HTTP replay: fail-closed 401.
    const badHttp = await request.get(`${BACKEND}/api/v1/nexus/realtime/events`, {
      headers: { Authorization: 'Bearer definitely-not-a-valid-jwt' },
      params: { workspace_id: orgA.workspaceId, after_seq: '0' },
    });
    expect(badHttp.status()).toBe(401);

    // 3. Garbage token on the SSE stream: identity resolves BEFORE the first
    //    byte — a 401 surfaces as JSON, never as a 200 stream.
    const badSse = await request.get(`${BACKEND}/api/v1/nexus/realtime/stream`, {
      params: {
        workspace_id: orgA.workspaceId,
        after_seq: '0',
        token: 'definitely-not-a-valid-jwt',
      },
    });
    expect(badSse.status()).toBe(401);

    // 4. Garbage token on the WS handshake: the server refuses to establish
    //    a session (never emits connection_established; socket closes).
    //    Browser-observed code is 1006 (handshake rejected before accept);
    //    the app-level 4401 is asserted by the backend's own A16d test.
    const wsResult = await page.evaluate(
      ({ url }) =>
        new Promise<{ code: number; established: boolean }>((resolve, reject) => {
          const ws = new WebSocket(url);
          let established = false;
          ws.onmessage = (ev: MessageEvent) => {
            try {
              const msg = JSON.parse(ev.data as string) as Record<string, unknown>;
              if (msg.type === 'connection_established') established = true;
            } catch {
              /* ignore malformed frames */
            }
          };
          ws.onclose = (ev: CloseEvent) => resolve({ code: ev.code, established });
          ws.onerror = () => {
            /* close follows; don't reject */
          };
          setTimeout(() => reject(new Error('WS did not close within 5s')), 5000);
        }),
      { url: `${WS_URL}?token=definitely-not-a-valid-jwt&workspace_id=${orgA.workspaceId}` },
    );
    expect([1006, 4401]).toContain(wsResult.code);
    expect(wsResult.established).toBe(false);
  });
});
