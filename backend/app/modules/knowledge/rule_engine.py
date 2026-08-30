"""Rule Engine — Evaluates Knowledge Rules Against World State.

Program J (World State & Digital Twin) rule engine:

The RuleEngine evaluates KnowledgeRules and KnowledgeConstraints
against a WorldState, determining which rules fire and which
constraints are violated.

Responsibilities:
- Evaluate rule triggers (IF conditions)
- Identify which rules fire
- Identify constraint violations
- Return ranked list of triggered actions

This is pure logic — no DB, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.knowledge.knowledge_models import (
    SLA,
    KnowledgeConstraint,
    KnowledgePolicy,
    KnowledgeRule,
    Playbook,
    RuleAction,
    RuleCondition,
    RuleSeverity,
    RuleTrigger,
)
from app.modules.world.state_projection import WorldState


@dataclass(frozen=True)
class RuleEvaluation:
    """Result of evaluating a single rule."""

    rule_id: str
    rule_name: str
    fired: bool
    action: RuleAction
    severity: RuleSeverity
    action_params: dict[str, Any] = field(default_factory=dict)
    matched_conditions: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "fired": self.fired,
            "action": self.action.value,
            "severity": self.severity.value,
            "action_params": dict(self.action_params),
            "matched_conditions": list(self.matched_conditions),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ConstraintViolation:
    """A constraint that was violated."""

    constraint_id: str
    constraint_name: str
    variable_id: str
    actual_value: Any
    expected_range: tuple[Any, Any] | None
    severity: RuleSeverity
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_name": self.constraint_name,
            "variable_id": self.variable_id,
            "actual_value": self.actual_value,
            "expected_range": self.expected_range,
            "severity": self.severity.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class SLABreach:
    """An SLA that was breached."""

    sla_id: str
    sla_name: str
    metric_name: str
    actual_value: float
    target_value: float
    comparison: str
    customer_facing: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "sla_id": self.sla_id,
            "sla_name": self.sla_name,
            "metric_name": self.metric_name,
            "actual_value": self.actual_value,
            "target_value": self.target_value,
            "comparison": self.comparison,
            "customer_facing": self.customer_facing,
        }


@dataclass(frozen=True)
class RuleEngineResult:
    """Complete result of rule engine evaluation."""

    state_hash: str
    fired_rules: list[RuleEvaluation] = field(default_factory=list)
    constraint_violations: list[ConstraintViolation] = field(default_factory=list)
    sla_breaches: list[SLABreach] = field(default_factory=list)
    triggered_playbooks: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    total_rules_evaluated: int = 0
    total_constraints_evaluated: int = 0
    total_slas_evaluated: int = 0

    def has_blocking_violations(self) -> bool:
        return any(v.severity == RuleSeverity.CRITICAL for v in self.constraint_violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_hash": self.state_hash,
            "fired_rules": [r.to_dict() for r in self.fired_rules],
            "constraint_violations": [v.to_dict() for v in self.constraint_violations],
            "sla_breaches": [b.to_dict() for b in self.sla_breaches],
            "triggered_playbooks": list(self.triggered_playbooks),
            "blocked_actions": list(self.blocked_actions),
            "total_rules_evaluated": self.total_rules_evaluated,
            "total_constraints_evaluated": self.total_constraints_evaluated,
            "total_slas_evaluated": self.total_slas_evaluated,
        }


class RuleEngine:
    """Evaluates rules, constraints, and SLAs against world state."""

    def __init__(self):
        pass

    def evaluate(
        self,
        state: WorldState,
        rules: list[KnowledgeRule] | None = None,
        constraints: list[KnowledgeConstraint] | None = None,
        slas: list[SLA] | None = None,
        playbooks: list[Playbook] | None = None,
        policies: list[KnowledgePolicy] | None = None,
    ) -> RuleEngineResult:
        """Evaluate all rules, constraints, and SLAs against the state.

        Args:
            state: The world state to evaluate against
            rules: Business rules to check
            constraints: Constraints to verify
            slas: SLAs to check for breaches
            playbooks: Playbooks to check for triggers
            policies: Policies (their bundled rules/constraints/SLAs are evaluated)

        Returns:
            RuleEngineResult with all evaluations
        """
        from app.modules.world.state_projection import create_state_snapshot

        state_hash = create_state_snapshot(state).state_hash

        fired_rules: list[RuleEvaluation] = []
        constraint_violations: list[ConstraintViolation] = []
        sla_breaches: list[SLABreach] = []
        triggered_playbooks: list[str] = []

        # Evaluate direct rules
        all_rules = list(rules or [])
        all_constraints = list(constraints or [])
        all_slas = list(slas or [])
        list(playbooks or [])

        # Expand policies into their components
        for policy in policies or []:
            if not policy.enabled:
                continue
            # In a real implementation, we'd look up the bundled rules by ID
            # For now, policies are just labels

        # Evaluate rules
        for rule in all_rules:
            if not rule.enabled:
                continue
            eval_result = self._evaluate_rule(state, rule)
            fired_rules.append(eval_result)
            if eval_result.fired and eval_result.action == RuleAction.TRIGGER_PLAYBOOK:
                triggered_playbooks.append(rule.action_params.get("playbook_id", ""))

        # Evaluate constraints
        for constraint in all_constraints:
            if not constraint.enabled:
                continue
            violation = self._evaluate_constraint(state, constraint)
            if violation is not None:
                constraint_violations.append(violation)

        # Evaluate SLAs
        for sla in all_slas:
            if not sla.enabled:
                continue
            breach = self._evaluate_sla(state, sla)
            if breach is not None:
                sla_breaches.append(breach)

        # Determine blocked actions
        blocked = []
        for violation in constraint_violations:
            if violation.severity == RuleSeverity.CRITICAL:
                blocked.append(violation.constraint_id)

        return RuleEngineResult(
            state_hash=state_hash,
            fired_rules=fired_rules,
            constraint_violations=constraint_violations,
            sla_breaches=sla_breaches,
            triggered_playbooks=[p for p in triggered_playbooks if p],
            blocked_actions=blocked,
            total_rules_evaluated=len(all_rules),
            total_constraints_evaluated=len(all_constraints),
            total_slas_evaluated=len(all_slas),
        )

    def evaluate_rules_only(
        self,
        state: WorldState,
        rules: list[KnowledgeRule],
    ) -> list[RuleEvaluation]:
        """Evaluate only rules (no constraints/SLAs)."""
        return [self._evaluate_rule(state, r) for r in rules if r.enabled]

    def evaluate_constraints_only(
        self,
        state: WorldState,
        constraints: list[KnowledgeConstraint],
    ) -> list[ConstraintViolation]:
        """Evaluate only constraints."""
        results = []
        for c in constraints:
            if not c.enabled:
                continue
            v = self._evaluate_constraint(state, c)
            if v is not None:
                results.append(v)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Internal Evaluation Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_rule(
        self,
        state: WorldState,
        rule: KnowledgeRule,
    ) -> RuleEvaluation:
        """Evaluate a single rule."""
        all_match, matched = self._evaluate_trigger(state, rule.trigger)
        return RuleEvaluation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            fired=all_match,
            action=rule.action,
            severity=rule.severity,
            action_params=rule.action_params,
            matched_conditions=matched,
            failure_reason=None if all_match else "Conditions not met",
        )

    def _evaluate_constraint(
        self,
        state: WorldState,
        constraint: KnowledgeConstraint,
    ) -> ConstraintViolation | None:
        """Evaluate a single constraint. Returns violation or None.

        Constraint semantics:
        - lt: value must be < max_value (violated if value >= max_value)
        - le: value must be <= max_value (violated if value > max_value)
        - gt: value must be > min_value (violated if value <= min_value)
        - ge: value must be >= min_value (violated if value < min_value)
        - between: value must be in [min_value, max_value]
        - eq: value must equal min_value (violated otherwise)
        - ne: value must not equal min_value (violated if equal)
        """
        var = state.variables.get(constraint.variable_id)
        if var is None:
            return None  # Variable doesn't exist, can't violate

        value = var.raw_value
        if not isinstance(value, (int, float)):
            return None

        violated = False

        op = constraint.operator
        if op == "lt":
            # value must be < max_value
            if constraint.max_value is not None and value >= constraint.max_value:
                violated = True
        elif op == "le":
            # value must be <= max_value
            if constraint.max_value is not None and value > constraint.max_value:
                violated = True
        elif op == "gt":
            # value must be > min_value
            if constraint.min_value is not None and value <= constraint.min_value:
                violated = True
        elif op == "ge":
            # value must be >= min_value
            if constraint.min_value is not None and value < constraint.min_value:
                violated = True
        elif op == "between":
            if constraint.min_value is not None and value < constraint.min_value or constraint.max_value is not None and value > constraint.max_value:
                violated = True
        elif op == "eq":
            if constraint.min_value is not None and value != constraint.min_value:
                violated = True
        elif op == "ne":  # noqa: SIM102
            if constraint.min_value is not None and value == constraint.min_value:
                violated = True

        if not violated:
            return None

        msg = constraint.violation_message or (
            f"Constraint {constraint.name} violated: "
            f"{constraint.variable_id}={value} violates {constraint.operator} "
            f"(min={constraint.min_value}, max={constraint.max_value})"
        )

        return ConstraintViolation(
            constraint_id=constraint.constraint_id,
            constraint_name=constraint.name,
            variable_id=constraint.variable_id,
            actual_value=value,
            expected_range=(constraint.min_value, constraint.max_value),
            severity=constraint.severity,
            message=msg,
        )

    def _evaluate_sla(
        self,
        state: WorldState,
        sla: SLA,
    ) -> SLABreach | None:
        """Evaluate a single SLA. Returns breach or None."""
        # Look for a variable matching the metric name
        matching_var = None
        for var in state.variables.values():
            if sla.metric_name in var.variable_id:
                matching_var = var
                break

        if matching_var is None or not isinstance(matching_var.raw_value, (int, float)):
            return None

        value = matching_var.raw_value

        breached = False
        if sla.comparison == "le" and value > sla.target_value or sla.comparison == "ge" and value < sla.target_value or sla.comparison == "lt" and value >= sla.target_value or sla.comparison == "gt" and value <= sla.target_value or sla.comparison == "eq" and value != sla.target_value:
            breached = True

        if not breached:
            return None

        return SLABreach(
            sla_id=sla.sla_id,
            sla_name=sla.name,
            metric_name=sla.metric_name,
            actual_value=value,
            target_value=sla.target_value,
            comparison=sla.comparison,
            customer_facing=sla.customer_facing,
        )

    def _evaluate_trigger(
        self,
        state: WorldState,
        trigger: RuleTrigger,
    ) -> tuple[bool, list[str]]:
        """Evaluate a rule trigger (composite condition)."""
        if not trigger.conditions:
            return False, []

        matched = []
        results = []
        for condition in trigger.conditions:
            result = self._evaluate_condition(state, condition)
            if result:
                matched.append(condition.variable_id)
            results.append(result)

        if trigger.combinator == "and":
            return all(results), matched
        elif trigger.combinator == "or":
            return any(results), matched
        return False, []

    def _evaluate_condition(
        self,
        state: WorldState,
        condition: RuleCondition,
    ) -> bool:
        """Evaluate a single condition."""
        var = state.variables.get(condition.variable_id)
        if var is None:
            return False

        actual = var.raw_value

        if condition.operator == "eq":
            return actual == condition.value
        if condition.operator == "ne":
            return actual != condition.value
        if condition.operator == "lt":
            return isinstance(actual, (int, float)) and actual < condition.value
        if condition.operator == "le":
            return isinstance(actual, (int, float)) and actual <= condition.value
        if condition.operator == "gt":
            return isinstance(actual, (int, float)) and actual > condition.value
        if condition.operator == "ge":
            return isinstance(actual, (int, float)) and actual >= condition.value
        if condition.operator == "in":
            return actual in (condition.value if isinstance(condition.value, list) else [condition.value])
        if condition.operator == "contains":
            return condition.value in str(actual)
        if condition.operator == "between":  # noqa: SIM102
            if isinstance(condition.value, (list, tuple)) and len(condition.value) == 2:
                return isinstance(actual, (int, float)) and condition.value[0] <= actual <= condition.value[1]

        return False
