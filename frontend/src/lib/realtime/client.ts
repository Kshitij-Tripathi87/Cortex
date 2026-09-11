/**
 * Cortex Nexus — B4 centralized realtime client.
 *
 * The single ingress for live outbox events. Owns the client side of the
 * v0.8.5-B4 reliability contract:
 *
 *   PG COMMIT → outbox row → relay → fabric → SSE/WS → sequence gate → replay/resync
 *
 * Guarantees:
 * - **Sequence gate**: a frame applies iff `seq === lastSeq + 1`. Stale frames
 *   (`seq <= lastSeq`) are duplicates and drop; a jump (`seq > lastSeq + 1`)
 *   is a gap and triggers durable replay — never a silent reorder.
 * - **Cursor resume**: every (re)connect passes `after_seq=lastSeq`; the
 *   server replays exactly the missed range before the live tail.
 * - **Gap recovery**: `resync_needed` (server-side gap) and client-side gaps
 *   both route through HTTP replay (`/nexus/realtime/events`, paged by
 *   `has_more`) with live frames buffered and merged afterwards.
 * - **Resync escalation**: when the server refuses page-by-page replay
 *   (`resync_required`), the client adopts `latest_seq` and calls
 *   `onResyncRequired` so the product surface refetches an authoritative
 *   snapshot. The client never invents state.
 * - **Auth honesty**: 401 (unauthorized) and 403 (forbidden) are terminal and
 *   distinct. A 403 is a workspace boundary verdict — the client stops
 *   retrying but NEVER clears the caller's token (403 ≠ logout).
 * - **Infinite reconnect** on transient failures with capped exponential
 *   backoff + jitter. No "max attempts then give up".
 *
 * Transports: `sse` (default; fetch + ReadableStream parsing, so handshake
 * status codes are visible and cursors are exact — native EventSource hides
 * both) or `ws` (native WebSocket with `after_seq` resume + catch-up).
 */

export type RealtimeStatus = "live" | "connecting" | "reconnecting" | "syncing" | "offline";

/** Terminal handshake outcome. `null` while no auth verdict was reached. */
export type RealtimeAuthError = "unauthorized" | "forbidden" | null;

export type RealtimeTransport = "sse" | "ws";

/** Canonical wire event (SSE `data:`, WS frame, replay envelope row). */
export interface CanonicalEvent {
  event_id: string;
  seq: number;
  /** Domain type, e.g. `decision_created`, `risk_changed`, `forecast_updated`. */
  type: string;
  entity_type: string | null;
  entity_id: string | null;
  payload: Record<string, unknown>;
  world_state_version: number | null;
  correlation_id: string | null;
  timestamp: string | null;
}

export interface ReplayPage {
  events: CanonicalEvent[];
  from_seq: number;
  to_seq: number;
  latest_seq: number;
  world_state_version: number;
  has_more: boolean;
  resync_required: boolean;
}

export interface RealtimeStats {
  received: number;
  applied: number;
  duplicates: number;
  gaps: number;
  replays: number;
  resyncs: number;
  reconnects: number;
}

export interface ResyncRequest {
  fromSeq: number;
  latestSeq: number;
}

export type EventHandler = (event: CanonicalEvent) => void;
export type StatusHandler = (status: RealtimeStatus, client: RealtimeClient) => void;

export interface RealtimeClientOptions {
  workspaceId: string;
  tenantId?: string;
  transport?: RealtimeTransport;
  baseUrl?: string;
  /** JWT for `?token=` on streams (+ `Authorization` fallback on HTTP). */
  getToken?: () => string | null;
  /**
   * Extra headers for HTTP calls (replay + SSE stream). In dev (`header`
   * identity) this carries `X-User-Id` / `X-User-Workspaces` / `X-User-Roles`;
   * in prod (`jwt` identity) it carries `Authorization: Bearer …` — or omit
   * it and let `getToken()` supply the bearer fallback.
   */
  authHeaders?: Record<string, string> | (() => Record<string, string>);
  /** Resume cursor. Defaults to 0 (full replay) or the client's live cursor. */
  initialSeq?: number;
  replayLimit?: number;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  syncBufferLimit?: number;
  /**
   * Minimum gap between two syncs. Consecutive syncs (a persistently
   * gapping server) wait out the remainder instead of hot-looping the
   * replay endpoint. Defaults to 1000ms.
   */
  minSyncIntervalMs?: number;
  /** Snapshot hook: refetch authoritative state for the workspace. */
  onResyncRequired?: (request: ResyncRequest) => void;
  onError?: (error: unknown) => void;
  fetchFn?: typeof fetch;
  webSocketFactory?: (url: string) => WebSocket;
}

const DEFAULT_REPLAY_LIMIT = 500;
const DEFAULT_BASE_BACKOFF_MS = 1000;
const DEFAULT_MAX_BACKOFF_MS = 30000;
const DEFAULT_SYNC_BUFFER_LIMIT = 5000;
const DEFAULT_MIN_SYNC_INTERVAL_MS = 1000;
/** Replay→drain cycles before escalating to snapshot resync. */
const MAX_SYNC_PASSES = 5;
/**
 * Replay pages per sync before escalating. Legit paging is bounded by the
 * server's resync threshold (gaps beyond it refuse paging outright), so an
 * unbounded `has_more` chain means a misbehaving server — snapshot instead.
 */
const MAX_SYNC_PAGES = 20;

export class RealtimeHttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "RealtimeHttpError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export class RealtimeClient {
  private readonly opts: Required<
    Pick<
      RealtimeClientOptions,
      | "transport"
      | "replayLimit"
      | "baseBackoffMs"
      | "maxBackoffMs"
      | "syncBufferLimit"
      | "minSyncIntervalMs"
    >
  > &
    RealtimeClientOptions;

  private status: RealtimeStatus = "offline";
  private authError: RealtimeAuthError = null;
  private lastSeq = 0;
  private closed = true;
  private syncing = false;
  private syncOverflow = false;
  private lastSyncCompletedAt = 0;
  private everConnected = false;
  private attempt = 0;
  /** Connection generation: stale timers/callbacks from a previous connect() are dropped. */
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private abort: AbortController | null = null;
  private socket: WebSocket | null = null;
  private syncBuffer: CanonicalEvent[] = [];
  private readonly handlers = new Map<string, Set<EventHandler>>();
  private readonly statusHandlers = new Set<StatusHandler>();
  private readonly stats: RealtimeStats = {
    received: 0,
    applied: 0,
    duplicates: 0,
    gaps: 0,
    replays: 0,
    resyncs: 0,
    reconnects: 0,
  };

  constructor(options: RealtimeClientOptions) {
    this.opts = {
      transport: "sse",
      replayLimit: DEFAULT_REPLAY_LIMIT,
      baseBackoffMs: DEFAULT_BASE_BACKOFF_MS,
      maxBackoffMs: DEFAULT_MAX_BACKOFF_MS,
      syncBufferLimit: DEFAULT_SYNC_BUFFER_LIMIT,
      minSyncIntervalMs: DEFAULT_MIN_SYNC_INTERVAL_MS,
      ...options,
    };
    this.lastSeq = Math.max(0, options.initialSeq ?? 0);
  }

  // ── Lifecycle ────────────────────────────────────────────────

  /** Open the stream, resuming from `cursor` (or the live cursor). */
  connect(cursor?: number): void {
    if (typeof cursor === "number" && Number.isFinite(cursor)) {
      this.lastSeq = Math.max(0, Math.floor(cursor));
    } else if (typeof this.opts.initialSeq === "number") {
      this.lastSeq = Math.max(0, Math.floor(this.opts.initialSeq));
    }
    this.closed = false;
    this.syncing = false;
    this.syncOverflow = false;
    this.lastSyncCompletedAt = 0;
    this.syncBuffer = [];
    this.authError = null;
    this.attempt = 0;
    this.generation += 1;
    this.clearTimer();
    void this.connectAttempt(this.generation);
  }

  /** Close the stream and stop all retries. Safe to call repeatedly. */
  disconnect(): void {
    this.closed = true;
    this.generation += 1;
    this.clearTimer();
    this.closeTransport();
    this.syncing = false;
    this.syncBuffer = [];
    this.setStatus("offline");
  }

  // ── Subscriptions ────────────────────────────────────────────

  /** Subscribe to a domain type (or `"*"` for all applied events). */
  on(type: string, handler: EventHandler): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler);
    return () => {
      this.handlers.get(type)?.delete(handler);
    };
  }

  onAny(handler: EventHandler): () => void {
    return this.on("*", handler);
  }

  /** Subscribe to status transitions. Fires immediately with the current status. */
  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    try {
      handler(this.status, this);
    } catch (error) {
      this.report(error);
    }
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  // ── Introspection ────────────────────────────────────────────

  getStatus(): RealtimeStatus {
    return this.status;
  }

  getAuthError(): RealtimeAuthError {
    return this.authError;
  }

  /** Last applied sequence number — the resume cursor. Persist to survive reloads. */
  getLastSeq(): number {
    return this.lastSeq;
  }

  getStats(): RealtimeStats {
    return { ...this.stats };
  }

  // ── Connection ───────────────────────────────────────────────

  private setStatus(next: RealtimeStatus): void {
    if (this.status === next) return;
    this.status = next;
    for (const handler of this.statusHandlers) {
      try {
        handler(next, this);
      } catch (error) {
        this.report(error);
      }
    }
  }

  private report(error: unknown): void {
    try {
      this.opts.onError?.(error);
    } catch {
      // Listener isolation: reporting must never throw back.
    }
  }

  private baseUrl(): string {
    const fromEnv =
      typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_URL : undefined;
    return (this.opts.baseUrl ?? fromEnv ?? "http://localhost:8000").replace(/\/$/, "");
  }

  private token(): string | null {
    try {
      return this.opts.getToken?.() ?? null;
    } catch {
      return null;
    }
  }

  private headers(): Record<string, string> {
    const base =
      typeof this.opts.authHeaders === "function"
        ? this.opts.authHeaders()
        : { ...(this.opts.authHeaders ?? {}) };
    const hasAuth = Object.keys(base).some((k) => k.toLowerCase() === "authorization");
    const token = this.token();
    if (!hasAuth && token) {
      base["Authorization"] = `Bearer ${token}`;
    }
    return base;
  }

  private fetchFn(): typeof fetch {
    if (this.opts.fetchFn) return this.opts.fetchFn;
    if (typeof fetch === "function") return fetch.bind(globalThis);
    throw new Error("RealtimeClient: no fetch implementation available");
  }

  private streamQuery(afterSeq: number): string {
    const params = new URLSearchParams({
      workspace_id: this.opts.workspaceId,
      after_seq: String(afterSeq),
    });
    if (this.opts.transport === "ws") {
      params.set("tenant_id", this.opts.tenantId ?? "");
      params.set("replay", "true");
    }
    const token = this.token();
    if (token) params.set("token", token);
    return params.toString();
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private closeTransport(): void {
    if (this.abort) {
      try {
        this.abort.abort();
      } catch {
        // ignore
      }
      this.abort = null;
    }
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      try {
        socket.close();
      } catch {
        // ignore
      }
    }
  }

  /**
   * Preflight every (re)connect through the durable replay endpoint: it
   * resolves 401/403 exactly (SSE gives no status codes), discovers
   * `latest_seq`, and routes straight to sync when the gap is unpageable.
   */
  private async connectAttempt(gen: number): Promise<void> {
    if (this.closed || gen !== this.generation) return;
    this.setStatus(this.everConnected || this.attempt > 0 ? "reconnecting" : "connecting");
    let page: ReplayPage;
    try {
      page = await this.fetchReplay(this.lastSeq, 1);
    } catch (error) {
      if (this.closed || gen !== this.generation) return;
      if (error instanceof RealtimeHttpError && error.status === 401) {
        this.authError = "unauthorized";
        this.setStatus("offline");
        return;
      }
      if (error instanceof RealtimeHttpError && error.status === 403) {
        // Boundary verdict, not a session kill: stop retrying, keep the token.
        this.authError = "forbidden";
        this.setStatus("offline");
        return;
      }
      this.scheduleReconnect(gen);
      return;
    }
    if (this.closed || gen !== this.generation) return;
    if (page.resync_required) {
      this.enterSync();
      return;
    }
    this.openStream(gen);
  }

  private scheduleReconnect(gen: number): void {
    if (this.closed || gen !== this.generation) return;
    this.attempt += 1;
    this.stats.reconnects += 1;
    this.setStatus("reconnecting");
    const grown = this.opts.baseBackoffMs * 2 ** (this.attempt - 1);
    const delay = Math.min(grown, this.opts.maxBackoffMs) * (0.5 + Math.random());
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.connectAttempt(gen);
    }, delay);
  }

  private async fetchReplay(afterSeq: number, limit: number): Promise<ReplayPage> {
    const url =
      `${this.baseUrl()}/api/v1/nexus/realtime/events?` +
      new URLSearchParams({
        workspace_id: this.opts.workspaceId,
        after_seq: String(afterSeq),
        limit: String(limit),
      }).toString();
    const response = await this.fetchFn()(url, {
      method: "GET",
      headers: this.headers(),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new RealtimeHttpError(response.status, `replay failed: HTTP ${response.status}`);
    }
    const body: unknown = await response.json();
    if (!isRecord(body) || !isRecord(body.data)) {
      throw new Error("replay failed: malformed envelope");
    }
    return body.data as unknown as ReplayPage;
  }

  private openStream(gen: number): void {
    if (this.closed || gen !== this.generation) return;
    if (this.opts.transport === "ws") {
      this.openWs(gen);
    } else {
      void this.openSse(gen);
    }
  }

  // ── SSE transport (fetch + manual framing) ───────────────────

  private async openSse(gen: number): Promise<void> {
    const url = `${this.baseUrl()}/api/v1/nexus/realtime/stream?${this.streamQuery(this.lastSeq)}`;
    const abort = new AbortController();
    this.abort = abort;
    let response: Response;
    try {
      response = await this.fetchFn()(url, {
        method: "GET",
        headers: { Accept: "text/event-stream", ...this.headers() },
        signal: abort.signal,
      });
    } catch (error) {
      if (this.closed || gen !== this.generation || abort.signal.aborted) return;
      this.report(error);
      this.scheduleReconnect(gen);
      return;
    }
    if (this.closed || gen !== this.generation || abort.signal.aborted) return;
    if (!response.ok || !response.body) {
      if (response.status === 401) {
        this.authError = "unauthorized";
        this.setStatus("offline");
        return;
      }
      if (response.status === 403) {
        this.authError = "forbidden";
        this.setStatus("offline");
        return;
      }
      this.scheduleReconnect(gen);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (this.closed || gen !== this.generation || abort.signal.aborted) {
          try {
            await reader.cancel();
          } catch {
            // ignore
          }
          return;
        }
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        buffer = this.consumeSseBuffer(buffer);
      }
      buffer += decoder.decode();
      this.consumeSseBuffer(buffer + "\n\n");
    } catch (error) {
      if (this.closed || gen !== this.generation || abort.signal.aborted) return;
      this.report(error);
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // ignore
      }
    }
    // Clean EOF (server break after resync_needed routes through sync first;
    // anything else is a dropped connection → resume from the cursor).
    if (!this.closed && gen === this.generation && !this.syncing) {
      this.scheduleReconnect(gen);
    }
  }

  /** Parse complete `\\n\\n`-delimited frames; return the unparsed tail. */
  private consumeSseBuffer(buffer: string): string {
    let rest = buffer;
    for (;;) {
      const boundary = rest.indexOf("\n\n");
      if (boundary === -1) return rest;
      const raw = rest.slice(0, boundary);
      rest = rest.slice(boundary + 2);
      this.handleSseFrame(raw);
      if (this.closed) return "";
    }
  }

  private handleSseFrame(raw: string): void {
    let name = "message";
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      const text = line.endsWith("\r") ? line.slice(0, -1) : line;
      if (text === "" || text.startsWith(":")) continue;
      if (text.startsWith("event:")) {
        name = text.slice("event:".length).trim();
      } else if (text.startsWith("data:")) {
        dataLines.push(text.slice("data:".length).trimStart());
      }
    }
    if (dataLines.length === 0) return;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    if (name === "connected") {
      this.everConnected = true;
      this.attempt = 0;
      this.setStatus("live");
      return;
    }
    if (name === "resync_needed") {
      this.stats.gaps += 1;
      this.enterSync();
      return;
    }
    if (isRecord(data) && typeof data.seq === "number") {
      this.onWireEvent(data as unknown as CanonicalEvent);
    }
  }

  // ── WebSocket transport ──────────────────────────────────────

  private openWs(gen: number): void {
    const factory =
      this.opts.webSocketFactory ??
      ((url: string) => {
        if (typeof WebSocket === "undefined") {
          throw new Error("RealtimeClient: no WebSocket implementation available");
        }
        return new WebSocket(url);
      });
    const httpBase = this.baseUrl();
    const wsBase = httpBase.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
    const url = `${wsBase}/api/v1/realtime/ws?${this.streamQuery(this.lastSeq)}`;
    let socket: WebSocket;
    try {
      socket = factory(url);
    } catch (error) {
      this.report(error);
      this.scheduleReconnect(gen);
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      if (this.closed || gen !== this.generation) return;
      this.everConnected = true;
      this.attempt = 0;
      // Catch-up frames flow before catchup_complete when resuming.
      this.setStatus(this.lastSeq > 0 ? "syncing" : "live");
    };
    socket.onmessage = (message: MessageEvent) => {
      if (this.closed || gen !== this.generation) return;
      let frame: unknown;
      try {
        frame = JSON.parse(String(message.data));
      } catch {
        return;
      }
      this.handleWsFrame(frame);
    };
    socket.onerror = () => {
      // Browsers follow with onclose; the guard below covers those that don't.
      if (this.closed || gen !== this.generation) return;
      if (socket.readyState === WebSocket.CLOSED) {
        this.scheduleReconnect(gen);
      }
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.closed || gen !== this.generation) return;
      if (event.code === 4401) {
        this.authError = "unauthorized";
        this.setStatus("offline");
        return;
      }
      this.scheduleReconnect(gen);
    };
  }

  private handleWsFrame(frame: unknown): void {
    if (!isRecord(frame)) return;
    const type = frame.type;
    switch (type) {
      case "connection_established":
        if (this.lastSeq === 0) this.setStatus("live");
        return;
      case "catchup_complete":
        this.setStatus("live");
        return;
      case "resync_needed":
        this.stats.gaps += 1;
        this.enterSync();
        return;
      case "resync_required":
        this.enterSync();
        return;
      case "subscription_ack":
      case "pong":
      case "heartbeat":
        return;
      default:
        break;
    }
    if (typeof frame.seq === "number") {
      // WS event frames carry `type` + `seq` alongside routing keys.
      this.onWireEvent(frame as unknown as CanonicalEvent);
    }
  }

  // ── Sequence gate + sync ─────────────────────────────────────

  private onWireEvent(event: CanonicalEvent): void {
    this.stats.received += 1;
    if (!Number.isInteger(event.seq) || event.seq < 0) return;
    if (this.syncing) {
      if (this.syncBuffer.length >= this.opts.syncBufferLimit) {
        // Bounded buffer: drop and escalate to snapshot instead of OOMing.
        this.syncBuffer = [];
        this.syncOverflow = true;
        return;
      }
      this.syncBuffer.push(event);
      return;
    }
    if (event.seq <= this.lastSeq) {
      this.stats.duplicates += 1;
      return;
    }
    if (event.seq === this.lastSeq + 1) {
      this.apply(event);
      return;
    }
    this.stats.gaps += 1;
    this.syncBuffer.push(event);
    this.enterSync();
  }

  private apply(event: CanonicalEvent): void {
    this.lastSeq = event.seq;
    this.stats.applied += 1;
    this.emit(event.type, event);
    this.emit("*", event);
  }

  private emit(type: string, event: CanonicalEvent): void {
    const listeners = this.handlers.get(type);
    if (!listeners) return;
    for (const listener of listeners) {
      try {
        listener(event);
      } catch (error) {
        this.report(error);
      }
    }
  }

  private enterSync(): void {
    if (this.closed || this.syncing) return;
    this.syncing = true;
    this.syncOverflow = false;
    this.setStatus("syncing");
    this.clearTimer();
    this.closeTransport();
    // Pace consecutive syncs: without this, a persistently gapping server
    // (resync_needed on every resume) hot-loops sync→resume→sync with zero
    // backoff. Live frames keep buffering while we wait.
    const gen = this.generation;
    const elapsed = Date.now() - this.lastSyncCompletedAt;
    const waitMs = Math.max(0, this.opts.minSyncIntervalMs - elapsed);
    if (waitMs === 0) {
      void this.replayLoop(gen);
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.closed || gen !== this.generation) return;
      void this.replayLoop(gen);
    }, waitMs);
  }

  /**
   * Page durable replay until caught up, merge buffered live frames, then
   * resume the stream. Escalates to snapshot resync when the server refuses
   * paging or the merge cannot converge.
   */
  private async replayLoop(gen: number): Promise<void> {
    let latestSeen = this.lastSeq;
    let pages = 0;
    for (let pass = 0; pass < MAX_SYNC_PASSES; pass += 1) {
      if (this.closed || gen !== this.generation) return;
      pages += 1;
      if (pages > MAX_SYNC_PAGES) {
        this.finishResync(latestSeen);
        return;
      }
      let page: ReplayPage;
      try {
        page = await this.fetchReplay(this.lastSeq, this.opts.replayLimit);
      } catch (error) {
        if (this.closed || gen !== this.generation) return;
        this.syncing = false;
        if (error instanceof RealtimeHttpError && error.status === 401) {
          this.authError = "unauthorized";
          this.setStatus("offline");
          return;
        }
        if (error instanceof RealtimeHttpError && error.status === 403) {
          this.authError = "forbidden";
          this.setStatus("offline");
          return;
        }
        this.report(error);
        this.scheduleReconnect(gen);
        return;
      }
      if (this.closed || gen !== this.generation) return;
      latestSeen = Math.max(latestSeen, page.latest_seq);
      if (page.resync_required) {
        this.finishResync(page.latest_seq);
        return;
      }
      for (const event of page.events) {
        if (!Number.isInteger(event.seq)) continue;
        if (event.seq <= this.lastSeq) continue;
        if (event.seq === this.lastSeq + 1) {
          this.apply(event);
        } else {
          break; // Defensive: the server pages contiguously; never skip.
        }
      }
      if (page.has_more) continue;
      if (this.syncOverflow) {
        this.finishResync(latestSeen);
        return;
      }
      if (this.drainSyncBuffer()) {
        this.stats.replays += 1;
        this.syncing = false;
        this.lastSyncCompletedAt = Date.now();
        this.openStream(gen);
        return;
      }
      // Buffered live frames exposed a further gap — replay again.
    }
    this.finishResync(latestSeen);
  }

  /** Merge buffered live frames through the gate. `false` = gap remains. */
  private drainSyncBuffer(): boolean {
    const buffered = this.syncBuffer;
    this.syncBuffer = [];
    buffered.sort((a, b) => a.seq - b.seq);
    for (const event of buffered) {
      if (event.seq <= this.lastSeq) {
        this.stats.duplicates += 1;
        continue;
      }
      if (event.seq === this.lastSeq + 1) {
        this.apply(event);
        continue;
      }
      this.stats.gaps += 1;
      this.syncBuffer = buffered.filter((candidate) => candidate.seq > this.lastSeq);
      return false;
    }
    return true;
  }

  private finishResync(latestSeq: number): void {
    const fromSeq = this.lastSeq;
    this.stats.resyncs += 1;
    this.syncing = false;
    this.lastSyncCompletedAt = Date.now();
    this.syncOverflow = false;
    this.syncBuffer = [];
    this.lastSeq = Math.max(this.lastSeq, latestSeq);
    try {
      this.opts.onResyncRequired?.({ fromSeq, latestSeq: this.lastSeq });
    } catch (error) {
      this.report(error);
    }
    if (!this.closed) {
      this.openStream(this.generation);
    } else {
      this.setStatus("offline");
    }
  }
}
