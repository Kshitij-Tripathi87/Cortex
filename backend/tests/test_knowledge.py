"""Tests for Knowledge Layer — Program J Workstream E.

Verifies:
- Knowledge models are immutable and serializable
- Rule engine evaluates rules correctly
- Constraints detect violations
- SLA breaches are detected
- Pre-defined factories work correctly
"""

from __future__ import annotations

from app.modules.knowledge.constraints import (
    capacity_range_constraint,
    data_residency_constraint,
    inventory_floor_constraint,
    lead_time_ceiling_constraint,
    supplier_health_floor_constraint,
)
from app.modules.knowledge.knowledge_models import (
    KnowledgeConstraint,
    KnowledgeRule,
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
from app.modules.knowledge.rule_engine import RuleEngine
from app.modules.knowledge.sla import (
    delivery_time_sla,
    inventory_availability_sla,
    order_fulfillment_rate_sla,
    platinum_customer_delivery_sla,
    production_uptime_sla,
    supplier_on_time_sla,
)
from app.modules.world.state_projection import create_initial_state
from app.modules.world.world_models import StateVariable, StateVariableType

# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Model Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_knowledge_rule_serialization():
    """KnowledgeRule serializes correctly."""
    rule = KnowledgeRule(
        rule_id="rule_1",
        workspace_id="ws_1",
        name="Test Rule",
        description="A test rule",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="inventory.test",
                    operator="lt",
                    value=10,
                ),
            ],
        ),
        action=RuleAction.EXPEDITE,
        severity=RuleSeverity.HIGH,
    )
    d = rule.to_dict()
    assert d["rule_id"] == "rule_1"
    assert d["action"] == "expedite"
    assert d["severity"] == "high"


def test_constraint_serialization():
    """KnowledgeConstraint serializes correctly."""
    constraint = KnowledgeConstraint(
        constraint_id="c_1",
        workspace_id="ws_1",
        name="Test Constraint",
        description="A test constraint",
        variable_id="inventory.test",
        operator="ge",
        min_value=10,
        severity=RuleSeverity.HIGH,
    )
    d = constraint.to_dict()
    assert d["constraint_id"] == "c_1"
    assert d["operator"] == "ge"
    assert d["min_value"] == 10


def test_playbook_serialization():
    """Playbook serializes correctly."""
    playbook = supplier_disruption_playbook("ws_1")
    d = playbook.to_dict()
    assert d["name"] == "Supplier Disruption Response"
    assert len(d["steps"]) >= 3


def test_sla_serialization():
    """SLA serializes correctly."""
    sla = delivery_time_sla("ws_1")
    d = sla.to_dict()
    assert d["name"] == "Delivery Time (95.0%)"
    assert d["comparison"] == "le"


def test_policy_serialization():
    """KnowledgePolicy serializes correctly."""
    policy = inventory_management_policy("ws_1")
    d = policy.to_dict()
    assert d["name"] == "Inventory Management Policy"
    assert d["domain"] == "inventory"


def test_approval_serialization():
    """ApprovalRequirement serializes correctly."""
    approval = large_order_approval("ws_1")
    d = approval.to_dict()
    assert d["action_type"] == "order_placed"
    assert d["approver_role"] == "manager"


# ─────────────────────────────────────────────────────────────────────────────
# Rule Engine Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_rule_engine_evaluates_simple_rule():
    """Rule engine evaluates simple rule correctly."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.test": StateVariable(
                variable_id="inventory.test",
                variable_type=StateVariableType.INVENTORY,
                entity_id="test",
                entity_type="warehouse",
                value=5,
            ),
        },
    )

    rule = KnowledgeRule(
        rule_id="rule_1",
        workspace_id="ws_1",
        name="Low Inventory",
        description="Trigger when inventory < 10",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(variable_id="inventory.test", operator="lt", value=10),
            ],
        ),
        action=RuleAction.EXPEDITE,
        severity=RuleSeverity.HIGH,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert len(result.fired_rules) == 1
    assert result.fired_rules[0].fired is True
    assert result.fired_rules[0].action == RuleAction.EXPEDITE


def test_rule_engine_does_not_fire_when_condition_not_met():
    """Rule does not fire when condition not met."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.test": StateVariable(
                variable_id="inventory.test",
                variable_type=StateVariableType.INVENTORY,
                entity_id="test",
                entity_type="warehouse",
                value=100,  # Above threshold
            ),
        },
    )

    rule = KnowledgeRule(
        rule_id="rule_1",
        workspace_id="ws_1",
        name="Low Inventory",
        description="Trigger when inventory < 10",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(variable_id="inventory.test", operator="lt", value=10),
            ],
        ),
        action=RuleAction.EXPEDITE,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert len(result.fired_rules) == 1
    assert result.fired_rules[0].fired is False


def test_rule_engine_and_combinator():
    """AND combinator requires all conditions."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "customer.priority": StateVariable(
                variable_id="customer.priority",
                variable_type=StateVariableType.CUSTOMER_PRIORITY,
                entity_id="cust_1",
                entity_type="customer",
                value="platinum",
            ),
            "inventory.test": StateVariable(
                variable_id="inventory.test",
                variable_type=StateVariableType.INVENTORY,
                entity_id="test",
                entity_type="warehouse",
                value=3,  # Below 5 days
            ),
        },
    )

    # Example from spec: Customer = Platinum AND Inventory < 5 days → EXPEDITE
    rule = KnowledgeRule(
        rule_id="rule_1",
        workspace_id="ws_1",
        name="Platinum Low Inventory",
        description="Expedite for platinum customers when inventory low",
        trigger=RuleTrigger(
            combinator="and",
            conditions=[
                RuleCondition(variable_id="customer.priority", operator="eq", value="platinum"),
                RuleCondition(variable_id="inventory.test", operator="lt", value=5),
            ],
        ),
        action=RuleAction.EXPEDITE,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert result.fired_rules[0].fired is True


def test_rule_engine_or_combinator():
    """OR combinator fires when any condition is met."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.a": StateVariable(
                variable_id="inventory.a",
                variable_type=StateVariableType.INVENTORY,
                entity_id="a",
                entity_type="warehouse",
                value=2,  # Below threshold
            ),
            "inventory.b": StateVariable(
                variable_id="inventory.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="warehouse",
                value=100,  # Above threshold
            ),
        },
    )

    rule = KnowledgeRule(
        rule_id="rule_1",
        workspace_id="ws_1",
        name="Any Low Inventory",
        description="Trigger when any inventory low",
        trigger=RuleTrigger(
            combinator="or",
            conditions=[
                RuleCondition(variable_id="inventory.a", operator="lt", value=10),
                RuleCondition(variable_id="inventory.b", operator="lt", value=10),
            ],
        ),
        action=RuleAction.NOTIFY,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert result.fired_rules[0].fired is True


def test_constraint_violation_detected():
    """Constraint violation is detected."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.warehouse.wh_001.comp_042": StateVariable(
                variable_id="inventory.warehouse.wh_001.comp_042",
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=5,  # Below floor of 10
            ),
        },
    )

    constraint = inventory_floor_constraint(
        workspace_id="ws_1",
        warehouse_id="wh_001",
        component_id="comp_042",
        minimum_units=10,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, constraints=[constraint])
    assert len(result.constraint_violations) == 1


def test_constraint_not_violated():
    """Constraint not violated when value is within range."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "lead_time.supplier.sup_001": StateVariable(
                variable_id="lead_time.supplier.sup_001",
                variable_type=StateVariableType.LEAD_TIME,
                entity_id="sup_001",
                entity_type="supplier",
                value=5,  # Below max of 14
            ),
        },
    )

    constraint = lead_time_ceiling_constraint(
        workspace_id="ws_1",
        supplier_id="sup_001",
        max_days=14,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, constraints=[constraint])
    assert len(result.constraint_violations) == 0


def test_capacity_range_constraint():
    """Capacity range constraint detects values outside range."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "capacity.factory.fac_001": StateVariable(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=120,  # Above 100 max
            ),
        },
    )

    constraint = capacity_range_constraint(
        workspace_id="ws_1",
        factory_id="fac_001",
        min_pct=0,
        max_pct=100,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, constraints=[constraint])
    assert len(result.constraint_violations) == 1


def test_sla_breach_detected():
    """SLA breach is detected when actual exceeds target."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "delivery_time.overall": StateVariable(
                variable_id="delivery_time.overall",
                variable_type=StateVariableType.TRANSIT_DELAY,  # Closest semantic
                entity_id="overall",
                entity_type="route",
                value=7,  # Above target of 5
            ),
        },
    )

    sla = delivery_time_sla("ws_1", max_days=5.0)

    engine = RuleEngine()
    result = engine.evaluate(state, slas=[sla])
    assert len(result.sla_breaches) == 1


def test_sla_not_breached():
    """SLA not breached when actual is within target."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "delivery_time.overall": StateVariable(
                variable_id="delivery_time.overall",
                variable_type=StateVariableType.TRANSIT_DELAY,
                entity_id="overall",
                entity_type="route",
                value=3,  # Below target of 5
            ),
        },
    )

    sla = delivery_time_sla("ws_1", max_days=5.0)

    engine = RuleEngine()
    result = engine.evaluate(state, slas=[sla])
    assert len(result.sla_breaches) == 0


def test_rule_engine_result_has_blocking_violations():
    """Critical constraint violations are blocking."""
    from app.modules.knowledge.rule_engine import ConstraintViolation, RuleEngineResult

    result = RuleEngineResult(
        state_hash="abc",
        constraint_violations=[
            ConstraintViolation(
                constraint_id="c1",
                constraint_name="Critical",
                variable_id="x",
                actual_value=0,
                expected_range=(10, 100),
                severity=RuleSeverity.CRITICAL,
                message="violated",
            ),
        ],
    )
    assert result.has_blocking_violations() is True


# ─────────────────────────────────────────────────────────────────────────────
# Pre-defined Factory Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_all_constraint_factories():
    """All constraint factories produce valid constraints."""
    c1 = inventory_floor_constraint("ws_1", "wh_1", "comp_1", 100)
    c2 = lead_time_ceiling_constraint("ws_1", "sup_1", 14)
    c3 = capacity_range_constraint("ws_1", "fac_1", 0, 100)
    c4 = supplier_health_floor_constraint("ws_1", "sup_1", 0.8)
    c5 = data_residency_constraint("ws_1", "us-east-1")

    for c in [c1, c2, c3, c4, c5]:
        assert c.constraint_id is not None
        assert c.workspace_id == "ws_1"
        assert c.operator is not None


def test_all_playbook_factories():
    """All playbook factories produce valid playbooks."""
    p1 = supplier_disruption_playbook("ws_1")
    p2 = demand_surge_playbook("ws_1")
    p3 = factory_shutdown_playbook("ws_1")
    p4 = inventory_shortage_playbook("ws_1")
    p5 = cyber_incident_playbook("ws_1")

    for p in [p1, p2, p3, p4, p5]:
        assert p.playbook_id is not None
        assert len(p.steps) >= 3
        assert p.estimated_total_duration_minutes > 0


def test_all_sla_factories():
    """All SLA factories produce valid SLAs."""
    slas = [
        delivery_time_sla("ws_1"),
        inventory_availability_sla("ws_1"),
        supplier_on_time_sla("ws_1", "sup_1"),
        production_uptime_sla("ws_1", "fac_1"),
        order_fulfillment_rate_sla("ws_1"),
        platinum_customer_delivery_sla("ws_1"),
    ]
    for sla in slas:
        assert sla.sla_id is not None
        assert sla.target_value > 0


def test_all_policy_factories():
    """All policy factories produce valid policies."""
    policies = [
        inventory_management_policy("ws_1"),
        supplier_management_policy("ws_1"),
        customer_service_policy("ws_1"),
        compliance_policy("ws_1"),
        risk_management_policy("ws_1"),
    ]
    for p in policies:
        assert p.policy_id is not None
        assert p.domain is not None


def test_all_approval_factories():
    """All approval factories produce valid approvals."""
    approvals = [
        large_order_approval("ws_1"),
        supplier_change_approval("ws_1"),
        emergency_production_approval("ws_1"),
    ]
    for a in approvals:
        assert a.approval_id is not None
        assert a.approver_role is not None


def test_playbook_steps_have_required_fields():
    """Playbook steps have required fields."""
    playbook = supplier_disruption_playbook("ws_1")
    for step in playbook.steps:
        assert step.step_number > 0
        assert step.action != ""
        assert step.required_role is not None
        assert step.estimated_duration_minutes > 0


def test_supplier_disruption_playbook_trigger():
    """Supplier disruption playbook has correct trigger."""
    playbook = supplier_disruption_playbook("ws_1")
    assert playbook.trigger is not None
    assert len(playbook.trigger.conditions) == 1
    assert playbook.trigger.conditions[0].variable_id == "lead_time.supplier.*"


def test_factory_shutdown_playbook_severity():
    """Factory shutdown playbook is CRITICAL severity."""
    playbook = factory_shutdown_playbook("ws_1")
    assert playbook.severity == RuleSeverity.CRITICAL


def test_cyber_incident_playbook_steps():
    """Cyber incident playbook has security-specific steps."""
    playbook = cyber_incident_playbook("ws_1")
    actions = [s.action for s in playbook.steps]
    assert any("Isolate" in a for a in actions)
    assert any("regulatory" in a.lower() for a in actions)
