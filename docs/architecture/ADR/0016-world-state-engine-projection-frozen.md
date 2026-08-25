# ADR-016: World State Engine — Canonical Projection & Version Semantics

**Status**: Accepted
**Date**: 2026-08-09
**Deciders**: Engineering
**Supersedes**: the pre-ADR dual-projection design (`event_projection.py` +
`state_projection.py`) — see Migration Plan §3.

## Context

ADR-015 declared the World State constitution. Program J milestone J.1
(Event Kernel) shipped it: hash-chained events, pure replay, structural
validation, and a 100k-event replay-determinism gate.

J.2 builds the layer above the Event Kernel — the World State Engine. It must
make one invariant literally impossible to violate:

> A World State can only be created or changed by applying validated
> `WorldEvent`s through the canonical projection path.

Two architectural hazards currently exist in the codebase:

1. **Two projection paths.** `event_projection.py` (typed `WorldEvent` →
   `StateTransition`) and `state_projection.py` (string-keyed event-type →
   `StateTransition`) implement the same semantics twice, with subtly
   different code. The event store uses one; the World State Engine uses the
   other. That is a fork — replay and live projection can drift.
2. **Loose value typing.** `StateVariable.value` is `float | int | str`, so
   arithmetic in projections is untyped (`mypy` currently emits ~12 "Unsupported
   operand types for + (-, /, *)" errors in `state_projection.py`).

This ADR freezes the resolution to both before the broader J.2 build.

## Decision

### 1. Single canonical projection path

Exactly one module projects `WorldEvent` → `StateTransition` → `WorldState`:

```
WorldEvent
     │
     ▼
Event Validation        (app.modules.events.event_validation)
     │
     ▼
Event Projection        (app.modules.world.state_projection)   ← SINGLE PATH
     │
     ▼
State Transition
     │
     ▼
World State             (apply_transition — pure)
     │
     ├─→ Snapshot      (derived; optimization only)
     ├─→ Diff          (derived)
     └─→ History       (derived; replay-based)
```

- An explicit `EVENT_PROJECTORS: dict[type[WorldEvent], Callable]` registry
  maps every `WorldEvent` subclass to exactly one projector. Dispatch is a
  single dict lookup — no `if/elif` chain.
- `event_projection.py` is deprecated and re-exports the canonical symbols
  (so existing callers keep working) but **does not implement logic**.
  After one release it is removed.

### 2. Version semantics — event sequence is canonical

The canonical ordering of state is the event sequence (`world_state_events`
ordered by `occurred_at, event_id`). Version numbers are *derived*:

```
workspace
   ↓ (source)
event sequence N        ← canonical ordering
   ↓ (project)
world version = N        ← derived; one per event applied
   ↓ (checkpoint)
snapshot                ← optimization; rebuildable from events
```

Consequences:

- There is **no independent version counter** in any module. The world's
  current version = (events applied so far) for that `world_id`, starting at
  version 0 (genesis, empty) and incrementing by 1 per successfully applied
  event.
- The `world_versions` table is **removed** in migration 009. Version lineage
  is reconstructable from `world_state_events` ordering + a snapshot at the
  tip. Provenance/parent linkage moves to `world_metadata.parent_world_id`.
- Snapshots are optimization artifacts only. `get_state_at_version(v)` is
  replay-from-events (optionally seeded from the nearest snapshot ≤ v), never
  a read of "the version row."

### 3. Typed state values

Replace `float | int | str` core values with typed per-domain wrappers.
Forge-time numeric inference happens once per domain, not at projection time.

```
WorldState
 ├── inventory:    InventoryState[{warehouse,component} -> qty:int]
 ├── capacity:     CapacityState[{factory} -> pct:float[0..100]]
 ├── demand:       DemandState[{component} -> qty:int]
 ├── supplier:      SupplierState[{supplier} -> {lead_time, health, ...}]
 ├── logistics:     LogisticsState[{warehouse|route} -> {util, delay, ...}]
 └── financial:    FinancialState[{component} -> {revenue, margin, ...}]
```

Every value carries provenance and freshness as separate fields, never mixed
into the value:

```
StateValue
 ├── value          (the actual numeric/string quantity)
 ├── observed_at    (when the source event occurred)
 ├── effective_at   (when the value takes effect — may be future)
 ├── expires_at     (for forecasts; None for facts)
 ├── source_event_id
 ├── source_system
 └── confidence     (0..1 separate from value; never "value ± confidence")
```

This makes simulation and ML feature extraction safe: Programs L/M never
have to disambiguate "is this number a fact or a forecast?".

### 4. Repository write path

`StateRepository` exposes only:

```
get_current(workspace_id) -> WorldState | None
get_snapshot(snapshot_id) -> WorldSnapshot | None
get_history(workspace_id, since?, until?) -> list[WorldSnapshot]
save_snapshot(snapshot) -> WorldSnapshot              # append-only
```

There is **no** `update_*`, `set_*`, or `delete_*` method. State mutation
happens exclusively through:

```
POST /world/events
   → validate WorldEvent
   → EventStore.append
   → project to transition
   → apply_transition to current WorldState
   → StateRepository.save_snapshot  (derived checkpoint)
```

### 5. Two-layer validation

- **Structural** (already in `event_validation`): identity fields present,
  payload-shape per event_type, metadata key whitelist.
- **Domain** (in `world_validation`): post-projection invariants on the
  resulting World State — `inventory >= 0`, `capacity in [0, 100]`,
  `lead_time >= 0`, etc. Domain validation returns a `ValidationReport`
  with `passed`, `errors`, `warnings`. It never silently repairs invalid
  state — repair is a separate, explicit operation that itself is event-sourced.

### 6. Diff carries provenance

`StateDiff` entries carry `entity`, `field`, `old_value`, `new_value`,
`event_id`, `from_version`, `to_version`, `effective_at`. That gives
simulation-time explainability ("which event moved warehouse W2's inventory
from 1200 to 700?") without re-deriving it from the event log.

### 7. Performance budgets are measured, not guessed

ADR-015 §6.3 listed arbitrary perf targets (`Replay <500 ms`). J.2 measures
first:

```
1k · 10k · 100k · 1M events
→ replay latency · snapshot generation · memory · serialization
```

Realistic SLOs are written as a follow-up to those benchmarks, not frozen
here.

## Consequences

**Positive**:

- The two-path bug class is eliminated by construction.
- Version semantics are unambiguous (event sequence = version).
- Typed values eliminate the arithmetic-typing `mypy` errors and give
  simulation/ML a safe surface.
- The architecture diagram's `world_versions` box is removed because it
  duplicated the event log's ordering — fewer tables, one source of truth.
- Agents arriving in Program M physically cannot bypass the event model:
  there is no `update_inventory` to call.

**Negative**:

- Existing callers of `event_projection.project_*` need migration update.
  Mitigated via re-exports in `event_projection.py` (one release of soft
  deprecation) before hard removal.
- Typed state values mean a one-time refactor of `StateVariable` consumers.
  Most consumers already coerce via `int()`/`float()`; the typed wrapper
  preserves numeric access via `__int__`/`__float__` proxies over a release.
- Removing `world_versions` from the live schema requires a migration that
  copies any persisted parent-linkage to `world_metadata` first. Scheduled
  in J.2.10.

## Migration Plan

### 1. ADR & DECISIONS entry (this document)

- Add this ADR: `docs/architecture/ADR/0016-world-state-engine-projection-frozen.md`.
- Append a row to `DECISIONS.md`.

### 2. Projection consolidation (J.2.1, J.2.2)

- Move all `project_*` projector functions from `event_projection.py` to
  `state_projection.py` keyed by `type[WorldEvent]` in `EVENT_PROJECTORS`.
- Add `apply_event(state, event) -> WorldState` (validate → project → apply).
- `event_projection.py` becomes a thin re-export layer with a `DeprecationWarning`.
- All callers updated to import from `state_projection`; the `event_replay.py`
  bridge updated accordingly.

### 3. Type-safe values (J.2.3, J.2.4)

- Define `StateValue` (with provenance + freshness split from value) and
  per-domain wrapper dataclasses in `world_models.py`.
- Update `StateVariable.value` to the typed value.
- The 42 pre-existing `mypy` errors in the world module resolve naturally.

### 4. Repository & version semantics (J.2.5, J.2.6)

- Trim `StateRepository` to read/snapshot-only. Remove `update_*`/`create`
  methods that mutate (retain `create` for genesis, not for mutations).
- Document version = event count.

### 5. History, Diff, Validation (J.2.7, J.2.8, J.2.9)

- Rebuild `state_history` on top of `event_replay` (replay_to_version etc.).
- Enrich `StateDiff` with provenance fields.
- Promote `WorldValidator.validate` to return `ValidationReport` with no
  silent repair.

### 6. Migration 009 (J.2.10)

- New schema for typed state values (one row per `StateValue` lane or a
  JSONB column keyed by domain — chosen after the contract is frozen).
- Drop `world_versions` after copying parent linkage to `world_metadata`.

### 7. APIs (J.2.11)

- `GET  /api/v1/world/state`
- `GET  /api/v1/world/state/history`
- `GET  /api/v1/world/state/{version}`
- `GET  /api/v1/world/state/diff`
- `POST /api/v1/world/events`  ← the single write path

### 8. Tests & CI (J.2.13, J.2.14, J.2.15)

- Unit: projection (all 11 event types), state construction/serialization/
  equality/hashing, history/time travel, diff, validation.
- Integration: Event→State, Replay≡Live, Snapshot≡Replay, Partition invariance.
- Security: workspace isolation, event tamper, replay tamper, unauthorized event.
- Stress: extend the J.1 100k gate to "live projection ≡ replay" + partition.

## References

- ADR-015 — World State constitution (invariants bind this ADR)
- ADR-008 — Feature flags gating (`FEATURE_WORLD_STATE`)
- ADR-007 — Deferred-capability boundary (precedent for deprecation)
- `app/modules/world/`, `app/modules/events/` — current implementation
