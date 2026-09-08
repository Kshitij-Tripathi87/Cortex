"""Nexus v0.7 — Recommendation Evaluation.

Every recommendation gets a measurable outcome, allowing Nexus to
answer: "How often do your recommendations actually outperform the
alternatives?"

Tracks:
  recommended_action
  alternative_actions
  predicted_nev / sla / cost
  confidence
→ after outcome:
  actual_nev / sla / cost
  outcome
→ compute:
  recommendation_accuracy
  recommendation_regret
  decision_success_rate
  simulation_error
"""

from app.modules.nexus_spine.recommendations.evaluator import (
    Recommendation,
    RecommendationEvaluator,
    get_recommendation_evaluator,
    reset_recommendation_evaluator,
)

__all__ = [
    "Recommendation",
    "RecommendationEvaluator",
    "get_recommendation_evaluator",
    "reset_recommendation_evaluator",
]
