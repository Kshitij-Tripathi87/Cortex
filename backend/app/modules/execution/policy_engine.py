"""Policy & Safety Engine — Pre-Execution Constraint & Boundary Verification.

Program N.2 (Enterprise Policy & Safety Engine):
Validates all proposed ActionPlans before simulation and human review:
- Monetary spending authority
- Inventory safety buffer minimums
- Approved supplier and vendor lists
- Parameter range sanity checks
"""

from __future__ import annotations

from app.modules.execution.execution_models import ActionPlan, PolicyViolation
from app.modules.rl.rl_models import ActionType
from app.modules.world.world_models import StateVariableType, WorldState


class PolicyEngine:
    """Evaluates ActionPlans against hard enterprise safety policies."""

    def __init__(
        self,
        max_operator_spend_usd: float = 50000.0,
        min_warehouse_safety_stock: float = 100.0,
        disallowed_suppliers: set[str] | None = None,
    ):
        self.max_spend = max_operator_spend_usd
        self.min_safety_stock = min_warehouse_safety_stock
        self.disallowed_suppliers = disallowed_suppliers or {"sup_sanctioned_01", "sup_fraud_alert"}

    def validate(
        self,
        plan: ActionPlan,
        world_state: WorldState,
        operator_role: str = "operator",
    ) -> tuple[bool, list[PolicyViolation]]:
        """Validate an ActionPlan against enterprise policies."""
        violations: list[PolicyViolation] = []

        action = plan.action

        # 1. Monetary Spend Limit Check
        if plan.expected_cost_usd > self.max_spend and operator_role != "executive":
            violations.append(
                PolicyViolation(
                    rule_name="MonetarySpendAuthority",
                    severity="critical",
                    violation_message=(
                        f"Action cost ${plan.expected_cost_usd:,.2f} exceeds operator limit of "
                        f"${self.max_spend:,.2f}."
                    ),
                    remediation_suggestion="Escalate to Executive approval tier.",
                )
            )

        # 2. Supplier Blacklist / Compliance Check
        if action.entity_id in self.disallowed_suppliers or (
            action.target_entity_id and action.target_entity_id in self.disallowed_suppliers
        ):
            target = (
                action.target_entity_id
                if action.target_entity_id in self.disallowed_suppliers
                else action.entity_id
            )
            violations.append(
                PolicyViolation(
                    rule_name="SupplierComplianceCheck",
                    severity="critical",
                    violation_message=f"Supplier '{target}' is on the restricted/sanctioned vendor list.",
                    remediation_suggestion="Select an alternative GNN-recommended compliant supplier.",
                )
            )

        # 3. Warehouse Safety Stock Depletion Check
        if action.action_type == ActionType.TRANSFER_INVENTORY:
            src_wh = action.entity_id
            # Find warehouse current inventory
            src_var = next(
                (
                    v
                    for v in world_state.variables.values()
                    if v.entity_id == src_wh and v.variable_type == StateVariableType.INVENTORY
                ),
                None,
            )
            if src_var:
                curr_inv = float(src_var.raw_value)
                rem_inv = curr_inv - action.quantity
                if rem_inv < self.min_safety_stock:
                    violations.append(
                        PolicyViolation(
                            rule_name="MinimumSafetyBuffer",
                            severity="critical",
                            violation_message=(
                                f"Transfer of {action.quantity:.0f} units reduces {src_wh} to "
                                f"{rem_inv:.0f} units (below {self.min_safety_stock:.0f} safety threshold)."
                            ),
                            remediation_suggestion=f"Reduce transfer quantity to maximum of {max(0.0, curr_inv - self.min_safety_stock):.0f} units.",
                        )
                    )

        # 4. Parameter Sanity Check
        if action.quantity < 0:
            violations.append(
                PolicyViolation(
                    rule_name="NonNegativeQuantity",
                    severity="critical",
                    violation_message=f"Negative action quantity ({action.quantity}) is invalid.",
                    remediation_suggestion="Quantity must be greater than or equal to zero.",
                )
            )

        is_allowed = len(violations) == 0
        return is_allowed, violations
