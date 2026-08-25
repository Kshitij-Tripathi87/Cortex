"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow events — publish stage transitions as domain events.

Integrates with the existing domain event dispatcher (app/modules/events/domain_events.py).
Every stage transition produces a typed domain event for downstream consumers
(monitoring dashboards, audit logs, the frontend cockpit).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cortex.workflow.events")


class WorkflowEventBus:
    """Publishes workflow lifecycle events to the domain event dispatcher."""

    async def publish(self, payload: dict[str, Any]) -> None:
        from app.modules.events.domain_events import emit_domain_event

        event_type = payload.get("event_type", "workflow.event")
        workspace_id = payload.get("workspace_id", "")

        try:
            await emit_domain_event(
                event_type=event_type,
                workspace_id=workspace_id,
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to publish workflow event type=%s", event_type)


workflow_event_bus = WorkflowEventBus()
