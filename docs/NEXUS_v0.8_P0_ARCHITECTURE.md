# Nexus v0.8 — P0 Production Foundations

This document describes the v0.8 P0 implementation that hardens Nexus for
multi-worker production deployments. v0.8 supersedes the v0.7 in-memory
singletons with authoritative PostgreSQL-backed services, real multi-worker
realtime via Redis Pub/Sub, a real AuthZ layer, and a structured Vanessa
LLM pipeline.

## v0.8.2 Closeout — Routing Flip & Dual-Path Removal (2026-09) — **CLOSED 2026-09-09**: merged to main via PR #1 (merge commit 57e5a51), 15/15 CI checks green

The persistent PostgreSQL-backed router (`app/api/v1/nexus_persistent.py`)
is the **only production authority** for the Nexus namespace. The v0.7
in-memory routers were demoted to an explicit legacy namespace:

```
/api/v1/nexus/*              → canonical: persistent router
                               (AsyncSession → PostgreSQL → Authoritative* services;
                                NO fallback to v0.7 in-memory singletons)

/api/v1/v07-legacy/nexus/*   → v0.7 in-memory routers, mounted ONLY when
                               CORTEX_NEXUS_V07_LEGACY_ROUTES is explicitly
                               enabled (unit tests, migration tooling,
                               historical v0.7 demos). Default: not mounted.
```

Enforced by `tests/test_nexus_v082_routing_flip.py`:
- the canonical surface is exactly the 14 persistent-router operations;
- the old in-memory authoritative ops are gone from `/api/v1/nexus/*`;
- a full HTTP lifecycle runs under legacy-singleton tripwires — the
  legacy `DecisionLifecycleManager` / `DecisionMemory` / `TruthLoop` /
  `ObservationStore` MUST NOT BE CALLED, and all state lands in the DB;
- envelopes, status codes, error envelopes, and workspace authorization
  are unchanged (only the backing implementation changed).

The real-PostgreSQL `FOR UPDATE` guarantee (exactly one winner, exactly
one 409, no duplicate audit transition, no corruption — at both service
and HTTP level) is covered by `tests/test_nexus_v082_pg_concurrency.py`.

Known follow-up (v0.9): remove the `/v07-legacy/*` mounts entirely.

## Core Invariant

> **ONE AUTHORITATIVE WORLD, ONE TRACE, ONE GOVERNED DECISION LOOP, ONE EVIDENCE CHAIN.**

PostgreSQL is the sole source of operational truth. Every other state —
ontology caches, graph caches, decision projections, in-memory buffers —
is derived from PG and rebuildable. No in-memory singleton is allowed to
hold authoritative state across requests, workers, or restarts.

## P0 Items (all complete)

### 1. PG-backed stateful services

Three v0.7 in-memory singletons are replaced with transactional PG services:

| v0.7 in-memory singleton            | v0.8 PG-backed service                          |
|-------------------------------------|-------------------------------------------------|
| `DecisionLifecycleManager`          | `AuthoritativeDecisionService`                  |
| `DecisionMemory`                    | `AuthoritativeDecisionMemory`                   |
| `TruthLoop` / observation store     | `AuthoritativeTruthLoop`                        |

**`AuthoritativeDecisionService`** (`p0_migration/authoritative_decisions.py`):
- Writes use `SELECT ... FOR UPDATE` row locking
- Validates transitions against the canonical `ALLOWED_TRANSITIONS` state machine
- Detects world-state staleness via world_state_version + world_state_hash
- Appends `DecisionTransitionDB` rows (append-only audit trail)
- Inserts outbox `EventRecordDB` rows in the SAME transaction
- Per-process LRU projection cache with 30s TTL + peer invalidation hooks
- Exposes `create` / `advance` / `record_outcome` / `get` / `list_by_phase` / `list_by_workspace`
- Raises `StaleWorldStateError` / `InvalidTransitionError`

**`AuthoritativeDecisionMemory`** (`p0_migration/authoritative_memory.py`):
- Token-overlap similarity retrieval (`find_analogous`) against PG
- `record` / `update_outcome` / `recent` — all transactional
- Per-process cache with invalidation on write

**`AuthoritativeTruthLoop`** (`p0_migration/authoritative_truth.py`):
- `record_forecast` / `observe` — forecasts and actuals persisted in PG
- `calibration_for` computes MAE/MPE/bias/P80-coverage/P95-coverage per SKU
- `systematic_bias` flags SKUs whose mean percentage error exceeds threshold

Multi-worker test (`test_decision_survives_simulated_restart`) exercises the
restart invariant: Worker A creates; drop the service (simulate restart);
Worker B (fresh cache) reads and advances through the full lifecycle; drop;
Worker C authorizes and executes; drop; Worker D records outcome, memory,
forecast, and observation. Final state is read back and asserted consistent.

### 2. Table classification

`p0_migration/table_classification.py` encodes every persisted table's role:

```
AUTHORITATIVE  : ground truth — world_states, world_state_events, nexus_decisions,
                 nexus_decision_transitions, nexus_approvals, nexus_executions,
                 nexus_outcomes, nexus_entities, nexus_relationships,
                 nexus_evidence_nodes/edges, nexus_forecasts, nexus_observations,
                 nexus_recommendations, nexus_model_registry, nexus_events,
                 nexus_vanessa_sessions/messages
PROJECTION     : derived from AUTHORITATIVE — nexus_risks, nexus_scenarios
CACHE          : (reserved for materialized caches in v0.9)
TEMPORARY      : (reserved for ephemeral per-request state in v0.9)
```

Tests verify every table is classified and that world/decisions/ontology are
AUTHORITATIVE while risks/scenarios are PROJECTION (never independent truth).

### 3. Multi-worker realtime bus (Redis Pub/Sub)

`infrastructure/realtime_bus.py` implements:

- **Channel**: `nexus:events:{workspace_id}` (per-workspace fan-out)
- **Sequence numbers**: `INCR nexus:seq:{workspace_id}` in Redis (monotonic per workspace); falls back to a local high-offset counter when Redis is unavailable (dev/test)
- **At-least-once delivery**: events persist in PG outbox; Redis delivery is best-effort; missed events are recovered by client-initiated replay
- **Idempotent consumers**: consumers key off `event_id`
- **Gap detection**: `sse_stream()` tracks prev_seq and emits `resync_needed` SSE event if the next seq jumps by >1, so clients know to reconnect with last-known seq
- **Replay/resync**: `replay_since()` replays from a circular in-memory buffer (1000 events / workspace); PG outbox is the source of truth for deep replays
- **Graceful fallback**: if Redis is unavailable (dev, tests), the bus degrades to local-fan-out mode so SSE still works within a single worker

SSE protocol:

```
-> client connects with last_seen_seq=N
<- event: connected  ({workspace_id, last_seen_seq})
<- [replay events with seq > N]
<- [live events]
<- event: resync_needed  ({from_seq, to_seq}) if gap detected
   (client disconnects and reconnects with new last_seen_seq)
```

### 4. AuthZ — real role-based permissions

`p0_migration/authz.py` implements the full chain:

```
User → Tenant → Organization → Workspace → Role → Tool permission → Data permission
```

**Roles** (3 operational tiers + admin):

| Role     | Query/Inspect | Analyze/Simulate/Compare | Approve/Execute | Admin |
|----------|:-------------:|:------------------------:|:---------------:|:-----:|
| viewer   |       ✓       |             ✗            |        ✗        |   ✗   |
| analyst  |       ✓       |             ✓            |        ✗        |   ✗   |
| operator |       ✓       |             ✓            |        ✓        |   ✗   |
| admin    |       ✓       |             ✓            |        ✓        |   ✓   |

24 tool permissions are enumerated in `TOOL_PERMISSIONS`.

**Tenant/workspace isolation**: every `check()` validates the data tenant and workspace match the principal's scope (admins may cross workspace within tenant).

**`SYSTEM_PRINCIPAL`** exists for internal background jobs (e.g. RL candidate generation) and is explicitly NEVER passed to LLM-initiated tool calls.

**CRITICAL INVARIANT**: the LLM cannot manufacture authority. If it claims permission the principal doesn't have, the tool raises `PermissionDenied` and the response reflects it.

### 5. Vanessa LLM pipeline

`p0_migration/vanessa_pipeline.py` replaces keyword-matching Vanessa with a
proper structured pipeline:

```
User message
   ↓
[1] Structured Intent Classification  (pluggable LLM adapter)
   ↓
[2] Permission Check                  (AuthZ against principal)
   ↓ (denied: stop with permission error — tool executor never invoked)
[3] Tool Plan                         (LLM + intent→tool mapping)
   ↓
[4] Tool Execution                    (registered executor, auth-gated)
   ↓ (Vanessa never writes DB — tools call services; services write PG)
[5] Reasoning synthesis               (LLM)
   ↓
[6] Structured Response               (citations, actions, trace ID)
```

**Invariants enforced in code and tested**:
- `VanessaPipeline` source does not import `AsyncSession` and never calls `session.add` / `session.commit` directly (verified by static source check in tests).
- All side effects go through registered tool executors.
- Tool executors are only invoked AFTER AuthZ.check() succeeds.
- Priority-ordered intent classification ensures operational verbs ("approve", "execute", "compare") beat generic nouns ("decision") so "approve the decision" classifies as APPROVE not DECISION_QUERY.
- When no LLM API is configured, `DeterministicLLMAdapter` provides a rule-based fallback that exercises the SAME pipeline (this is not a return to keyword Vanessa — intent classification is deterministic but the AuthZ, tool planning, evidence, and synthesis chain is identical).
- Every call produces a `trace_id` (`TRC-...`) for audit.

16 intents are recognized (read, analyze, operational, meta).

## Files

```
backend/app/modules/nexus_spine/p0_migration/
    __init__.py                       — package exports
    table_classification.py           — AUTHORITATIVE/PROJECTION/CACHE/TEMPORARY
    authoritative_decisions.py        — PG-backed decision lifecycle
    authoritative_memory.py           — PG-backed decision memory
    authoritative_truth.py            — PG-backed forecast/observation/calibration
    authz.py                          — roles, permissions, principals
    vanessa_pipeline.py               — structured LLM pipeline
backend/app/infrastructure/
    realtime_bus.py                   — Redis Pub/Sub bus with seq/gap/replay
backend/tests/
    test_nexus_v1_p0.py               — 16 tests covering all 5 P0 items
docs/
    NEXUS_v0.8_P0_ARCHITECTURE.md     — this document
    NEXUS_v0.7_IMPLEMENTATION.md      — v0.7 reference (unchanged)
```

## Test Results

```
tests/test_nexus_v07.py ............. 25 passed  (v0.7 golden trace — no regressions)
tests/test_nexus_v1_p0.py ........... 16 passed  (v0.8 P0 new)
                                      =========
                                      41 passed
```

The 16 new P0 tests cover:
- Multi-worker restart survival (3 tests — full lifecycle walk, invalid transitions, append-only)
- Table classification (2 tests — completeness + authoritative/projection split)
- Realtime bus (3 tests — delivery, monotonic seqs, gap detection)
- AuthZ (4 tests — viewer/analyst/operator permissions + tenant isolation)
- Vanessa pipeline (4 tests — viewer cannot approve, operator reads state, no direct DB writes, intent classification priority)

## v0.8 → v0.9 Roadmap (next)

P1 (v0.9 AI & Learning):
1. Production-grade forecasting pipeline (Data → Features → ModelRegistry → Candidate → Backtest → Calibrate → Shadow → Promote → Prod → Forecast → Actual → TruthLoop); every prediction stored with full provenance
2. Trained GNN replacement; deterministic algorithms kept as baseline/fallback/oracle
3. RL remains constrained (candidate → Digital Twin → simulation → KPI → policy → human; never executes)
4. Recommendation quality as first-class metric (regret / NEV / SLA / cost error)
5. Cockpit v2 as primary product (Attention + Operating World + Decision + Vanessa layout)
6. Forecast vs Reality flagship view with Vanessa "why did we miss?" investigations

P2 (v0.95 Enterprise Beta):
- Enterprise connectors (ERP/WMS/TMS/OMS/CRM/MES/Procurement + CSV/API/SFTP/DB)
- Production infra (LB→API-N→Redis/Broker→PG/ObjectStore; HPA/PDB/readiness/liveness/rollback/backup/PITR/DR)
- Real observability (intelligence health + infra health; Vanessa answers "Is Nexus operating normally?")

v1.0 Launch: live customers, SLOs, DR, security, ROI, ops support.

## Milestone Status

**v0.8.3 — Realtime Outbox & Distributed Event Fabric: CLOSED** (2026-09-09)
- Invariant: A committed World State change must not disappear from the realtime stream.
- Database (`nexus_events` + migration 013) is the per-workspace sequence authority (`UNIQUE(tenant_id, workspace_id, seq)`).
- `OutboxPublisher` with `FOR UPDATE SKIP LOCKED` sweeper ensures multi-worker safety and peer reclaim.
- Realtime bus consumes DB-allocated sequence numbers (`publish_from_outbox`); durable `replay_since`.
- Acceptance matrix A1–A15 fully verified in `backend/tests/test_nexus_v083_outbox_acceptance.py` against real PostgreSQL.

**v0.8.4 — Real ML Inference & Model Promotion: CLOSED** (2026-09-09)
- Invariant: A trained model is a governed, immutable production dependency with complete prediction provenance and closed-loop feedback.
- `AuthoritativeModelRegistry` with strict lifecycle state machine and promotion gate hurdles (WAPE, RMSE, F1, Quantile Coverage, Shadow Parity).
- `AuthoritativeInferenceEngine` with deterministic probabilistic demand forecasting, GNN graph risk scoring, and SHA-256 feature hashing.
- Complete prediction provenance persisted in `nexus_forecasts` with outbox event `forecast.generated`.
- Closed-loop feedback & drift detection via `AuthoritativeTruthLoop` (residual tracking, quantile containment, systematic bias alerts).
- Acceptance matrix M1–M15 fully verified in `backend/tests/test_nexus_v084_ml_acceptance.py` against real PostgreSQL.

---

## Next milestone

**v0.8.5 — Live Operational Cockpit Backed by Production Truth**

