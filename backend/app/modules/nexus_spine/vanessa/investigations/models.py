"""Nexus Vanessa — Typed Response System.

Every Vanessa answer is typed and carries evidence. The UI can render each
type with dedicated components. All fields are deterministic and grounded —
nothing renders without a supporting tool result and evidence trail.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> __import__("datetime").datetime:
    return __import__("datetime").datetime.now()


class ResponseKind(StrEnum):
    """Canonical Vanessa response types."""

    TEXT = "text"
    METRIC = "metric"
    TABLE = "table"
    TIME_SERIES = "time_series"
    GRAPH_PATH = "graph_path"
    SCENARIO_MATRIX = "scenario_matrix"
    RISK_CARD = "risk_card"
    DECISION_CARD = "decision_card"
    SIGNAL_DETAIL = "signal_detail"
    FORECAST_METRIC = "forecast_metric"
    EVIDENCE_CHAIN = "evidence_chain"
    CALIBRATION_REPORT = "calibration_report"


class Citation(BaseModel):
    """A reference to one source of evidence for a specific claim."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    request_id: str = ""
    data_point: str = ""  # Human-readable: "p50=14200"
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ResponseBlock(BaseModel):
    """One block of the rendered answer.

    Combines the text snippet with the citation(s) that back it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ResponseKind
    payload: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)


class VanessaResponse(BaseModel):
    """The typed response Vanessa produces.

    Supports:
    - plaintext (no citations)
    - table (rows/columns)
    - time_series (forecast vs actual)
    - graph_path (entity → entity chain)
    - metric (single number)
    - scenario_matrix (side-by-side options)
    - risk_card (specific risk presentation)
    - evidence_chain (linked evidence nodes)
    """

    model_config = ConfigDict(extra="forbid")

    query_id: str
    intent: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    response_blocks: list[ResponseBlock] = Field(default_factory=list)
    answer_text: str
    answer_kind: ResponseKind = ResponseKind.TEXT
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=lambda: str(_utc_now().isoformat()))
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestigationResult(BaseModel):
    """The result of a Vanessa investigation — an orchestrated multi-tool run.

    Carries:
    - an intent classification
    - a list of grounded tool results (evidence)
    - a final typed response built from those tools
    - the citations that justify every line
    """

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    intent: str
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # execution trace
    steps_executed: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    # aggregated, typed response
    response: VanessaResponse | None = None
    # who answered, when
    answered_at: str = Field(default_factory=lambda: str(_utc_now().isoformat()))
    permission_tier: str = "ANALYST"
    # auditing
    world_state_version: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
