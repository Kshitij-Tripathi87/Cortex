"""Test Closed-Loop Continuous Learning & Governance — Program O.

Verifies:
- Continuous learning flywheel report generation
- Model calibration tracking across GNN, RL, and Multi-Agent subsystems
- Cumulative revenue protected and operator acceptance metrics
"""

from __future__ import annotations

from app.modules.execution.decision_memory import DecisionMemoryStore
from app.modules.execution.execution_models import (
    ActionPlan,
    ExecutionSystem,
    OperatorDecision,
    PlanStatus,
)
from app.modules.governance.flywheel_service import ClosedLoopFlywheelService
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestClosedLoopGovernance:
    def test_governance_flywheel_report_generation(self) -> None:
        """Closed-loop flywheel service computes subsystem calibrations and overall health."""
        memory_store = DecisionMemoryStore()

        # Seed 2 decisions
        plan1 = ActionPlan(
            plan_id="p1",
            workspace_id="ws_gov",
            world_id="w1",
            objective="Obj 1",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_1"),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=4000.0,
            expected_benefit_usd=50000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.COMPLETED,
        )
        plan2 = ActionPlan(
            plan_id="p2",
            workspace_id="ws_gov",
            world_id="w1",
            objective="Obj 2",
            action=MitigationAction(
                ActionType.TRANSFER_INVENTORY, "wh_1", target_entity_id="wh_2", quantity=50
            ),
            target_system=ExecutionSystem.WMS,
            expected_cost_usd=400.0,
            expected_benefit_usd=20000.0,
            expected_risk_score=0.1,
            affected_entities=["wh_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.COMPLETED,
        )

        memory_store.capture_decision_outcome(
            workspace_id="ws_gov",
            world_id="w1",
            plan=plan1,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="op_1",
            actual_outcome_revenue_saved_usd=48000.0,  # 4% error
        )
        memory_store.capture_decision_outcome(
            workspace_id="ws_gov",
            world_id="w1",
            plan=plan2,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="op_1",
            actual_outcome_revenue_saved_usd=19000.0,  # 5% error
        )

        flywheel = ClosedLoopFlywheelService()
        report = flywheel.generate_governance_report("ws_gov", memory_store)

        assert report.workspace_id == "ws_gov"
        assert report.total_decisions_executed == 2
        assert report.total_revenue_saved_usd == 67000.0
        assert report.operator_acceptance_rate_pct == 100.0
        assert report.flywheel_health_score > 0.90
        assert len(report.subsystem_calibrations) == 3
        for cal in report.subsystem_calibrations:
            assert cal.drift_detected is False
            assert cal.status == "calibrated"
