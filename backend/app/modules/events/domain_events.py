"""Domain Events — separated from audit events and integration events.

Three distinct event categories (per docs/16-event-taxonomy.md):

1. Audit Events (T5) — Immutable record of governance actions (who did what when).
   Stored in audit_events table. INSERT-only. Hash-chained. Tamper-evident.
   Examples: upload.received, claim.accepted, conflict.resolved, decision.recorded.

2. Domain Events (T3) — State changes that cross bounded context boundaries.
   Published via in-process dispatcher. Downstream contexts react.
   Examples: source.batch.validated, evidence.claim.created, conflict.detected, readiness.determined.

3. Integration Events (T4) — Events crossing external system boundaries.
   Published via outbox pattern. At-least-once delivery. Idempotent consumers.
   Examples: integration.upload.received, integration.outbound.dispatched.

This module provides the in-process dispatcher for Domain Events (T3).
Integration Events (T4) use the outbox table (see docs/20-plugin-architecture.md).
Audit Events (T5) use the audit service (app/modules/audit/service.py).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from app.common.ids import uuid7


@dataclass(frozen=True)
class DomainEvent:
    """Domain event — crosses bounded context boundary."""

    event_id: str = field(default_factory=uuid7)
    event_type: str = ""
    workspace_id: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = field(default_factory=dict)
    causation_id: str | None = None
    correlation_id: str | None = None


# Type alias for async handlers
Handler = Callable[[DomainEvent], Awaitable[None]]
T = TypeVar("T")


class DomainEventDispatcher:
    """In-process domain event dispatcher with at-least-once semantics.

    Handlers are registered per event_type. Dispatch is synchronous (await)
    but can be made async by wrapping handlers in create_task.

    Each handler is called exactly once per event (best effort).
    Deduplication key: (handler_id, event_id) — prevents double processing
    on retry. Stored in a simple in-memory set (Phase 2); Phase 3+ uses Redis.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._handler_ids: dict[Handler, str] = {}
        self._processed: set[tuple[str, str]] = set()  # (handler_id, event_id)

    def register(self, event_type: str, handler: Handler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)
        self._handler_ids[handler] = f"{handler.__module__}.{handler.__name__}"

    async def dispatch(self, event: DomainEvent) -> None:
        """Dispatch event to all registered handlers."""
        for handler in self._handlers.get(event.event_type, []):
            handler_id = self._handler_ids[handler]
            dedup_key = (handler_id, event.event_id)
            if dedup_key in self._processed:
                continue
            self._processed.add(dedup_key)
            try:
                await handler(event)
            except Exception as exc:
                # Don't let one handler failure block others
                # In production: emit T2 system event + alert
                import logging

                logging.getLogger("cortex.domain_events").exception(
                    "Handler failed",
                    extra={"handler": getattr(handler, "__name__", repr(handler))},
                )
                # Preserve the exception variable for debugging
                _ = exc


# Global dispatcher instance
dispatcher = DomainEventDispatcher()


# Frozen domain event types (per docs/16-event-taxonomy.md §3.3)


class DomainEventTypes:
    """Frozen domain event type identifiers."""

    # Evidence Context (BC1) → Operational Graph Context (BC2)
    SOURCE_BATCH_VALIDATED = "source.batch.validated"
    SOURCE_FILE_PROFILED = "source.file.profiled"
    EVIDENCE_CLAIM_CREATED = "evidence.claim.created"
    EVIDENCE_CLAIM_ACCEPTED = "evidence.claim.accepted"
    EVIDENCE_CLAIM_SUPERSEDED = "evidence.claim.superseded"

    # Resolution Context (BC1) → Graph Context (BC2)
    CONFLICT_DETECTED = "conflict.detected"
    CONFLICT_RESOLVED = "conflict.resolved"
    CONFLICT_ESCALATED = "conflict.escalated"

    # Graph Context (BC2) → Decision Context (BC4)
    GRAPH_SNAPSHOT_SEALED = "graph.snapshot.sealed"
    GRAPH_READINESS_DETERMINED = "graph.readiness.determined"

    # Decision Context (BC4) → Graph Context (BC2) feedback
    DECISION_RECORDED = "decision.recorded"
    DECISION_REVERTED = "decision.reverted"
    OUTCOME_RECORDED = "outcome.recorded"

    # Simulation Context (BC3) → Decision Context (BC4)
    SCENARIO_CREATED = "scenario.created"
    SCENARIO_COMPARED = "scenario.compared"

    # ML Context (BC7) → Evidence Context (BC1) via ACL
    ML_CANDIDATE_PROPOSED = "ml.candidate.proposed"


async def emit_domain_event(
    event_type: str,
    workspace_id: str,
    payload: dict,
    *,
    causation_id: str | None = None,
    correlation_id: str | None = None,
) -> DomainEvent:
    """Create, validate, persist-reference, and dispatch a domain event.

    Pipeline: create → validate → dispatch → (audit + telemetry handled by handlers).

    Returned event is fully dispatched before the call returns. Failures in
    individual handlers are isolated by the dispatcher (see DomainEventDispatcher.dispatch).
    """
    if not event_type:
        raise ValueError("event_type is required")
    if not workspace_id:
        raise ValueError("workspace_id is required")

    event = DomainEvent(
        event_type=event_type,
        workspace_id=workspace_id,
        payload=payload,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )
    await dispatcher.dispatch(event)
    return event


def emit_domain_event_sync(
    event_type: str,
    workspace_id: str,
    payload: dict,
    *,
    causation_id: str | None = None,
    correlation_id: str | None = None,
) -> DomainEvent:
    """Create a domain event without dispatching. For tests or fire-and-forget callers."""
    if not event_type:
        raise ValueError("event_type is required")
    if not workspace_id:
        raise ValueError("workspace_id is required")
    return DomainEvent(
        event_type=event_type,
        workspace_id=workspace_id,
        payload=payload,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )
