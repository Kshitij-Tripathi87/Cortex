/**
 * B4 RealtimeClient — unit suite (mocked fetch streams + WebSocket doubles).
 *
 * Mirrors the backend A-series semantics on the client side: the sequence
 * gate applies exactly `lastSeq + 1`, duplicates drop, gaps replay-or-resync,
 * reconnects resume from the cursor, and 403 (boundary) never equals 401
 * (session). No sleeps: tiny backoffs plus `vi.waitFor` on real state.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CanonicalEvent,
  RealtimeClient,
  RealtimeStatus,
  ReplayPage,
} from "./client";

const WS_ID = "ws-test-1";

function makeEvent(seq: number, type = "decision_created"): CanonicalEvent {
  return {
    event_id: `EVT-${seq}`,
    seq,
    type,
    entity_type: "decision",
    entity_id: `D-${seq}`,
    payload: { n: seq },
    world_state_version: seq,
    correlation_id: null,
    timestamp: "2026-09-10T00:00:00Z",
  };
}

function sseFrame(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

/** Split one frame across two chunks to prove carry-over parsing works. */
function splitFrame(frame: string): [string, string] {
  const cut = Math.floor(frame.length / 2);
  return [frame.slice(0, cut), frame.slice(cut)];
}

function replayPage(overrides: Partial<ReplayPage> = {}): ReplayPage {
  return {
    events: [],
    from_seq: 0,
    to_seq: 0,
    latest_seq: 0,
    world_state_version: 0,
    has_more: false,
    resync_required: false,
    ...overrides,
  };
}

interface FetchCall {
  url: string;
  init?: RequestInit;
}

function streamUrlAfterSeq(url: string): number {
  return Number(new URL(url, "http://x").searchParams.get("after_seq"));
}

/** Minimal server-driven WebSocket double. */
class FakeWebSocket {
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  readyState = FakeWebSocket.OPEN;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;

  constructor(public readonly url: string) {}

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }

  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  serverClose(code: number): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
  }
}

const created: RealtimeClient[] = [];
afterEach(() => {
  while (created.length > 0) created.pop()?.disconnect();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function track(client: RealtimeClient): RealtimeClient {
  created.push(client);
  return client;
}

describe("RealtimeClient (SSE)", () => {
  it("connects, goes live, and applies in-order frames exactly once", async () => {
    const calls: FetchCall[] = [];
    const seen: CanonicalEvent[] = [];
    const statuses: RealtimeStatus[] = [];
    let streamsOpened = 0;

    const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.includes("/realtime/events")) {
        return Response.json({ data: replayPage({ latest_seq: 0 }) });
      }
      streamsOpened += 1;
      if (streamsOpened > 1) {
        // Later reconnects: handshake only, so stats stay deterministic.
        return new Response(sseStream([sseFrame("connected", { workspace_id: WS_ID })]), {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      const [a, b] = splitFrame(sseFrame("decision_created", makeEvent(2)));
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID, last_seen_seq: 0 }),
          sseFrame("decision_created", makeEvent(1)),
          a,
          b,
          // Redelivery of seq 1: duplicate, must drop.
          sseFrame("decision_created", makeEvent(1)),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.onStatus((status) => statuses.push(status));
    client.on("decision_created", (event) => seen.push(event));
    client.connect();

    await vi.waitFor(() => expect(client.getLastSeq()).toBe(2));
    expect(seen.map((event) => event.seq)).toEqual([1, 2]);
    expect(statuses).toContain("connecting");
    expect(statuses).toContain("live");
    expect(client.getStats()).toMatchObject({ applied: 2, duplicates: 1 });

    // The stream URL carries the resume cursor.
    const streamCalls = calls.filter((call) => call.url.includes("/realtime/stream"));
    expect(streamCalls.length).toBeGreaterThanOrEqual(1);
    expect(streamUrlAfterSeq(streamCalls[0].url)).toBe(0);
  });

  it("recovers a mid-stream gap via paged HTTP replay, then resumes live", async () => {
    const calls: FetchCall[] = [];
    const seen: number[] = [];
    const statuses: RealtimeStatus[] = [];
    let streamsOpened = 0;

    const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.includes("/realtime/events")) {
        const after = Number(new URL(url, "http://x").searchParams.get("after_seq"));
        const limit = Number(new URL(url, "http://x").searchParams.get("limit"));
        if (limit === 1) {
          return Response.json({ data: replayPage({ latest_seq: 4 }) });
        }
        if (after === 1) {
          return Response.json({
            data: replayPage({
              events: [makeEvent(2), makeEvent(3)],
              from_seq: 1,
              to_seq: 3,
              latest_seq: 4,
              has_more: true,
            }),
          });
        }
        return Response.json({
          data: replayPage({
            events: [makeEvent(4)],
            from_seq: 3,
            to_seq: 4,
            latest_seq: 4,
            has_more: false,
          }),
        });
      }
      streamsOpened += 1;
      if (streamsOpened === 1) {
        // Live jump 1 → 4: seqs 2,3 missed in transit.
        return new Response(
          sseStream([
            sseFrame("connected", { workspace_id: WS_ID, last_seen_seq: 0 }),
            sseFrame("decision_created", makeEvent(1)),
            sseFrame("risk_changed", makeEvent(4, "risk_changed")),
          ]),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID, last_seen_seq: 4 }),
          sseFrame("forecast_updated", makeEvent(5, "forecast_updated")),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.onStatus((status) => statuses.push(status));
    client.onAny((event) => seen.push(event.seq));
    client.connect();

    await vi.waitFor(() => expect(client.getLastSeq()).toBe(5));
    expect(seen).toEqual([1, 2, 3, 4, 5]);
    expect(statuses).toContain("syncing");
    expect(client.getStats()).toMatchObject({ gaps: 1, replays: 1 });

    // Resume carries the post-sync cursor (later reconnects advance it).
    const streamCalls = calls.filter((call) => call.url.includes("/realtime/stream"));
    const cursors = streamCalls.map((call) => streamUrlAfterSeq(call.url));
    expect(cursors[0]).toBe(0);
    expect(cursors).toContain(4);
  });

  it("treats resync_needed as a gap and heals through replay", async () => {
    const seen: number[] = [];
    let streamsOpened = 0;
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        const after = Number(new URL(url, "http://x").searchParams.get("after_seq"));
        if (after === 10) {
          return Response.json({
            data: replayPage({
              events: [makeEvent(11), makeEvent(12)],
              from_seq: 10,
              to_seq: 12,
              latest_seq: 12,
              has_more: false,
            }),
          });
        }
        return Response.json({ data: replayPage({ latest_seq: 12 }) });
      }
      streamsOpened += 1;
      const frames =
        streamsOpened === 1
          ? [
              sseFrame("connected", { workspace_id: WS_ID, last_seen_seq: 10 }),
              sseFrame("resync_needed", { from_seq: 10, to_seq: 12 }),
            ]
          : [sseFrame("connected", { workspace_id: WS_ID, last_seen_seq: 12 })];
      return new Response(sseStream(frames), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        initialSeq: 10,
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.onAny((event) => seen.push(event.seq));
    client.connect();

    await vi.waitFor(() => expect(client.getLastSeq()).toBe(12));
    expect(seen).toEqual([11, 12]);
    expect(client.getStats().gaps).toBeGreaterThanOrEqual(1);
  });

  it("paces consecutive syncs instead of hot-looping a persistent gap", async () => {
    let syncReplays = 0;
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        const limit = Number(new URL(url, "http://x").searchParams.get("limit"));
        if (limit !== 1) syncReplays += 1;
        return Response.json({ data: replayPage({ latest_seq: 0 }) });
      }
      // Every resume gaps again: without pacing this is a tight
      // sync→resume→sync microtask loop (timer starvation + OOM).
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID }),
          sseFrame("resync_needed", { from_seq: 0, to_seq: 2 }),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();
    await new Promise((resolve) => setTimeout(resolve, 150));
    // First sync runs immediately; the second waits out minSyncIntervalMs.
    expect(syncReplays).toBeLessThanOrEqual(1);
    expect(client.getStatus()).toBe("syncing");
  });

  it("escalates resync_required to the snapshot hook and adopts latest_seq", async () => {
    const resyncs: Array<{ fromSeq: number; latestSeq: number }> = [];
    const streamCursors: number[] = [];
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        return Response.json({
          data: replayPage({ latest_seq: 5000, has_more: true, resync_required: true }),
        });
      }
      streamCursors.push(streamUrlAfterSeq(url));
      return new Response(sseStream([sseFrame("connected", { workspace_id: WS_ID })]), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
        onResyncRequired: (request) => resyncs.push(request),
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(resyncs.length).toBe(1));
    expect(resyncs[0]).toEqual({ fromSeq: 0, latestSeq: 5000 });
    expect(client.getLastSeq()).toBe(5000);
    expect(client.getStats().resyncs).toBe(1);
    // Stream resumes from the adopted cursor, not from zero.
    await vi.waitFor(() => expect(streamCursors.length).toBeGreaterThanOrEqual(1));
    expect(streamCursors[0]).toBe(5000);
  });

  it("reconnects after EOF and resumes from the cursor", async () => {
    const streamCursors: number[] = [];
    let streamsOpened = 0;
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        return Response.json({ data: replayPage({ latest_seq: 1 }) });
      }
      streamsOpened += 1;
      streamCursors.push(streamUrlAfterSeq(url));
      const first = streamsOpened === 1;
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID }),
          ...(first ? [sseFrame("decision_created", makeEvent(1))] : []),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(streamsOpened).toBeGreaterThanOrEqual(2));
    expect(streamCursors[0]).toBe(0);
    expect(streamCursors[1]).toBe(1);
    expect(client.getStats().reconnects).toBeGreaterThanOrEqual(1);
  });

  it("stops on 403 with a forbidden verdict and never retries (403 ≠ logout)", async () => {
    const token = "stable-token";
    let calls = 0;
    const fetchFn = vi.fn(async () => {
      calls += 1;
      return new Response(JSON.stringify({ detail: "boundary" }), { status: 403 });
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        getToken: () => token,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(client.getAuthError()).toBe("forbidden"));
    expect(client.getStatus()).toBe("offline");
    const callsAfterVerdict = calls;
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(calls).toBe(callsAfterVerdict); // no retry storm against a boundary
  });

  it("stops on 401 with an unauthorized verdict", async () => {
    const fetchFn = vi.fn(async () => new Response("nope", { status: 401 }));
    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(client.getAuthError()).toBe("unauthorized"));
    expect(client.getStatus()).toBe("offline");
  });

  it("ignores malformed frames without losing the stream", async () => {
    const seen: number[] = [];
    const statuses: RealtimeStatus[] = [];
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        return Response.json({ data: replayPage({ latest_seq: 1 }) });
      }
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID }),
          "event: broken\ndata: {not-json\n\n",
          "event: noseq\ndata: {\"type\":\"x\"}\n\n",
          ": ping\n\n",
          sseFrame("decision_created", makeEvent(1)),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.onStatus((status) => statuses.push(status));
    client.onAny((event) => seen.push(event.seq));
    client.connect();

    await vi.waitFor(() => expect(seen).toEqual([1]));
    expect(statuses).toContain("live");
  });

  it("sends the token as ?token= on streams and Bearer on replay", async () => {
    const replayHeaders: Array<Record<string, string>> = [];
    const streamUrls: string[] = [];
    const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/realtime/events")) {
        replayHeaders.push((init?.headers ?? {}) as Record<string, string>);
        return Response.json({ data: replayPage({ latest_seq: 0 }) });
      }
      streamUrls.push(url);
      return new Response(sseStream([sseFrame("connected", { workspace_id: WS_ID })]), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        getToken: () => "jwt-123",
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(streamUrls.length).toBeGreaterThanOrEqual(1));
    expect(new URL(streamUrls[0], "http://x").searchParams.get("token")).toBe("jwt-123");
    expect(replayHeaders[0].Authorization).toBe("Bearer jwt-123");
  });

  it("escalates to snapshot when the sync buffer overflows", async () => {
    const resyncs: number[] = [];
    let streamsOpened = 0;
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        // Table has nothing new; the live jump is unfillable → snapshot.
        return Response.json({ data: replayPage({ latest_seq: 1, has_more: false }) });
      }
      streamsOpened += 1;
      if (streamsOpened > 1) {
        return new Response(sseStream([sseFrame("connected", { workspace_id: WS_ID })]), {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      // All frames in ONE chunk: the gap frame enters sync mid-parse and
      // the flood lands in the sync buffer (limit 2) → overflow.
      return new Response(
        sseStream([
          sseFrame("connected", { workspace_id: WS_ID }) +
            sseFrame("decision_created", makeEvent(1)) +
            sseFrame("risk_changed", makeEvent(9, "risk_changed")) +
            sseFrame("risk_changed", makeEvent(10, "risk_changed")) +
            sseFrame("risk_changed", makeEvent(11, "risk_changed")),
        ]),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        syncBufferLimit: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
        onResyncRequired: (request) => resyncs.push(request.latestSeq),
      }),
    );
    client.connect();

    await vi.waitFor(() => expect(resyncs.length).toBe(1));
    expect(client.getStats().resyncs).toBe(1);
  });

  it("disconnect() cancels pending reconnects", async () => {
    let calls = 0;
    const fetchFn = vi.fn(async () => {
      calls += 1;
      throw new Error("network down");
    });
    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
      }),
    );
    client.connect();
    await vi.waitFor(() => expect(calls).toBeGreaterThanOrEqual(2));
    client.disconnect();
    const frozen = calls;
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(calls).toBe(frozen);
    expect(client.getStatus()).toBe("offline");
  });
});

describe("RealtimeClient (WS)", () => {
  it("applies catch-up before the live tail and resumes with after_seq", async () => {
    const sockets: FakeWebSocket[] = [];
    const seen: number[] = [];
    const statuses: RealtimeStatus[] = [];
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        return Response.json({ data: replayPage({ latest_seq: 2 }) });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        tenantId: "tenant-1",
        transport: "ws",
        baseUrl: "http://api",
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
        webSocketFactory: (url: string) => {
          const socket = new FakeWebSocket(url);
          sockets.push(socket);
          return socket as unknown as WebSocket;
        },
      }),
    );
    client.onStatus((status) => statuses.push(status));
    client.onAny((event) => seen.push(event.seq));
    client.connect();

    await vi.waitFor(() => expect(sockets.length).toBe(1));
    expect(new URL(sockets[0].url).searchParams.get("after_seq")).toBe("0");
    sockets[0].open();
    sockets[0].receive({ type: "connection_established", session_id: "s1" });
    sockets[0].receive({ ...makeEvent(1), channel: "outbox" });
    sockets[0].receive({ ...makeEvent(2), channel: "outbox" });
    sockets[0].receive({ type: "catchup_complete", from_seq: 0, to_seq: 2 });

    await vi.waitFor(() => expect(client.getLastSeq()).toBe(2));
    expect(seen).toEqual([1, 2]);
    expect(client.getStatus()).toBe("live");

    // Unclean close → reconnect with the cursor.
    sockets[0].serverClose(1006);
    await vi.waitFor(() => expect(sockets.length).toBe(2));
    expect(new URL(sockets[1].url).searchParams.get("after_seq")).toBe("2");
    expect(statuses).toContain("reconnecting");
  });

  it("recovers a socket gap through replay, and honors 4401 as unauthorized", async () => {
    const sockets: FakeWebSocket[] = [];
    const seen: number[] = [];
    const fetchFn = vi.fn(async (url: string) => {
      if (url.includes("/realtime/events")) {
        const after = Number(new URL(url, "http://x").searchParams.get("after_seq"));
        if (after === 5) {
          return Response.json({
            data: replayPage({
              events: [makeEvent(6)],
              from_seq: 5,
              to_seq: 6,
              latest_seq: 6,
              has_more: false,
            }),
          });
        }
        return Response.json({ data: replayPage({ latest_seq: 6 }) });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const client = track(
      new RealtimeClient({
        workspaceId: WS_ID,
        transport: "ws",
        baseUrl: "http://api",
        initialSeq: 5,
        baseBackoffMs: 1,
        maxBackoffMs: 2,
        fetchFn: fetchFn as unknown as typeof fetch,
        webSocketFactory: (url: string) => {
          const socket = new FakeWebSocket(url);
          sockets.push(socket);
          return socket as unknown as WebSocket;
        },
      }),
    );
    client.onAny((event) => seen.push(event.seq));
    client.connect();

    await vi.waitFor(() => expect(sockets.length).toBe(1));
    sockets[0].open();
    sockets[0].receive({ type: "connection_established", session_id: "s1" });
    sockets[0].receive({ type: "catchup_complete", from_seq: 5, to_seq: 5 });
    // Server-side gap on the socket.
    sockets[0].receive({ type: "resync_needed", from_seq: 5, to_seq: 7 });

    await vi.waitFor(() => expect(client.getLastSeq()).toBe(6));
    expect(seen).toEqual([6]);
    await vi.waitFor(() => expect(sockets.length).toBe(2));

    // …and a forged session is terminal.
    sockets[1].open();
    sockets[1].serverClose(4401);
    await vi.waitFor(() => expect(client.getAuthError()).toBe("unauthorized"));
    expect(client.getStatus()).toBe("offline");
  });
});
