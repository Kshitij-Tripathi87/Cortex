"""Tests for the Event Kernel — Program J Workstream B (J.1 hardening).

Covers the three pure modules extracted from event_store.py:
- event_hashing (canonicalization, hashing, chain verification)
- event_replay (pure replay loop)
- event_validation (structural validation + forward-compat metadata)

Plus the J.1 exit-criterion stress test: 100k events replay deterministically.
All tests are pure-Python — no DB, no async.
"""

from __future__ import annotations

import pytest

from app.modules.events.event_hashing import (
    HASH_HEX_LENGTH,
    canonicalize_event,
    compute_event_hash,
    stable_json,
    verify_chain,
)
from app.modules.events.event_models import (
    METADATA_KEYS,
    CapacityChanged,
    DemandChanged,
    FactoryShutdown,
    InventoryChanged,
    OrderCancelled,
    OrderPlaced,
    PriceChanged,
    RouteDisruption,
    ShipmentDelayed,
    SupplierDelayed,
    SupplierHealthChanged,
)
from app.modules.events.event_replay import (
    ReplayRecord,
    replay_batches,
    replay_events,
    replay_timed,
)
from app.modules.events.event_validation import (
    EventValidationError,
    ValidationSeverity,
    check_event,
    has_errors,
    is_valid_event,
    validate_event,
)
from app.modules.world.state_projection import (
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
)

# ─────────────────────────────────────────────────────────────────────────────
# event_hashing: stable_json
# ─────────────────────────────────────────────────────────────────────────────


def test_stable_json_sorts_dict_keys():
    assert stable_json({"b": 1, "a": 2}) == {"a": 2, "b": 1}


def test_stable_json_recursive():
    payload = {"x": {"c": 3, "b": {"d": 4, "a": 5}}, "a": [{"y": 2, "x": 1}]}
    result = stable_json(payload)
    assert list(result.keys()) == ["a", "x"]
    assert list(result["x"].keys()) == ["b", "c"]
    assert list(result["x"]["b"].keys()) == ["a", "d"]
    assert list(result["a"][0].keys()) == ["x", "y"]


def test_stable_json_preserves_list_order():
    assert stable_json([3, 1, 2]) == [3, 1, 2]


def test_stable_json_passes_primitives():
    assert stable_json(42) == 42
    assert stable_json("x") == "x"
    assert stable_json(None) is None
    assert stable_json(1.5) == 1.5


# ─────────────────────────────────────────────────────────────────────────────
# event_hashing: canonicalization + compute_event_hash
# ─────────────────────────────────────────────────────────────────────────────


def _make_inventory_event(**overrides):
    base = dict(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=10,
        reason="production",
    )
    base.update(overrides)
    return InventoryChanged(**base)


def test_canonicalize_event_excludes_metadata_and_occurred_at():
    e = _make_inventory_event()
    canonical = canonicalize_event(e, e.to_payload())
    assert "occurred_at" not in canonical
    assert "metadata" not in canonical


def test_canonicalize_event_is_key_order_invariant():
    e = _make_inventory_event()
    p = e.to_payload()
    a = canonicalize_event(e, p)
    # Build the same payload with keys in reverse order — should match
    reversed_payload = dict(reversed(list(p.items())))
    b = canonicalize_event(e, reversed_payload)
    assert a == b


def test_compute_event_hash_returns_64_hex_chars():
    e = _make_inventory_event()
    h = compute_event_hash(e, e.to_payload())
    assert len(h) == HASH_HEX_LENGTH == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_event_hash_is_deterministic():
    e1 = _make_inventory_event()
    e2 = _make_inventory_event()
    assert compute_event_hash(e1, e1.to_payload()) == compute_event_hash(e2, e2.to_payload())


def test_event_hash_changes_with_payload():
    e = _make_inventory_event()
    h1 = compute_event_hash(e, e.to_payload())
    e2 = _make_inventory_event(quantity_change=11)
    h2 = compute_event_hash(e2, e2.to_payload())
    assert h1 != h2


def test_event_hash_ignores_metadata_changes():
    """Forward-compat metadata (policy_version, experiment_id) must not affect the hash."""
    e1 = _make_inventory_event()
    # Replace frozen field — but events are frozen, so we construct fresh
    e_with_meta = InventoryChanged(
        event_id=e1.event_id, world_id=e1.world_id, workspace_id=e1.workspace_id,
        entity_type=e1.entity_type, entity_id=e1.entity_id,
        warehouse_id=e1.warehouse_id, component_id=e1.component_id,
        quantity_change=e1.quantity_change, reason=e1.reason,
        metadata={"policy_version": "v1"},
    )
    e_with_meta2 = InventoryChanged(
        event_id=e1.event_id, world_id=e1.world_id, workspace_id=e1.workspace_id,
        entity_type=e1.entity_type, entity_id=e1.entity_id,
        warehouse_id=e1.warehouse_id, component_id=e1.component_id,
        quantity_change=e1.quantity_change, reason=e1.reason,
        metadata={"policy_version": "v2", "experiment_id": "exp_99"},
    )
    h1 = compute_event_hash(e1, e1.to_payload())
    h2 = compute_event_hash(e_with_meta, e_with_meta.to_payload())
    h3 = compute_event_hash(e_with_meta2, e_with_meta2.to_payload())
    assert h1 == h2 == h3


# ─────────────────────────────────────────────────────────────────────────────
# event_hashing: verify_chain
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_chain_empty_is_valid():
    result = verify_chain([])
    assert result.is_valid is True
    assert result.verified_records == 0
    assert result.errors == ()


def test_verify_chain_happy_path():
    triples = [
        ("h1", None, 1),
        ("h2", "h1", 2),
        ("h3", "h2", 3),
    ]
    result = verify_chain(triples)
    assert result.is_valid is True
    assert result.verified_records == 3


def test_verify_chain_detects_chain_break():
    triples = [
        ("h1", None, 1),
        ("h2", "WRONG", 2),
    ]
    result = verify_chain(triples)
    assert result.is_valid is False
    assert result.first_error is not None
    assert result.first_error.error_code == "chain_break"


def test_verify_chain_detects_sequence_gap():
    triples = [
        ("h1", None, 1),
        ("h2", "h1", 3),  # gap: expected 2
    ]
    result = verify_chain(triples)
    assert result.is_valid is False
    assert result.first_error is not None
    assert result.first_error.error_code == "sequence_gap"


def test_verify_chain_rejects_non_monotonic():
    triples = [
        ("h1", None, 1),
        ("h2", "h1", 2),
        ("h3", "h2", 1),  # repeats
    ]
    result = verify_chain(triples)
    assert result.is_valid is False
    assert result.first_error.error_code == "sequence_gap"


# ─────────────────────────────────────────────────────────────────────────────
# event_replay: pure replay loop
# ─────────────────────────────────────────────────────────────────────────────


def _initial_state_with_inventory(value: int = 100):
    return create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=value,
                unit="units",
            ),
        },
    )


def _inv_record(event_id: str, warehouse_id: str, component_id: str, qty: int) -> ReplayRecord:
    return ReplayRecord(
        event_id=event_id,
        world_id="world_1",
        workspace_id="ws_1",
        entity_id=warehouse_id,
        entity_type="warehouse",
        event_type="inventory_changed",
        payload={"warehouse_id": warehouse_id, "component_id": component_id, "quantity_change": qty, "reason": "production"},
    )


def test_replay_events_applies_all_records():
    state = _initial_state_with_inventory(value=100)
    records = [
        _inv_record("e1", "wh_001", "comp_042", 50),
        _inv_record("e2", "wh_001", "comp_042", -20),
    ]
    outcome = replay_events(state, records)
    assert outcome.events_seen == 2
    assert outcome.transitions_applied == 2
    assert outcome.warnings == ()
    final_value = outcome.world_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value
    assert final_value == 130


def test_replay_events_records_unrecognized_event_type_as_warning():
    state = _initial_state_with_inventory()
    records = [
        ReplayRecord(
            event_id="e1", world_id="world_1", workspace_id="ws_1",
            entity_id="wh_001", entity_type="warehouse",
            event_type="mystery_event", payload={},
        ),
    ]
    outcome = replay_events(state, records)
    assert outcome.events_seen == 1
    assert outcome.transitions_applied == 0
    assert len(outcome.warnings) == 1
    assert "unrecognized_event_type" in outcome.warnings[0]


def test_replay_events_is_pure_no_side_effects():
    state = _initial_state_with_inventory(value=100)
    records = [_inv_record("e1", "wh_001", "comp_042", 10)]
    state_a = replay_events(state, records).world_state
    state_b = replay_events(state, records).world_state
    # Original input state unchanged
    assert state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 100
    # Both replay results equal
    assert create_state_snapshot(state_a).state_hash == create_state_snapshot(state_b).state_hash


def test_replay_batches_invokes_progress_callback():
    state = _initial_state_with_inventory(value=0)
    batch1 = [_inv_record(f"e{i}", "wh_001", "comp_042", 1) for i in range(5)]
    batch2 = [_inv_record(f"e{i}", "wh_001", "comp_042", 1) for i in range(5, 10)]
    progress: list[tuple[int, int]] = []
    outcome = replay_batches(state, [batch1, batch2], on_progress=lambda s, a: progress.append((s, a)))
    assert outcome.events_seen == 10
    assert outcome.transitions_applied == 10
    assert progress == [(5, 5), (10, 10)]


def test_replay_timed_returns_outcome_and_elapsed_ms():
    state = _initial_state_with_inventory(value=0)
    records = [_inv_record(f"e{i}", "wh_001", "comp_042", 1) for i in range(100)]
    outcome, elapsed = replay_timed(state, records)
    assert outcome.events_seen == 100
    assert outcome.transitions_applied == 100
    assert elapsed >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# event_validation: structural validation
# ─────────────────────────────────────────────────────────────────────────────


def test_metadata_keys_constant_has_required_names():
    assert "experiment_id" in METADATA_KEYS
    assert "policy_version" in METADATA_KEYS
    assert "decision_source" in METADATA_KEYS
    assert "shadow_model_version" in METADATA_KEYS
    assert "feature_vector_hash" in METADATA_KEYS
    assert "training_tags" in METADATA_KEYS


def test_valid_inventory_event_passes():
    e = _make_inventory_event()
    assert is_valid_event(e) is True
    validate_event(e)  # does not raise


def test_event_missing_world_id_fails():
    e = _make_inventory_event(world_id="")
    issues = check_event(e)
    assert has_errors(issues) is True
    assert any(i.rule == "missing_world_id" for i in issues)


def test_event_missing_required_payload_field_fails():
    e = InventoryChanged(
        event_id="evt_1", world_id="w", workspace_id="ws",
        entity_type="warehouse", entity_id="wh_001",
        warehouse_id="wh_001", component_id="comp_042",
        quantity_change=10,
    )
    # Manually delete the payload field (bypasses __post_init__)
    bad_payload = {"warehouse_id": "wh_001"}  # missing component_id, quantity_change
    issues = check_event(e, bad_payload)
    error_rules = {i.rule for i in issues if i.severity == ValidationSeverity.ERROR}
    assert "missing_payload_field" in error_rules


def test_event_with_invalid_capacity_raises_warning():
    e = CapacityChanged(
        event_id="evt_1", world_id="w", workspace_id="ws",
        entity_type="factory", entity_id="f1",
        capacity_pct=150.0,
    )
    issues = check_event(e)
    assert any(i.rule == "field_above_maximum" for i in issues)


def test_event_with_negative_lead_time_warning():
    e = SupplierDelayed(
        event_id="evt_1", world_id="w", workspace_id="ws",
        entity_type="supplier", entity_id="sup_1",
        delay_days=-5,
    )
    issues = check_event(e)
    assert any(i.rule == "field_below_minimum" for i in issues)


def test_unknown_metadata_key_warns_but_does_not_error():
    e = _make_inventory_event()
    # Override metadata via fresh construction with metadata dict
    e_with_meta = InventoryChanged(
        event_id=e.event_id, world_id=e.world_id, workspace_id=e.workspace_id,
        entity_type=e.entity_type, entity_id=e.entity_id,
        warehouse_id=e.warehouse_id, component_id=e.component_id,
        quantity_change=e.quantity_change, reason=e.reason,
        metadata={"unknown_key": "x"},
    )
    issues = check_event(e_with_meta)
    assert any(i.rule == "unknown_metadata_key" for i in issues)
    # No errors — only warnings
    assert has_errors(issues) is False


def test_metadata_with_forward_compat_key_is_clean():
    """experiment_id, policy_version, etc. should not produce warnings."""
    e = _make_inventory_event()
    e_with_meta = InventoryChanged(
        event_id=e.event_id, world_id=e.world_id, workspace_id=e.workspace_id,
        entity_type=e.entity_type, entity_id=e.entity_id,
        warehouse_id=e.warehouse_id, component_id=e.component_id,
        quantity_change=e.quantity_change, reason=e.reason,
        metadata={"experiment_id": "exp_42", "policy_version": "v3"},
    )
    issues = check_event(e_with_meta)
    assert not any(i.rule == "unknown_metadata_key" for i in issues)


def test_validate_event_raises_on_hard_error():
    e = _make_inventory_event(world_id="")
    with pytest.raises(EventValidationError) as exc_info:
        validate_event(e)
    assert exc_info.value.issues
    assert any(i.severity == ValidationSeverity.ERROR for i in exc_info.value.issues)


def test_all_worldevent_subtypes_have_validation_schemas():
    """Every typed WorldEvent must have a payload schema (or be the base)."""
    from app.modules.events.event_validation import _PAYLOAD_SCHEMAS
    subtypes = [
        InventoryChanged, SupplierDelayed, SupplierHealthChanged,
        OrderPlaced, OrderCancelled, CapacityChanged, FactoryShutdown,
        RouteDisruption, ShipmentDelayed, DemandChanged, PriceChanged,
    ]
    for cls in subtypes:
        assert cls in _PAYLOAD_SCHEMAS, f"Missing validation schema for {cls.__name__}"


# ─────────────────────────────────────────────────────────────────────────────
# J.1 EXIT CRITERION: 100k-event replay determinism (no DB, pure Python)
# ─────────────────────────────────────────────────────────────────────────────


N_STRESS = 100_000


def _build_stress_records(n: int) -> list[ReplayRecord]:
    """Build `n` deterministic inventory events.

    Cycles through 4 warehouses × 5 components = 20 distinct (warehouse,
    component) pairs, alternating positive/negative quantity changes so
    we exercise both directions of the projection.
    """
    records: list[ReplayRecord] = []
    warehouses = [f"wh_{i:03d}" for i in range(4)]
    components = [f"comp_{i:03d}" for i in range(5)]
    for i in range(n):
        wh = warehouses[i % len(warehouses)]
        comp = components[i % len(components)]
        qty = 1 if i % 2 == 0 else -1
        records.append(
            ReplayRecord(
                event_id=f"evt_{i:06d}",
                world_id="world_1",
                workspace_id="ws_1",
                entity_id=wh,
                entity_type="warehouse",
                event_type="inventory_changed",
                payload={
                    "warehouse_id": wh,
                    "component_id": comp,
                    "quantity_change": qty,
                    "reason": "production" if qty > 0 else "consumption",
                },
            )
        )
    return records


@pytest.mark.stress
@pytest.mark.parametrize("n", [100_000])
def test_j1_exit_criterion_replay_100k_events_is_deterministic(n: int):
    """J.1 exit criterion (ADR-015 §3): replaying 100k events reconstructs
    identical state every run.

    Builds the same event stream twice and asserts the resulting state hash
    is byte-for-byte identical. Pure-Python, no DB.
    """
    initial = _initial_state_with_inventory(value=0)
    records = _build_stress_records(n)

    outcome_a, _ = replay_timed(initial, records)
    outcome_b, _ = replay_timed(initial, records)

    hash_a = create_state_snapshot(outcome_a.world_state).state_hash
    hash_b = create_state_snapshot(outcome_b.world_state).state_hash

    assert outcome_a.events_seen == n
    assert outcome_a.transitions_applied == n
    assert hash_a == hash_b

    # And the chain verification of the canonicalized record set passes
    # when fed synthetic hashes (computed inline here since we don't store them)
    triples: list[tuple[str, str | None, int]] = []
    prev: str | None = None
    for i, _r in enumerate(records, start=1):
        # Use the record's event_id as a synthetic hash — the point of this
        # assertion is determinism + chain integrity on a large sequence.
        h = f"h{i}"
        triples.append((h, prev, i))
        prev = h
    result = verify_chain(triples)
    assert result.is_valid is True
    assert result.verified_records == n


@pytest.mark.stress
def test_j1_replay_100k_batch_chunks_remain_consistent():
    """Same 100k events replayed as one batch vs 10x10k chunks produce
    the same final state hash.
    """
    initial = _initial_state_with_inventory(value=0)
    records = _build_stress_records(N_STRESS)

    one_shot = replay_events(initial, records)
    chunked = replay_batches(initial, [records[i : i + 10_000] for i in range(0, N_STRESS, 10_000)])

    h1 = create_state_snapshot(one_shot.world_state).state_hash
    h2 = create_state_snapshot(chunked.world_state).state_hash
    assert h1 == h2
    assert one_shot.transitions_applied == N_STRESS
    assert chunked.transitions_applied == N_STRESS
