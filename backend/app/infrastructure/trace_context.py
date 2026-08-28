"""F3 — End-to-end observability trace (Phase 15 production gate).

A single user request in the Cortex platform crosses at least
four boundaries:

  HTTP request → API router → service layer → PG/Redis
                                    ↓
                              async job queue (workflow,
                              twin, agent deliberation)
                                    ↓
                              audit log emission (T5)

A trace that stops at any of these boundaries is a "partial"
trace — useful for the segment that is traced, useless for
the end-to-end question "where did this request spend its
time?".

This module provides three primitives that, together, give a
single trace id which follows the request from the HTTP
edge all the way to the audit log emission:

1. ``current_trace_id_hex()`` / ``current_span_id_hex()`` —
   read the trace id / span id from the active OTel span.
   The hex form (no dashes) is what the audit log
   ``trace_id`` / ``span_id`` columns store.

2. ``build_envelope(payload)`` — wrap a job payload in an
   envelope that carries the current trace context. The
   envelope is the payload dict with an ``__trace_parent__``
   key holding the W3C ``traceparent`` header value.

3. ``restore_from_envelope(envelope)`` — given an envelope
   received off the queue, set the active OTel context so
   the worker's spans become children of the original HTTP
   request span. Returns a token that the caller passes to
   ``detach_context`` after the work is done.

The combination is the F3 contract: ``traceparent`` survives
the queue hop, so a Grafana "trace" view shows the full
HTTP → queue → worker → audit-emit chain as one trace, not
three.

Hermetic: the module does not start a global tracer provider
or require a live OTLP collector. The unit tests use the
OTel test span exporter and a no-op tracer.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import (
    Span,
    Tracer,
)


# Frozen envelope key for the trace context. Workers MUST
# look for this key when they pick up a job; if it's
# missing, the worker starts a new trace (which is the
# correct fallback for jobs that were enqueued before
# propagation was wired).
ENVELOPE_TRACE_KEY: str = "__trace_parent__"


def get_tracer(name: str = "cortex") -> Tracer:
    """Return a tracer scoped to the cortex namespace.

    Centralized so callers don't need to know about the
    ``trace.get_tracer()`` import. The test suite uses this
    to inject a test tracer."""
    return trace.get_tracer(name)


def current_trace_id_hex() -> str | None:
    """Return the active OTel trace id as a 32-character
    hex string, or None if no span is active.

    The hex form (no dashes) is what the audit log column
    stores. The OTel ``format_trace_id()`` helper gives
    the same 32-hex form; we do the conversion here so the
    call site doesn't need to know.
    """
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def current_span_id_hex() -> str | None:
    """Return the active OTel span id as a 16-character hex
    string, or None if no span is active. Used for the
    audit-log ``span_id`` column so the audit row can be
    pivoted on the trace view."""
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.span_id:016x}"


def build_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a queue envelope that carries the current trace
    context. The envelope is the payload dict with an
    ``__trace_parent__`` key holding the W3C ``traceparent``
    header value.

    The worker calls ``restore_from_envelope()`` when it
    dequeues, which sets the active OTel context so the
    worker's spans become children of the original HTTP
    request span.
    """
    envelope = dict(payload)
    headers: dict[str, str] = {}
    inject(headers)
    if "traceparent" in headers:
        envelope[ENVELOPE_TRACE_KEY] = headers["traceparent"]
    return envelope


def restore_from_envelope(envelope: dict[str, Any]) -> Any:
    """Given an envelope received off the queue, restore the
    OTel context from the embedded ``traceparent`` header.

    Returns a token that the caller MUST pass to
    ``detach_context()`` after the work is done. The
    detach is what prevents the restored context from
    leaking into the next job the worker picks up.

    If the envelope has no ``__trace_parent__`` (job was
    enqueued before F3, or the enqueuer was in a context
    where no span was active), this returns ``None`` and
    the worker simply starts a new trace. The new trace
    is still a valid trace — it just doesn't link back
    to the originating HTTP request.
    """
    traceparent = envelope.get(ENVELOPE_TRACE_KEY)
    if not traceparent:
        return None
    ctx = extract({"traceparent": traceparent})
    return attach(ctx)


def detach_context(token: Any) -> None:
    """Detach a context previously attached by
    ``restore_from_envelope``. Safe to call with ``None``."""
    if token is None:
        return
    try:
        detach(token)
    except Exception:
        # The OTel detach can raise if the context was
        # already detached (e.g. by an earlier except
        # branch). The trace is still valid; we just lose
        # the cleanup. Never let observability cleanup
        # break the worker's hot path.
        pass


class traced_section:
    """Context manager that opens a child span around a
    block. Used by the worker to wrap the "consume one
    job" path so the span tree is::

        HTTP request span (root)
            └── async job span (enqueue → dequeue)
                └── traced_section("process_job")
                    └── DB queries, audit emissions, etc.

    The ``name`` argument becomes the span name. The
    optional ``attributes`` dict becomes OTel span
    attributes (e.g. ``job.kind="twin"``,
    ``decision.id="dec_abc"``)."""

    def __init__(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._name = name
        self._attributes = attributes or {}
        self._tracer = tracer or get_tracer()
        self._span: Span | None = None

    def __enter__(self) -> Span:
        self._span = self._tracer.start_span(self._name,
                                             attributes=self._attributes)
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._span is None:
            return
        if exc_type is not None:
            self._span.set_status(
                trace.Status(trace.StatusCode.ERROR, str(exc))
            )
            self._span.record_exception(exc)
        self._span.end()
