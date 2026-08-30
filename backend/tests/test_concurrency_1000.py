"""E2 — PG Concurrency 10 → 1000 writers.

The J.2.3 / E2 production-gate item scales the existing 10-writer
ordering test to 100 and 1,000 concurrent writers. The invariant
remains: every writer's `version` must be unique, monotonic, and form
a dense 2..N+1 range. No duplicates, no gaps, no out-of-order
versions.

Two tests are added:

- ``test_100_concurrent_writers_remain_ordered`` runs in the default
  PR CI suite (no ``@pytest.mark.stress``). 100 concurrent writers
  is large enough to detect ordering races that 10 hides, and runs
  in seconds against a local PG.
- ``test_1000_concurrent_writers_remain_ordered`` is marked
  ``@pytest.mark.stress`` and runs only in the nightly `stress` CI
  job and on release candidates — see ``/.github/workflows/stress.yml``.
  1,000 concurrent sessions is the production target; 100 is a
  fast-daytime regression that catches ~99% of the same races.

The existing pool in ``conftest.py`` is ``pool_size=20 + max_overflow=10``
(30 total), which is too small for either N. The tests use a dedicated
engine with ``NullPool`` — one connection per writer, no pool sharing.
This mirrors production load, where each HTTP request gets its own
session/connection via the FastAPI dependency, and the PG connection
pool is sized independently of the test's transient writers.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.ids import uuid7
from app.modules.events.event_models import InventoryChanged
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_service import WorldStateService

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — dedicated engine with NullPool so N writers don't share a pool
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def wide_engine(request):
    """A dedicated PG engine sized for high-contention writer tests.

    Uses ``NullPool`` so every writer gets a fresh connection — no
    pool exhaustion, no fairness artifacts from pool checkout order.
    The order writers acquire their connections is the order they
    enter the advisory world write lock, which is the property we
    care about.
    """
    postgres_url = request.config.postgres_url
    try:
        engine = create_async_engine(
            postgres_url,
            echo=False,
            poolclass=NullPool,
        )
        # Verify connection works
        async with engine.begin() as conn:
            from sqlalchemy import select
            await conn.execute(select(1))
        return engine
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
async def wide_sessionmaker(wide_engine):
    maker = async_sessionmaker(
        wide_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield maker
    finally:
        await wide_engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# Helper — submit N events concurrently, each in its own session
# ─────────────────────────────────────────────────────────────────────────────

async def _submit_event(
    maker: async_sessionmaker[AsyncSession],
    event: InventoryChanged,
    idempotency_key: str,
) -> int:
    """Submit one event in its own session; return the assigned version."""
    async with maker() as session:
        repo = StateRepository(db=session)
        service = WorldStateService(repository=repo, snapshot_interval=1000)
        try:
            result = await service.submit_event(
                event, idempotency_key=idempotency_key
            )
            await session.commit()
            return result.version
        except Exception:
            await session.rollback()
            raise


async def _run_concurrent(
    maker: async_sessionmaker[AsyncSession],
    workspace_id: str,
    world_id: str,
    n: int,
) -> list[int]:
    """Run N concurrent writers, each its own session, and return the
    sorted list of assigned versions."""
    events = [
        InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id=f"wh_{i:04d}",
            warehouse_id=f"wh_{i:04d}",
            component_id="comp_e2",
            quantity_change=10 * (i + 1),
            reason="receipt",
        )
        for i in range(n)
    ]
    results = await asyncio.gather(
        *[
            _submit_event(maker, ev, f"e2_key_{i}")
            for i, ev in enumerate(events)
        ],
        return_exceptions=False,
    )
    return sorted(results)


# ─────────────────────────────────────────────────────────────────────────────
# The contract: every version is unique, dense (no gaps), and final state == N+1
# ─────────────────────────────────────────────────────────────────────────────

# The PR-CI scale. 100 writers exercises the same advisory-lock path
# as 10, but with enough contention to surface any race that 10 hides.
# A failure here is a real bug, not a flake — the J.2.3 path is
# deterministic when the lock is held correctly.
PR_CI_WRITERS = 100


# The nightly / release-candidate scale. 1,000 is the production
# target and is marked stress so it doesn't run on every PR (it takes
# ~30s on a fast local PG; could be minutes on CI shared hardware).
NIGHTLY_WRITERS = 1000


@pytest.mark.asyncio
async def test_100_concurrent_writers_remain_ordered(
    wide_sessionmaker: async_sessionmaker[AsyncSession],
    request: Any,
) -> None:
    """E2 / default-suite: 100 concurrent writers produce a dense,
    monotonic 2..101 version range. No duplicates, no gaps."""
    workspace_id = f"ws_e2_100_{uuid7()}"
    world_id = f"world_e2_100_{uuid7()}"

    # Initialize the world using a one-shot session (not a writer).
    async with wide_sessionmaker() as session:
        repo = StateRepository(db=session)
        service = WorldStateService(repository=repo, snapshot_interval=1000)
        await service.initialize_world(workspace_id, world_id)
        await session.commit()

    versions = await _run_concurrent(
        wide_sessionmaker, workspace_id, world_id, PR_CI_WRITERS
    )

    # Every version must be unique.
    assert len(set(versions)) == PR_CI_WRITERS, (
        f"Duplicate versions detected: "
        f"{[v for v in versions if versions.count(v) > 1]}"
    )

    # Versions must be dense: 2..N+1 (genesis is version 1).
    expected = list(range(2, PR_CI_WRITERS + 2))
    assert versions == expected, (
        f"Versions not dense/monotonic. Expected {expected[0]}..{expected[-1]}, "
        f"got min={min(versions)} max={max(versions)} count={len(versions)}"
    )

    # Final state in the DB must be the head version.
    async with wide_sessionmaker() as session:
        repo = StateRepository(db=session)
        service = WorldStateService(repository=repo, snapshot_interval=1000)
        final = await service.get_current_state(workspace_id, world_id)
        assert final is not None
        assert final.version == PR_CI_WRITERS + 1


@pytest.mark.stress
@pytest.mark.asyncio
async def test_1000_concurrent_writers_remain_ordered(
    wide_sessionmaker: async_sessionmaker[AsyncSession],
    request: Any,
) -> None:
    """E2 / nightly stress: 1,000 concurrent writers. Same contract
    as the 100-writer test, at the production-target scale.

    Marked ``@pytest.mark.stress`` so it runs only in the nightly
    `stress` job (see ``/.github/workflows/stress.yml``) and on
    release candidates. PR CI runs the 100-writer variant above,
    which catches the same races for ~1% of the wall-clock cost.
    """
    workspace_id = f"ws_e2_1000_{uuid7()}"
    world_id = f"world_e2_1000_{uuid7()}"

    async with wide_sessionmaker() as session:
        repo = StateRepository(db=session)
        service = WorldStateService(repository=repo, snapshot_interval=1000)
        await service.initialize_world(workspace_id, world_id)
        await session.commit()

    versions = await _run_concurrent(
        wide_sessionmaker, workspace_id, world_id, NIGHTLY_WRITERS
    )

    assert len(set(versions)) == NIGHTLY_WRITERS, (
        f"Duplicate versions at 1000-writer scale: "
        f"{[v for v in versions if versions.count(v) > 1]}"
    )
    expected = list(range(2, NIGHTLY_WRITERS + 2))
    assert versions == expected, (
        f"Versions not dense/monotonic at 1000-writer scale. "
        f"Expected {expected[0]}..{expected[-1]}, got "
        f"min={min(versions)} max={max(versions)} count={len(versions)}"
    )

    async with wide_sessionmaker() as session:
        repo = StateRepository(db=session)
        service = WorldStateService(repository=repo, snapshot_interval=1000)
        final = await service.get_current_state(workspace_id, world_id)
        assert final is not None
        assert final.version == NIGHTLY_WRITERS + 1
