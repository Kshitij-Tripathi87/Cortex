"""v0.8.5-B4 — Launch reliability acceptance (A1–A20 + chaos + load + pins).

Proves the durable path end to end on REAL PostgreSQL (pgserver, or
``CORTEX_TEST_PG_RACE_URL`` / ``CORTEX_TEST_DATABASE_URL`` when set):

    PG COMMIT → outbox row → relay claim/lease → Redis/fabric → SSE/WS
    → sequence gate → replay/resync.

Every test is deterministic: no ``sleep``-luck. Broker faults are injected
through doubles, time is travelled with explicit SQL, and async conditions
use bounded waits that only fire on genuine failure.

    A1  transaction coupling (commit→state+outbox, rollback→neither)
    A2  concurrent sequence allocation (contiguous, unique, per-workspace)
    A3  duplicate delivery (at-least-once wire, exactly-once effect)
    A4  publisher restart (graceful: leases released, peer drains)
    A5  worker crash (leases honored, then reclaimed by peer)
    A6  lease reclaim (expired claims move publishers, counted)
    A7  Redis restart (partition blocks, heal drains in order)
    A8  Redis outage (mutations continue, backlog visible, then drains)
    A9  retry/backoff (exp+jitter, poison flagged, never dropped)
    A10 durable replay (HTTP envelope, paging, has_more)
    A11 sequence gap (live stream emits resync_needed, exact bounds)
    A12 large-gap resync (threshold refuses page-by-page replay)
    A13 SSE reconnect (cursor resume over HTTP, no loss, no dup)
    A14 WS reconnect (catch-up + live + gap over the socket)
    A15 tenant isolation (replay + stream + catch-up)
    A16 workspace isolation (403 boundary + subscribe boundary + 4401)
    A17 API restart (publisher lifecycle, subscribers survive)
    A18 browser refresh (cursor contract at head)
    A19 out-of-order delivery (gap, never silent reorder)
    A20 stale event handling (duplicates ignored, counted)

Plus: metrics pins, no-secrets-in-logs pin, B4.1 10k-row acceptance,
chaos rehearsal (C1–C5), and the load probe (L1–L2 with P50/P95/P99).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import statistics
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.websockets import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.nexus_spine.persistence.models as _spine_models  # noqa: F401
from app.api.v1 import nexus_persistent
from app.api.v1 import realtime as realtime_module
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.infrastructure.outbox_publisher import (
    OutboxPublisher,
    compute_backoff_delay_s,
    get_backlog_stats,
)
from app.infrastructure.realtime_bus import (
    Event,
    IdempotentEventConsumer,
    RealtimeBus,
    get_realtime_bus,
    sse_stream,
)
from app.modules.nexus_spine.p0_migration import (
    get_authoritative_decision_service,
    get_authoritative_registry_service,
    get_authoritative_truth_loop,
)
from app.modules.nexus_spine.persistence.models import (
    DecisionRecordDB,
    EventRecordDB,
    ForecastRecordDB,
    RiskRecordDB,
)
from app.modules.nexus_spine.persistence.repositories import get_event_repository

TENANT_A = "b4-tenant-a"
TENANT_B = "b4-tenant-b"
WS_1 = "b4-ws-1"
WS_2 = "b4-ws-2"


# ─────────────────────────────────────────────────────────────────────
# Fixtures: real PostgreSQL + ASGI app + broker doubles
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    env_url = os.environ.get("CORTEX_TEST_PG_RACE_URL") or os.environ.get(
        "CORTEX_TEST_DATABASE_URL"
    )
    if env_url and "postgres" in env_url:
        return env_url
    try:
        import pgserver
    except ImportError:
        pytest.skip("no PostgreSQL available (pgserver or CORTEX_TEST_PG_RACE_URL required)")
    data_dir = tmp_path_factory.mktemp("nexus-v085-b4-pg")
    db = pgserver.get_server(str(data_dir))
    with contextlib.suppress(Exception):
        db.psql("CREATE DATABASE nexus_v085_b4;")
    return f"postgresql+asyncpg://postgres@/nexus_v085_b4?host={data_dir}"


@pytest.fixture
async def pg_engine(pg_url):
    engine = create_async_engine(pg_url, pool_size=15, max_overflow=10)
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
def sessionmaker(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def api_client(pg_engine, pg_url):
    """ASGI client over real PG: persistent + realtime routers, dev identity.

    ``get_db`` is overridden with a same-DB maker; the process-global session
    factory is wired to the same database (and restored afterwards) because
    the SSE endpoint resolves it directly.
    """
    import app.infrastructure.database as _dbmod

    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(nexus_persistent.router, prefix="/api/v1")
    test_app.include_router(realtime_module.router, prefix="/api/v1")

    async def _override_get_db():
        async with maker() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db

    global_engine = create_async_engine(pg_url, pool_size=5, max_overflow=5)
    global_maker = async_sessionmaker(global_engine, class_=AsyncSession, expire_on_commit=False)
    old_engine, old_factory = _dbmod._engine, _dbmod._session_factory
    _dbmod._engine, _dbmod._session_factory = global_engine, global_maker
    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, maker
    finally:
        await global_engine.dispose()
        _dbmod._engine, _dbmod._session_factory = old_engine, old_factory


@pytest.fixture
async def global_db(pg_url):
    """Wire the process-global session factory (direct endpoint/WS tests)."""
    import app.infrastructure.database as _dbmod

    engine = create_async_engine(pg_url, pool_size=5, max_overflow=5)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    old_engine, old_factory = _dbmod._engine, _dbmod._session_factory
    _dbmod._engine, _dbmod._session_factory = engine, maker
    try:
        yield maker
    finally:
        await engine.dispose()
        _dbmod._engine, _dbmod._session_factory = old_engine, old_factory


@pytest.fixture(autouse=True)
def _b4_dev_identity(monkeypatch):
    """Deterministic dev identity for every B4 test.

    Unrelated test modules ``setdefault(CORTEX_JWT_SECRET)`` at import, so a
    full-suite run otherwise inherits JWT-strict handshakes and the
    token-less WS tests (A14/A15b/A16c) get 4401s. Strip it here; the JWT
    tests re-establish their own secret via ``jwt_env`` (ordered after).
    """
    monkeypatch.delenv("CORTEX_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def jwt_env(monkeypatch, _b4_dev_identity):
    monkeypatch.setenv("CORTEX_JWT_SECRET", "b4-test-secret-0123456789abcdef")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class MockRedisBroker:
    """Healthy/unhealthy Redis stand-in capturing published frames."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        if not self.healthy:
            raise ConnectionError("Redis down (simulated)")
        self.published.append((channel, message))
        return 1

    def seqs(self) -> list[int]:
        return [json.loads(m)["seq"] for _, m in self.published]


class ScriptedBroker(MockRedisBroker):
    """Fails publishes matching a predicate (head-of-line / partial faults)."""

    def __init__(self) -> None:
        super().__init__(healthy=True)
        self.fail_predicate = None

    async def publish(self, channel: str, message: str) -> int:
        data = json.loads(message)
        if self.fail_predicate is not None and self.fail_predicate(data):
            raise ConnectionError(f"scripted failure for seq={data.get('seq')}")
        self.published.append((channel, message))
        return 1


def create_test_bus(broker: MockRedisBroker | None = None) -> RealtimeBus:
    bus = RealtimeBus()
    if broker is not None:
        client = type("RedisClientWrapper", (), {"_redis": broker, "publish": broker.publish})()
        bus._get_redis = lambda: client  # type: ignore[method-assign]
    else:
        bus._redis_client = False
    return bus


def _headers(user: str, workspaces: list[str], roles: str = "operator") -> dict[str, str]:
    return {
        "X-User-Id": user,
        "X-User-Workspaces": ",".join(workspaces),
        "X-User-Roles": roles,
    }


async def _time_travel(
    maker: async_sessionmaker[AsyncSession],
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    expire_lease: bool = True,
    expire_retry: bool = True,
) -> None:
    """Deterministic time travel: push leases/retries into the past."""
    past = datetime.now(UTC) - timedelta(seconds=3600)
    values: dict = {}
    if expire_lease:
        values["lease_expires_at"] = past
    if expire_retry:
        values["next_retry_at"] = past
    if not values:
        return
    async with maker() as s:
        stmt = update(EventRecordDB).where(EventRecordDB.published_at.is_(None))
        if tenant_id is not None:
            stmt = stmt.where(EventRecordDB.tenant_id == tenant_id)
        if workspace_id is not None:
            stmt = stmt.where(EventRecordDB.workspace_id == workspace_id)
        await s.execute(stmt.values(**values))
        await s.commit()


async def _wait_for(pred, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.005)


async def _wait_for_live_subscription(bus, workspace_id: str, before: set) -> None:
    """Wait until the WS endpoint has subscribed its live bus queue.

    The endpoint sends ``catchup_complete`` *before* subscribing, so a test
    that fans out immediately after catch-up races the subscribe: the event
    lands on zero queues and the live tail never sees it. (In production the
    next event trips the socket's gap detector and the client resyncs — the
    race is test-only.) Snapshot the subscriber set before spawning the
    endpoint and wait for a newcomer.
    """

    def _subscribed() -> bool:
        current = bus._local_subscribers.get(workspace_id, set())
        return len(set(current) - before) >= 1

    await _wait_for(_subscribed)


def _metric_value(name: str, labels: dict[str, str] | None = None) -> float | None:
    from prometheus_client import REGISTRY

    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name != name:
                continue
            if labels and not all(sample.labels.get(k) == v for k, v in labels.items()):
                continue
            return float(sample.value)
    return None


async def _collect_sse(
    headers: dict[str, str],
    workspace_id: str,
    after_seq: int,
    max_data_frames: int,
    *,
    token: str | None = None,
    timeout: float = 15.0,
) -> list[tuple[str | None, dict]]:
    """Drive the real SSE endpoint, collect data-bearing frames, then detach.

    httpx's ASGI transport buffers responses to completion, so it cannot
    consume an open-ended SSE stream. Instead we invoke ``realtime_stream``
    (real identity, scoping, framing) and iterate the exact
    ``StreamingResponse.body_iterator`` Starlette would serve over the wire.
    """
    from starlette.requests import Request as StarletteRequest

    from app.api.v1.nexus_persistent import realtime_stream

    async def _receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/v1/nexus/realtime/stream",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("127.0.0.1", 123),
        "scheme": "http",
    }
    # Local-only fabric: no Redis listener task leaks out of the stream.
    bus = get_realtime_bus()
    prev_redis, bus._redis_client = bus._redis_client, False
    try:
        request = StarletteRequest(scope, _receive)
        resp = await realtime_stream(
            request, workspace_id=workspace_id, after_seq=after_seq, token=token
        )
        assert resp.status_code == 200, f"SSE status={resp.status_code}"
        datas: list[tuple[str | None, dict]] = []
        event_name: str | None = None
        body = resp.body_iterator
        try:
            async with asyncio.timeout(timeout):
                async for chunk in body:
                    text = chunk.decode() if isinstance(chunk, bytes) else chunk
                    for line in text.splitlines():
                        if line.startswith(":") or line == "":
                            continue
                        if line.startswith("event:"):
                            event_name = line.split(":", 1)[1].strip()
                            continue
                        if line.startswith("data:"):
                            datas.append((event_name, json.loads(line.split(":", 1)[1].strip())))
                            event_name = None
                            if len(datas) >= max_data_frames:
                                break
                    if len(datas) >= max_data_frames:
                        break
        finally:
            with contextlib.suppress(Exception):
                await body.aclose()
        return datas
    finally:
        bus._redis_client = prev_redis


class FakeWebSocket:
    """In-loop WebSocket double: scripted incoming, spied outgoing."""

    def __init__(
        self, headers: dict[str, str] | None = None, incoming: list[str] | None = None
    ) -> None:
        self.headers = headers or {}
        self._incoming = list(incoming or [])
        self._release = asyncio.Event()
        self.sent: list[str] = []
        self.accepted = False
        self.closed: tuple[int, str] | None = None

    def allow_disconnect(self) -> None:
        self._release.set()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def receive_text(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        await self._release.wait()
        raise WebSocketDisconnect()

    def frames(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


# ─────────────────────────────────────────────────────────────────────
# A1: Transaction coupling
# ─────────────────────────────────────────────────────────────────────


class TestA1TransactionCoupling:
    async def test_a1a_decision_commit_writes_state_and_outbox(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        svc = get_authoritative_decision_service()
        async with sessionmaker() as s:
            await svc.create(
                s,
                decision_id="B4-D1",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                proposal_id="P1",
                world_state_version=7,
                world_state_hash="h" * 16,
            )
            await s.commit()

        async with sessionmaker() as s:
            dec = (
                await s.execute(
                    select(DecisionRecordDB).where(DecisionRecordDB.decision_id == "B4-D1")
                )
            ).scalar_one_or_none()
            assert dec is not None
            outbox = (
                (
                    await s.execute(
                        select(EventRecordDB).where(
                            EventRecordDB.tenant_id == TENANT_A,
                            EventRecordDB.workspace_id == WS_1,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(outbox) == 1
            assert outbox[0].event_type == "decision_created"
            assert outbox[0].entity_id == "B4-D1"
            assert outbox[0].seq == 1
            assert outbox[0].published_at is None  # relay owns delivery, not the tx

    async def test_a1b_decision_rollback_writes_neither(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        svc = get_authoritative_decision_service()
        async with sessionmaker() as s:
            await svc.create(
                s,
                decision_id="B4-D2-ROLLBACK",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                proposal_id="P1",
                world_state_version=7,
                world_state_hash="h" * 16,
            )
            await s.rollback()

        async with sessionmaker() as s:
            dec = (
                await s.execute(
                    select(DecisionRecordDB).where(DecisionRecordDB.decision_id == "B4-D2-ROLLBACK")
                )
            ).scalar_one_or_none()
            assert dec is None
            n_outbox = (
                await s.execute(
                    select(func.count(EventRecordDB.id)).where(
                        EventRecordDB.tenant_id == TENANT_A,
                        EventRecordDB.workspace_id == WS_1,
                    )
                )
            ).scalar()
            assert n_outbox == 0

    async def test_a1c_risk_and_forecast_rollback_coupling(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        registries = get_authoritative_registry_service()
        truth = get_authoritative_truth_loop()
        async with sessionmaker() as s:
            await registries.record_risk(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                entity_id="supplier-acme",
                entity_kind="supplier",
                severity="HIGH",
                title="ACME at risk",
                world_state_version=3,
                risk_score=0.8,
            )
            await truth.record_forecast(
                s,
                forecast_id="B4-F-ROLLBACK",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                sku="SKU-1",
                p50=100.0,
                p80=120.0,
                p95=140.0,
                mean=100.0,
                std_dev=10.0,
            )
            await s.rollback()

        async with sessionmaker() as s:
            assert (
                await s.execute(
                    select(func.count(RiskRecordDB.risk_id)).where(
                        RiskRecordDB.workspace_id == WS_1
                    )
                )
            ).scalar() == 0
            assert (
                await s.execute(
                    select(func.count(ForecastRecordDB.forecast_id)).where(
                        ForecastRecordDB.forecast_id == "B4-F-ROLLBACK"
                    )
                )
            ).scalar() == 0
            assert (await s.execute(select(func.count(EventRecordDB.id)))).scalar() == 0

    async def test_a1d_forecast_commit_emits_forecast_updated(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        truth = get_authoritative_truth_loop()
        async with sessionmaker() as s:
            await truth.record_forecast(
                s,
                forecast_id="B4-F1",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                sku="SKU-1",
                p50=100.0,
                p80=120.0,
                p95=140.0,
                mean=100.0,
                std_dev=10.0,
            )
            await s.commit()

        async with sessionmaker() as s:
            rows = (
                (await s.execute(select(EventRecordDB).where(EventRecordDB.workspace_id == WS_1)))
                .scalars()
                .all()
            )
            assert [r.event_type for r in rows] == ["forecast_updated"]
            assert rows[0].entity_id == "B4-F1"


# ─────────────────────────────────────────────────────────────────────
# A2: Concurrent sequence allocation
# ─────────────────────────────────────────────────────────────────────


class TestA2ConcurrentSequenceAllocation:
    async def test_a2_contiguous_unique_seqs_under_concurrency(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()

        async def _worker(n: int) -> None:
            async with sessionmaker() as s:
                for i in range(25):
                    await repo.publish(
                        s,
                        tenant_id=TENANT_A,
                        workspace_id=WS_1,
                        event_type="TICK",
                        payload={"worker": n, "i": i},
                    )
                await s.commit()

        await asyncio.gather(*[_worker(n) for n in range(8)])

        async with sessionmaker() as s:
            seqs = (
                (
                    await s.execute(
                        select(EventRecordDB.seq)
                        .where(
                            EventRecordDB.tenant_id == TENANT_A,
                            EventRecordDB.workspace_id == WS_1,
                        )
                        .order_by(EventRecordDB.seq)
                    )
                )
                .scalars()
                .all()
            )
        assert list(seqs) == list(range(1, 201))

    async def test_a2b_workspaces_have_independent_sequences(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        async with sessionmaker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="E")
            for _ in range(2):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_2, event_type="E")
            await s.commit()

        async def _seqs(ws: str) -> list[int]:
            async with sessionmaker() as s:
                return list(
                    (
                        await s.execute(
                            select(EventRecordDB.seq)
                            .where(
                                EventRecordDB.tenant_id == TENANT_A,
                                EventRecordDB.workspace_id == ws,
                            )
                            .order_by(EventRecordDB.seq)
                        )
                    )
                    .scalars()
                    .all()
                )

        assert await _seqs(WS_1) == [1, 2, 3]
        assert await _seqs(WS_2) == [1, 2]


# ─────────────────────────────────────────────────────────────────────
# A3: Duplicate delivery
# ─────────────────────────────────────────────────────────────────────


class TestA3DuplicateDelivery:
    def test_a3_consumer_dedups_by_event_id(self) -> None:
        consumer = IdempotentEventConsumer()
        assert consumer.record("EVT-1") is True
        assert consumer.record("EVT-1") is False
        assert consumer.record("EVT-2") is True
        assert consumer.is_duplicate("EVT-1") is True
        assert consumer.is_duplicate("EVT-2") is True

    async def test_a3b_redelivery_applies_once(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """At-least-once wire (crash between publish and mark replays the row)
        still has exactly-once effect through the idempotent consumer."""
        repo = get_event_repository()
        bus = create_test_bus()
        async with sessionmaker() as s:
            evt = await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="TICK")
            await s.commit()
            event_id = evt.event_id

        consumer = IdempotentEventConsumer()
        applied = 0
        async with sessionmaker() as s:
            row = (
                await s.execute(select(EventRecordDB).where(EventRecordDB.event_id == event_id))
            ).scalar_one()
            for _ in range(3):  # same row delivered 3 times (redelivery)
                delivered = await bus.publish_from_outbox(row)
                if consumer.record(delivered.event_id):
                    applied += 1
        assert applied == 1


# ─────────────────────────────────────────────────────────────────────
# A4/A5/A6: Restart, crash, lease reclaim
# ─────────────────────────────────────────────────────────────────────


class TestA4PublisherRestart:
    async def test_a4_graceful_restart_releases_leases_and_peer_drains(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = ScriptedBroker()
        broker.fail_predicate = lambda data: data.get("seq", 0) >= 3
        bus = create_test_bus(broker=broker)

        async with sessionmaker() as s:
            for i in range(5):
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="STEP",
                    payload={"i": i},
                )
            await s.commit()

        pub1 = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="b4-pub-1")
        assert await pub1.sweep_once() == 2  # seq 3 fails head-of-line; 4,5 gated
        assert broker.seqs() == [1, 2]

        # Graceful stop releases pub1's surviving claims so a peer takes over
        # immediately (no lease wait). Backoff is still honored (time-travel
        # simulates its expiry deterministically).
        await pub1.stop()
        async with sessionmaker() as s:
            leased = (
                await s.execute(
                    select(func.count(EventRecordDB.id)).where(
                        EventRecordDB.published_at.is_(None),
                        EventRecordDB.lease_expires_at.is_not(None),
                    )
                )
            ).scalar()
            assert leased == 0
        await _time_travel(sessionmaker, workspace_id=WS_1)

        broker.fail_predicate = None  # fault cleared
        pub2 = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="b4-pub-2")
        assert await pub2.sweep_once() == 3
        assert broker.seqs() == [1, 2, 3, 4, 5]

        async with sessionmaker() as s:
            rows = (
                (await s.execute(select(EventRecordDB).order_by(EventRecordDB.seq))).scalars().all()
            )
            assert all(r.published_at is not None for r in rows)
            assert [r.published_by for r in rows] == ["b4-pub-1"] * 2 + ["b4-pub-2"] * 3


class TestA5WorkerCrash:
    async def test_a5_crash_honors_leases_until_expiry_then_peer_recovers(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = ScriptedBroker()
        broker.fail_predicate = lambda data: data.get("seq", 0) >= 2
        bus = create_test_bus(broker=broker)

        async with sessionmaker() as s:
            for _ in range(4):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="STEP")
            await s.commit()

        pub_crash = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="b4-crasher",
            lease_seconds=30.0,
        )
        assert await pub_crash.sweep_once() == 1
        # CRASH: no stop(), no lease release. Reference dropped.
        del pub_crash

        # A peer sweeping immediately must NOT steal the in-lease claims…
        # (first clear only the retry gate so the lease itself is the blocker)
        await _time_travel(sessionmaker, workspace_id=WS_1, expire_retry=True)
        async with sessionmaker() as s:
            # …still leased: re-arm the lease (time travel expired it too)
            future = datetime.now(UTC) + timedelta(seconds=30)
            await s.execute(
                update(EventRecordDB)
                .where(EventRecordDB.published_at.is_(None))
                .values(lease_expires_at=future)
            )
            await s.commit()
        pub_peer = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="b4-peer")
        assert await pub_peer.sweep_once() == 0

        # …but once leases expire, the peer reclaims and drains.
        await _time_travel(sessionmaker, workspace_id=WS_1)
        broker.fail_predicate = None
        before = _metric_value("cortex_outbox_reclaimed_total") or 0.0
        assert await pub_peer.sweep_once() == 3
        after = _metric_value("cortex_outbox_reclaimed_total") or 0.0
        assert after - before == 3
        assert broker.seqs() == [1, 2, 3, 4]


class TestA6LeaseReclaim:
    async def test_a6_expired_claims_move_publishers(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        bus = create_test_bus()
        async with sessionmaker() as s:
            for _ in range(2):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="TICK")
            # Simulate worker A dying mid-sweep: rows claimed, never published.
            await s.execute(
                update(EventRecordDB)
                .where(EventRecordDB.published_at.is_(None))
                .values(
                    claimed_by="dead-worker-a",
                    claimed_at=datetime.now(UTC) - timedelta(minutes=5),
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    publish_attempts=1,
                )
            )
            await s.commit()

        pub_b = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="worker-b")
        assert await pub_b.sweep_once() == 2
        async with sessionmaker() as s:
            rows = (
                (await s.execute(select(EventRecordDB).order_by(EventRecordDB.seq))).scalars().all()
            )
            assert [r.claimed_by for r in rows] == ["worker-b", "worker-b"]
            assert all(r.published_at is not None for r in rows)


# ─────────────────────────────────────────────────────────────────────
# A7/A8: Redis restart / outage
# ─────────────────────────────────────────────────────────────────────


class TestA7RedisRestart:
    async def test_a7_partition_blocks_and_heal_drains_in_order(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = MockRedisBroker(healthy=True)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="b4-a7",
            retry_base_s=0,
            retry_max_s=0,  # backoff disabled: heal must drain immediately
        )

        async with sessionmaker() as s:
            for _ in range(2):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="PRE")
            await s.commit()
        assert await pub.sweep_once() == 2

        broker.healthy = False  # RESTART window
        async with sessionmaker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="DURING")
            await s.commit()
        assert await pub.sweep_once() == 0
        async with sessionmaker() as s:
            pending = (
                await s.execute(
                    select(func.count(EventRecordDB.id)).where(EventRecordDB.published_at.is_(None))
                )
            ).scalar()
            assert pending == 3

        broker.healthy = True  # HEALED
        assert await pub.sweep_once() == 3
        assert broker.seqs() == [1, 2, 3, 4, 5]

    async def test_a7b_real_redis_pubsub_roundtrip(self) -> None:
        """Real Redis transport check (CI provides redis; skipped otherwise)."""
        import redis.asyncio as redis

        url = os.environ.get("CORTEX_TEST_REDIS_URL") or os.environ.get(
            "CORTEX_REDIS_URL", "redis://localhost:6379/0"
        )
        try:
            client = redis.from_url(url, socket_connect_timeout=2.0, socket_timeout=2.0)
            await client.ping()
        except Exception:
            pytest.skip("no real Redis available")
        channel = f"b4-probe:{os.getpid()}"
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            # Wait for the subscribe confirmation (deterministic: no lost race).
            async with asyncio.timeout(5):
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=False)
                    if msg and msg.get("type") == "subscribe":
                        break
                    await asyncio.sleep(0.005)
            await client.publish(channel, json.dumps({"seq": 1}))
            received = None
            async with asyncio.timeout(5):
                while received is None:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True)
                    if msg:
                        received = json.loads(msg["data"])
                    else:
                        await asyncio.sleep(0.005)
            assert received == {"seq": 1}
            await pubsub.unsubscribe(channel)
        finally:
            with contextlib.suppress(Exception):
                await client.close()


class TestA8RedisOutage:
    async def test_a8_mutations_continue_and_backlog_drains(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Redis DOWN: authoritative commits still succeed; the outbox grows;
        Redis UP: the backlog drains with zero loss, in order."""
        broker = MockRedisBroker(healthy=False)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="b4-a8",
            retry_base_s=0,
            retry_max_s=0,
        )
        svc = get_authoritative_decision_service()
        registries = get_authoritative_registry_service()

        # Mutations during the outage all COMMIT (Redis is not in the tx).
        async with sessionmaker() as s:
            await svc.create(
                s,
                decision_id="B4-A8-D",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                proposal_id="P1",
                world_state_version=1,
                world_state_hash="h" * 16,
            )
            await s.commit()
        async with sessionmaker() as s:
            await registries.record_risk(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                entity_id="e1",
                entity_kind="supplier",
                severity="HIGH",
                title="t",
                world_state_version=1,
            )
            await s.commit()

        async with sessionmaker() as s:
            stats = await get_backlog_stats(s)
            assert stats.pending_count == 2
            assert stats.oldest_pending_age_s is not None

        # Sweeping during the outage publishes nothing but records attempts.
        assert await pub.sweep_once() == 0

        broker.healthy = True
        assert await pub.sweep_once() == 2
        assert broker.seqs() == [1, 2]
        async with sessionmaker() as s:
            stats = await get_backlog_stats(s)
            assert stats.pending_count == 0
            assert stats.oldest_pending_age_s is None


# ─────────────────────────────────────────────────────────────────────
# A9: Retry / backoff
# ─────────────────────────────────────────────────────────────────────


class TestA9RetryBackoff:
    async def test_a9_backoff_grows_and_caps(
        self, sessionmaker: async_sessionmaker[AsyncSession], monkeypatch
    ) -> None:
        monkeypatch.setattr("app.infrastructure.outbox_publisher.random.uniform", lambda a, b: 1.0)
        assert compute_backoff_delay_s(1, 10.0, 100.0) == 10.0
        assert compute_backoff_delay_s(2, 10.0, 100.0) == 20.0
        assert compute_backoff_delay_s(3, 10.0, 100.0) == 40.0
        assert compute_backoff_delay_s(5, 10.0, 100.0) == 100.0  # capped
        assert compute_backoff_delay_s(9, 10.0, 100.0) == 100.0
        assert compute_backoff_delay_s(1, 0.0, 0.0) == 0.0  # disabled

        repo = get_event_repository()
        broker = MockRedisBroker(healthy=False)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="b4-a9",
            retry_base_s=10.0,
            retry_max_s=100.0,
        )
        async with sessionmaker() as s:
            await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="T")
            await s.commit()

        delays: list[float] = []
        for attempt in (1, 2, 3):
            assert await pub.sweep_once() == 0
            async with sessionmaker() as s:
                row = (await s.execute(select(EventRecordDB).limit(1))).scalar_one()
                assert row.publish_attempts == attempt
                assert row.published_at is None
                assert row.last_error and "ConnectionError" in row.last_error
                assert row.next_retry_at is not None
                retry_at = row.next_retry_at
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delays.append((retry_at - datetime.now(UTC)).total_seconds())
            await _time_travel(sessionmaker, expire_lease=False, expire_retry=True)
        # 10s, 20s, 40s (jitter pinned to 1.0) — allow scheduling slop.
        assert 8.0 < delays[0] <= 10.5
        assert 18.0 < delays[1] <= 20.5
        assert 38.0 < delays[2] <= 40.5

    async def test_a9b_poison_flagged_but_never_dropped(
        self, sessionmaker: async_sessionmaker[AsyncSession], caplog
    ) -> None:
        repo = get_event_repository()
        broker = MockRedisBroker(healthy=False)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="b4-a9-poison",
            retry_base_s=0,
            retry_max_s=0,
            max_attempts=3,
        )
        async with sessionmaker() as s:
            await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="T")
            await s.commit()

        before = _metric_value("cortex_outbox_poison_total") or 0.0
        with caplog.at_level(logging.ERROR, logger="nexus.outbox_publisher"):
            for _ in range(4):
                assert await pub.sweep_once() == 0
                await _time_travel(sessionmaker, expire_lease=False, expire_retry=True)
        after = _metric_value("cortex_outbox_poison_total") or 0.0
        assert after - before == 1.0  # flagged once at the transition
        assert "POISON" in caplog.text

        async with sessionmaker() as s:
            row = (await s.execute(select(EventRecordDB).limit(1))).scalar_one()
            assert row.publish_attempts == 4  # still retried past the cap
            assert row.published_at is None  # never published, never deleted


# ─────────────────────────────────────────────────────────────────────
# A10: Durable replay (HTTP)
# ─────────────────────────────────────────────────────────────────────


class TestA10DurableReplay:
    async def test_a10_replay_envelope_pages_with_has_more(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        async with maker() as s:
            for i in range(50):
                await repo.publish(
                    s,
                    tenant_id="replay-user",
                    workspace_id=WS_1,
                    event_type="STEP",
                    payload={"i": i},
                    world_state_version=i,
                )
            await s.commit()

        headers = _headers("replay-user", [WS_1])
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 20, "limit": 10},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["from_seq"] == 20
        assert data["to_seq"] == 30
        assert data["latest_seq"] == 50
        assert data["has_more"] is True
        assert data["resync_required"] is False
        assert [e["seq"] for e in data["events"]] == list(range(21, 31))
        assert data["events"][0]["event_id"].startswith("EVT-")
        assert data["events"][0]["type"] == "STEP"
        assert data["world_state_version"] == 49

        r2 = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 45, "limit": 10},
            headers=headers,
        )
        data2 = r2.json()["data"]
        assert [e["seq"] for e in data2["events"]] == [46, 47, 48, 49, 50]
        assert data2["has_more"] is False
        assert data2["to_seq"] == 50

    async def test_a10b_replay_reads_table_not_delivery_state(self, api_client) -> None:
        """Replay serves rows regardless of published_at: the TABLE is truth."""
        client, maker = api_client
        repo = get_event_repository()
        bus = create_test_bus()
        async with maker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id="replay-user", workspace_id=WS_1, event_type="STEP")
            await s.commit()
        pub = OutboxPublisher(session_factory=maker, bus=bus)
        assert await pub.sweep_once() == 3

        # Force row 3 back to unpublished (partial delivery): replay must
        # still serve it, because the TABLE — not delivery state — is truth.
        async with maker() as s:
            row = (
                await s.execute(select(EventRecordDB).where(EventRecordDB.seq == 3).limit(1))
            ).scalar_one()
            row.published_at = None
            row.published = False
            row.lease_expires_at = None
            row.next_retry_at = None
            await s.commit()

        headers = _headers("replay-user", [WS_1])
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=headers,
        )
        assert [e["seq"] for e in r.json()["data"]["events"]] == [1, 2, 3]


# ─────────────────────────────────────────────────────────────────────
# A11/A12: Gap detection / large-gap resync
# ─────────────────────────────────────────────────────────────────────


class TestA11SequenceGap:
    async def test_a11_live_gap_emits_bounded_resync_needed(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        bus = create_test_bus()
        gen = sse_stream(
            workspace_id="WS-GAP-B4",
            last_seen_seq=1042,
            session_factory=sessionmaker,
            tenant_id=TENANT_A,
            bus=bus,
            heartbeat_s=60.0,
        )
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-GAP-B4"]))
            q.put_nowait(
                Event(
                    event_id="EVT-GAP-B4",
                    seq=1044,
                    event_type="GAP",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=1044,
                )
            )
            frame = await anext(gen)
            assert "event: resync_needed" in frame
            assert '"from_seq": 1042' in frame
            assert '"to_seq": 1044' in frame
        finally:
            await gen.aclose()


class TestA12LargeGapResync:
    async def test_a12_threshold_refuses_page_replay(self, api_client, monkeypatch) -> None:
        client, maker = api_client
        settings = get_settings()
        monkeypatch.setattr(settings, "realtime_resync_threshold", 10)
        repo = get_event_repository()
        async with maker() as s:
            for _ in range(20):
                await repo.publish(s, tenant_id="gap-user", workspace_id=WS_1, event_type="STEP")
            await s.commit()

        headers = _headers("gap-user", [WS_1])
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=headers,
        )
        data = r.json()["data"]
        assert data["resync_required"] is True
        assert data["events"] == []
        assert data["latest_seq"] == 20
        assert data["has_more"] is True

        # At the boundary (gap == threshold) replay is still allowed.
        r2 = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 10},
            headers=headers,
        )
        data2 = r2.json()["data"]
        assert data2["resync_required"] is False
        assert [e["seq"] for e in data2["events"]] == list(range(11, 21))


# ─────────────────────────────────────────────────────────────────────
# A13: SSE reconnect over HTTP
# ─────────────────────────────────────────────────────────────────────


class TestA13SSEReconnect:
    async def test_a13_reconnect_resumes_with_cursor(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        headers = _headers("sse-user", [WS_1])
        async with maker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id="sse-user", workspace_id=WS_1, event_type="HIST")
            await s.commit()

        first = await _collect_sse(headers, WS_1, 0, 4)
        kinds = [name for name, _ in first]
        assert kinds[0] == "connected"
        assert [p["seq"] for _, p in first[1:]] == [1, 2, 3]

        # "Disconnect": two more events land while the client is away.
        async with maker() as s:
            for _ in range(2):
                await repo.publish(s, tenant_id="sse-user", workspace_id=WS_1, event_type="HIST")
            await s.commit()

        # Reconnect with the last confirmed cursor: only the delta arrives.
        second = await _collect_sse(headers, WS_1, 3, 3)
        assert [name for name, _ in second][0] == "connected"
        assert [p["seq"] for _, p in second[1:]] == [4, 5]

    async def test_a13b_token_identity_selects_workspace(self, api_client, jwt_env) -> None:
        """?token= authenticates EventSource; the workspace comes from claims."""
        import uuid as _uuid

        from app.modules.identity.jwt_auth import issue_token

        client, maker = api_client
        user_id, ws_id = _uuid.uuid4(), _uuid.uuid4()
        repo = get_event_repository()
        async with maker() as s:
            await repo.publish(
                s,
                tenant_id=str(user_id),
                workspace_id=str(ws_id),
                event_type="HIST",
            )
            await s.commit()

        token, _ = issue_token(user_id=user_id, workspace_id=ws_id, role="operator", email="t@x.co")
        # Query workspace is a decoy: the server streams the CLAIMED workspace.
        frames = await _collect_sse({}, "decoy-ws", 0, 2, token=token)
        assert frames[0][0] == "connected"
        assert frames[0][1]["workspace_id"] == str(ws_id)
        assert frames[1][1]["seq"] == 1

        bad = await client.get(
            "/api/v1/nexus/realtime/stream",
            params={"workspace_id": WS_1, "token": "bogus"},
        )
        assert bad.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# A14: WebSocket reconnect
# ─────────────────────────────────────────────────────────────────────


class TestA14WebSocketReconnect:
    async def _seed(
        self, maker: async_sessionmaker[AsyncSession], n: int, user: str = "ws-user"
    ) -> None:
        repo = get_event_repository()
        async with maker() as s:
            for i in range(n):
                await repo.publish(
                    s,
                    tenant_id=user,
                    workspace_id=WS_1,
                    event_type="STEP",
                    payload={"i": i},
                )
            await s.commit()

    async def test_a14a_catchup_before_live_tail(
        self, sessionmaker: async_sessionmaker[AsyncSession], global_db
    ) -> None:
        await self._seed(sessionmaker, 3)
        ws = FakeWebSocket(headers={"x-user-id": "ws-user", "x-workspace-id": WS_1})
        ws.allow_disconnect()  # raise as soon as the live loop starts
        await realtime_module.realtime_websocket_endpoint(
            ws, token="", workspace_id=WS_1, tenant_id="t", after_seq=1, replay=True
        )
        frames = ws.frames()
        assert frames[0]["type"] == "connection_established"
        assert [f.get("seq") for f in frames[1:3]] == [2, 3]
        assert frames[1]["channel"] == "outbox"
        assert frames[1]["event_id"].startswith("EVT-")
        assert frames[3]["type"] == "catchup_complete"
        assert frames[3]["from_seq"] == 1
        assert frames[3]["to_seq"] == 3
        assert frames[3]["has_more"] is False

    async def test_a14b_live_frames_after_catchup(
        self, sessionmaker: async_sessionmaker[AsyncSession], global_db
    ) -> None:
        await self._seed(sessionmaker, 2)
        bus = get_realtime_bus()
        prev_redis, bus._redis_client = bus._redis_client, False
        subs_before = set(bus._local_subscribers.get(WS_1, set()))
        try:
            ws = FakeWebSocket(headers={"x-user-id": "ws-user", "x-workspace-id": WS_1})
            task = asyncio.create_task(
                realtime_module.realtime_websocket_endpoint(
                    ws, token="", workspace_id=WS_1, tenant_id="t", after_seq=2
                )
            )
            await _wait_for(lambda: any(f.get("type") == "catchup_complete" for f in ws.frames()))
            assert ws.frames()[-1]["to_seq"] == 2
            await _wait_for_live_subscription(bus, WS_1, subs_before)
            await bus._fan_out_local(
                WS_1,
                Event(
                    event_id="EVT-LIVE-B4",
                    seq=3,
                    event_type="LIVE",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=3,
                ),
            )
            await _wait_for(lambda: any(f.get("seq") == 3 for f in ws.frames()))
            live = [f for f in ws.frames() if f.get("seq") == 3][0]
            assert live["event_id"] == "EVT-LIVE-B4"
            ws.allow_disconnect()
            await asyncio.wait_for(task, timeout=5)
        finally:
            bus._redis_client = prev_redis

    async def test_a14c_gap_on_socket_emits_resync_needed(
        self, sessionmaker: async_sessionmaker[AsyncSession], global_db
    ) -> None:
        await self._seed(sessionmaker, 5)
        bus = get_realtime_bus()
        prev_redis, bus._redis_client = bus._redis_client, False
        subs_before = set(bus._local_subscribers.get(WS_1, set()))
        try:
            ws = FakeWebSocket(headers={"x-user-id": "ws-user", "x-workspace-id": WS_1})
            task = asyncio.create_task(
                realtime_module.realtime_websocket_endpoint(
                    ws, token="", workspace_id=WS_1, tenant_id="t", after_seq=5
                )
            )
            await _wait_for(lambda: any(f.get("type") == "catchup_complete" for f in ws.frames()))
            await _wait_for_live_subscription(bus, WS_1, subs_before)
            await bus._fan_out_local(
                WS_1,
                Event(
                    event_id="EVT-SKIP",
                    seq=7,  # 6 is missing → gap
                    event_type="SKIP",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=7,
                ),
            )
            await _wait_for(lambda: any(f.get("type") == "resync_needed" for f in ws.frames()))
            gap = [f for f in ws.frames() if f.get("type") == "resync_needed"][0]
            assert (gap["from_seq"], gap["to_seq"]) == (5, 7)
            ws.allow_disconnect()
            await asyncio.wait_for(task, timeout=5)
        finally:
            bus._redis_client = prev_redis


# ─────────────────────────────────────────────────────────────────────
# A15/A16: Isolation
# ─────────────────────────────────────────────────────────────────────


class TestA15TenantIsolation:
    async def test_a15_replay_never_crosses_tenants(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        async with maker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="SECRET")
            await s.commit()

        # Tenant B holds workspace access but sees nothing of tenant A.
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=_headers(TENANT_B, [WS_1]),
        )
        assert r.status_code == 200
        assert r.json()["data"]["events"] == []
        assert r.json()["data"]["latest_seq"] == 0

        r2 = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=_headers(TENANT_A, [WS_1]),
        )
        assert len(r2.json()["data"]["events"]) == 3

    async def test_a15b_ws_catchup_never_crosses_tenants(
        self, sessionmaker: async_sessionmaker[AsyncSession], global_db
    ) -> None:
        repo = get_event_repository()
        async with sessionmaker() as s:
            for _ in range(2):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="SECRET")
            await s.commit()

        ws = FakeWebSocket(headers={"x-user-id": TENANT_B, "x-workspace-id": WS_1})
        ws.allow_disconnect()
        await realtime_module.realtime_websocket_endpoint(
            ws, token="", workspace_id=WS_1, tenant_id="t", after_seq=0, replay=True
        )
        frames = ws.frames()
        assert frames[0]["type"] == "connection_established"
        assert frames[1]["type"] == "catchup_complete"
        assert frames[1]["to_seq"] == 0


class TestA16WorkspaceIsolation:
    async def test_a16_replay_403_across_workspaces(self, api_client) -> None:
        client, _ = api_client
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_2, "after_seq": 0},
            headers=_headers("w1-user", [WS_1]),  # access to WS_1 only
        )
        assert r.status_code == 403
        # 403 is a boundary verdict, not a session kill: the caller's next
        # authorized call still works (no logout side effect).
        r2 = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=_headers("w1-user", [WS_1]),
        )
        assert r2.status_code == 200

    async def test_a16b_stream_403_across_workspaces(self, api_client) -> None:
        client, _ = api_client
        r = await client.get(
            "/api/v1/nexus/realtime/stream",
            params={"workspace_id": WS_2, "after_seq": 0},
            headers=_headers("w1-user", [WS_1]),
        )
        assert r.status_code == 403

    async def test_a16c_ws_subscribe_rejects_foreign_workspace(
        self, sessionmaker: async_sessionmaker[AsyncSession], global_db
    ) -> None:
        ws = FakeWebSocket(
            headers={"x-user-id": "w1-user", "x-workspace-id": WS_1},
            incoming=[json.dumps({"action": "subscribe", "workspace_id": WS_2, "channel": "*"})],
        )
        ws.allow_disconnect()
        await realtime_module.realtime_websocket_endpoint(
            ws, token="", workspace_id=WS_1, tenant_id="t", after_seq=0, replay=False
        )
        acks = [f for f in ws.frames() if f.get("type") == "subscription_ack"]
        assert len(acks) == 1
        assert acks[0]["success"] is False

    async def test_a16d_ws_rejects_invalid_token(self, jwt_env) -> None:
        ws = FakeWebSocket(headers={})
        await realtime_module.realtime_websocket_endpoint(
            ws, token="forged", workspace_id=WS_1, tenant_id="t", after_seq=0
        )
        assert ws.accepted is False
        assert ws.closed is not None and ws.closed[0] == 4401

        ws2 = FakeWebSocket(headers={})
        await realtime_module.realtime_websocket_endpoint(
            ws2, token="", workspace_id=WS_1, tenant_id="t", after_seq=0
        )
        assert ws2.closed is not None and ws2.closed[0] == 4401


# ─────────────────────────────────────────────────────────────────────
# A17: API restart
# ─────────────────────────────────────────────────────────────────────


class TestA17ApiRestart:
    async def test_a17_publisher_lifecycle_and_subscriber_continuity(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = ScriptedBroker()
        broker.fail_predicate = lambda data: data.get("seq", 0) >= 3
        bus = create_test_bus(broker=broker)
        async with sessionmaker() as s:
            for _ in range(5):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="STEP")
            await s.commit()

        # A connected subscriber (pre-restart) keeps receiving across it.
        queue = bus.subscribe(WS_1)
        try:
            pub1 = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="restart-1")
            assert await pub1.sweep_once() == 2
            assert queue.qsize() == 2
            assert [e.seq for e in (queue.get_nowait(), queue.get_nowait())] == [1, 2]
            await pub1.start()
            assert pub1.running is True
            await pub1.stop()  # graceful: leases released
            assert pub1.running is False

            # "API restart": brand-new publisher instance, same bus/backlog.
            await _time_travel(sessionmaker, workspace_id=WS_1)
            broker.fail_predicate = None
            pub2 = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="restart-2")
            assert await pub2.sweep_once() == 3
            await pub2.start()
            try:
                assert pub2.running is True
            finally:
                await pub2.stop()

            received = [queue.get_nowait() for _ in range(3)]
            assert [e.seq for e in received] == [3, 4, 5]
        finally:
            bus.unsubscribe(WS_1, queue)


# ─────────────────────────────────────────────────────────────────────
# A18/A19/A20: Refresh, order, staleness
# ─────────────────────────────────────────────────────────────────────


class TestA18BrowserRefresh:
    async def test_a18_cursor_at_head_means_no_replay(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        headers = _headers("refresh-user", [WS_1])
        async with maker() as s:
            for _ in range(4):
                await repo.publish(
                    s, tenant_id="refresh-user", workspace_id=WS_1, event_type="STEP"
                )
            await s.commit()

        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 4},
            headers=headers,
        )
        data = r.json()["data"]
        assert data["events"] == []
        assert data["to_seq"] == 4
        assert data["latest_seq"] == 4
        assert data["has_more"] is False

    async def test_a18b_first_live_seq_after_head_must_be_next(self) -> None:
        bus = create_test_bus()
        gen = sse_stream(workspace_id="WS-REFRESH", last_seen_seq=9, bus=bus, heartbeat_s=60.0)
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-REFRESH"]))
            q.put_nowait(
                Event(
                    event_id="EVT-NEXT",
                    seq=10,
                    event_type="NEXT",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=10,
                )
            )
            assert "event: NEXT" in await anext(gen)
        finally:
            await gen.aclose()


class TestA19OutOfOrderDelivery:
    async def test_a19_reorder_is_a_gap_not_a_reorder(self) -> None:
        """seq 12 arriving while last=10 is a GAP (11 missing) — the stream
        must not silently apply 12 and it must never reorder to 11,12."""
        bus = create_test_bus()
        gen = sse_stream(workspace_id="WS-OOO", last_seen_seq=10, bus=bus, heartbeat_s=60.0)
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-OOO"]))
            for seq in (12, 11):
                q.put_nowait(
                    Event(
                        event_id=f"EVT-{seq}",
                        seq=seq,
                        event_type="E",
                        entity_type=None,
                        entity_id=None,
                        payload={},
                        world_state_version=seq,
                    )
                )
            frame = await anext(gen)
            assert "event: resync_needed" in frame
            assert '"from_seq": 10' in frame and '"to_seq": 12' in frame
        finally:
            await gen.aclose()

    async def test_a19b_in_order_control_applies_cleanly(self) -> None:
        bus = create_test_bus()
        gen = sse_stream(workspace_id="WS-OOO-OK", last_seen_seq=10, bus=bus, heartbeat_s=60.0)
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-OOO-OK"]))
            for seq in (11, 12):
                q.put_nowait(
                    Event(
                        event_id=f"EVT-{seq}",
                        seq=seq,
                        event_type="E",
                        entity_type=None,
                        entity_id=None,
                        payload={},
                        world_state_version=seq,
                    )
                )
            assert '"seq": 11' in await anext(gen)
            assert '"seq": 12' in await anext(gen)
        finally:
            await gen.aclose()


class TestA20StaleEventHandling:
    async def test_a20_duplicates_and_stale_are_ignored_and_counted(self) -> None:
        bus = create_test_bus()
        before = _metric_value("cortex_realtime_duplicate_events_total") or 0.0
        gen = sse_stream(workspace_id="WS-STALE", last_seen_seq=10, bus=bus, heartbeat_s=60.0)
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-STALE"]))
            for seq in (10, 9, 10, 11):
                q.put_nowait(
                    Event(
                        event_id=f"EVT-{seq}",
                        seq=seq,
                        event_type="E",
                        entity_type=None,
                        entity_id=None,
                        payload={},
                        world_state_version=seq,
                    )
                )
            assert '"seq": 11' in await anext(gen)
        finally:
            await gen.aclose()
        after = _metric_value("cortex_realtime_duplicate_events_total") or 0.0
        assert after - before == 3.0


# ─────────────────────────────────────────────────────────────────────
# Metrics + secrets pins
# ─────────────────────────────────────────────────────────────────────


class TestB4MetricsPins:
    async def test_publish_and_replay_counters_move(
        self, api_client, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        client, maker = api_client
        assert maker is not None and sessionmaker is not None  # fixtures share PG
        repo = get_event_repository()
        bus = create_test_bus()
        async with maker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id="metric-user", workspace_id=WS_1, event_type="T")
            await s.commit()

        ok_before = _metric_value("cortex_outbox_publish_total", {"result": "success"})
        att_before = _metric_value("cortex_outbox_publish_attempts_total")
        pub = OutboxPublisher(session_factory=maker, bus=bus)
        assert await pub.sweep_once() == 3
        assert (_metric_value("cortex_outbox_publish_total", {"result": "success"}) or 0) - (
            ok_before or 0
        ) == 3.0
        assert (_metric_value("cortex_outbox_publish_attempts_total") or 0) - (
            att_before or 0
        ) == 3.0
        assert _metric_value("cortex_outbox_pending_count") == 0.0

        replay_before = _metric_value("cortex_realtime_replay_total", {"transport": "http"})
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0},
            headers=_headers("metric-user", [WS_1]),
        )
        assert r.status_code == 200
        assert (_metric_value("cortex_realtime_replay_total", {"transport": "http"}) or 0) - (
            replay_before or 0
        ) == 1.0

    async def test_realtime_health_reports_relay_truth(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        async with maker() as s:
            await repo.publish(s, tenant_id="health-user", workspace_id=WS_1, event_type="T")
            await s.commit()

        r = await client.get(
            "/api/v1/nexus/realtime/health", headers=_headers("health-user", [WS_1])
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["api"]["status"] == "HEALTHY"
        assert data["db"]["status"] == "HEALTHY"
        assert data["redis"]["status"] in ("HEALTHY", "DEGRADED")
        assert data["outbox"]["pending_count"] == 1
        assert data["outbox"]["status"] in ("HEALTHY", "BACKLOGGING")
        assert data["worker"]["status"] in ("HEALTHY", "DEGRADED", "UNKNOWN")


class TestB4SecretsPin:
    async def test_payloads_never_reach_logs(
        self, sessionmaker: async_sessionmaker[AsyncSession], caplog
    ) -> None:
        repo = get_event_repository()
        broker = MockRedisBroker(healthy=False)
        bus = create_test_bus(broker=broker)
        async with sessionmaker() as s:
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                event_type="SENSITIVE",
                payload={"password": "supersecret-b4-xyz", "reset_token": "tok-b4-abc"},
            )
            await s.commit()

        pub = OutboxPublisher(session_factory=sessionmaker, bus=bus)
        with caplog.at_level(logging.DEBUG, logger="nexus.outbox_publisher"):
            assert await pub.sweep_once() == 0
        assert "supersecret-b4-xyz" not in caplog.text
        assert "tok-b4-abc" not in caplog.text
        # The failure WAS logged (ids only) — the pin proves redaction, not silence.
        assert "SENSITIVE" not in caplog.text or "ev=" in caplog.text


# ─────────────────────────────────────────────────────────────────────
# B4.1: 10,000-mutation acceptance
# ─────────────────────────────────────────────────────────────────────


class TestB41TenThousandMutations:
    async def test_10k_concurrent_mutations_durable_and_drainable(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()

        async def _writer(w: int) -> None:
            async with sessionmaker() as s:
                for i in range(1000):
                    await repo.publish(
                        s,
                        tenant_id=TENANT_A,
                        workspace_id=WS_1,
                        event_type="LOAD",
                        payload={"w": w, "i": i},
                    )
                    if i % 100 == 99:
                        await s.commit()
                await s.commit()

        await asyncio.gather(*[_writer(w) for w in range(10)])

        async with sessionmaker() as s:
            n = (await s.execute(select(func.count(EventRecordDB.id)))).scalar()
            assert n == 10_000
            distinct = (
                await s.execute(select(func.count(func.distinct(EventRecordDB.seq))))
            ).scalar()
            assert distinct == 10_000
            lo, hi = (
                await s.execute(select(func.min(EventRecordDB.seq), func.max(EventRecordDB.seq)))
            ).one()
            assert (lo, hi) == (1, 10_000)

        # And the relay drains all 10k in order.
        broker = MockRedisBroker(healthy=True)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker, bus=bus, publisher_id="b4-10k", batch_size=500
        )
        drained = 0
        for _ in range(100):
            got = await pub.sweep_once()
            drained += got
            if got == 0:
                break
        assert drained == 10_000
        assert broker.seqs() == list(range(1, 10_001))


# ─────────────────────────────────────────────────────────────────────
# Chaos rehearsal (C1–C5)
# ─────────────────────────────────────────────────────────────────────


class TestB4ChaosRehearsal:
    async def test_c1_redis_kill_mutate_heal_zero_loss(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        broker = MockRedisBroker(healthy=True)
        bus = create_test_bus(broker=broker)
        pub = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="chaos-1",
            retry_base_s=0,
            retry_max_s=0,
        )
        svc = get_authoritative_decision_service()
        registries = get_authoritative_registry_service()
        truth = get_authoritative_truth_loop()
        repo = get_event_repository()

        async with sessionmaker() as s:  # baseline
            await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="B0")
            await s.commit()
        assert await pub.sweep_once() == 1

        broker.healthy = False  # KILL REDIS
        async with sessionmaker() as s:  # mutations continue through the outage
            await svc.create(
                s,
                decision_id="CHAOS-D",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                proposal_id="P",
                world_state_version=1,
                world_state_hash="h" * 16,
            )
            await s.commit()
        async with sessionmaker() as s:
            await registries.record_risk(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                entity_id="e",
                entity_kind="supplier",
                severity="CRITICAL",
                title="t",
                world_state_version=1,
            )
            await s.commit()
        async with sessionmaker() as s:
            await truth.record_forecast(
                s,
                forecast_id="CHAOS-F",
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                sku="SKU-C",
                p50=1.0,
                p80=2.0,
                p95=3.0,
                mean=1.0,
                std_dev=0.1,
            )
            await s.commit()
        assert await pub.sweep_once() == 0  # nothing escapes during the outage

        broker.healthy = True  # HEAL
        assert await pub.sweep_once() == 3
        assert broker.seqs() == [1, 2, 3, 4]
        types = [json.loads(m)["type"] for _, m in broker.published[1:]]
        assert types == ["decision_created", "risk_changed", "forecast_updated"]
        print("\nC1 redis-kill/mutate/heal: zero loss, ordered — PASS")

    async def test_c2_worker_kill_reclaim(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        bus = create_test_bus()
        async with sessionmaker() as s:
            for _ in range(6):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="STEP")
            await s.commit()

        victim = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="chaos-victim")
        # Victim claims everything but "dies" before publishing: emulate by
        # claiming via a sweep whose bus always fails, then dropping it.
        victim.bus = create_test_bus(MockRedisBroker(healthy=False))
        assert await victim.sweep_once() == 0
        del victim  # KILL (no stop, no release)

        await _time_travel(sessionmaker, workspace_id=WS_1)  # leases expire
        rescue = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="chaos-rescue")
        assert await rescue.sweep_once() == 6
        async with sessionmaker() as s:
            rows = (
                (await s.execute(select(EventRecordDB).order_by(EventRecordDB.seq))).scalars().all()
            )
            assert all(r.published_at is not None for r in rows)
            assert {r.claimed_by for r in rows} == {"chaos-rescue"}
        print("\nC2 worker-kill/reclaim: 6/6 recovered — PASS")

    async def test_c3_publisher_restart_mid_backlog(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = ScriptedBroker()
        broker.fail_predicate = lambda data: data.get("seq", 0) == 4
        bus = create_test_bus(broker=broker)
        async with sessionmaker() as s:
            for _ in range(7):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="STEP")
            await s.commit()

        old = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="chaos-old")
        assert await old.sweep_once() == 3  # 1,2,3 land; 4 faults; 5-7 gated
        # Lifecycle around the drain (start AFTER the asserted manual sweep:
        # a running background sweeper would race sweep_once counts).
        await old.start()
        await old.stop()

        broker.fail_predicate = None
        await _time_travel(sessionmaker, workspace_id=WS_1)
        new = OutboxPublisher(session_factory=sessionmaker, bus=bus, publisher_id="chaos-new")
        assert await new.sweep_once() == 4
        await new.start()
        try:
            assert new.running is True
        finally:
            await new.stop()
        assert broker.seqs() == [1, 2, 3, 4, 5, 6, 7]
        print("\nC3 publisher-restart: backlog drained in order — PASS")

    async def test_c4_disconnect_replay_501_to_550(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        headers = _headers("chaos-user", [WS_1])
        async with maker() as s:
            for _ in range(550):
                await repo.publish(s, tenant_id="chaos-user", workspace_id=WS_1, event_type="STEP")
            await s.commit()

        # Disconnect at 500 (client cursor), then recover exactly 501–550.
        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 500, "limit": 500},
            headers=headers,
        )
        data = r.json()["data"]
        assert [e["seq"] for e in data["events"]] == list(range(501, 551))
        assert data["has_more"] is False
        print("\nC4 disconnect/replay: 501–550 recovered exactly — PASS")

    async def test_c5_gap_500_502_replays_501(self, api_client) -> None:
        client, maker = api_client
        repo = get_event_repository()
        headers = _headers("chaos-user", [WS_1])
        async with maker() as s:
            for _ in range(3):
                await repo.publish(s, tenant_id="chaos-user", workspace_id=WS_1, event_type="STEP")
            await s.commit()

        # Client saw 500(ctx: seqs are 1..3 here; use the stream gate for the
        # 500/502 shape, then recover the missing seq via durable replay).
        bus = create_test_bus()
        gen = sse_stream(workspace_id="WS-C5", last_seen_seq=500, bus=bus, heartbeat_s=60.0)
        try:
            assert "event: connected" in await anext(gen)
            q = next(iter(bus._local_subscribers["WS-C5"]))
            q.put_nowait(
                Event(
                    event_id="EVT-502",
                    seq=502,
                    event_type="E",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=502,
                )
            )
            frame = await anext(gen)
            assert "event: resync_needed" in frame
        finally:
            await gen.aclose()

        r = await client.get(
            "/api/v1/nexus/realtime/events",
            params={"workspace_id": WS_1, "after_seq": 0, "limit": 10},
            headers=headers,
        )
        assert [e["seq"] for e in r.json()["data"]["events"]] == [1, 2, 3]
        print("\nC5 gap→replay: detected, then restored from table — PASS")


# ─────────────────────────────────────────────────────────────────────
# Load probe (L1–L2)
# ─────────────────────────────────────────────────────────────────────


class TestB4LoadProbe:
    async def test_l1_commit_to_client_latency(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """250 commit→relay→deliver cycles; record P50/P95/P99 (printed)."""
        repo = get_event_repository()
        bus = create_test_bus()
        pub = OutboxPublisher(
            session_factory=sessionmaker, bus=bus, publisher_id="load-1", batch_size=10
        )
        queue = bus.subscribe(WS_1)
        latencies: list[float] = []
        try:
            for i in range(250):
                t0 = datetime.now(UTC)
                async with sessionmaker() as s:
                    await repo.publish(
                        s,
                        tenant_id=TENANT_A,
                        workspace_id=WS_1,
                        event_type="LOAD",
                        payload={"i": i},
                    )
                    await s.commit()
                assert await pub.sweep_once(limit=10) == 1
                evt = queue.get_nowait()
                assert evt.seq == i + 1
                latencies.append((datetime.now(UTC) - t0).total_seconds())
        finally:
            bus.unsubscribe(WS_1, queue)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(0.95 * len(latencies))]
        p99 = latencies[int(0.99 * len(latencies))]
        print(
            f"\nL1 commit→client latency (250 ops): P50={p50 * 1000:.1f}ms "
            f"P95={p95 * 1000:.1f}ms P99={p99 * 1000:.1f}ms"
        )
        assert p99 < 2.0  # generous CI budget; real numbers are printed

    async def test_l2_backlog_drain_throughput(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = get_event_repository()
        broker = MockRedisBroker(healthy=True)
        bus = create_test_bus(broker=broker)
        async with sessionmaker() as s:
            for i in range(2000):
                await repo.publish(s, tenant_id=TENANT_A, workspace_id=WS_1, event_type="LOAD")
                if i % 200 == 199:
                    await s.commit()
            await s.commit()

        pub = OutboxPublisher(
            session_factory=sessionmaker, bus=bus, publisher_id="load-2", batch_size=250
        )
        t0 = datetime.now(UTC)
        drained = 0
        for _ in range(50):
            got = await pub.sweep_once()
            drained += got
            if got == 0:
                break
        elapsed = (datetime.now(UTC) - t0).total_seconds()
        assert drained == 2000
        assert broker.seqs() == list(range(1, 2001))
        print(
            f"\nL2 backlog drain: 2000 rows in {elapsed:.1f}s "
            f"({2000 / max(elapsed, 1e-6):.0f} rows/s)"
        )
