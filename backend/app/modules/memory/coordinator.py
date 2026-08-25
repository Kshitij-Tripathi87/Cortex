"""Memory Coordinator 2.0 — Unified 4-Tier Memory Flywheel.

Coordinates:
1. Operational Memory: Real-time World State & active variables
2. Episodic Memory: Incidents, disruption timelines & root causes
3. Decision Memory: Closed-loop Decision Records & prediction error calculations
4. Semantic Vector Memory: Precedents, operating policies & lessons learned

When an outcome is realized, the coordinator:
- Computes prediction error percentage against the Decision Record
- Aggregates Brier and calibration metrics
- Automatically indexes the retrospective lesson into Semantic Vector Memory
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.memory.decision_memory import (
    DecisionMemoryEngine,
    get_decision_memory,
)
from app.modules.memory.episodic_memory import (
    EpisodicMemoryEngine,
    get_episodic_memory,
)
from app.modules.memory.operational_memory import (
    OperationalMemoryEngine,
    get_operational_memory,
)
from app.modules.memory.semantic_memory import (
    SemanticMemoryEngine,
    get_semantic_memory,
)


@dataclass
class ClosedLoopOutcomeResult:
    """Outcome recording with automatic prediction error and vector indexing."""

    decision_id: str
    predicted_impact: float
    realized_impact: float
    prediction_error_pct: float
    semantic_lesson_id: str
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "predicted_impact": self.predicted_impact,
            "realized_impact": self.realized_impact,
            "prediction_error_pct": round(self.prediction_error_pct, 2),
            "semantic_lesson_id": self.semantic_lesson_id,
            "recorded_at": self.recorded_at.isoformat(),
        }


class MemoryCoordinator:
    """Unified memory orchestrator maintaining the continuous learning flywheel."""

    def __init__(
        self,
        operational: OperationalMemoryEngine | None = None,
        episodic: EpisodicMemoryEngine | None = None,
        decision: DecisionMemoryEngine | None = None,
        semantic: SemanticMemoryEngine | None = None,
    ) -> None:
        self.operational = operational or get_operational_memory()
        self.episodic = episodic or get_episodic_memory()
        self.decision = decision or get_decision_memory()
        self.semantic = semantic or get_semantic_memory()

    async def record_closed_loop_outcome(
        self,
        tenant_id: str,
        workspace_id: str,
        decision_id: str,
        actual_cost_usd: float,
        actual_protected_revenue_usd: float,
        notes: str = "",
    ) -> ClosedLoopOutcomeResult:
        """Record decision outcome, compute prediction error, and index lesson into vector memory."""
        # 1. Update Decision Record in Decision Memory
        updated_decision = self.decision.record_outcome(
            decision_id=decision_id,
            actual_cost_usd=actual_cost_usd,
            actual_protected_revenue_usd=actual_protected_revenue_usd,
            lesson_learned=notes,
        )
        if not updated_decision:
            raise ValueError(f"Decision '{decision_id}' not found in memory")

        pred_err = updated_decision.prediction_error_pct or 0.0

        # 2. Extract lesson text
        lesson_text = (
            f"Decision Record '{decision_id}': "
            f"Predicted revenue protection ${updated_decision.predicted_protected_revenue_usd:,.0f} vs "
            f"Realized outcome ${actual_protected_revenue_usd:,.0f}. "
            f"Prediction Error: {pred_err:.1f}%. Rationale: {updated_decision.operator_rationale}. "
            f"Operator: {updated_decision.operator_id}. Notes: {notes}"
        )

        # 3. Vectorize and store lesson in Semantic Memory
        lesson_doc = self.semantic.index_document(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            doc_type="decision_precedent",
            title=f"Retrospective Lesson: Decision {decision_id}",
            content=lesson_text,
            metadata={
                "decision_id": decision_id,
                "prediction_error_pct": pred_err,
            },
        )

        return ClosedLoopOutcomeResult(
            decision_id=decision_id,
            predicted_impact=updated_decision.predicted_protected_revenue_usd,
            realized_impact=actual_protected_revenue_usd,
            prediction_error_pct=pred_err,
            semantic_lesson_id=lesson_doc.doc_id,
        )

    async def query_deliberative_context(
        self,
        tenant_id: str,
        workspace_id: str,
        disruption_query: str,
    ) -> dict[str, Any]:
        """Aggregate cross-tier memory context for the multi-agent supervisor."""
        live_state = self.operational.get_state(workspace_id)
        precedents = self.semantic.search_similar(
            query=disruption_query,
            workspace_id=workspace_id,
            doc_type="decision_precedent",
            limit=3,
            min_similarity=0.1,
        )

        return {
            "live_world_state": live_state.to_dict() if live_state else None,
            "relevant_precedents": [
                {"title": doc.title, "content": doc.content, "score": round(score, 3)}
                for score, doc in precedents
            ],
        }


# Global memory coordinator singleton
_global_coordinator: MemoryCoordinator | None = None


def get_memory_coordinator() -> MemoryCoordinator:
    """Retrieve or initialize the global memory coordinator singleton."""
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = MemoryCoordinator()
    return _global_coordinator
