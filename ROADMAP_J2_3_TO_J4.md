# Program J Roadmap: J.2.3 → J.3 → J.4

**Date:** 2026-08-18
**Status:** Planning → Execution
**Frozen:** Yes (J.2.2 complete, no reopening of typed StateValue work)

---

## Executive Summary

J.2 (typed StateValue) is **frozen and complete**. The next three phases establish a trustworthy, deterministic World State and Digital Twin substrate before any GNN/RL/agent work:

```
J.2.3  Repository / Write Boundary      (THIS PHASE)
  ↓
J.3    Digital Twin
  ↓
J.4    Simulation Quality & Evaluation
  ↓
K      GNN Intelligence
```

The non-negotiable principle: **there is exactly one authoritative path by which an event becomes World State, and every other subsystem consumes that state rather than recreating it.**

---

## Phase J.2.3 — Repository & Write-Path Hardening

### Goal

Make the repository a persistence boundary, not a second state engine. Freeze the canonical write path:

```
WorldEvent
   ↓
Structural Validation
   ↓
Domain Validation
   ↓
Canonical Projection
   ↓
WorldState
   ↓
Snapshot / Persistence
```

### 1. Canonical Write Path Contract

**Freeze this signature:**

```python
class WorldStateService:
    async def append_event(
        self,
        workspace_id: str,
        world_id: str,
        event: WorldEvent,
        idempotency_key: str,
    ) -> SubmitEventResult:
        """
        Sole application-level write.
        
        Guarantees:
        - Structural validation (schema)
        - Domain validation (semantics)
        - Canonical projection (deterministic)
        - Atomic persistence (all-or-nothing)
        - Idempotent (same key ⇒ same result)
        - Monotonic versioning (workspace_id + sequence_number)
        
        Returns: version_id, version, state, is_snapshot, snapshot (optional)
        """
```

**No other writes permitted from:**
- Twin
- Scenario engine
- GNN
- RL agent
- External adapters

### 2. Remove Forbidden Mutation Paths

Audit `StateRepository` and confirm it exposes **only**:

```python
async def get_current(workspace_id: str, world_id: str) -> WorldState | None
async def get_snapshot(snapshot_id: str) -> WorldSnapshot | None
async def get_history(world_id: str, from_version: int = 1, to_version: int | None = None) -> list[VersionRecord]
async def save_snapshot(snapshot: WorldSnapshot) -> None
async def append_event(event: WorldStateEventDB) -> None
async def append_version(version: WorldVersionDB) -> None
```

**No hidden:**
```python
update_state()
archive_snapshot()
mutate_version()
mutate_event()
delete_event()
hard_reset()
```

### 3. WorldStateService Orchestration

Verify single orchestration boundary:

```python
class WorldStateService:
    async def append_event()          # SOLE WRITE
    async def validate_event()        # Structural + domain
    async def project_event()         # Deterministic state transition
    async def persist_version()       # Version lineage
    async def snapshot()              # Checkpoint creation
    async def replay()                # Deterministic reconstruction
    async def get_state()             # Read current
    async def get_snapshot()          # Read checkpoint
```

### 4. Concurrency & Sequencing

Enforce:

```sql
CREATE UNIQUE INDEX uq_world_sequence
  ON world_versions (world_id, workspace_id, sequence_number);
```

Test invariant:

```python
async def test_concurrent_appends():
    # Worker A submits event N
    # Worker B submits event N+1
    # both to same world/workspace
    
    result_a = await service.append_event(event_n, key_a)
    result_b = await service.append_event(event_n1, key_b)
    
    # Verify:
    # result_a.version == N
    # result_b.version == N+1
    # no race, no duplicate sequence
```

### 5. Idempotency

Enforce:

```sql
CREATE UNIQUE INDEX uq_world_event_idempotency
  ON world_state_events (world_id, workspace_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

Test invariant:

```python
async def test_idempotent_resubmit():
    event = make_event()
    key = "test-idempotent-123"
    
    result1 = await service.append_event(event, key)
    result2 = await service.append_event(event, key)
    
    # Verify:
    # result1.version == result2.version
    # result1.event_id == result2.event_id
    # state after both calls is identical
    # no duplicate state version created
```

### 6. Workspace Isolation

Test invariant:

```python
async def test_workspace_isolation():
    # Create state in workspace A
    state_a = await service.initialize_world("workspace-a", "world-1")
    
    # Workspace B event CANNOT mutate workspace A state
    event_b = WorldEvent(...)
    await service.append_event("workspace-b", "world-1", event_b, "key-b")
    
    # Verify:
    # Workspace A state unchanged
    # Workspace B has its own world-1 (separate entity)
    # no cross-workspace contamination
```

### 7. Contract Tests

Create `tests/modules/world/test_repository_contract.py`:

| Test | Invariant |
|------|-----------|
| `test_repository_append_only` | Events never updated/deleted |
| `test_repository_versioning` | Versions are sequential, immutable |
| `test_repository_snapshots_sealed` | Snapshots created, never mutated |
| `test_repository_lineage` | Parent/child chains form DAG |
| `test_repository_isolation` | Workspace A ≠ Workspace B |
| `test_get_methods_no_side_effects` | Reads never mutate |
| `test_forbidden_methods_removed` | No `update_state`, `delete_event`, etc. |

### 8. Concurrency Tests

Create `tests/modules/world/test_concurrency.py`:

| Test | Invariant |
|------|-----------|
| `test_concurrent_append_serialization` | Dual worker writes are ordered |
| `test_concurrent_duplicate_sequence_rejected` | No duplicate sequence number |
| `test_concurrent_snapshot_atomicity` | Snapshot read/write is atomic |
| `test_high_contention_ordering` | 10 workers, 100 events each → perfect order |

### 9. Idempotency Tests

Create `tests/modules/world/test_idempotency.py`:

| Test | Invariant |
|------|-----------|
| `test_resubmit_same_key_same_result` | Identical output, no dup state |
| `test_different_key_same_event_creates_new_version` | Different keys ⇒ separate versions |
| `test_idempotent_network_retry` | Simulate network duplicate |
| `test_idempotency_across_replicas` | Distributed consensus |

### 10. Replay & Snapshot Consistency

Create `tests/modules/world/test_replay_consistency.py`:

| Test | Invariant |
|------|-----------|
| `test_replay_live_events_matches_live_state` | `replay(all_events) == get_current()` |
| `test_snapshot_replay_equivalence` | `replay(snapshot_version) == snapshot` |
| `test_deterministic_projection` | Same input ⇒ same state |
| `test_replay_idempotent` | Multiple replays ⇒ identical hash |

### J.2.3 Exit Gate

All must pass:

```python
assert replay(live_events) == live_state
assert snapshot == replay(snapshot_version)
assert concurrent_submissions_serialized
assert duplicate_events_idempotent
assert tenant_isolation_enforced
assert ruff passes  # no linting errors
assert mypy passes  # no type errors
assert full_regression passes  # 452+ tests
```

---

## Phase J.3 — Digital Twin

Once J.2.3 is green, implement the counterfactual substrate.

### J.3.1 — Twin Lifecycle

```python
class DigitalTwinService:
    async def create(workspace_id, parent_world_id, parent_version) -> Twin
    async def clone(twin_id) -> Twin
    async def fork(twin_id) -> Twin
    async def run(twin_id, scenario, seed) -> SimulationResult
    async def get(twin_id) -> Twin
    async def list(workspace_id) -> list[Twin]
    async def archive(twin_id) -> None
    async def destroy(twin_id) -> None
```

Every twin carries provenance:

```python
@dataclass
class Twin:
    twin_id: str
    workspace_id: str
    parent_world_id: str
    parent_version: int
    snapshot_id: str  # immutable base
    created_at: datetime
    created_by: str
    status: TwinStatus  # draft, running, complete, archived
```

### J.3.2 — Isolation Invariant

```python
async def test_twin_production_isolation():
    # Create twin from production snapshot
    twin = await twin_service.create("ws-1", "world-prod", 42)
    
    # Run scenario in twin
    result = await twin_service.run(twin.id, "supplier_failure", seed=1)
    
    # Verify:
    # Production world_states: unchanged
    # Production world_state_events: unchanged
    # Production world_snapshots: unchanged
    # Twin has its own isolated copies
```

### J.3.3 — Scenario Execution

Support deterministic scenarios:

| Scenario | Implementation |
|----------|-----------------|
| `supplier_failure` | Set supplier lifecycle to `suspended` |
| `supplier_delay` | Add N days to all lead times |
| `inventory_shortage` | Reduce on_hand by X% |
| `demand_spike` | Multiply demand by N |
| `route_disruption` | Set route risk_index to 1.0 |

### J.3.4 — KPI Computation

Return decision-grade metrics:

```python
@dataclass
class KPIComputation:
    # Inventory
    total_inventory: float
    safety_stock_coverage: float
    
    # Demand
    fulfilled_demand: float
    backorder_qty: float
    
    # Capacity
    utilization: float
    available_capacity: float
    
    # Lead time
    average_lead_time: float
    lead_time_variance: float
    
    # Stockout
    stockout_probability: float
    avg_stockout_duration: float
    
    # SLA
    on_time_delivery_rate: float
    
    # Revenue exposure
    at_risk_revenue: float
    
    # Margin exposure
    margin_exposure: float
    
    # Recovery time
    recovery_time_hours: float
```

### J.3.5 — Twin Comparison

```python
@dataclass
class TwinComparison:
    baseline_twin_id: str
    scenario_twin_id: str
    
    # Deltas
    delta_revenue: float
    delta_inventory: float
    delta_sla: float
    delta_downtime: float
    delta_cost: float
    delta_recovery: float
    
    # Metadata
    computed_at: datetime
    scenario: str
    summary: str
```

### J.3 Exit Gate

```python
assert same_snapshot + same_scenario + same_seed -> identical_result
assert production_state_unchanged_after_twin_run
assert forked_twins_remain_isolated
assert scenario_results_reproducible
```

---

## Phase J.4 — Simulation Quality & Evaluation

Before GNN/RL/agent work, establish that simulation is trustworthy.

### J.4.1 — Scenario Correctness

Create analytical ground truth for:

| Scenario | Ground Truth |
|----------|--------------|
| Supplier failure | Inventory depletes by day N, SLA missed on day N+1 |
| Supplier delay | Lead time increases, safety stock depletes by X% |
| Inventory shortage | On-hand = 0 by day N, backorder = Y units |
| Demand spike | Inventory depleted in 80% less time, SLA at risk |

### J.4.2 — Reproducibility

```python
async def test_reproducibility():
    snapshot = await repo.get_snapshot("snap-1")
    scenario = "supplier_failure"
    seed = 42
    
    result1 = await twin_service.run(scenario, snapshot, seed)
    result2 = await twin_service.run(scenario, snapshot, seed)
    
    # Verify:
    # result1.hash == result2.hash
    # identical KPIs
    # identical events
```

### J.4.3 — Partition Invariance

```python
async def test_partition_invariance():
    events_1k = make_events(1000)
    events_10k = make_events(10000)
    events_100k = make_events(100000)
    
    # Single batch
    state_1k_single = await service.replay(events_1k)
    state_10k_single = await service.replay(events_10k)
    state_100k_single = await service.replay(events_100k)
    
    # Many batches
    state_1k_batched = await service.replay_batched(events_1k, batch_size=100)
    state_10k_batched = await service.replay_batched(events_10k, batch_size=100)
    state_100k_batched = await service.replay_batched(events_100k, batch_size=100)
    
    # Verify:
    # state_*_single.hash == state_*_batched.hash (for all scales)
```

### J.4.4 — Evaluation Bridge

```python
@dataclass
class EvaluationResult:
    # Reference
    snapshot_id: str
    scenario: str
    seed: int
    
    # Inputs
    kpi_baseline: KPIComputation
    kpi_scenario: KPIComputation
    
    # Analysis
    metrics: dict[str, float]
    deltas: dict[str, float]
    
    # Reproducibility
    content_hash: str
    execution_time_ms: int
```

This becomes the foundation for:

```
GNN model training
    ↓ uses
Evaluation Harness
    ↓ produces
EvaluationResult
    ↓ feedback loop
Policy refinement
```

### J.4 Exit Gate

```python
assert scenario_ground_truth_correct
assert reproducibility_pass
assert partition_invariance_pass(scales: [1k, 10k, 100k, 1M])
assert evaluation_bridge_wired
```

---

## What NOT to Do Yet

**Explicitly defer:**

- GNN model training
- RL policy training
- Autonomous execution
- LLM orchestration
- External ERP adapters
- Graph database migration
- Kubernetes
- Microservices

All depend on trustworthy, deterministic World State and Twin substrate.

---

## Execution Order (Sequential Gates)

```
J.2.2  Typed StateValue                ✅ (FROZEN)
  ↓
J.2.3  Repository / Write Boundary    ← START HERE
  ├─ Remove forbidden mutations
  ├─ WorldStateService orchestration
  ├─ Concurrency (sequence_number)
  ├─ Idempotency (idempotency_key)
  ├─ Workspace isolation
  ├─ Contract tests
  ├─ Replay consistency
  └─ EXIT GATE ✓
  ↓
J.3.1  Twin Lifecycle                 (NEXT)
  ↓
J.3.2  Isolation
  ↓
J.3.3  Scenario Runtime
  ↓
J.3.4  KPI / Delta
  ↓
J.3.5  Twin Comparison
  └─ EXIT GATE ✓
  ↓
J.4.1  Scenario Ground Truth
  ↓
J.4.2  Reproducibility
  ↓
J.4.3  Partition Invariance
  ↓
J.4.4  Simulation Evaluation Bridge
  └─ EXIT GATE ✓
  ↓
K      GNN Intelligence (SAFE TO START)
```

---

## Immediate Next Task

**Start with J.2.3 — Repository Simplification + WorldStateService**

Success condition:

> **There is exactly one authoritative path by which an event becomes World State, and every other subsystem—including future Twin, GNN, RL, and agents—consumes that state rather than re-creating it.**

See J.2.3 detailed plan above for specific tests and contract gates.
