# ADR-015: Event-Sourced World State Architecture

**Status**: Accepted
**Date**: 2026-08-09
**Deciders**: Engineering
**Supersedes**: (none — codifies prior in-flight work; see Migration Plan §3)

## Context

Program J — World State & Digital Twin — is the **kernel of Cortex**. Every
later capability (Programs K–N: GNN, RL, Multi-Agent Runtime, Execution Plane)
will operate on the substrate defined here. If we get the invariants wrong,
every later program inherits the mistake; if we get them right, K–N evolve on
a stable, explainable, replayable foundation.

Today Cortex answers:

```
Evidence → Graph → Recommendation
```

Program J elevates Cortex to:

```
Evidence → Operational Graph → World State → Digital Twin → Simulation → Decision
```

This is achieved by re-platforming the substrate from "database rows" to:

```
State  +  Events  +  Time
```

### Why a constitution, not just code

Most of the Program J code already exists in `app/modules/events/`,
`app/modules/world/`, `app/modules/twin/`, `app/modules/simulation/`, and
`app/modules/knowledge/`, with `008_world_state.py` migration applied and
~40 tests covering projections, replay determinism, validation, and
event-sourcing. What is missing is the **architectural contract** — the
explicit, written invariants that future contributors (including AI agents and
later program authors) must not violate.

This ADR is that contract.

## Decision

### 1. Core Invariants (the constitution)

These invariants are **non-negotiable** for the entire lifetime of the
World State substrate. They bind every later program.

| # | Invariant | Rationale |
|---|-----------|-----------|
| I1 | **Append-only events.** The event log is never updated and never hard-deleted. Snapshots are derived caches and may be archived but the underlying events are permanent. | Audit, replay, tamper evidence. |
| I2 | **Hash-chained events.** Every event stores `event_hash` and `prev_event_hash`. The chain is verifiable end-to-end. | Tamper evidence + deterministic ordering. |
| I3 | **Deterministic projections.** Given the same event sequence, a projection produces the same state hash. No clocks, no randomness, no non-deterministic I/O in projection functions. | Replay reproducibility, simulation parity, RL training reproducibility. |
| I4 | **State is derived, never edited.** World state is reconstructed by projecting events. There is no `UPDATE world_states SET …` codepath. State rows may be inserted (for materialized views) but never mutated in place. | Single source of truth = the event log. |
| I5 | **Twin isolation.** A Digital Twin cannot `UPDATE`, `DELETE`, or `INSERT` into any table of its parent world. Twins have their own `world_id` lineage (via `parent_world_id`). | Prevent simulator accidents from corrupting production. |
| I6 | **Simulation operates only on twins.** The simulation engine reads and writes state for twin `world_id`s. It never references the production `world_id` of a workspace. | Architectural firewall. |
| I7 | **Per-workstream feature flags.** Each capability (events, world state, twin, simulation, knowledge) has its own flag. A failure in one capability never blocks another. | Independent rollout and rollback. |
| I8 | **Immutable history.** `world_state_events`, `world_versions`, and `world_snapshots` are INSERT-only. No `UPDATE` or `DELETE` in production code paths. | Reproducibility + audit. |
| I9 | **Replay is the source of truth.** If materialized state disagrees with replayed state, replay wins. The materialization is repaired. | Drift detection. |
| I10 | **Forward-compatible metadata.** Every event and state transition carries a `metadata` JSONB column reserved for future Programs (K–N) including `experiment_id`, `policy_version`, `decision_source`, `shadow_model_version`, `feature_vector_hash`. The columns exist now; consumers do not. | Pay no migration cost later. |

### 2. Architecture Layers

```
Layer 4 — Knowledge / Policy Engine   (rules, SLAs, playbooks, constraints)
Layer 3 — Simulation & Impact          (timeline, impact calculator, scenario registry)
Layer 2 — Digital Twin Runtime         (clone, inject, run, destroy)
Layer 1 — World State Engine           (state repository, projection, diff, validation, history)
Layer 0 — Event Kernel                 (event models, event store, hash chain, projection, replay)
```

Each layer depends only on the layer below it. Layer 2 (Twin) depends on
Layer 1 (World State) for state materialization; Layer 3 (Simulation) depends
on Layer 2 (Twin) for its substrate; Layer 4 (Knowledge) constrains all of
the above.

### 3. Event Kernel — Storage & Schema

**Tables** (single migration `008_world_state.py`, already applied):

- `world_state_events` — append-only event log (source of truth)
- `world_versions` — version lineage (parent_version_id chain)
- `world_snapshots` — periodic materialized checkpoints
- `world_states` — current materialized state per world_id
- `world_metadata` — provenance, tags, parent_world_id

**Hash storage.** `event_hash` and `prev_event_hash` are stored inside the
`metadata` JSONB column on `world_state_events` (along with `sequence`). This
is a deliberate deviation from a naïve first-class-column design — see
§6 Negative Consequences. The chain is verifiable via
`EventStore.verify(world_id)`.

**Event payload.** Every event row carries:

| Field | Type | Notes |
|-------|------|-------|
| `event_id` | `String(36)` PK | UUIDv7 (time-ordered) |
| `world_id` | `String(36)` indexed | Workspace's production or twin world |
| `workspace_id` | `String(36)` indexed | Tenant scope |
| `entity_type` | `String(64)` | warehouse, supplier, factory, route, component |
| `entity_id` | `String(64)` | Affected entity |
| `event_type` | `String(64)` | One of `WorldEventType` enum values |
| `payload` | `JSONB` | Event-specific fields |
| `caused_by_event_id` | `String(36)` nullable | Provenance link |
| `occurred_at` | `DateTime(tz)` indexed | Business time (not insert time) |
| `metadata` | `JSONB` | `{event_hash, prev_event_hash, sequence, …forward-compat keys}` |

**Forward-compatible metadata keys** (reserved names, consumed by K/L/M/N
later):

- `experiment_id`
- `policy_version`
- `decision_source`
- `shadow_model_version`
- `feature_vector_hash`
- `training_tags` (list[str])

These keys are written by future programs only. Program J does not write them.

### 4. Projection Rules

Projection functions live in `app/modules/events/event_projection.py`. They
are:

- **Pure**: no DB, no network, no clock, no randomness, no `datetime.now()`.
  The only inputs are `(state, event)`. All "current time" comes from the
  event's `occurred_at` field.
- **Total over typed events**: every `WorldEvent` subclass has a projector.
  The projector registry `_PROJECTORS` is the single source of truth and is
  asserted by `test_event_sourcing.py::test_all_event_types_have_projectors`.
- **Versioned**: each transition increments `state.version` by 1.
- **Closed-world**: event payloads carry enough context to compute the
  transition without external lookup.

### 5. Digital Twin Isolation

A Twin is identified by a distinct `world_id` whose `world_metadata` row has
`parent_world_id` pointing at the production world. Twin writes:

- **Append** to `world_state_events` where `world_id = twin.world_id` (allowed).
- **Never** `UPDATE` or `DELETE` rows in `world_state_events` where
  `world_id != twin.world_id`.
- **Never** mutate `world_states` for the parent.

The DB-level guarantee is provided by `twin_isolation.py` — twin services
must reject any operation whose `world_id` does not match the twin's lineage.

### 6. Simulation Boundary

The simulation engine accepts a `world_id` parameter and validates that
`world_metadata.source != "production"` for that world. Production workspaces
have a single production world per workspace; twins are tagged
`source = "twin:<twin_id>"`. Simulations against a production `world_id` raise
a `SimulationOnProductionError`.

### 7. Feature Flags (per-workstream)

Per ADR-008 (Feature Flags) plus this ADR, the following flags are added to
`Settings.feature_flags`:

| Flag | Default | Capability |
|------|---------|-----------|
| `FEATURE_EVENT_STORE` | `True` | Append + replay + verify events |
| `FEATURE_WORLD_STATE` | `True` | Materialize + diff + validate state |
| `FEATURE_DIGITAL_TWIN` | `False` | Clone / fork / destroy twin worlds |
| `FEATURE_SIMULATION` | `False` | Run scenarios on twins |
| `FEATURE_KNOWLEDGE` | `False` | Apply rules / SLAs / playbooks |

**Default-off** twins/simulation/knowledge so the wedge ships safe. Each
capability can be enabled independently.

### 8. Out of Scope (deliberately deferred to Programs K–N)

Program J does **not** add:

- Graph Neural Networks (Program K)
- Reinforcement Learning environments or policy learning (Program L)
- Multi-agent runtime (Program M)
- Execution plane / ERP writes (Program N)
- Streaming / live sync (Phase 3)
- LLM-based planning (Phase 3+)

These capabilities will consume the World State substrate but are not built
on top of it in Program J.

## Consequences

**Positive**:

- Locked invariants prevent K–N from "fixing" the substrate under them.
- Hash chain gives tamper-evident audit for free (regulator-ready).
- Determinism unlocks RL training reproducibility (Program L prerequisite).
- Twin isolation prevents the simulator from being the next outage vector.
- Per-workstream flags make partial-rollout safe.
- Forward-compatible metadata means no migrations when K/L land.

**Negative**:

- Storing hashes in the `metadata` JSONB column (not first-class columns)
  costs ~10–15% on chain-verification queries. Accepted because (a) it avoids
  a schema migration on already-deployed tables, (b) Postgres JSONB
  containment queries suffice for `verify()`, and (c) we can promote the
  columns to first-class later without breaking consumers. Migration plan §4
  schedules the optional promotion.
- Append-only events mean unbounded table growth. Mitigated by snapshot
  compaction (snapshots older than N versions can be archived, events never
  can) plus Postgres partitioning on `occurred_at` when event volume justifies
  it (Phase 3).
- Five feature flags instead of one. Mitigated by keeping the list short
  and reviewing on every ADR.

## Migration Plan

### 1. ADR & DECISIONS entry (this document)

- Add this ADR as `docs/architecture/ADR/0015-event-sourced-world-state-architecture.md`.
- Append a row to `DECISIONS.md`.

### 2. Feature flags

Add to `app/config.py:Settings.feature_flags` (defaults in §7):

```python
"FEATURE_EVENT_STORE": True,
"FEATURE_WORLD_STATE": True,
"FEATURE_DIGITAL_TWIN": False,
"FEATURE_SIMULATION": False,
"FEATURE_KNOWLEDGE": False,
```

### 3. Milestone sequence

Four milestones, each with its own CI gate and exit criterion:

| Milestone | Scope | CI Gate | Exit Criterion |
|-----------|-------|---------|----------------|
| **J.1** Event Kernel | Hash chain hardening, `event_replay.py` module, `event_hashing.py` extraction, `event_validation.py` module, replay-determinism stress test, `FEATURE_EVENT_STORE` boundary check | Replay Determinism · Hash Verification | Replaying 100k events reconstructs identical state every run. |
| **J.2** World State Engine | Wire `state_projection` projectors into the canonical event flow; ensure `store_version` is the only write path; add `state_history.reconstruct`; add diff + validation API | Projection · Diff · Validation | World State is fully reconstructable from events; `get(world_id)` equals `replay(world_id)` byte-for-byte. |
| **J.3** Digital Twin | Lock `twin_isolation.py` invariants; add concurrency test (100 twins, no prod mutation); add `cleanup` invariants; add `FEATURE_DIGITAL_TWIN` boundary check | Twin Isolation · Concurrency | 100 concurrent twins cannot mutate production. |
| **J.4** Simulation + Knowledge | Implement only the four seed scenarios (Supplier Delay, Supplier Failure, Demand Spike, Inventory Shortage); `policy_engine.py` constraints; `FEATURE_SIMULATION` + `FEATURE_KNOWLEDGE` boundary checks | Simulation Regression · Knowledge Rule Validation | Simulations are deterministic; knowledge rules reject invalid scenarios. |

Frontend is deferred until J.3 has stable APIs. Only three pages ship in J.4:
`World Viewer`, `Twin Viewer`, `Simulation Timeline`.

### 4. Optional future work (post-Program J)

- Promote `event_hash` / `prev_event_hash` / `sequence` from JSONB to
  first-class columns on `world_state_events` if verify() becomes a hot path.
- Add Postgres declarative partitioning on `world_state_events(occurred_at)`
  when a single workspace exceeds ~10M events.
- Externalize feature flags to a DB or remote service if per-workspace
  toggling is required (currently env-based, per ADR-008).

### 5. Known implementation gaps vs this ADR (to close during J.1)

- `event_hashing.py` does not exist as a separate module — hashing is inline
  in `event_store.py`. Extract during J.1 for testability.
- `event_replay.py` does not exist — replay logic lives inside `EventStore`.
  Extract during J.1 for reuse by Twin (Layer 2) and Simulation (Layer 3).
- `event_validation.py` does not exist — typed dataclasses do not validate
  payload shape. Add structural validation during J.1.
- The `state_projection` projector registry in `event_projection.py` and
  the legacy `state_projection.py` (`project_event_to_transition` etc.) are
  two parallel paths. Consolidate during J.2.
- Forward-compatible metadata keys (`experiment_id`, `policy_version`, etc.)
  are not yet documented in code. Add a `METADATA_KEYS` constant during J.1.

## References

- ADR-008 (Feature Flags) — flag mechanism
- ADR-007 (Workflow Engine Deferred) — boundary-enforcement precedent
- ADR-003 (Deterministic MVP) — determinism invariant precedent
- `docs/16-event-taxonomy.md` — event-category precedent (T3/T4/T5)
- `docs/13-constitution.md` — Cortex's platform-level constitution
- `app/modules/events/` — existing Event Kernel
- `app/modules/world/` — existing World State Engine
- `app/modules/twin/`, `app/modules/simulation/`, `app/modules/knowledge/`
  — existing capability layers
- `alembic/versions/008_world_state.py` — current schema
- `tests/test_event_sourcing.py`, `tests/test_world_state.py` — existing
  coverage baseline
