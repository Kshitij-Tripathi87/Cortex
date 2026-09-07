"""Nexus Vanessa — Observation Layer: Answer Claims with Grounding Proof.

Every Vanessa claim about operational state carries proof:
- which tool produced the evidence
- the world_state_version at the time of the claim
- the confidence the tool declared

The UI renders each claim with a source attribution, proving the answer
is grounded in data rather than hallucinated by the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.modules.nexus_spine.ontology import get_world_model
from app.modules.nexus_spine.vanessa.investigations.planner import VanessaInvestigator


def _safe_uuid(val: Any) -> UUID | None:
    try:
        return UUID(val) if val else None
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class AnswerClaim:
    """One verified claim with full provenance.

    Every piece of supported evidence lives here so the operator can
    trace the answer back to the exact world state and tool calls.
    """

    claim_id: str
    statement: str
    evidence: list[dict[str, Any]]
    entity_trace: list[str]  # entity_ids referenced in this claim
    world_state_version: int
    confidence: float
    explanation: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class AnswerClaimRegistry:
    """In-memory store of AnswerClaim records.

    In power-user mode (Vanessa), this is the memory oracle. Most tools
    on this layer should write claims for auditing.
    """

    def __init__(self) -> None:
        self._claims: dict[str, AnswerClaim] = {}

    def record(self, claim: AnswerClaim) -> None:
        """Append an answer claim."""
        self._claims[claim.claim_id] = claim

    def get(self, claim_id: str) -> AnswerClaim | None:
        return self._claims.get(claim_id)

    def list_all(self) -> list[AnswerClaim]:
        return sorted(self._claims.values(), key=lambda c: c.timestamp, reverse=True)


_registry: AnswerClaimRegistry | None = None


def get_answer_claim_registry() -> AnswerClaimRegistry:
    global _registry
    if _registry is None:
        _registry = AnswerClaimRegistry()
    return _registry


def reset_answer_claim_registry() -> None:
    global _registry
    _registry = None
