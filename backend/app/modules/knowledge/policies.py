"""Policies — Bundled Knowledge Artifacts.

Program J (World State & Digital Twin) policies module:

Policies group related rules, constraints, playbooks, and SLAs
into cohesive units that can be applied together.

Pre-defined policies:
- Inventory Management Policy
- Supplier Management Policy
- Customer Service Policy
- Compliance Policy
- Risk Management Policy
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.knowledge.knowledge_models import (
    ApprovalRequirement,
    KnowledgePolicy,
    RuleCondition,
    RuleTrigger,
)


def inventory_management_policy(workspace_id: str) -> KnowledgePolicy:
    """Bundle all inventory-related rules, constraints, SLAs."""
    return KnowledgePolicy(
        policy_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Inventory Management Policy",
        description="Standard policy for inventory management",
        domain="inventory",
        sla_ids=[],  # Would link to actual SLA IDs
        tags=["inventory", "operations"],
    )


def supplier_management_policy(workspace_id: str) -> KnowledgePolicy:
    """Bundle all supplier-related knowledge."""
    return KnowledgePolicy(
        policy_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Supplier Management Policy",
        description="Standard policy for supplier relationship management",
        domain="supplier",
        tags=["supplier", "procurement"],
    )


def customer_service_policy(workspace_id: str) -> KnowledgePolicy:
    """Bundle all customer-facing SLAs and rules."""
    return KnowledgePolicy(
        policy_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Customer Service Policy",
        description="Standard policy for customer service and SLAs",
        domain="customer",
        tags=["customer", "service"],
    )


def compliance_policy(workspace_id: str) -> KnowledgePolicy:
    """Bundle all compliance requirements."""
    return KnowledgePolicy(
        policy_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Compliance Policy",
        description="Standard policy for regulatory compliance",
        domain="compliance",
        tags=["compliance", "regulatory"],
    )


def risk_management_policy(workspace_id: str) -> KnowledgePolicy:
    """Bundle all risk management rules."""
    return KnowledgePolicy(
        policy_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Risk Management Policy",
        description="Standard policy for risk management",
        domain="risk",
        tags=["risk", "management"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Approval Requirements
# ─────────────────────────────────────────────────────────────────────────────


def large_order_approval(workspace_id: str, threshold_units: int = 1000) -> ApprovalRequirement:
    """Orders above threshold_units require manager approval."""
    return ApprovalRequirement(
        approval_id=str(uuid7()),
        workspace_id=workspace_id,
        action_type="order_placed",
        description=f"Orders above {threshold_units} units require manager approval",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="order.quantity",
                    operator="gt",
                    value=threshold_units,
                ),
            ],
        ),
        approver_role="manager",
        min_approvers=1,
        timeout_hours=24,
    )


def supplier_change_approval(workspace_id: str) -> ApprovalRequirement:
    """Supplier changes require director approval."""
    return ApprovalRequirement(
        approval_id=str(uuid7()),
        workspace_id=workspace_id,
        action_type="supplier_change",
        description="Changing suppliers requires director approval",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="action.type",
                    operator="eq",
                    value="supplier_change",
                ),
            ],
        ),
        approver_role="director",
        min_approvers=1,
        timeout_hours=72,
    )


def emergency_production_approval(workspace_id: str) -> ApprovalRequirement:
    """Emergency production runs require VP approval."""
    return ApprovalRequirement(
        approval_id=str(uuid7()),
        workspace_id=workspace_id,
        action_type="emergency_production",
        description="Emergency production runs require VP approval",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="action.type",
                    operator="eq",
                    value="emergency_production",
                ),
            ],
        ),
        approver_role="vp_operations",
        min_approvers=2,  # VP + Director
        timeout_hours=12,
        auto_approve_if_inactive=False,
    )
