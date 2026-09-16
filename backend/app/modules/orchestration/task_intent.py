"""Framework-independent task intent model for Cortex Nexus.

The model is deliberately owned by Nexus rather than Microsoft Agent Framework.
It turns an unstructured user objective into explicit, reviewable intent fields
that downstream planning and governance can validate before execution.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskClass(StrEnum):
    """Governance risk classification for a task."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TimeHorizon(BaseModel):
    """Optional temporal scope for a task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime | None = None
    end: datetime | None = None
    label: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("end")
    @classmethod
    def validate_end(cls, value: datetime | None, info: Any) -> datetime | None:
        start = info.data.get("start")
        if value is not None and start is not None and value < start:
            raise ValueError("time horizon end must be greater than or equal to start")
        return value


class EvidenceRequirement(BaseModel):
    """A concrete fact/source that must be established before reasoning is trusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    required: bool = True


class TaskIntent(BaseModel):
    """Canonical, framework-neutral representation of a user's operational task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str = Field(min_length=3, max_length=2000)
    constraints: dict[str, Any] = Field(default_factory=dict)
    entity_ids: tuple[str, ...] = ()
    time_horizon: TimeHorizon | None = None
    risk_class: RiskClass = RiskClass.MEDIUM
    required_evidence: tuple[EvidenceRequirement, ...] = ()

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("objective must not be empty")
        return normalized

    @field_validator("entity_ids")
    @classmethod
    def validate_entity_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("entity_ids must not contain blank identifiers")
        if len(set(normalized)) != len(normalized):
            raise ValueError("entity_ids must be unique")
        return normalized

    @field_validator("required_evidence")
    @classmethod
    def validate_evidence_keys(
        cls, value: tuple[EvidenceRequirement, ...]
    ) -> tuple[EvidenceRequirement, ...]:
        keys = [item.key for item in value]
        if len(set(keys)) != len(keys):
            raise ValueError("required_evidence keys must be unique")
        return value

    def missing_evidence(self, available_refs: set[str]) -> tuple[str, ...]:
        """Return required evidence keys that have not been established yet.

        The planner can use this as a hard gate: an intent may be constructed
        from an LLM output, but execution cannot silently treat a missing fact
        as established evidence.
        """

        return tuple(
            requirement.key
            for requirement in self.required_evidence
            if requirement.required and requirement.key not in available_refs
        )

    @property
    def requires_consequential_governance(self) -> bool:
        """Whether this intent must remain behind explicit governance gates."""

        return self.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
