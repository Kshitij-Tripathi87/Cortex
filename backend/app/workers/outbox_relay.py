"""Dedicated outbox-relay worker (v0.8.5-B4).

Runs the :class:`OutboxPublisher` sweeper as a standalone process for
deployments that want the relay isolated from API replicas:

    python -m app.workers.outbox_relay

Configuration is the same ``CORTEX_OUTBOX_*`` surface as the in-process
sweeper; set ``CORTEX_OUTBOX_PUBLISHER_ID`` for a stable identity and
``CORTEX_OUTBOX_PUBLISHER_ENABLED=false`` on the API tier if the relay
should run ONLY here. Multiple relay replicas are safe (SKIP LOCKED +
per-workspace exclusion + leases).

The process exits 0 on SIGTERM/SIGINT after stopping the sweeper and
closing the DB pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.config import get_settings
from app.infrastructure.database import close_db, get_session_factory, init_db
from app.infrastructure.logging import setup_logging
from app.infrastructure.metrics import start_metrics_server
from app.infrastructure.outbox_publisher import OutboxPublisher

logger = logging.getLogger("nexus.outbox_relay")


async def _run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    start_metrics_server(port=settings.metrics_port)
    await init_db(settings.db_dsn)

    publisher = OutboxPublisher.from_settings(
        session_factory=get_session_factory(),
        publisher_id=settings.outbox_publisher_id or None,
    )
    await publisher.start()
    logger.info(
        "outbox relay started id=%s sweep=%.2fs batch=%d",
        publisher.publisher_id,
        publisher.sweep_interval,
        publisher.batch_size,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, ValueError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    logger.info("outbox relay stopping id=%s", publisher.publisher_id)
    await publisher.stop()
    await close_db()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
