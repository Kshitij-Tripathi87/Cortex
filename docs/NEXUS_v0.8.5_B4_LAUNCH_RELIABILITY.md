# Nexus v0.8.5-B4 — Launch Reliability (Durable Realtime)

Dedicated reliability PR for the realtime path. No product expansion: the
work proves that every committed mutation reaches every connected client
exactly-once-in-effect, and that every failure mode degrades loudly and
recovers automatically.

```
PG COMMIT → outbox row → relay claim/lease → Redis fabric → SSE/WS
  → sequence gate → replay/resync → React state
```

## 1. What B4 guarantees (acceptance)

| ID | Guarantee | Proven by |
|----|-----------|-----------|
| A1 | Transaction coupling: commit writes state+outbox, rollback writes neither | `test_nexus_v085_b4_reliability.py::TestA1*` |
| A2 | Concurrent writers get contiguous, unique, per-workspace seqs | TestA2* |
| A3 | At-least-once wire, exactly-once effect (idempotent consumer) | TestA3* |
| A4 | Graceful publisher restart: leases released, peer drains, order kept | TestA4* |
| A5 | Worker crash: leases honored until expiry, then peer reclaims | TestA5* |
| A6 | Expired claims move publishers and count `reclaimed_total` | TestA6* |
| A7 | Redis restart: partition blocks, heal drains in order | TestA7* |
| A8 | Redis outage: mutations still commit, backlog visible, then drains | TestA8* |
| A9 | Retry is exponential+jitter, poison is flagged once, rows never drop | TestA9* |
| A10 | Durable replay serves the TABLE (not delivery state), paged | TestA10* |
| A11 | Live gap emits bounded `resync_needed`, never silent reorder | TestA11* |
| A12 | Gap over threshold refuses paging (`resync_required`) | TestA12* |
| A13 | SSE reconnect resumes from cursor; `?token=` selects claims workspace | TestA13* |
| A14 | WS reconnect: catch-up → live tail → gap `resync_needed` | TestA14* |
| A15 | Replay/stream/catch-up never cross tenants | TestA15* |
| A16 | Workspace boundary is 403 (never logout); subscribe boundary; 4401 | TestA16* |
| A17 | API restart: publisher lifecycle, subscribers survive | TestA17* |
| A18 | Cursor-at-head replays nothing; next live seq must be `head+1` | TestA18* |
| A19 | Out-of-order arrival is a gap, never applied, never reordered | TestA19* |
| A20 | Stale/duplicate frames are ignored and counted | TestA20* |
| B4.1 | 10,000 concurrent mutations: contiguous, drained in order | TestB41* |
| C1–C5 | Chaos rehearsal: redis-kill, worker-kill, restart, replay 501–550, gap→replay | TestB4ChaosRehearsal |
| L1–L2 | Load probe: commit→client P50/P95/P99 + backlog drain throughput | TestB4LoadProbe |
| Pins | Outbox/realtime counters move; payloads never reach logs | TestB4MetricsPins, TestB4SecretsPin |
| FE1–FE14 | Client gate/dup/gap/replay/resync/reconnect/401/403/WS/token/overflow/pacing | `frontend/src/lib/realtime/client.test.ts` (vitest, 14 tests) |

Backend run: `pytest tests/test_nexus_v085_b4_reliability.py`
(needs `pgserver` or `CORTEX_TEST_PG_RACE_URL`; ~60s).
Frontend run: `npm test -- src/lib/realtime/client.test.ts` (~2s).

## 2. Wire protocol

### 2.1 Canonical event

Every transport carries the same shape (`Event.to_sse()` / WS frame /
replay row; WS adds `channel`/`tenant_id`/`workspace_id` routing keys):

```json
{
  "event_id": "EVT-…", "seq": 42, "type": "decision_created",
  "entity_type": "decision", "entity_id": "D-1",
  "payload": { "phase": "PROPOSED" },
  "world_state_version": 7, "correlation_id": "CORR-…",
  "timestamp": "2026-09-10T00:00:00Z"
}
```

`seq` is the per-workspace cursor allocated by Postgres at commit time
(`allocate_outbox_seq`, advisory-xact serialized). It is preserved
end-to-end: outbox row → Redis message → SSE/WS frame → client gate.

### 2.2 SSE — `GET /api/v1/nexus/realtime/stream`

Query: `workspace_id` (required), `after_seq` (default 0), `token`
(optional JWT for EventSource, which cannot set headers).

Frame order is load-bearing: `connected` → durable replay → live tail.

```
event: connected
data: {"workspace_id": "…", "last_seen_seq": 42}

event: decision_created
data: {"event_id": "…", "seq": 43, "type": "decision_created", …}

: ping

event: resync_needed
data: {"from_seq": 43, "to_seq": 45}
```

- Identity resolves **before the first byte**: 401/403 surface as JSON,
  never as a 200 stream.
- A presented `?token=` must verify (fail-closed 401); the streamed
  workspace comes from verified claims — the query value is ignored.
- `resync_needed` ends the stream (server-side gap). The client replays
  `after_seq=from_seq` over HTTP, then reconnects with the new cursor.

### 2.3 WebSocket — `/api/v1/realtime/ws`

Query: `workspace_id`, `tenant_id`, `after_seq` (default 0),
`replay` (default true), `token` (optional JWT).

```
→ {"type": "connection_established", "session_id": "…", …}
→ {"event_id": "…", "seq": 43, "type": "…", "channel": "outbox", …}  (catch-up)
→ {"type": "catchup_complete", "from_seq": 42, "to_seq": 43, …}
→ {"event_id": "…", "seq": 44, …}                                    (live tail)
→ {"type": "resync_needed", "from_seq": 44, "to_seq": 46}             (gap: stop)
```

- `resync_required` replaces paging when the gap exceeds
  `CORTEX_REALTIME_RESYNC_THRESHOLD` (snapshot, don't page).
- Handshake failures close with **4401** (no session). Control acks use
  `subscription_ack` (`success: false` across workspaces, never logout).

### 2.4 Durable replay — `GET /api/v1/nexus/realtime/events`

`workspace_id`, `after_seq`, `limit` → reconciliation envelope
(`{request_id, correlation_id, timestamp, data: {…}}`):

```json
{
  "events": [ …seq > after_seq, contiguous… ],
  "from_seq": 42, "to_seq": 47, "latest_seq": 52,
  "world_state_version": 9, "has_more": true, "resync_required": false
}
```

Page with `after_seq=to_seq` while `has_more`. `resync_required: true`
returns an empty page: refetch the authoritative snapshot and adopt
`latest_seq`.

### 2.5 Relay health — `GET /api/v1/nexus/realtime/health`

Aggregate-only (no tenant data): `api` / `db` / `redis` /
`outbox {pending_count, oldest_pending_age_s}` / `worker {heartbeat}`.
`/readyz` stays the K8s traffic gate; this endpoint is on-call truth —
a dead relay with a growing backlog reads `BACKLOGGING`/`DEGRADED` here.

## 3. Event catalog

### 3.1 Durable outbox types (SSE + WS + replay)

| `type` | Emitter (transactional) | Payload keys | Frontend reaction |
|--------|-------------------------|--------------|-------------------|
| `decision_created` | `authoritative_decisions.create` | `phase` | `refreshLiveState()` |
| `decision_invalidated` | decision advance → STALE/INVALIDATED | `reason` | invalidate decision UI + reason |
| `approval_granted` / `approval_rejected` | decision advance | `phase` | version bump (via `*`) |
| `execution_started` / `execution_completed` / `execution_failed` | decision advance | `phase` | version bump (via `*`) |
| `outcome_recorded` | decision advance / record | `phase`, outcome | version bump (via `*`) |
| `risk_changed` | `authoritative_registries` | graph delta + `kpis` | refetch signals |
| `risk.inferred` | `authoritative_inference` | `risk_score`, `criticality`, `revenue_exposure`, `blast_radius_count`, `entity_id`, model ids | refetch signals |
| `forecast_updated` | `authoritative_truth.record_forecast` | `sku`, `p50/p80/p95`, `forecast_id`, model ids | `refreshLiveState()` |
| `forecast.generated` | `authoritative_inference` | `sku`, `p50/p80/p95`, `horizon_days`, `confidence`, model ids | `refreshLiveState()` |
| `observation.recorded` | `authoritative_truth` | `sku`, actual vs bands, errors, `within_p80` | `refreshLiveState()` |
| `scenario_completed` | `authoritative_registries` | graph delta + `kpis`, `decision_id` | `refreshLiveState()` |
| `evidence_appended` | registries | evidence refs | version bump (via `*`) |
| `model.registered` / `model.evaluated` / `model.approved` / `model.promoted` / `model.rolled_back` | `authoritative_models` | `model_id`, `name`, `version`, `model_type` | version bump (via `*`) |

Declared in `NexusEventType` but **not emitted yet** (do not subscribe for
behavior): `world_state_changed`, `signal_created`, `vanessa_response`,
`model_deployed`, `model_rolled_back`, `drift_detected`,
`recommendation_made`.

### 3.2 Ephemeral gateway types (WS-only, unsequenced, not replayable)

| `event_type` | Emitter | Notes |
|---|---|---|
| `world_state_updated` | `state_pipeline` → gateway broadcast | legacy fanout; no `seq` |
| `agent.deliberation.completed` | `agent_runtime` → gateway broadcast | legacy fanout; no `seq` |

These bypass the outbox (no cursor, no replay, no SSE). `RealtimeClient`
ignores WS frames without a numeric `seq`. Migrating them to the outbox is
explicitly out of B4 scope.

### 3.3 Control frames (transport, never domain)

`connected`, `connection_established`, `catchup_complete`,
`resync_needed {from_seq,to_seq}`, `resync_required {from_seq,latest_seq}`,
`subscription_ack`, `: ping`, `4401` close.

## 4. Client contract (`frontend/src/lib/realtime/client.ts`)

- **Sequence gate**: apply iff `seq === lastSeq + 1`; `≤ lastSeq` drops as
  duplicate (counted); `> lastSeq + 1` is a gap → sync.
- **Preflight**: every (re)connect first hits replay with `limit=1`, which
  resolves 401/403 exactly and discovers `latest_seq`.
- **Sync**: close transport → page replay (`has_more`) → merge buffered live
  frames through the gate → resume stream. Consecutive syncs pace at
  `minSyncIntervalMs` (default 1s); unbounded paging escalates to snapshot.
- **Resync**: `resync_required` / buffer overflow / unmergeable gap → adopt
  `latest_seq`, call `onResyncRequired` (the surface refetches its snapshot),
  resume live.
- **Auth**: 401 → `unauthorized`, 403 → `forbidden`, both terminal
  (`offline`, no retry). 403 never clears the token. WS 4401 → unauthorized.
- **Reconnect**: infinite, capped exponential backoff + jitter, always with
  `after_seq=lastSeq`.
- **Cursor**: `getLastSeq()` is the resume cursor. `WorkspaceContext`
  persists it per workspace in `localStorage` (`cortex:realtime_seq:<ws>`);
  a browser refresh resumes instead of replaying from zero.
- **Status** (header pill): `live` → LIVE, `reconnecting`/`connecting` →
  RECONNECTING, `syncing` → SYNCING, `offline` → OFFLINE.

Legacy clients (`src/lib/realtime.ts`, `src/lib/realtime/nexusSocket.ts`,
`src/lib/api/realtime.ts`) are deprecated; the Playwright realtime spec
still targets the pre-B4 `/ws/realtime` URL and needs live-infra updates
outside this PR.

### Frontend env

| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend origin (default `http://localhost:8000`) |
| `NEXT_PUBLIC_NEXUS_WORKSPACE_ID` | Streamed workspace (default `default_workspace`) |
| `NEXT_PUBLIC_DEV_USER_ID` / `NEXT_PUBLIC_DEV_WORKSPACES` / `NEXT_PUBLIC_DEV_ROLES` | Dev `header`-identity headers; unset in prod |
| `cortex:access_token` (localStorage) | JWT → `?token=` on streams, `Authorization` fallback on HTTP |

## 5. Relay operations

- **Publishers**: in-process (`app.main` lifespan), dedicated worker
  (`app.workers.outbox_relay`), or both. Claim via `FOR UPDATE SKIP LOCKED`
  + lease; per-workspace publish exclusion on a sweep-pinned connection;
  head-of-line backoff gating; poison flagged at `max_attempts`, never
  dropped. Config: `CORTEX_OUTBOX_*` (`outbox_publisher_id` defaults to
  hostname; K8s uses the pod name).
- **Deploy**: `docker-compose.prod.yml` (`outbox-relay` service),
  `k8s/workers.yaml` (2 replicas). API boots even if the relay fails to
  start (writes stay durable; delivery resumes with the relay).
- **Migration**: `016_outbox_claim_lease` (claim/lease/retry columns).
- **Metrics**: `cortex_outbox_publish_total{result}`,
  `cortex_outbox_publish_attempts_total`, `cortex_outbox_reclaimed_total`,
  `cortex_outbox_poison_total`, `cortex_outbox_pending_count`,
  `cortex_outbox_oldest_pending_age_seconds`,
  `cortex_realtime_{connections,events_delivered_total,duplicate_events_total,gap_detected_total,replay_total,reconnect_total,resync_total}{transport,…}`.
  Payloads never appear in logs (pinned by test).
- **Knobs**: `CORTEX_REALTIME_RESYNC_THRESHOLD` (default 1000),
  `CORTEX_REALTIME_REPLAY_LIMIT`, `CORTEX_REALTIME_SSE_HEARTBEAT_S`.

## 6. Chaos & load evidence

```bash
# Full B4 backend suite (prints C1–C5 verdicts + L1/L2 numbers)
pytest tests/test_nexus_v085_b4_reliability.py -q -p no:cacheprovider

# Frontend gate
npm test -- src/lib/realtime/client.test.ts && npx tsc --noEmit
```

Reference numbers are printed by the suite (L1 commit→client P50/P95/P99,
L2 rows/s drain); the suite asserts generous CI budgets, humans judge the
trend. Chaos C1–C5 print one-line PASS verdicts.
