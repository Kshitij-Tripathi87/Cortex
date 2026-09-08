"""Nexus v0.7 — Realtime event types (item 11).

Every significant state transition produces a typed event that flows
through the SSE endpoint to drive the UI. This makes Nexus visibly
behave like a live operational system.

Event types:
  WORLD_STATE_CHANGED
  SIGNAL_CREATED
  RISK_CHANGED
  FORECAST_UPDATED
  SCENARIO_COMPLETED
  DECISION_CREATED
  DECISION_INVALIDATED
  APPROVAL_GRANTED
  EXECUTION_STARTED
  EXECUTION_COMPLETED
  OUTCOME_RECORDED
  VANESSA_RESPONSE
  MODEL_DEPLOYED
  DRIFT_DETECTED
"""

from __future__ import annotations

from enum import StrEnum


class NexusEventType(StrEnum):
    WORLD_STATE_CHANGED = "world_state_changed"
    SIGNAL_CREATED = "signal_created"
    RISK_CHANGED = "risk_changed"
    FORECAST_UPDATED = "forecast_updated"
    SCENARIO_COMPLETED = "scenario_completed"
    DECISION_CREATED = "decision_created"
    DECISION_INVALIDATED = "decision_invalidated"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    OUTCOME_RECORDED = "outcome_recorded"
    VANESSA_RESPONSE = "vanessa_response"
    MODEL_DEPLOYED = "model_deployed"
    MODEL_ROLLED_BACK = "model_rolled_back"
    DRIFT_DETECTED = "drift_detected"
    RECOMMENDATION_MADE = "recommendation_made"


def event_to_sse(event_type: NexusEventType, data: dict) -> str:
    """Format an event as an SSE message."""
    import json
    return f"event: {event_type.value}\ndata: {json.dumps(data)}\n\n"


__all__ = ["NexusEventType", "event_to_sse"]
