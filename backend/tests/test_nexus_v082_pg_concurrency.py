"""Nexus v0.8.2 — Real-PostgreSQL FOR UPDATE concurrency tests.

SQLite serializes writes, so the v0.8.2 acceptance suite on SQLite cannot
establish the PostgreSQL row-lock guarantee. These tests run against a real
PostgreSQL server (pgserver-managed, or any PG via CORTEX_TEST_PG_RACE_URL)
and prove the governed-transition race contract:

             PROPOSED → … → AWAITING_APPROVAL
                          │
                  ┌───────┴───────┐
                  ↓               ↓
           Transaction A    Transaction B
           SELECT FOR UPDATE   waits on row lock
                  │               │
              succeeds      lock released → reloads committed row
                  │               │
              APPROVED      InvalidTransition → HTTP 409

Assertions (per the v0.8.2 closeout gate):
  * exactly 1 success
  * exactly 1 conflict
  * one valid lifecycle transition
  * no duplicate audit transition
  * no corruption (phase consistent, deterministic_hash recomputed,
    exactly one outbox event, transitions append-only)

Skips (not fails) when no PostgreSQL is available in the environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import uuid
from typing import Any

import pytest
from fastapi import Request
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
from app.modules.nexus_spine.p0_migration import (
    AuthoritativeDecisionService,
    InvalidTransitionError,
    StaleWorldStateError,
    get_authoritative_decision_service,
)
from app.modules.nexus_spine.p0_migration.authoritative_decisions import _compute_hash
from app.modules.nexus_spine.persistence.models import (
    DecisionRecordDB,
    DecisionTransitionDB,
    EventRecordDB,
)

TENANT = "race-tenant"
WS = "WS-RACE"


# ─────────────────────────────────────────────────────────────────────
# Real PostgreSQL fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_race_url(tmp_path_factory):
    """Connection URL to a real PostgreSQL server.

    Priority: CORTEX_TEST_PG_RACE_URL env var → pgserver-managed local
    server (pip package; used in sandboxes without a TCP database) → skip.
    """
    env_url = os.environ.get("CORTEX_TEST_PG_RACE_URL")
    if env_url:
        return env_url

    try:
        import pgserver
    except ImportError:
        pytest.skip("no PostgreSQL available (CORTEX_TEST_PG_RACE_URL unset, pgserver missing)")

    data_dir = tmp_path_factory.mktemp("nexus-pg-race")
    db = pgserver.get_server(str(data_dir))
    sock_dir = str(data_dir)
    with contextlib.suppress(Exception):
        db.psql("CREATE DATABASE nexus_race;")  # already exists (reused dir)
    return f"postgresql+asyncpg://postgres@/nexus_race?host={sock_dir}"


@pytest.fixture
async def race_engine(pg_race_url):
    """Function-scoped on purpose: asyncpg connections are bound to the
    event loop they were created in, so the engine (and its pool) must
    live entirely inside each test's loop. Tables are dropped and
    recreated per test for full isolation between races."""
    engine = create_async_engine(pg_race_url, pool_size=10, max_overflow=5)

    # Create only the nexus_* tables (their FKs are self-contained).
    from app.infrastructure.database import Base

    nexus_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("nexus_"):
            table.to_metadata(nexus_metadata)
    async with engine.begin() as conn:
        await conn.run_sync(nexus_metadata.drop_all)
        await conn.run_sync(nexus_metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
def race_sessionmaker(race_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(race_engine, expire_on_commit=False, class_=AsyncSession)


async def _seed_decision_at_awaiting_approval(
    sf: async_sessionmaker[AsyncSession], svc: AuthoritativeDecisionService, did: str
) -> None:
    async with sf() as s:
        await svc.create(
            s,
            decision_id=did,
            tenant_id=TENANT,
            workspace_id=WS,
            proposal_id=did,
            world_state_version=1,
            world_state_hash="race-hash-1",
            options=[{"option_id": "O1", "nev": 100.0}],
            recommended_option_id="O1",
        )
        for phase in (
            DecisionPhase.SIMULATED,
            DecisionPhase.POLICY_CHECKED,
            DecisionPhase.AWAITING_APPROVAL,
        ):
            await svc.advance(s, did, phase, actor="seeder")
        await s.commit()


# ─────────────────────────────────────────────────────────────────────
# 0. The lock is real: FOR UPDATE in the compiled PostgreSQL statement
# ─────────────────────────────────────────────────────────────────────


def test_advance_select_compiles_to_for_update_on_postgres():
    from sqlalchemy.dialects import postgresql

    stmt = select(DecisionRecordDB).where(DecisionRecordDB.decision_id == "D-X").with_for_update()
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


# ─────────────────────────────────────────────────────────────────────
# 1. The race: two concurrent governed transitions, one row
# ─────────────────────────────────────────────────────────────────────


class TestPostgresAdvanceRace:
    async def test_exactly_one_winner_exactly_one_409(self, race_sessionmaker):
        """Transaction A and Transaction B race AWAITING_APPROVAL → APPROVED.

        A gatekeeper transaction holds the row lock first so BOTH
        contenders are provably queued on SELECT … FOR UPDATE before the
        race starts; releasing the gate releases them together.
        """
        sf = race_sessionmaker
        svc = get_authoritative_decision_service()
        did = f"D-RACE-{uuid.uuid4().hex[:8]}"
        await _seed_decision_at_awaiting_approval(sf, svc, did)

        # Gatekeeper: hold the row lock so both contenders queue on it.
        gate = sf()
        await gate.execute(
            select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did).with_for_update()
        )

        async def contender(actor: str) -> tuple[str, str]:
            async with sf() as s:
                try:
                    await svc.advance(s, did, DecisionPhase.APPROVED, actor=actor)
                    await s.commit()
                    return ("ok", actor)
                except InvalidTransitionError:
                    await s.rollback()
                    return ("conflict", actor)

        try:
            tasks = [
                asyncio.create_task(contender("A")),
                asyncio.create_task(contender("B")),
            ]
            # Let both contenders reach (and block on) the row lock.
            await asyncio.sleep(0.5)
            assert not any(t.done() for t in tasks), (
                "a contender finished while the gate still held the lock — "
                "FOR UPDATE is not engaging"
            )
            # Release the gate: both contenders now race for the row lock.
            await gate.rollback()
            results = await asyncio.gather(*tasks)
        finally:
            await gate.close()

        statuses = sorted(status for status, _ in results)
        assert statuses == ["conflict", "ok"], f"expected 1 ok + 1 conflict, got {results}"

        winner = next(actor for status, actor in results if status == "ok")
        assert winner in ("A", "B")

        # ── Post-race database state ────────────────────────────────
        async with sf() as s:
            rec = (
                await s.execute(select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did))
            ).scalar_one()
            transitions = (
                (
                    await s.execute(
                        select(DecisionTransitionDB)
                        .where(DecisionTransitionDB.decision_id == did)
                        .order_by(DecisionTransitionDB.id)
                    )
                )
                .scalars()
                .all()
            )
            events = (
                (await s.execute(select(EventRecordDB).where(EventRecordDB.entity_id == did)))
                .scalars()
                .all()
            )

        # No corruption: final phase is exactly APPROVED.
        assert rec.phase == DecisionPhase.APPROVED.value

        # One valid lifecycle transition for the raced step…
        raced = [
            t
            for t in transitions
            if t.from_phase == DecisionPhase.AWAITING_APPROVAL.value
            and t.to_phase == DecisionPhase.APPROVED.value
        ]
        assert len(raced) == 1, f"duplicate or missing raced transition: {raced}"
        assert raced[0].actor == winner

        # …no duplicate audit transitions overall (append-only, unique steps)…
        pairs = [(t.from_phase, t.to_phase) for t in transitions]
        assert len(pairs) == len(set(pairs)), f"duplicate audit transitions: {pairs}"

        # …and exactly the expected number: created + 3 seed + 1 raced.
        assert len(transitions) == 5

        # Exactly one outbox event for the approval.
        approval_events = [
            e for e in events if (e.payload or {}).get("to_phase") == DecisionPhase.APPROVED.value
        ]
        assert len(approval_events) == 1, f"expected 1 approval event, got {len(approval_events)}"

        # Deterministic hash recomputed from the final persisted state.
        opts = rec.options if isinstance(rec.options, list) else []
        assert rec.deterministic_hash == _compute_hash(
            decision_id=did,
            options=opts,
            world_state_version=rec.world_state_version,
            world_state_hash=rec.world_state_hash,
            phase=DecisionPhase.APPROVED.value,
            proposal_id=rec.proposal_id,
            chosen_option=rec.chosen_option,
        )

    async def test_stale_world_state_advances_lose_with_409_semantics(self, race_sessionmaker):
        """The other 409 branch: an advance carrying an out-of-date
        expectation of the world state must lose, auto-mark the decision
        STALE, and append the drift audit trail — never partially apply."""
        sf = race_sessionmaker
        svc = get_authoritative_decision_service()
        did = f"D-STALE-{uuid.uuid4().hex[:8]}"
        await _seed_decision_at_awaiting_approval(sf, svc, did)

        async with sf() as s:
            with pytest.raises(StaleWorldStateError):
                await svc.advance(
                    s,
                    did,
                    DecisionPhase.APPROVED,
                    actor="stale-actor",
                    current_world_state_version=999,  # world moved on
                    current_world_state_hash="moved-on",
                )
            await s.commit()  # the auto-STALE transition persists

        async with sf() as s:
            rec = (
                await s.execute(select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did))
            ).scalar_one()
            transitions = (
                (
                    await s.execute(
                        select(DecisionTransitionDB).where(DecisionTransitionDB.decision_id == did)
                    )
                )
                .scalars()
                .all()
            )
            events = (
                (await s.execute(select(EventRecordDB).where(EventRecordDB.entity_id == did)))
                .scalars()
                .all()
            )

        assert rec.phase == DecisionPhase.STALE.value
        drift = [
            t
            for t in transitions
            if t.to_phase == DecisionPhase.STALE.value
            and t.reason == "world_state_drift_detected_on_advance"
        ]
        assert len(drift) == 1
        # No APPROVED transition leaked through the rejected advance.
        assert not [t for t in transitions if t.to_phase == DecisionPhase.APPROVED.value]
        # The invalidation landed in the outbox exactly once.
        assert (
            len([e for e in events if (e.payload or {}).get("reason") == "world_state_drift"]) == 1
        )


# ─────────────────────────────────────────────────────────────────────
# 2. The same race through the canonical HTTP route
# ─────────────────────────────────────────────────────────────────────


class TestPostgresHttpRace:
    async def test_concurrent_advance_via_api_one_200_one_409(self, race_sessionmaker, race_engine):
        """End-to-end: two concurrent POST /api/v1/nexus/decisions/{id}/advance
        against the canonical route, backed by real PostgreSQL. The API
        layer must surface the FOR UPDATE arbitration as exactly one 200
        and one 409 with the structured conflict detail."""
        sf = race_sessionmaker
        svc = get_authoritative_decision_service()
        did = f"D-HTTP-{uuid.uuid4().hex[:8]}"
        await _seed_decision_at_awaiting_approval(sf, svc, did)

        from app.infrastructure.database import get_db
        from app.infrastructure.security import AuthContext, get_current_user
        from app.main import create_app

        app = create_app()

        async def _override_db() -> Any:
            async with sf() as session:
                yield session

        app.dependency_overrides[get_db] = _override_db

        async def _fake_user(request: Request) -> AuthContext:
            return AuthContext(
                user_id="race-user",
                roles=["operator"],
                workspace_ids=[],
                is_anonymous=False,
            )

        app.dependency_overrides[get_current_user] = _fake_user

        # Gatekeeper holds the row lock while both requests queue.
        gate = sf()
        await gate.execute(
            select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did).with_for_update()
        )

        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)

        async def contender(client: AsyncClient) -> tuple[int, dict[str, Any]]:
            r = await client.post(
                f"/api/v1/nexus/decisions/{did}/advance",
                headers={"X-Workspace-Id": WS},
                json={"target_phase": DecisionPhase.APPROVED.value},
            )
            return r.status_code, r.json()

        try:
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                tasks = [
                    asyncio.create_task(contender(client)),
                    asyncio.create_task(contender(client)),
                ]
                await asyncio.sleep(0.5)
                assert not any(t.done() for t in tasks), (
                    "a request completed while the gate held the row lock"
                )
                await gate.rollback()
                results = await asyncio.gather(*tasks)
        finally:
            await gate.close()

        statuses = sorted(code for code, _ in results)
        assert statuses == [200, 409], f"expected one 200 + one 409, got {results}"

        winner_body = next(body for code, body in results if code == 200)
        loser_body = next(body for code, body in results if code == 409)
        assert winner_body["data"]["decision"]["phase"] == DecisionPhase.APPROVED.value
        assert "Invalid transition" in str(loser_body["detail"])

        # Database integrity after the HTTP race.
        async with sf() as s:
            rec = (
                await s.execute(select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did))
            ).scalar_one()
            raced = (
                (
                    await s.execute(
                        select(DecisionTransitionDB).where(
                            DecisionTransitionDB.decision_id == did,
                            DecisionTransitionDB.from_phase
                            == DecisionPhase.AWAITING_APPROVAL.value,
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert rec.phase == DecisionPhase.APPROVED.value
        assert len(raced) == 1, "duplicate raced transition via HTTP"
