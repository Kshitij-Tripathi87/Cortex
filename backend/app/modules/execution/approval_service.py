"""Human Approval & Decision Control Plane.

Program N.4 (Human-in-the-Loop Approval & Decision Briefs):
Presents clear decision cards containing:
- Incident summary
- Predicted impact
- Multi-option trade-off comparison
- Human operator decision choices (Approve, Reject, Modify, Simulate Alternative)
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.execution.execution_models import (
    ActionPlan,
    DecisionCard,
    DecisionCardOption,
    OperatorDecision,
    PlanStatus,
)
from app.modules.rl.rl_models import ActionType
from app.modules.world.world_models import WorldState


class ApprovalService:
    """Manages human operator decision cards and approval lifecycle."""

    def generate_decision_card(
        self,
        plan: ActionPlan,
        world_state: WorldState,
    ) -> DecisionCard:
        """Construct an audited decision card comparing mitigation options."""
        card_id = f"card_{uuid7()}"

        # 1. Build Multi-Option Comparison Table
        options = [
            DecisionCardOption(
                option_id="opt_rec",
                name=f"Recommended: {plan.action.action_type.value.replace('_', ' ').title()}",
                action_type=plan.action.action_type.value,
                cost_usd=plan.expected_cost_usd,
                revenue_protected_usd=plan.expected_benefit_usd,
                risk_level="Low" if plan.expected_risk_score < 0.3 else "Medium",
                estimated_duration_hours=8
                if plan.action.action_type == ActionType.EXPEDITE_SUPPLIER
                else 12,
                is_recommended=True,
            ),
            DecisionCardOption(
                option_id="opt_transfer",
                name="Alternative: Inter-Warehouse Stock Transfer",
                action_type=ActionType.TRANSFER_INVENTORY.value,
                cost_usd=plan.expected_cost_usd * 0.40,
                revenue_protected_usd=plan.expected_benefit_usd * 0.85,
                risk_level="Medium",
                estimated_duration_hours=16,
                is_recommended=False,
            ),
            DecisionCardOption(
                option_id="opt_noop",
                name="Inaction: Absorb Disruption Delay",
                action_type=ActionType.NOOP.value,
                cost_usd=0.0,
                revenue_protected_usd=0.0,
                risk_level="High",
                estimated_duration_hours=0,
                is_recommended=False,
            ),
        ]

        summary = (
            f"Supply chain operational anomaly detected on {', '.join(plan.affected_entities) or 'network'}. "
            f"Objective: {plan.objective}."
        )

        prediction = (
            f"Without intervention, disruption will result in ${plan.expected_benefit_usd:,.2f} "
            f"revenue exposure and potential SLA breach."
        )

        rationale = (
            f"Executing {plan.action.action_type.value} protects ${plan.expected_benefit_usd:,.2f} "
            f"for ${plan.expected_cost_usd:,.2f} expenditure (Net benefit: ${plan.expected_benefit_usd - plan.expected_cost_usd:,.2f})."
        )

        return DecisionCard(
            card_id=card_id,
            plan_id=plan.plan_id,
            incident_summary=summary,
            cortex_prediction=prediction,
            financial_exposure_usd=plan.expected_benefit_usd,
            options=options,
            recommendation_rationale=rationale,
        )

    def process_decision(
        self,
        plan: ActionPlan,
        decision: OperatorDecision,
        operator_id: str,
        modifications: dict[str, Any] | None = None,
    ) -> ActionPlan:
        """Transition plan status based on operator decision."""
        new_status = PlanStatus.APPROVED
        if decision == OperatorDecision.REJECT:
            new_status = PlanStatus.REJECTED
        elif decision == OperatorDecision.MODIFY:
            new_status = PlanStatus.MODIFIED
        elif decision == OperatorDecision.SIMULATE_ALTERNATIVE:
            new_status = PlanStatus.SIMULATION_PENDING

        return ActionPlan(
            plan_id=plan.plan_id,
            workspace_id=plan.workspace_id,
            world_id=plan.world_id,
            objective=plan.objective,
            action=plan.action,
            target_system=plan.target_system,
            expected_cost_usd=plan.expected_cost_usd,
            expected_benefit_usd=plan.expected_benefit_usd,
            expected_risk_score=plan.expected_risk_score,
            affected_entities=plan.affected_entities,
            prerequisites=plan.prerequisites,
            policy_version=plan.policy_version,
            simulation_id=plan.simulation_id,
            status=new_status,
            violations=plan.violations,
        )
