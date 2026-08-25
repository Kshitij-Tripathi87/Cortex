"""Decision Memory Engine — Complete Decision Lifecycles and Continuous Learning Flywheel.

Preserves the complete trace:
World State -> Recommendations -> Operator Choice -> Execution -> Actual Outcome -> Prediction Error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class DecisionRecord:
    """Complete record of a human-approved or rejected operational decision."""

    decision_id: str
    workspace_id: str
    tenant_id: str
    disruption_id: str
    world_state_version: int
    recommendations_presented: list[dict[str, Any]]
    chosen_action: dict[str, Any]
    operator_id: str
    operator_decision: str  # approved | rejected | modified
    operator_rationale: str
    predicted_cost_usd: float
    predicted_protected_revenue_usd: float
    actual_cost_usd: float | None = None
    actual_protected_revenue_usd: float | None = None
    prediction_error_pct: float | None = None
    lesson_learned: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    outcome_recorded_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "disruption_id": self.disruption_id,
            "world_state_version": self.world_state_version,
            "recommendations_presented": self.recommendations_presented,
            "chosen_action": self.chosen_action,
            "operator_id": self.operator_id,
            "operator_decision": self.operator_decision,
            "operator_rationale": self.operator_rationale,
            "predicted_cost_usd": round(self.predicted_cost_usd, 2),
            "predicted_protected_revenue_usd": round(self.predicted_protected_revenue_usd, 2),
            "actual_cost_usd": round(self.actual_cost_usd, 2) if self.actual_cost_usd is not None else None,
            "actual_protected_revenue_usd": round(self.actual_protected_revenue_usd, 2) if self.actual_protected_revenue_usd is not None else None,
            "prediction_error_pct": round(self.prediction_error_pct, 2) if self.prediction_error_pct is not None else None,
            "lesson_learned": self.lesson_learned,
            "created_at": self.created_at.isoformat(),
            "outcome_recorded_at": self.outcome_recorded_at.isoformat() if self.outcome_recorded_at else None,
        }


class DecisionMemoryEngine:
    """Manages long-lived decision records and closed-loop feedback calibration."""

    def __init__(self) -> None:
        self._records: dict[str, DecisionRecord] = {}

    def record_decision(self, record: DecisionRecord) -> None:
        """Store initial decision record."""
        self._records[record.decision_id] = record

    def record_outcome(
        self,
        decision_id: str,
        actual_cost_usd: float,
        actual_protected_revenue_usd: float,
        lesson_learned: str = "",
    ) -> DecisionRecord | None:
        """Update decision with realized outcome and compute prediction error."""
        record = self._records.get(decision_id)
        if not record:
            return None

        pred = record.predicted_protected_revenue_usd
        error_pct = (
            abs(actual_protected_revenue_usd - pred) / max(1.0, pred) * 100.0
            if pred > 0
            else 0.0
        )

        updated = DecisionRecord(
            decision_id=record.decision_id,
            workspace_id=record.workspace_id,
            tenant_id=record.tenant_id,
            disruption_id=record.disruption_id,
            world_state_version=record.world_state_version,
            recommendations_presented=record.recommendations_presented,
            chosen_action=record.chosen_action,
            operator_id=record.operator_id,
            operator_decision=record.operator_decision,
            operator_rationale=record.operator_rationale,
            predicted_cost_usd=record.predicted_cost_usd,
            predicted_protected_revenue_usd=record.predicted_protected_revenue_usd,
            actual_cost_usd=actual_cost_usd,
            actual_protected_revenue_usd=actual_protected_revenue_usd,
            prediction_error_pct=error_pct,
            lesson_learned=lesson_learned,
            created_at=record.created_at,
            outcome_recorded_at=datetime.now(UTC),
        )
        self._records[decision_id] = updated
        return updated

    def query_by_workspace(
        self, workspace_id: str, limit: int = 50
    ) -> list[DecisionRecord]:
        """Query decisions for workspace."""
        results = [
            r for r in self._records.values() if r.workspace_id == workspace_id
        ]
        results.sort(key=lambda x: x.created_at, reverse=True)
        return results[:limit]

    def get_calibration_summary(self, workspace_id: str) -> dict[str, Any]:
        """Compute calibration accuracy metrics across resolved decisions."""
        records = [
            r for r in self._records.values()
            if r.workspace_id == workspace_id and r.outcome_recorded_at is not None
        ]
        if not records:
            return {
                "total_decisions": len(self.query_by_workspace(workspace_id)),
                "resolved_outcomes": 0,
                "mean_prediction_error_pct": 0.0,
                "acceptance_rate": 1.0,
            }

        total = len(records)
        avg_error = sum(r.prediction_error_pct or 0.0 for r in records) / total
        approved = sum(1 for r in records if r.operator_decision == "approved")

        return {
            "total_decisions": len(self.query_by_workspace(workspace_id)),
            "resolved_outcomes": total,
            "mean_prediction_error_pct": round(avg_error, 2),
            "acceptance_rate": round(approved / max(1, total), 3),
        }


_global_decision_mem = DecisionMemoryEngine()


def get_decision_memory() -> DecisionMemoryEngine:
    return _global_decision_mem
