"""Test Tiered Autonomy Guard & Security — Program P.6 & P.7.

Verifies:
- Enforcement of autonomy tiers (L0 to L5)
- Prevention of unauthorized automated execution under L3
- Multi-tier role spending limits (Operator <= $50k vs Executive <= $500k)
"""

from __future__ import annotations

from app.modules.execution.execution_models import ActionPlan, ExecutionSystem, PlanStatus
from app.modules.production_validation.autonomy_guard import AutonomyGuard
from app.modules.production_validation.validation_models import AutonomyLevel
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestAutonomyAndSecurity:
    def test_autonomy_level_dispatch_constraints(self) -> None:
        """Actions under L3 require human approval; low-risk actions under L4 can auto-execute."""
        guard = AutonomyGuard(max_l4_cost_usd=500.0)

        # $3,500 material action
        plan_material = ActionPlan(
            plan_id="p_mat",
            workspace_id="ws_sec",
            world_id="w_sec",
            objective="Supplier charter",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_1", cost_usd=3500.0),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=3500.0,
            expected_benefit_usd=40000.0,
            expected_risk_score=0.15,
            affected_entities=["sup_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        # $250 minor action
        plan_minor = ActionPlan(
            plan_id="p_min",
            workspace_id="ws_sec",
            world_id="w_sec",
            objective="Minor adjustment",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_1", cost_usd=250.0),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=250.0,
            expected_benefit_usd=5000.0,
            expected_risk_score=0.05,
            affected_entities=["sup_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        # Under L3: Both require human approval
        can_l3_mat, _ = guard.can_auto_execute(
            plan_material, configured_level=AutonomyLevel.L3_HUMAN_APPROVE
        )
        assert can_l3_mat is False

        can_l3_min, _ = guard.can_auto_execute(
            plan_minor, configured_level=AutonomyLevel.L3_HUMAN_APPROVE
        )
        assert can_l3_min is False

        # Under L4: Minor can auto-execute, Material escalates
        can_l4_min, _ = guard.can_auto_execute(
            plan_minor, configured_level=AutonomyLevel.L4_POLICY_AUTO
        )
        assert can_l4_min is True

        can_l4_mat, _ = guard.can_auto_execute(
            plan_material, configured_level=AutonomyLevel.L4_POLICY_AUTO
        )
        assert can_l4_mat is False

    def test_role_spending_authority(self) -> None:
        """Operator approved up to $50k; Executive up to $500k."""
        guard = AutonomyGuard()

        plan_60k = ActionPlan(
            plan_id="p_60k",
            workspace_id="ws_sec",
            world_id="w_sec",
            objective="Large PO",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_1", cost_usd=60000.0),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=60000.0,
            expected_benefit_usd=200000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        # Operator -> Rejected
        ok_op, msg_op = guard.verify_role_authority(plan_60k, user_role="operator")
        assert ok_op is False
        assert "exceeds Operator limit" in msg_op

        # Executive -> Approved
        ok_exec, msg_exec = guard.verify_role_authority(plan_60k, user_role="executive")
        assert ok_exec is True
        assert "Executive authority approved" in msg_exec
