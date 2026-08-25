"""Test helpers for Digital Twin module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class FakeEvent:
    """Fake WorldStateEventDB for testing projection."""

    event_id: str
    world_id: str
    workspace_id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    caused_by_event_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


def make_fake_event(
    event_id: str,
    world_id: str,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    caused_by_event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> FakeEvent:
    """Create a FakeEvent for testing.

    ``occurred_at`` is explicit (deterministic) twin execution: pass the
    scenario clock's timestamp so projections are a pure function of inputs.
    Defaults to wall clock for ad-hoc test usage (matches historical behavior).
    """
    return FakeEvent(
        event_id=event_id,
        world_id=world_id,
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload or {},
        caused_by_event_id=caused_by_event_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )
