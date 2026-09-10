"""Cortex application factory with observability integration."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace

from app.api.v1.router import api_router
from app.common.ids import uuid7
from app.config import get_settings
from app.infrastructure.database import close_db, get_session_factory, init_db
from app.infrastructure.logging import setup_logging
from app.infrastructure.metrics import MetricsMiddleware, start_metrics_server
from app.infrastructure.security import (
    CircuitBreakerMiddleware,
    RateLimitHeadersMiddleware,
    SecurityHeadersMiddleware,
)
from app.infrastructure.tracing import setup_tracing

_shutdown_event = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — startup and shutdown."""
    global _shutdown_event
    settings = get_settings()

    # Startup
    setup_logging(settings.log_level)
    setup_tracing(endpoint="http://localhost:4317")
    start_metrics_server()
    await init_db(settings.db_dsn)

    # B4: start the outbox relay sweeper in-process (env-gated). SKIP LOCKED
    # + per-workspace exclusion make N API replicas a safe publisher pool.
    # Deployments that prefer an isolated relay run app.workers.outbox_relay
    # and set CORTEX_OUTBOX_PUBLISHER_ENABLED=false here.
    outbox_publisher = None
    if settings.outbox_publisher_enabled:
        try:
            from app.infrastructure.outbox_publisher import get_outbox_publisher

            # The process singleton: commit_and_notify() wakes exactly this
            # instance, and the realtime health endpoint reads its heartbeat.
            outbox_publisher = get_outbox_publisher(session_factory=get_session_factory())
            outbox_publisher.apply_settings(settings)
            await outbox_publisher.start()
        except Exception:
            # The API must boot even if the relay cannot start (mutations
            # still commit durably; the backlog drains when a publisher
            # appears). The realtime health endpoint exposes the outage.
            import logging as _logging

            _logging.getLogger("nexus.outbox_publisher").exception(
                "OutboxPublisher failed to start; continuing without relay"
            )
            outbox_publisher = None

    # Setup signal handlers for graceful shutdown
    _shutdown_event = asyncio.Event()

    def _signal_handler(signum: int, frame):
        _shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows lacks add_signal_handler (NotImplementedError), and a
        # non-main thread cannot install signal handlers (ValueError) — e.g.
        # the SSE contract test runs uvicorn in a worker thread. Installing
        # handlers is best-effort in both cases.
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, _signal_handler, sig, None)

    try:
        yield
    finally:
        # Shutdown - stop the relay first (lets an in-flight sweep finish
        # its commit; the task cancel is bounded by stop()), then drain.
        if outbox_publisher is not None:
            with contextlib.suppress(Exception):
                await outbox_publisher.stop()
        # Shutdown - wait for signal or explicit close
        if _shutdown_event and not _shutdown_event.is_set():
            # Give in-flight requests time to complete
            await asyncio.sleep(2)
        await close_db()


def create_app() -> FastAPI:
    """Build the FastAPI application with full observability."""
    app = FastAPI(
        title="Cortex API",
        description="Evidence-first operational intelligence platform for supply chains",
        version="0.2.0",
        lifespan=lifespan,
    )

    settings = get_settings()

    # Add CORS middleware (outermost for proper preflight handling)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allowed_methods,
        allow_headers=settings.cors_allowed_headers,
    )

    # Add security middleware (order matters - outermost first)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitHeadersMiddleware)
    app.add_middleware(CircuitBreakerMiddleware)

    # Add metrics middleware
    app.add_middleware(MetricsMiddleware)

    # Add request ID middleware — generate server-side if missing (never "unknown")
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid7()
        # Propagate to OTel span + structured logs
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("request.id", request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Include API router
    app.include_router(api_router, prefix="/api/v1")

    # Health endpoints
    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Liveness probe — is the process running?"""
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness probe — are dependencies healthy?

        F2: composes the verdict from the four mandatory
        dependency checks (db, redis, object_storage, audit
        chain) in ``app.infrastructure.health``. The response
        body lists every component state so the on-call
        runbook can read the 503 cause from the payload
        without checking logs.
        """
        from app.infrastructure.health import check_dependencies

        all_ok, components = await check_dependencies()
        body: dict[str, object] = {
            "status": "ok" if all_ok else "unavailable",
            "components": [c.to_dict() for c in components],
        }
        status_code = 200 if all_ok else 503
        return JSONResponse(body, status_code=status_code)

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus metrics endpoint (proxied from metrics server)."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
