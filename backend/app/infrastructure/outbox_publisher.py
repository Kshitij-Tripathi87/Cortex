"""Nexus v0.8.3 — Realtime Outbox Publisher & SKIP LOCKED Sweeper.

Fulfills the invariant:
    A committed World State change must not disappear from the realtime stream.

Architecture:
    1. The DB transaction writes state mutations and outbox events together
       with in-transaction monotonic sequence numbers (allocated per workspace).
    2. OutboxPublisher publishes committed events to the fabric (Redis / local bus).
    3. Multi-worker safe via `FOR UPDATE SKIP LOCKED` sweeper:
       - No distributed locks needed
       - Peer workers re-claim orphaned events from crashed workers
       - Delivery is at-least-once, ordered per workspace by seq
       - Tracks publish_attempts, published_at, published_by for observability.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.realtime_bus import RealtimeBus, get_realtime_bus
from app.modules.nexus_spine.persistence.models import EventRecordDB

logger = logging.getLogger("nexus.outbox_publisher")


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def allocate_outbox_seq(
    session: AsyncSession,
    tenant_id: str,
    workspace_id: str,
) -> int:
    """Allocate the next monotonic sequence number for a workspace in-transaction.

    Uses a PostgreSQL advisory transaction lock keyed on (tenant_id, workspace_id)
    to serialize concurrent writers at the database layer, followed by
    SELECT COALESCE(MAX(seq), 0) + 1.
    """
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        from sqlalchemy import text

        lock_key = f"nexus_outbox:{tenant_id}:{workspace_id}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

    stmt = select(func.coalesce(func.max(EventRecordDB.seq), 0)).where(
        EventRecordDB.tenant_id == tenant_id,
        EventRecordDB.workspace_id == workspace_id,
    )
    result = await session.execute(stmt)
    max_seq = result.scalar() or 0
    return int(max_seq) + 1


class OutboxPublisher:
    """Publishes unpublished outbox events to the realtime fabric with peer sweep."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        bus: RealtimeBus | None = None,
        publisher_id: str | None = None,
        sweep_interval: float = 1.0,
        batch_size: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus or get_realtime_bus()
        self.publisher_id = publisher_id or f"pub-{uuid4().hex[:8]}"
        self.sweep_interval = sweep_interval
        self.batch_size = batch_size
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._notify_event = asyncio.Event()

    def set_session_factory(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    def trigger_publish(self) -> None:
        """Wake up the sweeper loop immediately."""
        self._notify_event.set()

    async def start(self) -> None:
        """Start background sweeper task."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop background sweeper task."""
        self.running = False
        self._notify_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run_loop(self) -> None:
        while self.running:
            try:
                await self.sweep_once(limit=self.batch_size)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("OutboxPublisher sweep loop error: %s", e)

            try:
                await asyncio.wait_for(self._notify_event.wait(), timeout=self.sweep_interval)
            except TimeoutError:
                pass
            finally:
                self._notify_event.clear()

    async def sweep_once(
        self,
        limit: int | None = None,
        workspace_id: str | None = None,
    ) -> int:
        """Execute one sweep pass to claim and publish unpublished outbox events.

        Uses FOR UPDATE SKIP LOCKED on PostgreSQL so multiple publishers
        safely partition work with zero duplicate processing or deadlocks.
        """
        if self.session_factory is None:
            return 0

        batch_limit = limit or self.batch_size
        published_count = 0

        async with self.session_factory() as session:
            stmt = select(EventRecordDB).where(EventRecordDB.published_at.is_(None))
            if workspace_id:
                stmt = stmt.where(EventRecordDB.workspace_id == workspace_id)

            stmt = stmt.order_by(EventRecordDB.workspace_id, EventRecordDB.seq).limit(batch_limit)

            bind = session.bind
            if bind is not None and bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)

            result = await session.execute(stmt)
            events = list(result.scalars().all())

            if not events:
                return 0

            # Group events by workspace to maintain strict sequential ordering per workspace
            ws_events: dict[str, list[EventRecordDB]] = defaultdict(list)
            for evt in events:
                ws_events[evt.workspace_id].append(evt)

            for _ws, ev_list in ws_events.items():
                # Sort ascending by seq
                ev_list.sort(key=lambda e: e.seq)
                failed_for_ws = False

                for evt in ev_list:
                    if failed_for_ws:
                        # Stop processing further events for this workspace in this batch
                        # to avoid out-of-order publication
                        break

                    evt.publish_attempts += 1
                    evt.published_by = self.publisher_id

                    try:
                        await self.bus.publish_from_outbox(evt)
                        evt.published_at = _utc_now()
                        evt.published = True
                        published_count += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to publish outbox event %s (workspace %s, seq %s): %s",
                            evt.event_id,
                            evt.workspace_id,
                            evt.seq,
                            e,
                        )
                        failed_for_ws = True

            await session.commit()

        return published_count


_singleton_publisher: OutboxPublisher | None = None


def get_outbox_publisher(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    bus: RealtimeBus | None = None,
) -> OutboxPublisher:
    global _singleton_publisher
    if _singleton_publisher is None:
        _singleton_publisher = OutboxPublisher(
            session_factory=session_factory,
            bus=bus,
        )
    elif session_factory is not None:
        _singleton_publisher.set_session_factory(session_factory)
    return _singleton_publisher
