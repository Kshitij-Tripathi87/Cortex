"""Nexus Recommendation Evaluator — measurable outcomes for every recommendation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Recommendation:
    """A recommendation with predicted and (later) actual KPIs."""
    recommendation_id: str
    decision_id: str | None
    tenant_id: str
    workspace_id: str

    recommended_action: str
    alternative_actions: list[dict[str, Any]]
    predicted_nev: float
    predicted_sla: float
    predicted_cost: float
    confidence: float
    model_version: str | None

    actual_nev: float | None = None
    actual_sla: float | None = None
    actual_cost: float | None = None
    outcome: str | None = None  # success|failure|mixed

    recommendation_accuracy: float | None = None
    recommendation_regret: float | None = None
    decision_success_rate: float | None = None
    simulation_error: float | None = None

    scenario_id: str | None = None
    evidence_root_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    evaluated_at: datetime | None = None

    def evaluate(self, *, actual_nev: float, actual_sla: float, actual_cost: float, outcome: str) -> None:
        """Close the loop: record actual outcomes and compute metrics."""
        self.actual_nev = actual_nev
        self.actual_sla = actual_sla
        self.actual_cost = actual_cost
        self.outcome = outcome

        # Accuracy: how close was NEV prediction?
        if abs(self.predicted_nev) > 0.001:
            self.recommendation_accuracy = max(0.0, 1.0 - abs(actual_nev - self.predicted_nev) / abs(self.predicted_nev))
        else:
            self.recommendation_accuracy = 1.0 if abs(actual_nev) < 0.001 else 0.0

        # Regret: how much worse was the chosen action vs hypothetical best alternative
        # In a closed loop we'd compare with actual outcomes of alternatives;
        # here we measure how much NEV we left on the table.
        self.recommendation_regret = max(0.0, self.predicted_nev - actual_nev)

        # Simulation error: how wrong was the cost simulation
        if self.predicted_cost > 0:
            self.simulation_error = abs(actual_cost - self.predicted_cost) / self.predicted_cost

        self.evaluated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "decision_id": self.decision_id,
            "recommended_action": self.recommended_action,
            "alternative_actions": self.alternative_actions,
            "predicted_nev": round(self.predicted_nev, 2),
            "predicted_sla": round(self.predicted_sla, 4),
            "predicted_cost": round(self.predicted_cost, 2),
            "confidence": round(self.confidence, 4),
            "model_version": self.model_version,
            "actual_nev": round(self.actual_nev, 2) if self.actual_nev is not None else None,
            "actual_sla": round(self.actual_sla, 4) if self.actual_sla is not None else None,
            "actual_cost": round(self.actual_cost, 2) if self.actual_cost is not None else None,
            "outcome": self.outcome,
            "recommendation_accuracy": round(self.recommendation_accuracy, 4) if self.recommendation_accuracy is not None else None,
            "recommendation_regret": round(self.recommendation_regret, 2) if self.recommendation_regret is not None else None,
            "simulation_error": round(self.simulation_error, 4) if self.simulation_error is not None else None,
            "scenario_id": self.scenario_id,
            "evidence_root_id": self.evidence_root_id,
            "created_at": self.created_at.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
        }


class RecommendationEvaluator:
    """Tracks and aggregates recommendation performance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._recommendations: dict[str, Recommendation] = {}

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        recommended_action: str,
        alternative_actions: list[dict[str, Any]],
        predicted_nev: float,
        predicted_sla: float,
        predicted_cost: float,
        confidence: float,
        decision_id: str | None = None,
        model_version: str | None = None,
        scenario_id: str | None = None,
        evidence_root_id: str | None = None,
    ) -> Recommendation:
        with self._lock:
            rec = Recommendation(
                recommendation_id=f"REC-{uuid4().hex[:10]}",
                decision_id=decision_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                recommended_action=recommended_action,
                alternative_actions=alternative_actions,
                predicted_nev=predicted_nev,
                predicted_sla=predicted_sla,
                predicted_cost=predicted_cost,
                confidence=confidence,
                model_version=model_version,
                scenario_id=scenario_id,
                evidence_root_id=evidence_root_id,
            )
            self._recommendations[rec.recommendation_id] = rec
            return rec

    def evaluate(
        self,
        recommendation_id: str,
        *,
        actual_nev: float,
        actual_sla: float,
        actual_cost: float,
        outcome: str = "success",
    ) -> Recommendation | None:
        with self._lock:
            rec = self._recommendations.get(recommendation_id)
            if rec is None:
                return None
            rec.evaluate(
                actual_nev=actual_nev,
                actual_sla=actual_sla,
                actual_cost=actual_cost,
                outcome=outcome,
            )
            return rec

    def get(self, recommendation_id: str) -> Recommendation | None:
        with self._lock:
            return self._recommendations.get(recommendation_id)

    def list_by_workspace(self, tenant_id: str, workspace_id: str, limit: int = 100) -> list[Recommendation]:
        with self._lock:
            recs = [
                r for r in self._recommendations.values()
                if r.tenant_id == tenant_id and r.workspace_id == workspace_id
            ]
            recs.sort(key=lambda r: r.created_at, reverse=True)
            return recs[:limit]

    def performance_summary(self, tenant_id: str, workspace_id: str) -> dict[str, Any]:
        """Aggregate performance metrics — answers: 'how good are our recommendations?'."""
        with self._lock:
            recs = [
                r for r in self._recommendations.values()
                if r.tenant_id == tenant_id and r.workspace_id == workspace_id
            ]
            evaluated = [r for r in recs if r.outcome is not None]
            total = len(recs)
            n_eval = len(evaluated)
            if n_eval == 0:
                return {
                    "total_recommendations": total,
                    "evaluated": 0,
                    "decision_success_rate": 0.0,
                    "avg_recommendation_accuracy": 0.0,
                    "avg_recommendation_regret": 0.0,
                    "avg_simulation_error": 0.0,
                    "pending_evaluation": total,
                }
            successes = [r for r in evaluated if r.outcome == "success"]
            avg_acc = sum(r.recommendation_accuracy or 0 for r in evaluated) / n_eval
            avg_regret = sum(r.recommendation_regret or 0 for r in evaluated) / n_eval
            avg_sim_error = sum(r.simulation_error or 0 for r in evaluated) / n_eval
            return {
                "total_recommendations": total,
                "evaluated": n_eval,
                "decision_success_rate": round(len(successes) / n_eval, 4),
                "avg_recommendation_accuracy": round(avg_acc, 4),
                "avg_recommendation_regret": round(avg_regret, 2),
                "avg_simulation_error": round(avg_sim_error, 4),
                "pending_evaluation": total - n_eval,
            }


_singleton: RecommendationEvaluator | None = None


def get_recommendation_evaluator() -> RecommendationEvaluator:
    global _singleton
    if _singleton is None:
        _singleton = RecommendationEvaluator()
    return _singleton


def reset_recommendation_evaluator() -> None:
    global _singleton
    _singleton = None
