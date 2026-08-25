"""Episodic Memory Engine — Historical Incidents, Timelines, and Root Causes.

Enables retrospective analysis and case-based retrieval for operational disruptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IncidentRecord:
    """Historical incident record captured in episodic memory."""

    incident_id: str
    workspace_id: str
    tenant_id: str
    incident_type: str
    severity: str
    title: str
    description: str
    root_cause: str
    affected_entities: list[str]
    timeline_events: list[dict[str, Any]]
    resolution_summary: str
    actual_financial_impact_usd: float
    occurred_at: datetime
    resolved_at: datetime | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "incident_type": self.incident_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "root_cause": self.root_cause,
            "affected_entities": self.affected_entities,
            "timeline_events": self.timeline_events,
            "resolution_summary": self.resolution_summary,
            "actual_financial_impact_usd": round(self.actual_financial_impact_usd, 2),
            "occurred_at": self.occurred_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "tags": self.tags,
        }


class EpisodicMemoryEngine:
    """Stores and retrieves historical operational episodes."""

    def __init__(self) -> None:
        self._incidents: dict[str, IncidentRecord] = {}

    def record_incident(self, incident: IncidentRecord) -> None:
        """Store an incident record."""
        self._incidents[incident.incident_id] = incident

    def get_incident(self, incident_id: str) -> IncidentRecord | None:
        """Retrieve an incident by ID."""
        return self._incidents.get(incident_id)

    def query_incidents(
        self,
        workspace_id: str,
        incident_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 20,
    ) -> list[IncidentRecord]:
        """Query past incidents matching filters."""
        results: list[IncidentRecord] = []
        for inc in self._incidents.values():
            if inc.workspace_id != workspace_id:
                continue
            if incident_type and inc.incident_type != incident_type:
                continue
            if entity_id and entity_id not in inc.affected_entities:
                continue
            results.append(inc)

        results.sort(key=lambda x: x.occurred_at, reverse=True)
        return results[:limit]


_global_episodic_mem = EpisodicMemoryEngine()


def get_episodic_memory() -> EpisodicMemoryEngine:
    return _global_episodic_mem
