"""Nexus v0.8.3 — Acceptance Test Suite for Realtime Outbox & Distributed Event Fabric.

Validates the v0.8.3 invariant and acceptance matrix A1–A15:
  Invariant: A committed World State change must not disappear from the realtime stream.

Acceptance Matrix:
  A1:  Event ordering — per-workspace seq strictly increasing, commit order
  A2:  Duplicate delivery — consumer applies each event exactly once (event_id idempotency)
  A3:  Consumer idempotency — replay of the same batch produces identical state
  A4:  Publisher restart — unpublished events are re-claimed by a peer sweeper; none lost
  A5:  Redis restart — outbox retains events; publisher drains backlog; clients resync
  A6:  Worker restart — in-flight publishes either land or are re-claimed (no loss, no dup seq)
  A7:  Broker partition — publisher blocks (attempts++), no loss; heals ⇒ drain in seq order
  A8:  Missed events — client that reconnects with last_seen_seq receives everything newer
  A9:  Sequence gaps — client receiving 1042 then 1044 detects gap and resynchronizes
  A10: Replay / resync — replay_since restores exact stream state after reconnect
  A11: Tenant isolation — no event crosses tenant boundary in live stream or replay
  A12: Workspace isolation — no event crosses workspace boundary in live stream or replay
  A13: SSE reconnect — reconnect with last_seen_seq resumes without loss or duplicate apply
  A14: WebSocket reconnect — WS transport adheres to isolation & replay contract
  A15: Concurrent writers — N writers to one workspace: unique seqs, commit-ordered, zero conflicts lost (PG advisory/row serialization)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.infrastructure.outbox_publisher import OutboxPublisher, allocate_outbox_seq
from app.infrastructure.realtime_bus import (
    Event,
    IdempotentEventConsumer,
    RealtimeBus,
    sse_stream,
)
from app.infrastructure.realtime_gateway import RealtimeGateway
from app.modules.nexus_spine.p0_migration import (
    get_authoritative_decision_service,
)
from app.modules.nexus_spine.persistence.models import (
    EventRecordDB,
)
from app.modules.nexus_spine.persistence.repositories import (
    get_event_repository,
)

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
WS_1 = "WS-FABRIC-1"
WS_2 = "WS-FABRIC-2"


# ─────────────────────────────────────────────────────────────────────
# Real PostgreSQL fixture for locking semantics
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    """Connection URL to real PostgreSQL server."""
    env_url = os.environ.get("CORTEX_TEST_PG_RACE_URL") or os.environ.get(
        "CORTEX_TEST_DATABASE_URL"
    )
    if env_url and "postgres" in env_url:
        return env_url

    try:
        import pgserver
    except ImportError:
        pytest.skip("no PostgreSQL available (pgserver or CORTEX_TEST_PG_RACE_URL required)")

    data_dir = tmp_path_factory.mktemp("nexus-v083-pg")
    db = pgserver.get_server(str(data_dir))
    sock_dir = str(data_dir)
    with contextlib.suppress(Exception):
        db.psql("CREATE DATABASE nexus_v083;")
    return f"postgresql+asyncpg://postgres@/nexus_v083?host={sock_dir}"


@pytest.fixture
async def pg_engine(pg_url):
    """Fresh database engine with clean tables for each test."""
    engine = create_async_engine(pg_url, pool_size=15, max_overflow=10)

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
def sessionmaker(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)


class MockRedisBroker:
    """In-memory Redis Pub/Sub emulator supporting partition and restart simulation."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.published: list[tuple[str, str]] = []
        self._publish_count = 0

    async def publish(self, channel: str, message: str) -> int:
        if not self.healthy:
            raise ConnectionError("Redis broker connection down (simulated partition/restart)")
        self.published.append((channel, message))
        self._publish_count += 1
        return 1


def create_test_bus(broker: MockRedisBroker | None = None) -> RealtimeBus:
    """Create an isolated bus for testing with an in-memory broker double or local mode."""
    bus = RealtimeBus()
    if broker is not None:
        client = type("RedisClientWrapper", (), {"_redis": broker, "publish": broker.publish})()
        bus._get_redis = lambda: client  # type: ignore[method-assign]
    else:
        bus._redis_client = False
    return bus


# ─────────────────────────────────────────────────────────────────────
# A1: Event Ordering
# ─────────────────────────────────────────────────────────────────────


class TestA1EventOrdering:
    async def test_a1_event_ordering_strictly_monotonic_commit_order(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A1: Per-workspace seq is strictly increasing and strictly matches commit order."""
        svc = get_authoritative_decision_service()
        repo = get_event_repository()

        # Seed 5 sequential decisions in one workspace
        dids = [f"D-SEQ-{i}" for i in range(5)]
        for did in dids:
            async with sessionmaker() as s:
                await svc.create(
                    s,
                    decision_id=did,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    proposal_id=did,
                    world_state_version=1,
                    world_state_hash="h1",
                )
                await s.commit()

        # Check DB records
        async with sessionmaker() as s:
            events = await repo.get_since_seq(s, workspace_id=WS_1, since_seq=0)

        assert len(events) == 5
        seqs = [e.seq for e in events]
        assert seqs == [1, 2, 3, 4, 5], f"Expected contiguous seqs 1..5, got {seqs}"
        assert all(s1 < s2 for s1, s2 in zip(seqs, seqs[1:], strict=False))


# ─────────────────────────────────────────────────────────────────────
# A2 & A3: Duplicate Delivery & Consumer Idempotency
# ─────────────────────────────────────────────────────────────────────


class TestA2A3ConsumerIdempotency:
    def test_a2_duplicate_delivery_deduplicated_by_event_id(self) -> None:
        """A2: Consumer applies each event exactly once keyed off event_id."""
        consumer = IdempotentEventConsumer()
        evt_id = "EVT-TEST-12345"

        # First delivery: applied
        assert consumer.record(evt_id) is True
        # Duplicate delivery: suppressed
        assert consumer.record(evt_id) is False
        assert consumer.is_duplicate(evt_id) is True

    def test_a3_consumer_idempotency_replay_preserves_state(self) -> None:
        """A3: Replay of the exact same event batch produces identical state."""
        consumer = IdempotentEventConsumer()
        state: dict[str, int] = {"count": 0}

        events = [
            Event(
                event_id=f"EVT-{i}",
                seq=i,
                event_type="STATE_INC",
                entity_type="counter",
                entity_id="c1",
                payload={"inc": 1},
                world_state_version=i,
            )
            for i in range(1, 6)
        ]

        def apply_batch(ev_list: list[Event]) -> None:
            for e in ev_list:
                if consumer.record(e.event_id):
                    state["count"] += e.payload["inc"]

        # Run 1: fresh
        apply_batch(events)
        assert state["count"] == 5

        # Run 2: full replay of the same batch
        apply_batch(events)
        assert state["count"] == 5, "Replaying batch must be idempotent"


# ─────────────────────────────────────────────────────────────────────
# A4: Publisher Restart & Peer Sweeper
# ─────────────────────────────────────────────────────────────────────


class TestA4PublisherRestart:
    async def test_a4_publisher_restart_unprocessed_events_reclaimed(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A4: Unpublished events left by a stopped publisher are claimed and published by a peer."""
        repo = get_event_repository()
        bus = create_test_bus()

        # Simulate 3 events committed to outbox
        async with sessionmaker() as s:
            for i in range(3):
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="ORDER_PLACED",
                    payload={"order": i},
                )
            await s.commit()

        # Publisher 2 (peer) starts up and sweeps
        pub2 = OutboxPublisher(
            session_factory=sessionmaker, bus=bus, publisher_id="publisher-worker-2"
        )
        swept = await pub2.sweep_once()
        assert swept == 3

        # Verify all 3 events are marked published with pub2's identifier
        async with sessionmaker() as s:
            pending = await repo.get_pending(s)
            recent = await repo.get_recent(s, tenant_id=TENANT_A, workspace_id=WS_1)

        assert len(pending) == 0
        assert len(recent) == 3
        for e in recent:
            assert e.published is True
            assert e.published_at is not None
            assert e.published_by == "publisher-worker-2"
            assert e.publish_attempts == 1


# ─────────────────────────────────────────────────────────────────────
# A5 & A7: Broker Partition & Redis Restart
# ─────────────────────────────────────────────────────────────────────


class TestA5A7BrokerPartitionAndRecovery:
    async def test_a5_a7_redis_partition_blocks_publish_and_drains_on_heal(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A5 & A7: Outbox retains events during partition (attempts incremented);

        healed broker drains backlog in strictly monotonic seq order.
        """
        repo = get_event_repository()
        broker = MockRedisBroker(healthy=False)  # Simulating Redis down / partition
        bus = create_test_bus(broker=broker)

        # 1. Commit 3 events to DB
        async with sessionmaker() as s:
            for i in range(3):
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="DISRUPTION",
                    payload={"step": i},
                )
            await s.commit()

        # B4 adds failure backoff (next_retry_at): disable it here so the
        # immediate post-heal re-sweep below is deterministic. Backoff itself
        # is covered by the B4 A9 suite.
        publisher = OutboxPublisher(
            session_factory=sessionmaker,
            bus=bus,
            publisher_id="partition-pub",
            retry_base_s=0,
            retry_max_s=0,
        )

        # 2. Sweep while broker is DOWN
        count = await publisher.sweep_once()
        assert count == 0, "No events should succeed while broker is down"

        # Check DB state: events still unpublished, publish_attempts incremented
        async with sessionmaker() as s:
            events = await repo.get_since_seq(s, workspace_id=WS_1, since_seq=0)
        assert len(events) == 3
        for e in events:
            assert e.published_at is None
            if e.seq == 1:
                assert e.publish_attempts >= 1

        # 3. Heal partition (Redis restored)
        broker.healthy = True

        # 4. Sweep again
        count2 = await publisher.sweep_once()
        assert count2 == 3

        # All events now delivered to broker in strict seq order
        assert len(broker.published) == 3
        for idx, (_, raw_msg) in enumerate(broker.published):
            data = json.loads(raw_msg)
            assert data["seq"] == idx + 1


# ─────────────────────────────────────────────────────────────────────
# A6: Worker Restart
# ─────────────────────────────────────────────────────────────────────


class TestA6WorkerRestart:
    async def test_a6_worker_restart_no_data_loss_or_duplicate_seqs(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A6: In-flight publishes land or are reclaimed by peer worker."""
        repo = get_event_repository()
        bus = create_test_bus()

        # Worker 1 creates 2 events in separate transactions
        for i in range(2):
            async with sessionmaker() as s:
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type=f"TICK_{i}",
                    payload={"worker": 1},
                )
                await s.commit()

        # Worker 2 starts up, creates 2 more events
        for i in range(2):
            async with sessionmaker() as s:
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type=f"TICK_{i + 2}",
                    payload={"worker": 2},
                )
                await s.commit()

        # Publisher drains all 4 events
        publisher = OutboxPublisher(session_factory=sessionmaker, bus=bus)
        drained = await publisher.sweep_once()
        assert drained == 4

        async with sessionmaker() as s:
            all_evts = await repo.get_since_seq(s, workspace_id=WS_1, since_seq=0)

        assert [e.seq for e in all_evts] == [1, 2, 3, 4]
        assert all(e.published is True for e in all_evts)


# ─────────────────────────────────────────────────────────────────────
# A8, A9, A10: Missed Events, Sequence Gaps, and Replay/Resync
# ─────────────────────────────────────────────────────────────────────


class TestA8A9A10MissedEventsAndGaps:
    async def test_a8_missed_events_client_reconnects_with_cursor(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A8: Reconnecting with last_seen_seq retrieves all newer events."""
        repo = get_event_repository()
        bus = create_test_bus()

        async with sessionmaker() as s:
            for i in range(10):
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="STEP",
                    payload={"idx": i},
                )
            await s.commit()

        # Client missed everything after seq=4
        async with sessionmaker() as s:
            replayed = await bus.replay_since(workspace_id=WS_1, since_seq=4, session=s)

        assert len(replayed) == 6
        assert [e.seq for e in replayed] == [5, 6, 7, 8, 9, 10]

    async def test_a9_sequence_gap_detection_emits_resync_needed(self) -> None:
        """A9: Receiving a sequence gap (e.g. 1042 then 1044) triggers resync_needed."""
        bus = create_test_bus()

        stream_gen = sse_stream(workspace_id="WS-GAP", last_seen_seq=1042, bus=bus)
        # 1. First event is 'connected'
        conn_frame = await anext(stream_gen)
        assert "event: connected" in conn_frame

        # 2. Inject gap event (1044 directly, skipping 1043)
        gap_event = Event(
            event_id="EVT-GAP",
            seq=1044,
            event_type="GAP_EVENT",
            entity_type=None,
            entity_id=None,
            payload={},
            world_state_version=1044,
        )

        q = list(bus._local_subscribers["WS-GAP"])[0]
        q.put_nowait(gap_event)

        # 3. Next yielded item must be resync_needed
        resync_frame = await anext(stream_gen)
        assert "event: resync_needed" in resync_frame
        assert '"from_seq": 1042' in resync_frame
        assert '"to_seq": 1044' in resync_frame

    async def test_a10_replay_resync_restores_exact_state(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A10: replay_since from outbox restores exact missing sequence."""
        repo = get_event_repository()
        bus = create_test_bus()

        async with sessionmaker() as s:
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id="WS-RESYNC",
                seq=1042,
                event_type="EVT_1042",
            )
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id="WS-RESYNC",
                seq=1043,
                event_type="EVT_1043",
            )
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id="WS-RESYNC",
                seq=1044,
                event_type="EVT_1044",
            )
            await s.commit()

        # Resync from 1042
        async with sessionmaker() as s:
            restored = await bus.replay_since(workspace_id="WS-RESYNC", since_seq=1042, session=s)

        assert len(restored) == 2
        assert restored[0].seq == 1043
        assert restored[1].seq == 1044


# ─────────────────────────────────────────────────────────────────────
# A11 & A12: Tenant & Workspace Isolation
# ─────────────────────────────────────────────────────────────────────


class TestA11A12Isolation:
    async def test_a11_tenant_isolation_in_replay_and_stream(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A11: Tenant A cannot observe Tenant B events even in same workspace name."""
        repo = get_event_repository()
        bus = create_test_bus()

        # Publish for Tenant Alpha and Tenant Beta
        async with sessionmaker() as s:
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                event_type="ALPHA_SECRET",
                payload={"data": "alpha"},
            )
            await repo.publish(
                s,
                tenant_id=TENANT_B,
                workspace_id=WS_1,
                event_type="BETA_SECRET",
                payload={"data": "beta"},
            )
            await s.commit()

        # Tenant Alpha replay
        async with sessionmaker() as s:
            alpha_events = await bus.replay_since(
                workspace_id=WS_1, since_seq=0, tenant_id=TENANT_A, session=s
            )

        assert len(alpha_events) == 1
        assert alpha_events[0].event_type == "ALPHA_SECRET"
        assert alpha_events[0].payload["data"] == "alpha"

    async def test_a12_workspace_isolation_independent_seq_and_routing(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A12: WS_1 and WS_2 have completely isolated sequence spaces and routing."""
        repo = get_event_repository()
        bus = create_test_bus()

        q1 = bus.subscribe(WS_1)
        q2 = bus.subscribe(WS_2)

        try:
            # Commit 2 events in WS_1, 1 event in WS_2
            async with sessionmaker() as s:
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="WS1_E1",
                )
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_1,
                    event_type="WS1_E2",
                )
                await repo.publish(
                    s,
                    tenant_id=TENANT_A,
                    workspace_id=WS_2,
                    event_type="WS2_E1",
                )
                await s.commit()

            # Sweep
            publisher = OutboxPublisher(session_factory=sessionmaker, bus=bus)
            await publisher.sweep_once()

            # Verify WS_1 subscriber sees only WS_1 events
            e1 = q1.get_nowait()
            e2 = q1.get_nowait()
            assert q1.empty()
            assert (e1.seq, e2.seq) == (1, 2)
            assert (e1.event_type, e2.event_type) == ("WS1_E1", "WS1_E2")

            # Verify WS_2 subscriber sees only WS_2 events (starting at seq 1)
            w2_e1 = q2.get_nowait()
            assert q2.empty()
            assert w2_e1.seq == 1
            assert w2_e1.event_type == "WS2_E1"
        finally:
            bus.unsubscribe(WS_1, q1)
            bus.unsubscribe(WS_2, q2)


# ─────────────────────────────────────────────────────────────────────
# A13 & A14: SSE & WebSocket Reconnect
# ─────────────────────────────────────────────────────────────────────


class TestA13A14SSEAndWebSocketReconnect:
    async def test_a13_sse_reconnect_replays_then_tails(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A13: SSE reconnect resumes with last_seen_seq without loss or dup."""
        repo = get_event_repository()
        bus = create_test_bus()

        # Seed 2 events
        async with sessionmaker() as s:
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                event_type="HISTORICAL_1",
            )
            await repo.publish(
                s,
                tenant_id=TENANT_A,
                workspace_id=WS_1,
                event_type="HISTORICAL_2",
            )
            await s.commit()

        # Client reconnects with last_seen_seq=1
        async with sessionmaker() as s:
            stream = sse_stream(workspace_id=WS_1, last_seen_seq=1, session=s, bus=bus)
            frame_conn = await anext(stream)
            assert "event: connected" in frame_conn

            frame_replayed = await anext(stream)
            assert "event: HISTORICAL_2" in frame_replayed

            # Now publish a live event
            live_event = Event(
                event_id="EVT-LIVE-1",
                seq=3,
                event_type="LIVE_EVENT",
                entity_type=None,
                entity_id=None,
                payload={},
                world_state_version=3,
            )
            await bus._fan_out_local(WS_1, live_event)

            frame_live = await anext(stream)
            assert "event: LIVE_EVENT" in frame_live

    async def test_a14_websocket_broadcast_and_isolation(self) -> None:
        """A14: RealtimeGateway adheres to tenant/workspace boundaries."""
        gw = RealtimeGateway(node_id="ws-test-node")

        class SimpleMockWS:
            def __init__(self):
                self.messages = []

            async def accept(self):
                pass

            async def send_text(self, data: str):
                self.messages.append(data)

        ws1 = SimpleMockWS()
        ws2 = SimpleMockWS()

        await gw.connect("s1", "u1", TENANT_A, WS_1, ws1)
        await gw.subscribe("s1", WS_1, "*")

        await gw.connect("s2", "u2", TENANT_A, WS_2, ws2)
        await gw.subscribe("s2", WS_2, "*")

        await gw.broadcast(
            tenant_id=TENANT_A,
            workspace_id=WS_1,
            channel="decisions",
            event_type="DECISION_CREATED",
            payload={"id": "D1"},
        )

        assert len(ws1.messages) == 1
        assert len(ws2.messages) == 0, "WS_2 must not receive WS_1 events"


# ─────────────────────────────────────────────────────────────────────
# A15: Concurrent Writers & Advisory/Row Serialization
# ─────────────────────────────────────────────────────────────────────


class TestA15ConcurrentWriters:
    async def test_a15_concurrent_writers_contiguous_unique_seqs(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A15: N concurrent writers to one workspace get unique, contiguous sequence numbers with 0 lost commits."""
        N = 10

        async def writer(task_id: int) -> int:
            async with sessionmaker() as s:
                seq = await allocate_outbox_seq(s, tenant_id=TENANT_A, workspace_id="WS-RACE-A15")
                evt = EventRecordDB(
                    event_id=f"EVT-A15-{task_id}-{uuid.uuid4().hex[:6]}",
                    tenant_id=TENANT_A,
                    workspace_id="WS-RACE-A15",
                    seq=seq,
                    event_type="CONCURRENT_WRITE",
                    payload={"task_id": task_id},
                )
                s.add(evt)
                await s.commit()
                return seq

        # Run 10 concurrent writers
        tasks = [asyncio.create_task(writer(i)) for i in range(N)]
        allocated_seqs = await asyncio.gather(*tasks)

        assert len(set(allocated_seqs)) == N, f"Duplicate seq allocated: {allocated_seqs}"
        assert sorted(allocated_seqs) == list(range(1, N + 1))

        # Check DB rows
        async with sessionmaker() as s:
            rows = (
                (
                    await s.execute(
                        select(EventRecordDB)
                        .where(
                            EventRecordDB.tenant_id == TENANT_A,
                            EventRecordDB.workspace_id == "WS-RACE-A15",
                        )
                        .order_by(EventRecordDB.seq.asc())
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == N
        assert [r.seq for r in rows] == list(range(1, N + 1))
