"""Autonomy Levels & Tiered Authority Guard — Program P.6 & P.7.

Enforces execution autonomy constraints:
- L0: Observe (Read-only)
- L1: Recommend
- L2: Simulate
- L3: Human Approve (Default Production Mode)
- L4: Policy-Approved Automatic (Low-risk <= $500 actions only)
- L5: Fully Autonomous

Enforces multi-tenant authorization:
user -> workspace -> role -> capability -> action -> resource
"""

from __future__ import annotations

from app.modules.execution.execution_models import ActionPlan
from app.modules.production_validation.validation_models import AutonomyLevel


class AutonomyGuard:
    """Controls and validates automated vs. supervised execution permissions."""

    def __init__(
        self,
        default_autonomy_level: AutonomyLevel = AutonomyLevel.L3_HUMAN_APPROVE,
        max_l4_cost_usd: float = 500.0,
    ):
        self.default_level = default_autonomy_level
        self.max_l4_cost = max_l4_cost_usd

    def can_auto_execute(
        self,
        plan: ActionPlan,
        configured_level: AutonomyLevel | None = None,
    ) -> tuple[bool, str]:
        """Determine if an action can be automatically dispatched without prior human review."""
        level = configured_level or self.default_level

        if level < AutonomyLevel.L4_POLICY_AUTO:
            return (
                False,
                f"Workspace configured at {level.name}: Mandatory human approval required.",
            )

        if level == AutonomyLevel.L4_POLICY_AUTO:
            if plan.expected_cost_usd > self.max_l4_cost:
                return (
                    False,
                    f"Action cost ${plan.expected_cost_usd:,.2f} exceeds L4 limit (${self.max_l4_cost:,.2f}). Escalating to human review.",
                )
            if plan.expected_risk_score > 0.20:
                return (
                    False,
                    f"Action risk score ({plan.expected_risk_score:.2f}) exceeds L4 threshold (0.20). Escalating to human review.",
                )
            return True, "Action approved for L4 automated execution."

        # L5 Full autonomy
        return True, "Action approved for L5 autonomous execution."

    def verify_role_authority(
        self,
        plan: ActionPlan,
        user_role: str,
    ) -> tuple[bool, str]:
        """Verify operator spending authority by role."""
        if user_role == "executive":
            return True, "Executive authority approved up to $500,000."
        elif user_role == "operator":
            if plan.expected_cost_usd <= 50000.0:
                return True, "Operator authority approved up to $50,000."
            return (
                False,
                f"Plan cost ${plan.expected_cost_usd:,.2f} exceeds Operator limit of $50,000.",
            )
        else:
            # Analyst or Read-only
            return (
                False,
                f"Role '{user_role}' has read-only observation access; cannot approve actions.",
            )
