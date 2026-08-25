"""Knowledge Module — Program J Workstream E.

This module provides the Knowledge Layer for Cortex:

Components:
- Knowledge Models: KnowledgeRule, KnowledgeConstraint, Playbook, SLA, KnowledgePolicy
- Rule Engine: Evaluates rules/constraints/SLAs against world state
- Constraints: Pre-defined constraint factories
- Playbooks: Pre-defined SOP factories
- SLAs: Pre-defined SLA factories
- Policies: Bundled knowledge artifact factories

The Knowledge Layer ensures that:
- Simulations respect business rules
- World state changes trigger appropriate actions
- Constraints are never violated
- SLAs are tracked and breaches escalated
"""

from app.modules.knowledge.constraints import (
    capacity_range_constraint,
    data_residency_constraint,
    inventory_floor_constraint,
    lead_time_ceiling_constraint,
    supplier_health_floor_constraint,
)
from app.modules.knowledge.knowledge_models import (
    SLA,
    ApprovalRequirement,
    KnowledgeConstraint,
    KnowledgePolicy,
    KnowledgeRule,
    KnowledgeType,
    Playbook,
    PlaybookStep,
    RuleAction,
    RuleCondition,
    RuleSeverity,
    RuleTrigger,
)
from app.modules.knowledge.playbooks import (
    cyber_incident_playbook,
    demand_surge_playbook,
    factory_shutdown_playbook,
    inventory_shortage_playbook,
    supplier_disruption_playbook,
)
from app.modules.knowledge.policies import (
    compliance_policy,
    customer_service_policy,
    emergency_production_approval,
    inventory_management_policy,
    large_order_approval,
    risk_management_policy,
    supplier_change_approval,
    supplier_management_policy,
)
from app.modules.knowledge.rule_engine import (
    ConstraintViolation,
    RuleEngine,
    RuleEngineResult,
    RuleEvaluation,
    SLABreach,
)
from app.modules.knowledge.sla import (
    delivery_time_sla,
    inventory_availability_sla,
    order_fulfillment_rate_sla,
    platinum_customer_delivery_sla,
    production_uptime_sla,
    supplier_on_time_sla,
)

__all__ = [
    # Models
    "ApprovalRequirement",
    "KnowledgeConstraint",
    "KnowledgePolicy",
    "KnowledgeRule",
    "KnowledgeType",
    "Playbook",
    "PlaybookStep",
    "RuleAction",
    "RuleCondition",
    "RuleSeverity",
    "RuleTrigger",
    "SLA",
    # Engine
    "ConstraintViolation",
    "RuleEngine",
    "RuleEngineResult",
    "RuleEvaluation",
    "SLABreach",
    # Constraints
    "capacity_range_constraint",
    "data_residency_constraint",
    "inventory_floor_constraint",
    "lead_time_ceiling_constraint",
    "supplier_health_floor_constraint",
    # Playbooks
    "cyber_incident_playbook",
    "demand_surge_playbook",
    "factory_shutdown_playbook",
    "inventory_shortage_playbook",
    "supplier_disruption_playbook",
    # SLAs
    "delivery_time_sla",
    "inventory_availability_sla",
    "order_fulfillment_rate_sla",
    "platinum_customer_delivery_sla",
    "production_uptime_sla",
    "supplier_on_time_sla",
    # Policies
    "compliance_policy",
    "customer_service_policy",
    "emergency_production_approval",
    "inventory_management_policy",
    "large_order_approval",
    "risk_management_policy",
    "supplier_change_approval",
    "supplier_management_policy",
]
