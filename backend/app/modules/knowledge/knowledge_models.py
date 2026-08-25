"""Knowledge Models — Immutable Contracts for the Knowledge Layer.

Program J (World State & Digital Twin) knowledge layer:

The Knowledge Layer encodes business logic, rules, SOPs, contracts,
SLAs, and policies that constrain world state and guide decisions.

Knowledge Types:
- Business Rules: IF-THEN logic that fires on conditions
- SOPs: Standard Operating Procedures (multi-step playbooks)
- Contracts: Binding agreements (commitments, terms)
- SLAs: Service Level Agreements (performance targets)
- Compliance: Regulatory requirements
- Risk Rules: Constraints to mitigate risk
- Escalation: When and how to escalate
- Approvals: Who can approve what

All models are immutable (frozen dataclasses).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class KnowledgeType(StrEnum):
    """Types of knowledge artifacts."""

    BUSINESS_RULE = "business_rule"
    SOP = "sop"
    CONTRACT = "contract"
    SLA = "sla"
    COMPLIANCE = "compliance"
    RISK_RULE = "risk_rule"
    ESCALATION = "escalation"
    APPROVAL = "approval"


class RuleSeverity(StrEnum):
    """Severity of a rule violation or trigger."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleAction(StrEnum):
    """Actions a rule can take when triggered."""

    NOTIFY = "notify"
    WARN = "warn"
    BLOCK = "block"
    EXPEDITE = "expedite"
    ESCALATE = "escalate"
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"
    TRIGGER_PLAYBOOK = "trigger_playbook"


# ─────────────────────────────────────────────────────────────────────────────
# Rule Conditions
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RuleCondition:
    """A single condition in a rule.

    Format: variable_id + operator + value
    Example: "inventory.warehouse.wh_001" + "lt" + 100
    """

    variable_id: str  # e.g., "inventory.warehouse.wh_001"
    operator: str  # eq, ne, lt, le, gt, ge, in, between, contains
    value: Any  # Threshold value

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_id": self.variable_id,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass(frozen=True)
class RuleTrigger:
    """A composite trigger: all conditions must be met (AND logic).

    Example:
        Customer = Platinum AND Inventory < 5 days
    """

    conditions: list[RuleCondition] = field(default_factory=list)
    combinator: str = "and"  # "and" or "or"

    def to_dict(self) -> dict[str, Any]:
        return {
            "conditions": [c.to_dict() for c in self.conditions],
            "combinator": self.combinator,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Rule
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgeRule:
    """A business rule: IF conditions THEN action.

    Example:
        IF customer_priority == "platinum" AND inventory < 5
        THEN EXPEDITE
    """

    rule_id: str
    workspace_id: str
    name: str
    description: str
    trigger: RuleTrigger
    action: RuleAction
    severity: RuleSeverity = RuleSeverity.MEDIUM
    action_params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger.to_dict(),
            "action": self.action.value,
            "severity": self.severity.value,
            "action_params": dict(self.action_params),
            "enabled": self.enabled,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Constraint
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgeConstraint:
    """A constraint that must NEVER be violated.

    Unlike rules (which trigger actions), constraints are hard limits.
    Used for:
    - Risk limits (max lead time, min inventory)
    - Compliance requirements (data residency)
    - Contractual obligations (minimum order quantity)
    """

    constraint_id: str
    workspace_id: str
    name: str
    description: str
    variable_id: str
    operator: str  # lt, le, gt, ge, eq, ne, between
    min_value: Any = None
    max_value: Any = None
    severity: RuleSeverity = RuleSeverity.CRITICAL
    violation_message: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "variable_id": self.variable_id,
            "operator": self.operator,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "severity": self.severity.value,
            "violation_message": self.violation_message,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SLA
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SLA:
    """A Service Level Agreement — performance targets with breach tracking.

    Example:
        - Delivery time: 95% of orders delivered within 5 days
        - Inventory availability: 99% of SKUs in stock
    """

    sla_id: str
    workspace_id: str
    name: str
    description: str
    metric_name: str  # e.g., "delivery_time", "inventory_availability"
    target_value: float  # e.g., 5.0 days, 99.0%
    comparison: str = "le"  # le, ge, lt, gt, eq
    measurement_window: str = "daily"  # daily, weekly, monthly
    breach_action: RuleAction = RuleAction.ESCALATE
    customer_facing: bool = False
    contract_id: str | None = None  # Linked contract
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sla_id": self.sla_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "metric_name": self.metric_name,
            "target_value": self.target_value,
            "comparison": self.comparison,
            "measurement_window": self.measurement_window,
            "breach_action": self.breach_action.value,
            "customer_facing": self.customer_facing,
            "contract_id": self.contract_id,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Playbook (SOP)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlaybookStep:
    """A single step in a playbook/SOP."""

    step_number: int
    action: str  # Human-readable action description
    required_role: str | None = None  # Role required to execute
    estimated_duration_minutes: int | None = None
    conditions: list[RuleCondition] = field(default_factory=list)
    on_success: int | None = None  # Next step on success
    on_failure: int | None = None  # Next step on failure


@dataclass(frozen=True)
class Playbook:
    """A Standard Operating Procedure — a sequence of steps.

    Example:
        Playbook: "Respond to Supplier Disruption"
        Step 1: Notify procurement
        Step 2: Identify alternative suppliers
        Step 3: Issue emergency orders
        Step 4: Monitor delivery
    """

    playbook_id: str
    workspace_id: str
    name: str
    description: str
    trigger: RuleTrigger | None = None  # When this playbook should be invoked
    steps: list[PlaybookStep] = field(default_factory=list)
    estimated_total_duration_minutes: int = 0
    severity: RuleSeverity = RuleSeverity.MEDIUM
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger.to_dict() if self.trigger else None,
            "steps": [
                {
                    "step_number": s.step_number,
                    "action": s.action,
                    "required_role": s.required_role,
                    "estimated_duration_minutes": s.estimated_duration_minutes,
                    "conditions": [c.to_dict() for c in s.conditions],
                    "on_success": s.on_success,
                    "on_failure": s.on_failure,
                }
                for s in self.steps
            ],
            "estimated_total_duration_minutes": self.estimated_total_duration_minutes,
            "severity": self.severity.value,
            "enabled": self.enabled,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgePolicy:
    """A policy: a bundle of rules, constraints, and playbooks.

    Policies group related knowledge artifacts for a specific domain
    (e.g., "Inventory Policy", "Supplier Policy", "Compliance Policy").
    """

    policy_id: str
    workspace_id: str
    name: str
    description: str
    domain: str  # e.g., "inventory", "supplier", "compliance"
    rule_ids: list[str] = field(default_factory=list)
    constraint_ids: list[str] = field(default_factory=list)
    playbook_ids: list[str] = field(default_factory=list)
    sla_ids: list[str] = field(default_factory=list)
    enabled: bool = True
    version: int = 1
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "rule_ids": list(self.rule_ids),
            "constraint_ids": list(self.constraint_ids),
            "playbook_ids": list(self.playbook_ids),
            "sla_ids": list(self.sla_ids),
            "enabled": self.enabled,
            "version": self.version,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Approval
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovalRequirement:
    """Defines when approval is needed for an action."""

    approval_id: str
    workspace_id: str
    action_type: str  # e.g., "order_over_threshold", "supplier_change"
    description: str
    trigger: RuleTrigger  # When approval is required
    approver_role: str  # e.g., "manager", "director", "vp"
    min_approvers: int = 1
    timeout_hours: int | None = 72
    auto_approve_if_inactive: bool = False
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "workspace_id": self.workspace_id,
            "action_type": self.action_type,
            "description": self.description,
            "trigger": self.trigger.to_dict(),
            "approver_role": self.approver_role,
            "min_approvers": self.min_approvers,
            "timeout_hours": self.timeout_hours,
            "auto_approve_if_inactive": self.auto_approve_if_inactive,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }
