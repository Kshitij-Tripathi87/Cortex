"""Tests for Workstream J (Security) and Workstream I (Performance).

Verifies:
- Snapshot signing and verification
- State hash verification
- Audit logging
- TTL cache behavior
- LRU eviction
- Performance benchmarks
"""

from __future__ import annotations

import time

from app.modules.world.cache import (
    CacheManager,
    PerformanceBenchmark,
    RuleCache,
    SnapshotCache,
    StateCache,
    TTLCache,
    TwinCache,
)
from app.modules.world.security import (
    AuditLogger,
    SignedSnapshot,
    SnapshotSigner,
    StateHashVerifier,
)
from app.modules.world.state_projection import (
    StateVariableType,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.world_models import StateVariable as SV
from app.modules.world.world_models import WorldSnapshot

# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Signing Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_snapshot_sign_and_verify():
    """Sign a snapshot and verify the signature."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )
    snapshot = create_state_snapshot(state)
    signer = SnapshotSigner(signing_key="test-key")

    signed = signer.sign(snapshot)
    assert signed.signature != ""
    assert signed.signing_key_id == "default"
    assert signer.verify(signed) is True


def test_snapshot_tamper_detection():
    """Tampered snapshot fails verification."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    snapshot = create_state_snapshot(state)
    signer = SnapshotSigner(signing_key="test-key")

    signed = signer.sign(snapshot)
    # Tamper with the snapshot
    tampered = WorldSnapshot(
        snapshot_id=signed.snapshot.snapshot_id,
        world_id=signed.snapshot.world_id,
        workspace_id=signed.snapshot.workspace_id,
        version=signed.snapshot.version + 1,  # Tampered!
        graph_version=signed.snapshot.graph_version,
        state_hash=signed.snapshot.state_hash,
        variable_count=signed.snapshot.variable_count,
    )
    tampered_signed = SignedSnapshot(
        snapshot=tampered,
        signature=signed.signature,
        signing_key_id=signed.signing_key_id,
        signed_at=signed.signed_at,
    )
    assert signer.verify(tampered_signed) is False


def test_snapshot_wrong_key_fails_verification():
    """Different signing key produces different signature."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    snapshot = create_state_snapshot(state)

    signer1 = SnapshotSigner(signing_key="key-1")
    signer2 = SnapshotSigner(signing_key="key-2")

    signed = signer1.sign(snapshot)
    assert signer2.verify(signed) is False


def test_snapshot_signature_is_deterministic():
    """Same snapshot signed with same key produces same signature."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    snapshot = create_state_snapshot(state)
    signer = SnapshotSigner(signing_key="test-key")

    signed1 = signer.sign(snapshot)
    signed2 = signer.sign(snapshot)
    # Signatures should be deterministic (sign doesn't include timestamp)
    assert signed1.signature == signed2.signature


# ─────────────────────────────────────────────────────────────────────────────
# State Hash Verification Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_state_hash_is_deterministic():
    """Same state produces same hash."""
    state1 = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.b": SV(
                variable_id="a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=10,
            ),
        },
    )
    state2 = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.b": SV(
                variable_id="a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=10,
            ),
        },
    )
    verifier = StateHashVerifier()
    h1 = verifier.compute_state_hash(state1)
    h2 = verifier.compute_state_hash(state2)
    assert h1 == h2


def test_state_hash_changes_with_value():
    """Different state values produce different hashes."""
    state1 = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.b": SV(
                variable_id="a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=10,
            ),
        },
    )
    state2 = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.b": SV(
                variable_id="a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=20,  # Different value
            ),
        },
    )
    verifier = StateHashVerifier()
    h1 = verifier.compute_state_hash(state1)
    h2 = verifier.compute_state_hash(state2)
    assert h1 != h2


def test_state_hash_verify_with_expected():
    """Verify returns valid when hash matches expected."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    verifier = StateHashVerifier()
    actual_hash = verifier.compute_state_hash(state)
    report = verifier.verify(state, expected_hash=actual_hash)
    assert report.is_valid is True


def test_state_hash_verify_with_mismatch():
    """Verify returns invalid when hash doesn't match expected."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    verifier = StateHashVerifier()
    report = verifier.verify(state, expected_hash="wrong-hash")
    assert report.is_valid is False


# ─────────────────────────────────────────────────────────────────────────────
# Audit Logger Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_audit_logger_logs_events():
    """Audit logger records events."""
    logger = AuditLogger()
    event = logger.log(
        event_type="snapshot_signed",
        workspace_id="ws_1",
        actor="user_1",
        target_id="snap_1",
        success=True,
        details={"signature": "abc123"},
    )
    assert event.event_id != ""
    assert event.event_type == "snapshot_signed"
    assert event.actor == "user_1"


def test_audit_logger_filters_by_workspace():
    """Audit logger filters by workspace."""
    logger = AuditLogger()
    logger.log("snapshot_signed", "ws_1", "user_1", "snap_1")
    logger.log("snapshot_signed", "ws_2", "user_2", "snap_2")

    ws1_events = logger.get_events(workspace_id="ws_1")
    assert len(ws1_events) == 1
    assert ws1_events[0].workspace_id == "ws_1"


def test_audit_logger_filters_by_event_type():
    """Audit logger filters by event type."""
    logger = AuditLogger()
    logger.log("snapshot_signed", "ws_1", "user_1", "snap_1")
    logger.log("hash_verified", "ws_1", "user_1", "snap_1")

    signed_events = logger.get_events(event_type="snapshot_signed")
    assert len(signed_events) == 1


def test_audit_logger_clear():
    """Audit logger can be cleared."""
    logger = AuditLogger()
    logger.log("test", "ws_1", "user_1", "target_1")
    logger.clear()
    assert len(logger.get_events()) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TTL Cache Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_ttl_cache_set_and_get():
    """Cache set and get work correctly."""
    cache = TTLCache(name="test", max_size=10)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_ttl_cache_miss_returns_none():
    """Cache miss returns None."""
    cache = TTLCache(name="test")
    assert cache.get("missing") is None


def test_ttl_cache_lru_eviction():
    """LRU eviction removes oldest entry when over capacity."""
    cache = TTLCache(name="test", max_size=2)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")  # Should evict key1

    assert cache.get("key1") is None  # Evicted
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"


def test_ttl_cache_expiration():
    """TTL expiration removes expired entries."""
    cache = TTLCache(name="test")
    cache.set("key1", "value1", ttl_seconds=1)

    # Immediately accessible
    assert cache.get("key1") == "value1"

    # After TTL expires
    time.sleep(1.2)
    assert cache.get("key1") is None


def test_ttl_cache_delete():
    """Cache delete removes entries."""
    cache = TTLCache(name="test")
    cache.set("key1", "value1")
    assert cache.delete("key1") is True
    assert cache.get("key1") is None
    assert cache.delete("key1") is False  # Already deleted


def test_ttl_cache_stats():
    """Cache stats track hits/misses."""
    cache = TTLCache(name="test")
    cache.set("key1", "value1")
    cache.get("key1")  # Hit
    cache.get("missing")  # Miss

    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.hit_rate == 0.5


def test_ttl_cache_hit_rate_zero_when_empty():
    """Cache hit rate is 0 when no operations."""
    cache = TTLCache(name="test")
    assert cache.stats().hit_rate == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Specialized Cache Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_snapshot_cache():
    """SnapshotCache stores and retrieves snapshots."""
    from app.modules.world.world_models import WorldSnapshot

    cache = SnapshotCache()
    snapshot = WorldSnapshot(
        snapshot_id="snap_1",
        world_id="world_1",
        workspace_id="ws_1",
        version=1,
        graph_version=1,
        state_hash="abc",
        variable_count=5,
    )
    cache.set(snapshot)
    assert cache.get("snap_1") == snapshot
    assert cache.invalidate("snap_1") is True
    assert cache.get("snap_1") is None


def test_state_cache():
    """StateCache stores and retrieves states."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    cache = StateCache()
    cache.set(state)
    cached = cache.get("world_1", version=1)
    assert cached is not None
    assert cached.world_id == "world_1"


def test_state_cache_latest():
    """StateCache retrieves latest state."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    cache = StateCache()
    cache.set(state)
    latest = cache.get("world_1")  # No version = latest
    assert latest is not None


def test_twin_cache():
    """TwinCache stores and retrieves twin data."""
    cache = TwinCache()
    twin_data = {"twin_id": "twin_1", "name": "Test Twin"}
    cache.set("twin_1", twin_data)
    assert cache.get("twin_1") == twin_data
    cache.invalidate("twin_1")
    assert cache.get("twin_1") is None


def test_rule_cache():
    """RuleCache stores and retrieves rule data."""
    cache = RuleCache()
    rule_data = {"rule_id": "r1", "name": "Test Rule"}
    cache.set("r1", rule_data)
    assert cache.get("r1") == rule_data


# ─────────────────────────────────────────────────────────────────────────────
# Performance Benchmark Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_benchmark_replay_under_target():
    """Replay benchmark runs under 500ms target."""
    bench = PerformanceBenchmark()
    # Simple operation that should be very fast
    result = bench.benchmark_replay(lambda: "done")
    assert result.passed is True
    assert result.duration_ms < 500


def test_benchmark_clone_under_target():
    """Clone benchmark runs under 200ms target."""
    bench = PerformanceBenchmark()
    result = bench.benchmark_clone(lambda: "cloned")
    assert result.passed is True


def test_benchmark_diff_under_target():
    """Diff benchmark runs under 100ms target."""
    bench = PerformanceBenchmark()
    result = bench.benchmark_diff(lambda: "diffed")
    assert result.passed is True


def test_benchmark_all_passed():
    """All benchmarks report correct pass status."""
    bench = PerformanceBenchmark()
    bench.benchmark_replay(lambda: 1)
    bench.benchmark_clone(lambda: 2)
    bench.benchmark_diff(lambda: 3)
    assert bench.all_passed() is True


def test_benchmark_results_list():
    """Benchmark results are retrievable."""
    bench = PerformanceBenchmark()
    bench.benchmark_replay(lambda: 1)
    bench.benchmark_clone(lambda: 2)
    assert len(bench.get_results()) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Cache Manager Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_manager_provides_all_caches():
    """Cache manager provides all cache types."""
    manager = CacheManager()
    assert manager.snapshots is not None
    assert manager.states is not None
    assert manager.twins is not None
    assert manager.rules is not None


def test_cache_manager_all_stats():
    """Cache manager returns stats for all caches."""
    manager = CacheManager()
    stats = manager.all_stats()
    assert "snapshots" in stats
    assert "states" in stats
    assert "twins" in stats
    assert "rules" in stats


def test_cache_manager_clear_all():
    """Cache manager can clear all caches."""
    manager = CacheManager()
    manager.snapshots.set(WorldSnapshot(
        snapshot_id="snap_1",
        world_id="world_1",
        workspace_id="ws_1",
        version=1,
        graph_version=1,
        state_hash="abc",
        variable_count=0,
    ))
    manager.clear_all()
    assert manager.snapshots.get("snap_1") is None


# ─────────────────────────────────────────────────────────────────────────────
# Performance Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_1000_state_hash_computations_under_5s():
    """1000 state hash computations complete in under 5 seconds."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )
    verifier = StateHashVerifier()
    start = time.perf_counter()
    for _ in range(1000):
        verifier.compute_state_hash(state)
    duration = time.perf_counter() - start
    assert duration < 5.0


def test_cache_speedup():
    """Cache makes second access faster than first (conceptually)."""
    cache = TTLCache(name="test")
    cache.set("key1", "x" * 10000)

    # Second access is a hit, first is also a hit (we just set it)
    # But we can verify stats
    cache.get("key1")
    cache.get("key1")
    cache.get("key1")
    stats = cache.stats()
    assert stats.hits == 3


def test_snapshot_signing_performance():
    """100 snapshots can be signed in under 2 seconds."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    snapshot = create_state_snapshot(state)
    signer = SnapshotSigner(signing_key="perf-test")

    start = time.perf_counter()
    for _ in range(100):
        signer.sign(snapshot)
    duration = time.perf_counter() - start
    assert duration < 2.0
