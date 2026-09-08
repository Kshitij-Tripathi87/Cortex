# NEXUS v0.8.3 — Realtime Outbox & Distributed Event Fabric (Design)

Status: **DESIGN — milestone opened 2026-09-09** (v0.8.2 closed via PR #1, 15/15 CI green)
Owner: NEXUS spine program
Predecessor: `NEXUS_v0.8_P0_ARCHITECTURE.md` §v0.8.2 Closeout (routing flip; persistent path is the only production authority)

---

## 1. The invariant

> **A committed World State change must not disappear from the realtime stream.**

Corollaries:

1. The outbox event is written **in the same database transaction** as the state
   mutation — never published to the broker first and "hoped" to succeed.
2. Sequence numbers are allocated by the **database**, per workspace, at INSERT
   time — the outbox is the single sequence authority.
3. Delivery to the fabric (Redis / broker) is **at-least-once**; consumers are
   **idempotent** by `event_id`.
4. A client that observes a sequence gap (e.g. receives `1042` then `1044`)
   **must detect the gap and resynchronize** — never silently accept an
   inconsistent operational view.

## 2. Target architecture

```text
World State Transaction
        │
        ├── state mutation
        └── outbox event (seq allocated in-tx)
                │
              COMMIT
                │
                ▼
          Outbox Publisher (per worker, post-commit)
                │
                ▼
           Redis / Broker
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
     API-1    API-2    API-N
        │       │        │
        └───────┼────────┘
                ▼
          SSE / WebSocket
                │
                ▼
          Nexus Cockpit
                │
                ▼
             Vanessa
```

## 3. Current state (what exists, verified in code)

| Piece | Status | Where |
|---|---|---|
| Outbox table | ✅ exists | `nexus_events` (`EventRecordDB`, persistence/models.py): event_id (unique), tenant/workspace, event_type, correlation/causation ids, payload, world_state_version, `published` flag |
| Transactional outbox write | ✅ exists | `p0_migration/authoritative_decisions.py` — decision + audit + outbox event in one `session.flush()` scope |
| Per-workspace monotonic seq on the outbox | ❌ missing | the bus allocates seq **after the fact** (Redis `INCR`, fallback `1e9+n` local) |
| Realtime bus | ✅ exists | `infrastructure/realtime_bus.py`: Redis pub/sub fan-out, local subscribers, 1000-event in-memory replay buffer, `sse_stream` with gap detection |
| Seq-source stickiness | ✅ shipped (v0.8.2 CI-green round) | first-allocation-fallback pins the workspace to the local counter — monotonic by construction; regression-pinned in `tests/test_realtime_bus_seq_fallback.py` |
| SSE endpoints | ✅ exist | `GET /api/v1/workspace/stream`, `POST /append-stream` |
| Readiness/health | ✅ fixed | `/readyz` redis check (was 503-everywhere coroutine bug) |

The v0.8.2 seq-stickiness fix is **permanent and carries forward**: it is the
stopgap that keeps a single workspace monotonic when Redis hiccups. v0.8.3
replaces its *cause* — the outbox becomes the sequence authority and the
Redis/local dual-space disappears entirely.

## 4. Design

### 4.1 Migration 013 — outbox becomes the sequence authority

`nexus_events` gains:

- `seq BIGINT NOT NULL` — per-`workspace_id` monotonic, allocated in-transaction
- `UNIQUE (tenant_id, workspace_id, seq)` — the database enforces monotonicity
  and rejects duplicate allocation (same discipline as the J.2.3
  concurrency-sequencing work on world-state events)
- `published_at TIMESTAMPTZ NULL` + `publish_attempts INT NOT NULL DEFAULT 0`
  — replaces the boolean `published` with observability (when, how hard we tried)
- `published_by TEXT NULL` — which publisher instance claimed the event

Allocation strategy (chosen for correctness under concurrency, mirroring the
FOR UPDATE race tests of v0.8.2):

```sql
-- inside the state-mutation transaction
INSERT INTO nexus_events (..., seq, ...)
SELECT ..., COALESCE(MAX(seq), 0) + 1
  FROM nexus_events
 WHERE tenant_id = :t AND workspace_id = :ws
```

wrapped with the workspace-sequence row lock the J.2.3 repository hardening
already uses — two concurrent writers to one workspace serialize at the
database, never at the application layer.

### 4.2 Publisher — post-commit, at-least-once

- **Trigger:** transaction-after-commit hook (`asyncpg`/SQLAlchemy event) for
  the writing worker, PLUS a periodic sweeper (`SELECT ... WHERE published_at
  IS NULL ORDER BY seq FOR UPDATE SKIP LOCKED LIMIT n`) so events orphaned by
  a crashed worker are picked up by peers.
- **Claim:** `FOR UPDATE SKIP LOCKED` on the sweeper makes multi-worker claim
  race-free without distributed locks.
- **Publish:** the event (with its DB-allocated `seq`) goes to the fabric via
  the existing bus channel; `published_at`/`published_by`/`publish_attempts`
  are updated after the broker ack.
- **Ordering:** within a workspace, publish in `seq` order. The sweeper batch
  is per-workspace ordered; cross-workspace order is irrelevant by contract.
- **Failure:** broker down ⇒ `publish_attempts` grows, event stays claimed
  briefly, is retried; nothing is lost (it is still in the database).

### 4.3 Bus & consumers

- `RealtimeBus.publish` gains `publish_from_outbox(event: Event)` — the seq
  arrives **with** the event; Redis `INCR` and the `1e9+n` local fallback are
  deleted for outbox-sourced events (the local fallback remains only for
  non-transactional demo paths, if any).
- Consumers deduplicate on `event_id` (idempotent apply).
- Gap detection stays client-side: `sse_stream` already emits
  `resync_needed` on a seq jump; the client then reconnects with
  `last_seen_seq` and the server replays from the outbox (`replay_since`),
  which v0.8.3 backs with the durable table instead of the 1000-event
  in-memory buffer.

### 4.4 Isolation

Tenant and workspace isolation are enforced at the outbox itself (RLS
policies exist for `integration_outbox`; the same pattern applies to
`nexus_events`) and at every consumer boundary — a replay or live stream for
workspace W can never contain another workspace's events. Both are in the
acceptance matrix.

## 5. Acceptance criteria

Every scenario below is a test, in the spirit of the v0.8.2 race tests:
real PostgreSQL (no SQLite substitutes for locking semantics), real
processes where process boundaries matter.

| # | Scenario | Must hold |
|---|---|---|
| A1 | Event ordering | per-workspace seq strictly increasing, commit order |
| A2 | Duplicate delivery | consumer applies each event exactly once (event_id idempotency) |
| A3 | Consumer idempotency | replay of the same batch produces identical state |
| A4 | Publisher restart | unpublished events are re-claimed by a peer sweeper; none lost |
| A5 | Redis restart | outbox retains events; publisher drains backlog; clients resync |
| A6 | Worker restart | in-flight publishes either land or are re-claimed — no loss, no dup seq |
| A7 | Broker partition | publisher blocks (attempts++), no data loss; partition heals ⇒ drain in seq order |
| A8 | Missed events | client that reconnects with last_seen_seq receives everything newer |
| A9 | Sequence gaps | client receiving 1042 then 1044 detects the gap and resynchronizes |
| A10 | Replay / resync | replay_since restores exact stream state after reconnect |
| A11 | Tenant isolation | no event crosses tenant boundary in live stream or replay |
| A12 | Workspace isolation | no event crosses workspace boundary in live stream or replay |
| A13 | SSE reconnect | reconnect with last_seen_seq resumes without loss or duplicate apply |
| A14 | WebSocket reconnect | same contract as A13 over WS transport |
| A15 | Concurrent writers | N writers to one workspace: unique seqs, commit-ordered, zero conflicts lost (FOR UPDATE serialization, same race-test discipline as v0.8.2) |

## 6. Out of scope (explicitly)

- Kafka as transport (compose already runs it; the fabric interface keeps a
  transport seam, but the MVP fabric is Redis pub/sub + outbox durability)
- Vanessa consumption changes beyond receiving the same guarantees
- Any ML-plane work (constitution: no ML until the spine is done)

## 7. Deliverables

1. Migration `013_outbox_sequence_authority` (seq + uniqueness + publish columns)
2. `OutboxPublisher` (after-commit hook + SKIP LOCKED sweeper)
3. `RealtimeBus.publish_from_outbox` + removal of post-hoc seq allocation for
   transactional events
4. Durable `replay_since` backed by the table
5. Acceptance tests A1–A15 (real PG; process-level where the scenario says so)
6. Docs: this file + updates to `16-event-taxonomy.md` and
   `NEXUS_v0.8_P0_ARCHITECTURE.md` on closeout
