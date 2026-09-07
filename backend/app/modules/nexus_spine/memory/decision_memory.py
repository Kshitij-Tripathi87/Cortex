"""Nexus Decision Memory — Long-Term Learning Subsystem.

Records every completed decision with its full context (situation, evidence,
world state, recommendation, chosen option, outcome, financial impact,
actual result, human feedback) and provides similarity-based retrieval.

When a new situation arises, DecisionMemory retrieves analogous past
decisions so the system can:
- recommend actions that worked in similar contexts
- warn about actions that underperformed
- ground Vanessa's reasoning in actual organizational history

This is the substrate that converts Nexus from "AI on top of data" into
"decision intelligence that learns from its own outcomes".
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _tokenize(text: str) -> set[str]:
    """Simple whitespace + alphanumeric tokenizer for similarity scoring."""
    return {t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t}


@dataclass(frozen=True)
class DecisionRecord:
    """One recorded decision.

    Persisted to the decision memory at decision-completion time. Carries
    enough context for the system to reason about outcomes later.
    """

    decision_id: str
    tenant_id: str
    workspace_id: str
    situation: str
    evidence_ids: list[str]
    world_state_version: int
    options: list[dict[str, Any]]
    recommended_option_id: str
    chosen_option_id: str
    policy_id: str
    approval_id: str | None
    executed_at: datetime
    outcome_status: str = "pending"  # pending | succeeded | failed | mixed
    financial_impact: float | None = None
    actual_result: str | None = None
    human_feedback: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "situation": self.situation,
            "evidence_ids": list(self.evidence_ids),
            "world_state_version": self.world_state_version,
            "options": list(self.options),
            "recommended_option_id": self.recommended_option_id,
            "chosen_option_id": self.chosen_option_id,
            "policy_id": self.policy_id,
            "approval_id": self.approval_id,
            "executed_at": self.executed_at.isoformat(),
            "outcome_status": self.outcome_status,
            "financial_impact": self.financial_impact,
            "actual_result": self.actual_result,
            "human_feedback": self.human_feedback,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class AnalogousDecision:
    """A past decision retrieved as analogous to a new situation.

    Carries similarity + outcome so the caller can decide whether to use
    the historical outcome as guidance.
    """

    decision: DecisionRecord
    similarity: float  # 0.0-1.0
    outcome_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "similarity": round(self.similarity, 4),
            "outcome_summary": self.outcome_summary,
        }


class DecisionMemory:
    """Thread-safe decision memory with similarity-based retrieval."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, DecisionRecord] = {}

    # ── Record / update ────────────────────────────────────────────────────

    def record(self, record: DecisionRecord) -> None:
        with self._lock:
            self._records[record.decision_id] = record

    def update_outcome(
        self,
        decision_id: str,
        *,
        outcome_status: str | None = None,
        financial_impact: float | None = None,
        actual_result: str | None = None,
        human_feedback: str | None = None,
    ) -> DecisionRecord | None:
        with self._lock:
            existing = self._records.get(decision_id)
            if existing is None:
                return None
            updated = DecisionRecord(
                decision_id=existing.decision_id,
                tenant_id=existing.tenant_id,
                workspace_id=existing.workspace_id,
                situation=existing.situation,
                evidence_ids=existing.evidence_ids,
                world_state_version=existing.world_state_version,
                options=existing.options,
                recommended_option_id=existing.recommended_option_id,
                chosen_option_id=existing.chosen_option_id,
                policy_id=existing.policy_id,
                approval_id=existing.approval_id,
                executed_at=existing.executed_at,
                outcome_status=outcome_status or existing.outcome_status,
                financial_impact=financial_impact if financial_impact is not None else existing.financial_impact,
                actual_result=actual_result if actual_result is not None else existing.actual_result,
                human_feedback=human_feedback if human_feedback is not None else existing.human_feedback,
                tags=existing.tags,
            )
            self._records[decision_id] = updated
            return updated

    # ── Retrieval ──────────────────────────────────────────────────────────

    def get(self, decision_id: str) -> DecisionRecord | None:
        with self._lock:
            return self._records.get(decision_id)

    def find_analogous(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        situation: str,
        limit: int = 5,
        min_similarity: float = 0.1,
    ) -> list[AnalogousDecision]:
        """Find historical decisions most similar to the given situation.

        Uses Jaccard similarity over tokenized text. Returns up to `limit`
        results ordered by descending similarity.
        """
        needles = _tokenize(situation)
        if not needles:
            return []
        with self._lock:
            scored: list[AnalogousDecision] = []
            for record in self._records.values():
                if record.tenant_id != tenant_id or record.workspace_id != workspace_id:
                    continue
                haystack = _tokenize(record.situation + " " + " ".join(record.tags))
                if not haystack:
                    continue
                intersection = needles & haystack
                union = needles | haystack
                if not union:
                    continue
                similarity = len(intersection) / len(union)
                if similarity < min_similarity:
                    continue
                outcome = self._outcome_summary(record)
                scored.append(
                    AnalogousDecision(
                        decision=record,
                        similarity=similarity,
                        outcome_summary=outcome,
                    )
                )
            scored.sort(key=lambda x: x.similarity, reverse=True)
            return scored[:limit]

    def recent(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 20,
    ) -> list[DecisionRecord]:
        with self._lock:
            filtered = [
                r for r in self._records.values()
                if r.tenant_id == tenant_id and r.workspace_id == workspace_id
            ]
            filtered.sort(key=lambda r: r.executed_at, reverse=True)
            return filtered[:limit]

    # ── Internals ──────────────────────────────────────────────────────────

    def _outcome_summary(self, record: DecisionRecord) -> str:
        parts = [f"Chose option {record.chosen_option_id}", f"Outcome: {record.outcome_status}"]
        if record.financial_impact is not None:
            parts.append(f"Financial impact: {record.financial_impact:+.2f}")
        if record.actual_result:
            parts.append(record.actual_result)
        return "; ".join(parts)


_singleton: DecisionMemory | None = None


def get_decision_memory() -> DecisionMemory:
    """Return the process-wide singleton DecisionMemory."""
    global _singleton
    if _singleton is None:
        _singleton = DecisionMemory()
    return _singleton


def reset_decision_memory() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
