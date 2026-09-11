"""Nexus v0.8.3+ — Realtime Outbox Publisher (B4 launch reliability).

Fulfills the invariant:
    A committed World State change must not disappear from the realtime stream.

Pipeline:
    1. The DB transaction writes state mutations and outbox events together
       with in-transaction monotonic sequence numbers (``allocate_outbox_seq``).
    2. After commit, the endpoint calls ``commit_and_notify`` (fast path):
       the sweeper loop wakes immediately and attempts delivery.
    3. The sweeper is the durable backstop: every ``sweep_interval`` it claims
       due rows and publishes them. Fast path improves latency; the sweeper
       guarantees recovery.

Two-phase sweep (crash-safe, multi-worker safe):
    Phase 1 — CLAIM: select due rows
        ``published_at IS NULL``
        ``AND (lease_expires_at IS NULL OR lease_expires_at <= now)``
        ``AND (next_retry_at IS NULL OR next_retry_at <= now)``
        ordered by (workspace, seq), ``FOR UPDATE SKIP LOCKED`` on PG;
        stamp ``claimed_by/at`` + ``lease_expires_at``; commit.
    Phase 2 — PUBLISH: re-select own claims in (workspace, seq) order and
        publish strictly in order per workspace (Redis may fail; the bus
        raises so the attempt is recorded). Success marks ``published_at``;
        failure records ``last_error`` + ``next_retry_at`` with exponential
        backoff + jitter and gates the workspace tail behind the same retry
        time (head-of-line order preservation across sweep passes AND
        across publishers).

Ordering across concurrent publishers:
    A workspace's unpublished rows are published by at most one publisher at
    a time, enforced by a per-workspace PG advisory session lock
    (``pg_try_advisory_lock``; non-blocking — a contended workspace is simply
    skipped this pass). Without this, two sweepers could interleave seqs on
    the wire. Non-PG dialects fall back to a process-local asyncio guard
    (single-process dev/test use only).

Delivery is at-least-once, ordered per workspace by seq. Consumers deduplicate
by ``event_id`` and validate ``seq`` continuity (gap → replay/resync).
Rows are NEVER deleted by the relay; ``published_at IS NULL`` is the single
source of "still needs delivery". A poison row (attempts >= max_attempts) is
loudly metriced but still retried with capped backoff — never dropped,
never skipped (order is preserved over latency, always).

Logging discipline: log ids only (tenant/workspace/event_id/seq/attempt).
Event payloads are NEVER logged (B4 secrets pin).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.infrastructure.realtime_bus import RealtimeBus, get_realtime_bus
from app.modules.nexus_spine.persistence.models import EventRecordDB

logger = logging.getLogger("nexus.outbox_publisher")

_SEQ_LOCK_KEY_PREFIX = "nexus_outbox:"  # + tenant:workspace (allocation)
_PUB_LOCK_KEY_PREFIX = "nexus_outbox_pub:"  # + tenant:workspace (publish exclusion)

# Process-local fallback exclusion for non-PG dialects (sqlite dev/test).
_ws_guards: dict[str, asyncio.Lock] = {}
_ws_guards_lock = asyncio.Lock()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_postgres(session: AsyncSession) -> bool:
    bind = session.bind
    return bind is not None and bind.dialect.name == "postgresql"


async def allocate_outbox_seq(
    session: AsyncSession,
    tenant_id: str,
    workspace_id: str,
) -> int:
    """Allocate the next monotonic sequence number for a workspace in-transaction.

    Uses a PostgreSQL advisory transaction lock keyed on (tenant_id, workspace_id)
    to serialize concurrent writers at the database layer, followed by
    SELECT COALESCE(MAX(seq), 0) + 1. The UNIQUE(tenant, workspace, seq)
    constraint is the backstop: any race the lock misses fails loudly here,
    inside the writer's transaction, instead of corrupting the stream.
    """
    if _is_postgres(session):
        lock_key = f"{_SEQ_LOCK_KEY_PREFIX}{tenant_id}:{workspace_id}"
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


def compute_backoff_delay_s(attempts: int, base_s: float, max_s: float) -> float:
    """Exponential backoff with jitter for a failed publish attempt.

    ``attempts`` is the 1-based attempt count that just failed. Returns
    ``min(base * 2**(attempts-1), max)`` scaled by U[0.5, 1.5) jitter.
    ``base_s <= 0`` disables backoff (retry immediately due).
    """
    if base_s <= 0:
        return 0.0
    grown = base_s * (2 ** max(0, attempts - 1))
    capped = min(grown, max_s) if max_s > 0 else grown
    # Non-cryptographic jitter for retry spreading (thundering-herd avoidance).
    return float(capped * random.uniform(0.5, 1.5))  # noqa: S311


@dataclass(frozen=True)
class OutboxBacklogStats:
    pending_count: int
    oldest_pending_age_s: float | None
    oldest_event_id: str | None = None


class OutboxPublisher:
    """Publishes unpublished outbox events to the realtime fabric."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        bus: RealtimeBus | None = None,
        publisher_id: str | None = None,
        sweep_interval: float = 1.0,
        batch_size: int = 100,
        lease_seconds: float = 30.0,
        retry_base_s: float = 1.0,
        retry_max_s: float = 60.0,
        max_attempts: int = 50,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus or get_realtime_bus()
        self.publisher_id = publisher_id or f"pub-{uuid4().hex[:8]}"
        self.sweep_interval = sweep_interval
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.retry_base_s = retry_base_s
        self.retry_max_s = retry_max_s
        self.max_attempts = max_attempts
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._notify_event = asyncio.Event()
        # Heartbeat for the realtime health endpoint.
        self.started_at: datetime | None = None
        self.last_sweep_at: datetime | None = None
        self.last_sweep_published: int = 0
        self.last_sweep_error: str | None = None

    def apply_settings(self, settings: Any) -> None:
        """Copy the CORTEX_OUTBOX_* knobs onto this publisher (bus/factory untouched)."""
        self.sweep_interval = settings.outbox_sweep_interval_s
        self.batch_size = settings.outbox_batch_size
        self.lease_seconds = settings.outbox_lease_s
        self.retry_base_s = settings.outbox_retry_base_s
        self.retry_max_s = settings.outbox_retry_max_s
        self.max_attempts = settings.outbox_max_attempts
        configured_id = (settings.outbox_publisher_id or "").strip()
        if configured_id:
            self.publisher_id = configured_id

    @classmethod
    def from_settings(
        cls,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        bus: RealtimeBus | None = None,
        publisher_id: str | None = None,
    ) -> OutboxPublisher:
        from app.config import get_settings

        pub = cls(
            session_factory=session_factory,
            bus=bus,
            publisher_id=publisher_id,
        )
        pub.apply_settings(get_settings())
        if publisher_id:
            pub.publisher_id = publisher_id
        return pub

    def set_session_factory(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    def trigger_publish(self) -> None:
        """Fast path: wake the sweeper loop immediately (post-commit)."""
        self._notify_event.set()

    async def start(self) -> None:
        """Start background sweeper task."""
        if self.running:
            return
        self.running = True
        self.started_at = _utc_now()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the background sweeper task and release surviving claims.

        A graceful stop hands work to peers immediately (no lease wait);
        backoff (``next_retry_at``) is still honored. Best-effort: a
        failed release degrades to lease expiry, never to loss.
        """
        self.running = False
        self._notify_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(Exception):
            await self.release_own_claims()

    async def release_own_claims(self) -> int:
        """Release this publisher's unpublished claims (lease → NULL).

        Returns the number of rows released. Their ``next_retry_at``
        backoff is left intact so a failing head still gates its tail.
        """
        if self.session_factory is None:
            return 0
        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    update(EventRecordDB)
                    .where(
                        EventRecordDB.claimed_by == self.publisher_id,
                        EventRecordDB.published_at.is_(None),
                    )
                    .values(lease_expires_at=None)
                )
                await session.commit()
                rowcount = getattr(result, "rowcount", 0) or 0
                return int(rowcount)
        except Exception as e:  # noqa: BLE001 — release is best-effort
            logger.warning("OutboxPublisher %s failed to release claims: %s", self.publisher_id, e)
            return 0

    async def _run_loop(self) -> None:
        while self.running:
            try:
                published = await self.sweep_once(limit=self.batch_size)
                self.last_sweep_published = published
                self.last_sweep_error = None
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 — sweeper must never die
                self.last_sweep_error = f"{type(e).__name__}: {e}"
                logger.warning("OutboxPublisher sweep loop error: %s", e)
            finally:
                self.last_sweep_at = _utc_now()

            try:
                await asyncio.wait_for(self._notify_event.wait(), timeout=self.sweep_interval)
            except TimeoutError:
                pass
            finally:
                self._notify_event.clear()

    # ── Fast path ─────────────────────────────────────────────────────

    async def publish_committed(self, event_ids: list[str]) -> int:
        """Attempt immediate delivery of just-committed outbox rows.

        Best-effort by design: any failure leaves the rows for the sweeper.
        Never raises — the sweeper is the durable backstop, not the caller.
        """
        if not event_ids:
            return 0
        try:
            return await self.sweep_once(event_ids=list(event_ids))
        except Exception as e:  # noqa: BLE001 — fast path must never break commits
            logger.warning("OutboxPublisher fast path failed (%d ids): %s", len(event_ids), e)
            return 0

    # ── Core sweep ────────────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def _sweep_session(self):  # type: ignore[no-untyped-def]
        """Yield a session pinned to ONE pooled connection for the sweep.

        Workspace publish exclusion uses session-scoped PG advisory locks,
        which live on the backend connection — but a plain ``factory()``
        session may hop pooled connections across commits, leaking the
        lock onto a pooled backend and stalling later sweeps. Checking out
        one connection for the whole sweep keeps acquire→release on the
        same backend PID.
        """
        factory = self.session_factory
        if factory is None:
            raise RuntimeError("OutboxPublisher has no session factory")
        bind = factory.kw.get("bind")
        if isinstance(bind, AsyncEngine):
            async with bind.connect() as conn:
                session = factory(bind=conn)
                try:
                    yield session
                finally:
                    await session.close()
        else:
            async with factory() as session:
                yield session

    async def sweep_once(
        self,
        limit: int | None = None,
        workspace_id: str | None = None,
        event_ids: list[str] | None = None,
    ) -> int:
        """Claim due rows and publish them in (workspace, seq) order.

        Returns the number of rows newly marked published. Multi-worker safe:
        claim via ``FOR UPDATE SKIP LOCKED`` + lease, per-workspace publish
        exclusion, head-of-line backoff gating. Raises only on unexpected
        (non-publish) failures; per-event publish failures are recorded on
        the row and gated, never raised.
        """
        if self.session_factory is None:
            return 0
        from app.infrastructure import metrics as m

        batch_limit = limit or self.batch_size
        now = _utc_now()

        stmt = select(EventRecordDB).where(
            EventRecordDB.published_at.is_(None),
            or_(
                EventRecordDB.lease_expires_at.is_(None),
                EventRecordDB.lease_expires_at <= now,
            ),
            or_(
                EventRecordDB.next_retry_at.is_(None),
                EventRecordDB.next_retry_at <= now,
            ),
        )
        if workspace_id:
            stmt = stmt.where(EventRecordDB.workspace_id == workspace_id)
        if event_ids:
            stmt = stmt.where(EventRecordDB.event_id.in_(event_ids))
        stmt = stmt.order_by(EventRecordDB.workspace_id, EventRecordDB.seq).limit(batch_limit)

        published_count = 0
        async with self._sweep_session() as session:
            is_pg = _is_postgres(session)
            claim_stmt = stmt.with_for_update(skip_locked=True) if is_pg else stmt
            result = await session.execute(claim_stmt)
            candidates = list(result.scalars().all())
            if not candidates:
                await self._refresh_backlog_gauges(session)
                return 0

            # Per-workspace publish exclusion. Deterministic order; try-only.
            workspaces = sorted({c.workspace_id for c in candidates})
            tenants = {c.workspace_id: c.tenant_id for c in candidates}
            acquired: set[str] = set()
            try:
                for ws in workspaces:
                    if await self._try_acquire_workspace(session, tenants[ws], ws):
                        acquired.add(ws)
                if not acquired:
                    await session.rollback()
                    return 0

                # ── Phase 1: claim ──
                claim_at = _utc_now()
                lease_until = claim_at + timedelta(seconds=self.lease_seconds)
                claimed_ids: list[int] = []
                for evt in candidates:
                    if evt.workspace_id not in acquired:
                        continue
                    if (
                        evt.claimed_by is not None
                        and evt.claimed_by != self.publisher_id
                        and evt.lease_expires_at is not None
                        and evt.lease_expires_at <= now
                    ):
                        m.outbox_reclaimed_total.inc()
                        logger.info(
                            "outbox reclaim ev=%s ws=%s seq=%s from=%s",
                            evt.event_id,
                            evt.workspace_id,
                            evt.seq,
                            evt.claimed_by,
                        )
                    evt.claimed_at = claim_at
                    evt.claimed_by = self.publisher_id
                    evt.lease_expires_at = lease_until
                    evt.published_by = self.publisher_id
                    claimed_ids.append(evt.id)
                await session.commit()

                # ── Phase 2: publish in (workspace, seq) order ──
                restmt = (
                    select(EventRecordDB)
                    .where(
                        EventRecordDB.id.in_(claimed_ids),
                        EventRecordDB.published_at.is_(None),
                        EventRecordDB.claimed_by == self.publisher_id,
                    )
                    .order_by(EventRecordDB.workspace_id, EventRecordDB.seq)
                )
                result = await session.execute(restmt)
                claims = list(result.scalars().all())

                ws_events: dict[str, list[EventRecordDB]] = defaultdict(list)
                for evt in claims:
                    ws_events[evt.workspace_id].append(evt)

                for ws in sorted(ws_events):
                    ev_list = sorted(ws_events[ws], key=lambda e: e.seq)
                    for evt in ev_list:
                        evt.publish_attempts += 1
                        m.outbox_publish_attempts_total.inc()
                        t0 = perf_counter()
                        try:
                            await self.bus.publish_from_outbox(evt)
                        except Exception as e:  # noqa: BLE001 — recorded, gated
                            await self._record_failure(session, evt, e, gate_tail=True)
                            m.outbox_publish_total.labels(result="failure").inc()
                            break
                        evt.published_at = _utc_now()
                        evt.published = True
                        evt.lease_expires_at = None
                        evt.next_retry_at = None
                        evt.last_error = None
                        await session.commit()
                        published_count += 1
                        m.outbox_publish_total.labels(result="success").inc()
                        m.outbox_publish_latency_seconds.observe(perf_counter() - t0)
                        logger.info(
                            "outbox published ev=%s ws=%s seq=%s attempt=%d",
                            evt.event_id,
                            evt.workspace_id,
                            evt.seq,
                            evt.publish_attempts,
                        )
                    # A workspace batch aborted on failure: the failed head's
                    # retry gate was propagated to the tail inside
                    # _record_failure; leases were released.
            finally:
                await self._release_workspaces(session, tenants, acquired)

            await self._refresh_backlog_gauges(session)
        return published_count

    async def _record_failure(
        self,
        session: AsyncSession,
        evt: EventRecordDB,
        error: BaseException,
        *,
        gate_tail: bool,
    ) -> None:
        """Record a failed attempt: error + backoff + tail gating + release."""
        from app.infrastructure import metrics as m

        now = _utc_now()
        delay = compute_backoff_delay_s(evt.publish_attempts, self.retry_base_s, self.retry_max_s)
        retry_at = now + timedelta(seconds=delay)
        evt.last_error = f"{type(error).__name__}: {error}"[:500]
        evt.next_retry_at = retry_at
        evt.lease_expires_at = None  # releasable once the retry is due
        if evt.publish_attempts == self.max_attempts:
            # Poison transition: loud, once. The row is STILL retried with
            # capped backoff afterwards — never dropped, never skipped.
            m.outbox_poison_total.inc()
            logger.error(
                "outbox POISON ev=%s ws=%s seq=%s attempts=%d err=%s",
                evt.event_id,
                evt.workspace_id,
                evt.seq,
                evt.publish_attempts,
                evt.last_error,
            )
        else:
            logger.warning(
                "outbox publish failed ev=%s ws=%s seq=%s attempt=%d retry_in=%.2fs err=%s",
                evt.event_id,
                evt.workspace_id,
                evt.seq,
                evt.publish_attempts,
                delay,
                evt.last_error,
            )
        if gate_tail:
            # Head-of-line gate: every later unpublished row in this workspace
            # (claimed this pass or not yet claimed) waits behind the head's
            # retry time. This is what keeps per-workspace order total across
            # sweep passes and across publishers.
            await session.execute(
                update(EventRecordDB)
                .where(
                    EventRecordDB.tenant_id == evt.tenant_id,
                    EventRecordDB.workspace_id == evt.workspace_id,
                    EventRecordDB.seq > evt.seq,
                    EventRecordDB.published_at.is_(None),
                )
                .values(next_retry_at=retry_at, lease_expires_at=None)
            )
        await session.commit()

    # ── Workspace exclusion ───────────────────────────────────────────

    async def _try_acquire_workspace(
        self, session: AsyncSession, tenant_id: str, workspace_id: str
    ) -> bool:
        if _is_postgres(session):
            key = f"{_PUB_LOCK_KEY_PREFIX}{tenant_id}:{workspace_id}"
            result = await session.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": key}
            )
            return bool(result.scalar())
        # Non-PG fallback (sqlite dev/test, single process): try-only guard.
        guard_key = f"{tenant_id}:{workspace_id}"
        async with _ws_guards_lock:
            guard = _ws_guards.setdefault(guard_key, asyncio.Lock())
            if guard.locked():
                return False
            await guard.acquire()
            return True

    async def _release_workspaces(
        self,
        session: AsyncSession,
        tenants: dict[str, str],
        acquired: set[str],
    ) -> None:
        if not acquired:
            return
        if _is_postgres(session):
            # Session-scoped: this session only ever holds publish-exclusion
            # locks, so unlock_all is precise here.
            with contextlib.suppress(Exception):
                await session.execute(text("SELECT pg_advisory_unlock_all()"))
            return
        async with _ws_guards_lock:
            for ws in acquired:
                guard = _ws_guards.get(f"{tenants[ws]}:{ws}")
                if guard is not None and guard.locked():
                    with contextlib.suppress(RuntimeError):
                        guard.release()

    # ── Observability ─────────────────────────────────────────────────

    async def _refresh_backlog_gauges(self, session: AsyncSession) -> None:
        from app.infrastructure import metrics as m

        try:
            stats = await get_backlog_stats(session)
        except Exception:  # noqa: BLE001, S110 — gauges must never break sweeps
            return
        m.outbox_pending_count.set(float(stats.pending_count))
        if stats.oldest_pending_age_s is not None:
            m.outbox_oldest_pending_age_seconds.set(stats.oldest_pending_age_s)
        else:
            m.outbox_oldest_pending_age_seconds.set(0.0)

    def heartbeat(self) -> dict[str, Any]:
        return {
            "publisher_id": self.publisher_id,
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_sweep_at": self.last_sweep_at.isoformat() if self.last_sweep_at else None,
            "last_sweep_published": self.last_sweep_published,
            "last_sweep_error": self.last_sweep_error,
            "sweep_interval_s": self.sweep_interval,
            "batch_size": self.batch_size,
        }


async def get_backlog_stats(session: AsyncSession) -> OutboxBacklogStats:
    """Pending outbox depth + oldest-row age (health + gauges)."""
    count_stmt = select(func.count(EventRecordDB.id)).where(EventRecordDB.published_at.is_(None))
    pending = int((await session.execute(count_stmt)).scalar() or 0)
    if pending == 0:
        return OutboxBacklogStats(pending_count=0, oldest_pending_age_s=None)
    oldest_stmt = (
        select(EventRecordDB.created_at, EventRecordDB.event_id)
        .where(EventRecordDB.published_at.is_(None))
        .order_by(EventRecordDB.created_at.asc())
        .limit(1)
    )
    row = (await session.execute(oldest_stmt)).first()
    if row is None or row[0] is None:
        return OutboxBacklogStats(pending_count=pending, oldest_pending_age_s=None)
    created = row[0]
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age = max(0.0, (_utc_now() - created).total_seconds())
    return OutboxBacklogStats(
        pending_count=pending, oldest_pending_age_s=age, oldest_event_id=row[1]
    )


async def commit_and_notify(session: AsyncSession) -> None:
    """Commit the caller's transaction, then wake the outbox sweeper.

    The wake is best-effort and never raises: if the in-process publisher is
    disabled or the loop is saturated, the periodic sweep is the backstop.
    Redis NEVER participates in the transaction — the commit is purely PG.
    """
    await session.commit()
    # Notify must never break the caller (the periodic sweep is the backstop).
    with contextlib.suppress(Exception):
        get_outbox_publisher().trigger_publish()


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


def current_outbox_publisher() -> OutboxPublisher | None:
    """Return the process singleton WITHOUT creating it (health/observability)."""
    return _singleton_publisher


def reset_outbox_publisher() -> None:
    """Drop the process singleton (tests + lifespan re-entry)."""
    global _singleton_publisher
    _singleton_publisher = None
