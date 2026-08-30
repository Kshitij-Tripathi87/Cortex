"""Production Qualification (PQ-4) — Load, Saturation & High-Throughput Benchmarking.

Validates:
1. High-throughput event processing through RealtimeStatePipeline
2. Parallel multi-agent deliberations under concurrent load
3. High-concurrency distributed lock contention with zero deadlocks
"""

import asyncio
import os
from datetime import UTC, datetime

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest

from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.state_pipeline import get_state_pipeline
from app.modules.events.event_models import InventoryChanged
from app.modules.multi_agent.runtime.supervisor import (
    AgentSupervisor,
    SupervisorConfig,
    SupervisorTask,
    TaskPriority,
)
from app.modules.world.world_models import StateVariable, StateVariableType, WorldState


# ─────────────────────────────────────────────────────────────────────────────
# 1. High-Throughput Pipeline Event Ingestion
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_load_state_pipeline_throughput():
    """Verify high-throughput event processing through state pipeline with latency tracking."""
    pipeline = get_state_pipeline()
    ctx = ExecutionContext.create_system_context(
        tenant_id="tenant_load",
        organization_id="org_load",
        workspace_id="ws_load",
    )

    current_state = WorldState(
        world_id="w_load",
        workspace_id="ws_load",
        version=1,
        variables={
            "inventory_qty": StateVariable(
                variable_id="inventory_qty",
                variable_type=StateVariableType.INVENTORY,
                entity_id="warehouse_load",
                entity_type="warehouse",
                value=50000.0,
            )
        },
        graph_version=1,
    )

    events_to_process = 50

    async def ingest_one(i: int):
        evt = InventoryChanged(
            event_id=f"evt_load_{i}_{uuid7()}",
            world_id="w_load",
            workspace_id="ws_load",
            entity_type="warehouse",
            entity_id="warehouse_load",
            warehouse_id="warehouse_load",
            component_id=f"part_{i % 10}",
            quantity_change=-10,
            reason="assembly",
            occurred_at=datetime.now(UTC),
        )
        return await pipeline.ingest_event_and_propagate(evt, current_state, ctx)

    tasks = [ingest_one(i) for i in range(events_to_process)]
    results = await asyncio.gather(*tasks)

    assert len(results) == events_to_process
    success_count = sum(1 for r in results if r.success)
    assert success_count == events_to_process

    # Check that latency metrics were computed for all operations
    latencies = [r.latency_metrics.total_pipeline_latency_ms for r in results]
    assert all(lat >= 0.0 for lat in latencies)
    avg_latency = sum(latencies) / len(latencies)
    assert avg_latency < 100.0  # Measured average pipeline latency under load < 100ms


# ─────────────────────────────────────────────────────────────────────────────
# 2. Parallel Multi-Agent Deliberations
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_load_concurrent_multi_agent_deliberations():
    """Verify multiple multi-agent deliberations execute concurrently without state interference."""
    supervisor = AgentSupervisor(
        config=SupervisorConfig(max_rounds=2, enable_parallel_execution=True)
    )

    concurrent_runs = 5

    async def run_deliberation_task(idx: int):
        ctx = ExecutionContext.create_system_context(
            tenant_id=f"tenant_{idx}",
            organization_id=f"org_{idx}",
            workspace_id=f"ws_{idx}",
        )
        task = SupervisorTask(
            task_id=f"task_load_{idx}",
            task_type="SUPPLIER_SHORTAGE",
            description=f"Automated scenario test #{idx}",
            world_state_version=1,
            priority=TaskPriority.NORMAL,
        )
        state = WorldState(
            world_id=f"w_{idx}",
            workspace_id=f"ws_{idx}",
            version=1,
            variables={},
            graph_version=1,
        )
        return await supervisor.run_deliberation(task, ctx, state)

    delib_tasks = [run_deliberation_task(i) for i in range(concurrent_runs)]
    results = await asyncio.gather(*delib_tasks)

    assert len(results) == concurrent_runs
    for r in results:
        assert r.status.value in {"COMPLETED", "PARTIAL"}
        assert len(r.messages) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# 3. High-Concurrency Distributed Lock Contention
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_load_distributed_lock_contention():
    """Verify distributed lock prevents race conditions under 30 concurrent competing workers."""
    cache = get_cache_manager()
    lock_resource = "worldstate_atomic_version_increment"
    shared_counter = 0
    num_workers = 30

    async def worker():
        nonlocal shared_counter
        # Attempt to acquire lock with retry
        for _ in range(20):
            async with cache.lock(lock_resource, ttl_seconds=2) as acquired:
                if acquired:
                    current = shared_counter
                    await asyncio.sleep(0.005)  # Simulate brief critical section work
                    shared_counter = current + 1
                    return True
            await asyncio.sleep(0.01)
        return False

    workers = [worker() for _ in range(num_workers)]
    outcomes = await asyncio.gather(*workers)

    success_count = sum(1 for o in outcomes if o)
    assert success_count > 0
    assert shared_counter == success_count
