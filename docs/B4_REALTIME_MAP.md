# B4-REALTIME-MAP — Realtime stack recon (v0.8.5-B4)

Date: 2026-09-10. Base tree: `fc3c0bc` (= PR #5 head: main `50fcbfd` + B2 + B3).
Scope: durable outbox → relay → Redis transport → SSE/WS delivery → sequence
validation → replay/resync. No product expansion.

Legend: ✅ implemented+active · ⚠️ implemented+NOT activated · ❌ missing.

---

## 1. Outbox schema — ✅ (v0.8.3, migration 013)

Table `nexus_events` (`backend/app/modules/nexus_spine/persistence/models.py::EventRecordDB`):

| column | role |
|---|---|
| `id` | surrogate PK (NOT the order key) |
| `event_id` | identity (`EVT-*`, unique) — idempotency key |
| `tenant_id`, `workspace_id` | scope (indexed) |
| `seq` | **per-workspace order key**, `UNIQUE(tenant_id, workspace_id, seq)` |
| `event_type`, `entity_type`, `entity_id` | classification |
| `correlation_id`, `causation_id` | tracing |
| `payload` (JSON), `world_state_version` | content + authoritative state version |
| `published` (bool, legacy) + `published_at` | delivery state |
| `publish_attempts`, `published_by` | observability / worker attribution |
| `created_at` | insertion time |

Indexes: `ix_nexus_events_unpublished(published_at, seq)` for the sweep;
seq/tenant/workspace/type/entity/correlation/published/created indexes.
Migration `013_outbox_sequence_authority.py` is idempotent (create-or-alter).

**Gap vs B4:** no claim/lease columns (`claimed_at`, `claimed_by`, `lease_expires_at`,
`next_retry_at`, `last_error`). The sweeper marks `published_by` but a crash between
claim and commit leaves no reclaimable lease — reclaim today = "still unpublished",
which is correct but has no backoff/visibility-timeout, so a poisoned head-of-line
event is retried hot on every sweep.

## 2. OutboxPublisher — ⚠️ (exists, never runs)

`backend/app/infrastructure/outbox_publisher.py::OutboxPublisher`:

- ✅ `sweep_once()`: `SELECT … WHERE published_at IS NULL ORDER BY workspace, seq
  LIMIT n FOR UPDATE SKIP LOCKED` (PG), per-workspace in-order publish, stops a
  workspace batch on first failure (head-of-line guard).
- ✅ `publish_attempts += 1`, `published_by = publisher_id` per attempt.
- ✅ `start()/stop()` background loop + `trigger_publish()` wake-up event.
- ✅ `allocate_outbox_seq()`: `pg_advisory_xact_lock(hashtext(tenant:workspace))`
  + `MAX(seq)+1` — in-transaction, PG-serialized; UNIQUE constraint is the backstop.
- ❌ **Never instantiated at runtime**: no call in `app/main.py` lifespan, no worker
  entrypoint, no container. `trigger_publish()` has zero call sites (no fast path).
- ❌ **No claim/lease**: claim is the row lock held only for the sweep transaction;
  crash-safety relies on "unpublished rows get re-swept", which is fine for
  correctness but provides no attempt visibility timeout.
- ❌ **No retry policy**: no exponential backoff/jitter, no `next_retry_at`, no
  poison-event quarantine. A permanently failing event blocks its workspace
  (by design, order-preserving) but retries at sweep frequency, hot.
- ❌ **No metrics emission** (attempts/success/failure/latency/pending/age).

## 3. Publisher startup / lifecycle — ❌

- `app/main.py::lifespan`: init logging/tracing/metrics/DB only. No publisher start.
- No `python -m app…` worker entrypoint for a dedicated relay process.
- Containers: `docker-compose.prod.yml` has `agent-runtime` and `simulation-worker`
  only; no outbox-relay worker. Same for `k8s/workers.yaml`.
- B4 decision: run the sweeper **in-process in the API** (lifespan start/stop,
  `SKIP LOCKED` makes N API replicas a safe publisher pool) AND provide a
  dedicated worker entrypoint + container for deployments that want the relay
  isolated. Both share `OutboxPublisher`. No new infra (no Kafka, no microservice).

## 4. Redis bus — ⚠️ (transport exists, authz/hardening gaps)

`backend/app/infrastructure/realtime_bus.py::RealtimeBus` (v0.8.3 rewrite):

- ✅ `publish_from_outbox()`: consumes DB-allocated seq; publishes JSON to
  `nexus:events:{workspace}`; fans out to local subscribers; buffers for replay.
- ✅ Redis failure propagates (no suppress) → publisher counts attempt, row stays
  unpublished → backlog drains on recovery. Correct at-least-once posture.
- ✅ `_redis_listener` per workspace: subscribe → parse → `_fan_out_local`.
- ⚠️ Listener has no reconnect loop: any Redis error kills the task silently; the
  workspace then receives only local publishes until resubscribe. SSE gap logic
  papers over it via `resync_needed`, but cross-node fan-in is silently lost.
- ❌ Channel has no tenant component (`nexus:events:{workspace_id}`): workspace ids
  must be globally unique (they are UUIDs in v0.8) — document, don't redesign.
- ❌ `publish()` legacy path still mints Redis-`INCR`/local seqs — must be quarantined
  to non-authoritative/demo use; authoritative events flow only via outbox.
- `redis_client.py`: bounded timeouts (200ms connect / 500ms cmd, no retry) — good;
  E2E/CI uses authed Redis; `is_redis_available()` exists for health.

## 5. SSE gateway — ⚠️ (helper exists, no canonical endpoint)

- ✅ `realtime_bus.sse_stream()`: `connected` handshake → durable `replay_since`
  (DB session when provided, buffer fallback) → live tail with
  `event.seq <= prev → skip`, `> prev+1 → resync_needed + break`, else emit.
- ❌ **No HTTP endpoint serves it.** `/api/v1/workspace/stream` is the legacy
  graph-delta stream (in-memory `GraphDeltaEngine`, unrelated seq domain).
  The v0.7 `GET /nexus/realtime/events` returns in-memory `wm.events` (legacy).
- ❌ No authN/authZ on any SSE path delivering outbox events (endpoint doesn't exist).
- B4: add canonical `GET /api/v1/nexus/realtime/stream` (SSE, auth, `after_seq`
  replay) on the persistent router + keep legacy untouched.

## 6. WebSocket gateway — ⚠️ (auth + fanout exist, no seq/replay)

`realtime_gateway.py::RealtimeGateway` + `api/v1/realtime.py::/realtime/ws`:

- ✅ Handshake auth: JWT verify (secret envs) / dev header identity; fail-closed
  4401; workspace taken from verified claims.
- ✅ `subscribe()` enforces session workspace; tenant+workspace match on dispatch;
  cluster fan-out via Redis `cortex:realtime:cluster_events` (fire-and-forget,
  failure-counted). Dead-session pruning.
- ❌ **No sequence on WS frames, no replay/resync, no catch-up on connect.**
  WS and SSE are two disjoint fabrics (different Redis channels, different payload
  shapes). A WS client that disconnects loses events silently.
- B4: unify — WS subscribes the session to the `RealtimeBus` workspace feed and
  speaks the same `{event_id, seq, type, …}` envelope; add `after_seq` catch-up
  on connect + `resync_needed` semantics identical to SSE. Keep `RealtimeChannel`
  broadcast API for non-seq control traffic (agent messages etc. stay as-is).

## 7. Replay buffer — ⚠️ (dual, needs canonicalization)

- In-memory circular buffer (1000/ws) in `realtime_bus` — fast catch-up, lost on
  restart (acceptable: DB is the durable replay source).
- Durable `replay_since(workspace, since_seq, limit, session, tenant)` — ✅ queries
  `nexus_events WHERE seq > since ORDER BY seq`, tenant-scoped when provided.
- ❌ No HTTP replay endpoint; no `has_more`/`latest_seq`/`world_state_version`
  reconciliation envelope; no large-gap snapshot policy (threshold config).
- B4: `GET /api/v1/nexus/realtime/events?workspace&after_seq&limit` returning
  `{events, from_seq, to_seq, latest_seq, world_state_version, has_more}` with
  `require_workspace_access` authz; resync threshold config
  (`realtime_resync_threshold`, default e.g. 1000 → snapshot instead of replay).

## 8. Sequence generation — ✅ (PG authority, needs load proof)

- `allocate_outbox_seq`: advisory xact lock + `MAX+1`, UNIQUE backstop. No Redis
  participation. ✅ correct design.
- v0.8.3 A15 proves concurrent uniqueness on real PG (test-only scale).
- B4: B4.1 acceptance (10k concurrent mutations → 10k durable rows, contiguous
  per-workspace seq), plus rollback-coupling tests (commit→state+outbox,
  rollback→neither). No Redis in the transaction (already true — verify by test).

## 9. Frontend realtime clients — ❌ (three clients, zero seq discipline)

| file | transport | seq? | replay? | state machine? |
|---|---|---|---|---|
| `src/lib/realtime.ts` (`NexusRealtimeClient`) | WS `/api/v1/realtime/ws` | ❌ | ❌ (blind reconnect) | ❌ |
| `src/lib/realtime/nexusSocket.ts` (`NexusSocketManager`) | WS `/api/v1/ws/workspace` (stale URL) | ❌ | ❌ (`reconcileMissedDeltas` is a stub) | ❌ |
| `src/lib/api/realtime.ts` | WS helpers/types, no seq | ❌ | ❌ | ❌ |

- No `lastSeq`, no gap detection, no replay/resync, no connection-state exposure
  for UI (`Live/Reconnecting/Syncing`).
- B4: ONE `RealtimeClient` (`src/lib/realtime/client.ts`): `connect/disconnect/
  reconnect/subscribe/handleEvent/detectGap/replay/resync`, states
  `DISCONNECTED/CONNECTING/LIVE/RECONNECTING/RESYNCING/FAILED`, SSE-first with WS
  fallback sharing the envelope + sequence gate; `useRealtimeStatus()` hook +
  `<ConnectionStatus/>` indicator. Legacy clients stay until cockpit rewire (post-B4).

## 10. Existing realtime tests — ⚠️ (good bones, B4 family missing)

- `test_nexus_v083_outbox_acceptance.py`: A1–A15 on real PG (pgserver or
  `CORTEX_TEST_DATABASE_URL`), incl. ordering, idempotency, publisher/worker
  restart, Redis partition, gaps, replay, isolation, SSE/WS reconnect sketches,
  concurrent writers. ✅ keep green; extend, don't fork.
- `test_realtime_seq_resync.py`: legacy graph-delta seq contract (unrelated domain).
- `test_multi_instance_realtime_fanout.py`, `test_replay_consistency.py`,
  `test_program_s_live_workspace.py`: adjacent coverage.
- B4 adds `test_nexus_v085_b4_reliability.py`: A1–A20 per spec (transaction
  coupling, concurrent seq, duplicates, publisher restart, worker crash, lease
  reclaim, Redis restart/outage, backoff, durable replay, gaps, large-gap resync,
  SSE/WS reconnect, tenant+workspace isolation, API restart, browser refresh
  ≡ reconnect-with-cursor, out-of-order, stale). Deterministic: pgserver PG +
  fakeredis/fault-injecting bus doubles, no `sleep`-luck.
- E2E (Playwright, 26/26 = `critical-path` + `auth`): `realtime-e2e.spec.ts` is
  NOT in the CI run list and points at stale URLs — B4 adds a small realtime
  spec (`stream → mutate → frame arrives; disconnect → replay`) and wires it into
  `e2e.yml` without breaking the 26-count gate (additive).

## 11. Worker / container definitions — ❌ (relay has none)

- API: `backend/Dockerfile` + compose `backend`/`backend-api-{a,b}` (uvicorn).
- Workers: only `agent-runtime`, `simulation-worker`.
- B4: `backend/app/workers/outbox_relay.py` (`asyncio` entrypoint: init DB → start
  `OutboxPublisher` → run until SIGTERM) + `outbox-relay` service in
  `docker-compose.prod.yml` + `k8s/workers.yaml` entry. Env knobs:
  `CORTEX_OUTBOX_*` (enabled, sweep interval, batch size, lease/backoff) — see §12.

## 12. Health / readiness — ⚠️ (deps only, no relay awareness)

- `GET /healthz` (liveness), `GET /readyz` → `check_dependencies()`: db, redis,
  object_storage, audit_chain. Redis DOWN currently fails readiness (F2 design).
- B4 tension (spec Phase 14): relay-dead must be VISIBLE but Redis must not
  needlessly hard-fail the API when the outbox design explicitly tolerates Redis
  outage (mutations continue, backlog drains). Resolution: keep `/readyz`
  semantics (traffic gate), add `GET /api/v1/nexus/realtime/health` (or extend
  readyz components) reporting `API/DB/Redis/Outbox(backlog, oldest-age)/Worker`
  with `HEALTHY/DEGRADED/BACKLOGGING` — operational truth without changing the
  K8s gate. Outbox component reads pending count + oldest pending age + publisher
  heartbeat.
- Metrics today: api/uploads/evidence/conflicts/readiness/db/worker only.
  B4 adds `cortex_outbox_*` + `cortex_realtime_*` per spec Phase 13 + correlation
  fields (`request_id, tenant_id, workspace_id, event_id, seq`) on logs/frames.
  Never log secrets (already the posture — add a test pin).

## 13. B3 mutation → outbox coverage (event catalog input)

All via in-transaction `allocate_outbox_seq` + `EventRecordDB` insert; endpoint owns
commit; zero `trigger_publish` calls (sweeper-only once activated):

| producer (service) | endpoint(s) | event(s) |
|---|---|---|
| `AuthoritativeDecisionService.create` | `POST /nexus/persistent/decisions` | `decision_created` |
| `…advance` (invalidate path) | `POST …/advance` | `decision_invalidated` |
| `…advance` (`_phase_event_type`) | `POST …/advance` | `approval_granted/rejected`, `execution_started/completed/failed`, `outcome_recorded`, `decision_invalidated` |
| `…record_outcome` | `POST …/outcome` | `outcome_recorded` |
| `AuthoritativeRegistryService` risks | `POST/PATCH /nexus/persistent/risks` | `risk_changed` |
| `…` scenarios | `POST …/scenarios`, `POST …/simulate` | `scenario_completed` |
| `…` evidence | `POST …/evidence/nodes|edges` | `evidence_appended` |
| forecasts/observations (`nexus_persistent` direct) | `POST /nexus/persistent/forecasts|observations` | ❌ NO outbox write |
| models/inference/vanessa/memory | various | ❌ NO outbox write |

B4 scope decision: harden the relay for the events that exist (priority catalog:
`forecast.generated`≡`forecast_updated` name TBD, `signal.created`, `risk.updated`
≡`risk_changed`, `scenario.created/completed`, `decision.updated`, `approval.recorded`
≡`approval_granted/rejected`, `execution.completed`, `outcome.recorded`); do NOT
mint dozens of new types. Add missing `forecast_updated` + `signal_created` writes
only if they are one-line `_emit` calls in existing transactions (forecast record is;
signal detection is read-path — document as non-mutating, no outbox). Keep the
`NexusEventType` snake_case wire values (B4-EVENT-CATALOG.md maps spec names →
wire names).

## 14. Activation checklist (what B4 actually builds)

1. `EventRecordDB` + migration 014: `claimed_at/by`, `lease_expires_at`,
   `next_retry_at`, `last_error` (+ index on `(lease_expires_at, next_retry_at)`).
2. `OutboxPublisher`: fast path (`publish_committed()` immediate attempt post-commit),
   lease claim (`lease_seconds`, heartbeat), reclaim-expired, exp-backoff+jitter
   (`next_retry_at`), poison cap (`max_attempts` → DLQ-ish `last_error`, still
   order-blocking, loudly metriced), metrics, structured logs w/ correlation.
3. Lifespan wiring: start/stop singleton publisher in API (env-gated
   `CORTEX_OUTBOX_PUBLISHER_ENABLED`, default ON) + `workers/outbox_relay.py`
   entrypoint + compose + k8s.
4. Fast-path triggers: after `session.commit()` in B3 mutation endpoints (or a
   decorator/helper — one place, not 20 edits).
5. Canonical replay endpoint + SSE endpoint on persistent router (authN+authZ).
6. WS upgrade: same envelope + `after_seq` catch-up + gap/resync semantics.
7. Frontend `RealtimeClient` + status hook + indicator; unit tests (vitest/jest
   per repo convention — check `frontend/package.json`).
8. Metrics (`cortex_outbox_*`, `cortex_realtime_*`), realtime health endpoint,
   `/readyz` unchanged.
9. `B4-EVENT-CATALOG.md` + `docs/LAUNCH_BUILD_LOG.md` B4 entry + OpenAPI/TS regen.
10. `test_nexus_v085_b4_reliability.py` (A1–A20) + chaos script
    (`scripts/b4_chaos_rehearsal.py`, deterministic, pgserver+fakeredis) + load
    probe (P50/P95/P99 commit→client, backlog drain time) + Playwright realtime
    spec wired into `e2e.yml`.
11. Full regression gate: focused B4 → backend suite → frontend unit/typecheck →
    prod build → real PG/Redis integration → E2E → chaos → full CI (15/15, 26/26+).

## 15. Explicit non-goals (spec: What NOT to do)

No Kafka · no microservices · at-least-once + idempotency (no exactly-once) ·
PG authoritative (Redis never mints authoritative seq) · no second event store ·
no autonomous execution from events · no cockpit redesign · no event-type explosion ·
correctness before scale.
