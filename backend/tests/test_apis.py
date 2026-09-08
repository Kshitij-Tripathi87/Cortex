"""Tests for Workstream F APIs — smoke tests for endpoint contracts.

These tests verify the API route definitions compile and respond
with the correct request/response models. They do not require
a running database (full integration tests live in test_integration.py).
"""

from __future__ import annotations


def test_api_routes_import():
    """All Program J API modules import successfully."""
    from app.api.v1 import knowledge, simulation, twin, world

    assert world.router is not None
    assert twin.router is not None
    assert simulation.router is not None
    assert knowledge.router is not None


def test_world_router_has_endpoints():
    """World router has expected endpoints."""
    from app.api.v1 import world

    routes = [r.path for r in world.router.routes]
    assert "/world/state" in routes
    assert "/world/event" in routes
    assert "/world/history" in routes
    assert "/world/diff" in routes
    assert "/world/replay" in routes
    assert "/world/events" in routes
    assert "/world/verify" in routes


def test_twin_router_has_endpoints():
    """Twin router has expected endpoints."""
    from app.api.v1 import twin

    routes = [r.path for r in twin.router.routes]
    assert "/twin/create" in routes
    assert "/twin/run" in routes
    assert "/twin/fork" in routes
    assert "/twin/scenario" in routes
    assert "/twin/scenarios" in routes


def test_simulation_router_has_endpoints():
    """Simulation router has expected endpoints."""
    from app.api.v1 import simulation

    routes = [r.path for r in simulation.router.routes]
    assert "/simulation/run" in routes
    assert "/simulation/batch" in routes
    assert "/simulation/scenarios" in routes


def test_knowledge_router_has_endpoints():
    """Knowledge router has expected endpoints."""
    from app.api.v1 import knowledge

    routes = [r.path for r in knowledge.router.routes]
    assert "/knowledge/rules" in routes
    assert "/knowledge/constraints" in routes
    assert "/knowledge/playbooks" in routes
    assert "/knowledge/slas" in routes
    assert "/knowledge/policies" in routes
    assert "/knowledge/evaluate" in routes


def test_request_models_validate():
    """Pydantic request models accept valid input."""
    from app.api.v1.world import (
        AppendEventRequest,
        CreateWorldStateRequest,
    )

    create_req = CreateWorldStateRequest(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={},
    )
    assert create_req.workspace_id == "ws_1"

    event_req = AppendEventRequest(
        workspace_id="ws_1",
        world_id="world_1",
        entity_type="warehouse",
        entity_id="wh_001",
        event_type="inventory_changed",
        payload={"warehouse_id": "wh_001", "component_id": "c1", "quantity_change": 10},
    )
    assert event_req.event_type == "inventory_changed"


def test_twin_request_models_validate():
    """Twin request models accept valid input."""
    from app.api.v1.twin import CreateTwinRequest, RunScenarioRequest

    create_req = CreateTwinRequest(
        workspace_id="ws_1",
        world_id="world_1",
        snapshot_id="snap_1",
        name="My Twin",
    )
    assert create_req.name == "My Twin"

    run_req = RunScenarioRequest(
        workspace_id="ws_1",
        twin_id="twin_1",
        scenario_id="scn_1",
    )
    assert run_req.twin_id == "twin_1"


def test_knowledge_rule_request_validates():
    """Knowledge rule request model validates."""
    from app.api.v1.knowledge import CreateRuleRequest, RuleConditionRequest, RuleTriggerRequest
    from app.modules.knowledge.knowledge_models import RuleAction, RuleSeverity

    req = CreateRuleRequest(
        workspace_id="ws_1",
        name="Low inventory alert",
        description="Notify when inventory below threshold",
        trigger=RuleTriggerRequest(
            conditions=[
                RuleConditionRequest(
                    variable_id="inventory.test",
                    operator="lt",
                    value=10,
                ),
            ],
        ),
        action=RuleAction.EXPEDITE,
        severity=RuleSeverity.HIGH,
    )
    assert req.name == "Low inventory alert"
    assert len(req.trigger.conditions) == 1


def test_simulation_request_models():
    """Simulation request models validate."""
    from app.api.v1.simulation import (
        BatchSimulationRequest,
        RunSimulationRequest,
        SimulationConfigRequest,
    )
    from app.modules.simulation.simulation_models import TickGranularity

    req = RunSimulationRequest(
        workspace_id="ws_1",
        twin_id="twin_1",
        scenario_id="scn_1",
        config=SimulationConfigRequest(
            tick_granularity=TickGranularity.DAY,
            max_ticks=14,
        ),
    )
    assert req.config.max_ticks == 14

    batch = BatchSimulationRequest(
        workspace_id="ws_1",
        twin_id="twin_1",
        scenario_ids=["scn_1", "scn_2"],
    )
    assert len(batch.scenario_ids) == 2
