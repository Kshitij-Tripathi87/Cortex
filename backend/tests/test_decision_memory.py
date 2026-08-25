"""Test Decision Memory & Outcome Capture — Program N.6.

Verifies:
- Decision memory record creation closing the loop
- Prediction error calculation (predicted vs actual revenue protected)
- Calibration analytics querying
"""

from __future__ import annotations

from app.modules.execution.decision_memory import DecisionMemoryStore
from app.modules.execution.execution_models import (
    ActionPlan,
    ExecutionResult,
    ExecutionSystem,
    OperatorDecision,
    PlanStatus,
)
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestDecisionMemory:
    def test_capture_decision_memory_and_analytics(self) -> None:
        """Executed action and real-world outcome are captured into decision memory."""
        store = DecisionMemoryStore()

        plan = ActionPlan(
            plan_id="plan_mem_01",
            workspace_id="ws_mem",
            world_id="world_mem",
            objective="Prevent plant shutdown",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_01", quantity=2.0),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=3000.0,
            expected_benefit_usd=40000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_01"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.COMPLETED,
        )

        exec_res = ExecutionResult(
            execution_id="exec_01",
            plan_id="plan_mem_01",
            target_system=ExecutionSystem.PROCUREMENT,
            idempotency_key="idem_01",
            success=True,
            external_transaction_id="TX_123",
            latency_ms=35.0,
        )

        # Record with actual outcome of $38,000 saved (vs $40,000 predicted)
        record = store.capture_decision_outcome(
            workspace_id="ws_mem",
            world_id="world_mem",
            plan=plan,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="operator_01",
            execution_result=exec_res,
            actual_outcome_revenue_saved_usd=38000.0,
        )

        assert record.record_id.startswith("mem_")
        assert record.actual_outcome_revenue_saved_usd == 38000.0
        assert record.predicted_vs_actual_error_pct == 5.0  # (40000 - 38000) / 40000 = 5%
        assert record.flywheel_feedback_applied is True

        # Query analytics
        analytics = store.get_calibration_analytics("ws_mem")
        assert analytics["total_decisions"] == 1
        assert analytics["total_actual_revenue_saved_usd"] == 38000.0
        assert analytics["approval_rate_pct"] == 100.0
        assert analytics["mean_prediction_error_pct"] == 5.0
