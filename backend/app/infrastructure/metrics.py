"""Prometheus metrics for Cortex backend.

Frozen metric catalog per docs/22-observability-model.md:
- cortex_api_requests_total{method, status, route}
- cortex_api_latency_seconds{route}
- cortex_uploads_total{result, source_system}
- cortex_evidence_extracted_total{extractor, verdict}
- cortex_claims_total{state, source_system}
- cortex_conflicts_open{entity_type}
- cortex_readiness_state{workspace_id}
- cortex_db_query_duration_seconds
- cortex_worker_jobs{state}
"""

from __future__ import annotations

import contextlib
from time import perf_counter
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

    class _DummyMetric:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def labels(self, *args: Any, **kwargs: Any) -> _DummyMetric:
            return self

        def inc(self, amount: float = 1.0) -> None:
            pass

        def set(self, value: float) -> None:
            pass

        def observe(self, value: float) -> None:
            pass

    Counter = _DummyMetric  # type: ignore[assignment, misc]
    Gauge = _DummyMetric  # type: ignore[assignment, misc]
    Histogram = _DummyMetric  # type: ignore[assignment, misc]

    def start_http_server(port: int = 8001) -> None:  # type: ignore[misc]
        pass


# API Metrics
api_requests_total = Counter(
    "cortex_api_requests_total",
    "Total API requests",
    ["method", "status", "route"],
)

api_latency_seconds = Histogram(
    "cortex_api_latency_seconds",
    "API request latency",
    ["route"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Upload Metrics
uploads_total = Counter(
    "cortex_uploads_total",
    "Total file uploads",
    ["result", "source_system"],
)

# Evidence Metrics
evidence_extracted_total = Counter(
    "cortex_evidence_extracted_total",
    "Total evidence records extracted",
    ["extractor", "verdict"],
)

claims_total = Counter(
    "cortex_claims_total",
    "Total evidence claims",
    ["state", "source_system"],
)

# Conflict Metrics
conflicts_open = Gauge(
    "cortex_conflicts_open",
    "Open conflicts by entity type",
    ["entity_type"],
)

# Readiness Metrics
readiness_state = Gauge(
    "cortex_readiness_state",
    "Readiness state per workspace "
    "(1=READY, 0=BLOCKED, -1=REVIEW_REQUIRED, -2=READY_WITH_ASSUMPTIONS)",
    ["workspace_id"],
)

# Database Metrics
db_query_duration_seconds = Histogram(
    "cortex_db_query_duration_seconds",
    "Database query duration",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# Worker Metrics
worker_jobs = Gauge(
    "cortex_worker_jobs",
    "Background jobs by state",
    ["state"],
)

# ─────────────────────────────────────────────────────────────────────
# Outbox relay metrics (v0.8.5-B4 — durable outbox → Redis → SSE/WS)
# ─────────────────────────────────────────────────────────────────────
outbox_pending_count = Gauge(
    "cortex_outbox_pending_count",
    "Outbox rows awaiting delivery (published_at IS NULL)",
)

outbox_oldest_pending_age_seconds = Gauge(
    "cortex_outbox_oldest_pending_age_seconds",
    "Age of the oldest undelivered outbox row",
)

outbox_publish_total = Counter(
    "cortex_outbox_publish_total",
    "Outbox publish outcomes",
    ["result"],  # success | failure
)

outbox_publish_attempts_total = Counter(
    "cortex_outbox_publish_attempts_total",
    "Outbox publish attempts (claims)",
)

outbox_reclaimed_total = Counter(
    "cortex_outbox_reclaimed_total",
    "Outbox rows reclaimed from expired leases (crashed peers)",
)

outbox_publish_latency_seconds = Histogram(
    "cortex_outbox_publish_latency_seconds",
    "Outbox claim-to-acknowledged-publish latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

outbox_poison_total = Counter(
    "cortex_outbox_poison_total",
    "Outbox rows exceeding max attempts (flagged, still retried, never dropped)",
)

# ─────────────────────────────────────────────────────────────────────
# Realtime delivery metrics (v0.8.5-B4)
# ─────────────────────────────────────────────────────────────────────
realtime_connections = Gauge(
    "cortex_realtime_connections",
    "Active realtime client connections",
    ["transport"],  # sse | ws
)

realtime_events_published_total = Counter(
    "cortex_realtime_events_published_total",
    "Events handed to the realtime fabric (Redis + local fan-out)",
)

realtime_events_delivered_total = Counter(
    "cortex_realtime_events_delivered_total",
    "Events delivered to connected clients",
    ["transport"],  # sse | ws | replay
)

realtime_duplicate_events_total = Counter(
    "cortex_realtime_duplicate_events_total",
    "Duplicate/stale events suppressed (idempotency + sequence gate)",
)

realtime_gap_detected_total = Counter(
    "cortex_realtime_gap_detected_total",
    "Sequence gaps detected on live streams",
    ["transport"],  # sse | ws
)

realtime_replay_total = Counter(
    "cortex_realtime_replay_total",
    "Replay operations served (catch-up + reconnect)",
    ["transport"],  # sse | ws | http
)

realtime_resync_total = Counter(
    "cortex_realtime_resync_total",
    "Full resyncs required (gap exceeds threshold)",
    ["transport"],  # sse | ws | http
)

realtime_reconnect_total = Counter(
    "cortex_realtime_reconnect_total",
    "Client reconnects with a cursor (after_seq > 0)",
    ["transport"],  # sse | ws
)

realtime_delivery_latency_seconds = Histogram(
    "cortex_realtime_delivery_latency_seconds",
    "Event commit-to-handoff latency (outbox created_at → fabric/client frame)",
    ["transport"],  # fabric | sse | ws | replay
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


def start_metrics_server(port: int = 8001) -> None:
    """Start Prometheus metrics HTTP server."""
    with contextlib.suppress(Exception):
        start_http_server(port)


class MetricsMiddleware:
    """ASGI middleware for automatic request metrics."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope["method"]
        path = scope["path"]
        start_time = perf_counter()

        status_code = "500"

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = perf_counter() - start_time
            route = path.split("/")[1] if "/" in path else "unknown"
            api_requests_total.labels(method=method, status=status_code, route=route).inc()
            api_latency_seconds.labels(route=route).observe(duration)
