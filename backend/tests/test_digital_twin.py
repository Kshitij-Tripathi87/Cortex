"""Tests for Digital Twin — Program J Workstream C.

Verifies:
- Twin scenario factories produce correct events
- Twin isolation enforcer prevents production access
- Twin service executes scenarios deterministically
"""

from __future__ import annotations

from app.modules.twin.twin_models import (
    ScenarioType,
    TwinRunStatus,
    create_currency_shock_scenario,
    create_cyber_attack_scenario,
    create_demand_spike_twin_scenario,
    create_factory_fire_scenario,
    create_labor_strike_scenario,
    create_port_closure_scenario,
    create_pricing_shock_scenario,
    create_supplier_failure_twin_scenario,
    create_weather_scenario,
)
from app.modules.twin.twin_validation_helpers import make_fake_event
from app.modules.world.state_projection import (
    apply_transition,
    create_initial_state,
    inventory_var_id,
    project_event_to_transition,
)
from app.modules.world.world_models import StateVariable


def test_supplier_failure_scenario_factory():
    """Supplier failure scenario creates correct event."""
    scenario = create_supplier_failure_twin_scenario(
        scenario_id="scn_1",
        supplier_id="sup_001",
        delay_days=7,
        disruption_type="factory_fire",
    )
    assert scenario.scenario_type == ScenarioType.SUPPLIER_FAILURE
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "supplier_delayed"
    assert event["entity_id"] == "sup_001"
    assert event["payload"]["delay_days"] == 7
    assert event["payload"]["disruption_type"] == "factory_fire"


def test_demand_spike_scenario_factory():
    """Demand spike scenario creates correct event."""
    scenario = create_demand_spike_twin_scenario(
        scenario_id="scn_2",
        component_id="comp_042",
        demand_change=500,
        confidence=0.9,
    )
    assert scenario.scenario_type == ScenarioType.DEMAND_SPIKE
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "demand_changed"
    assert event["entity_id"] == "comp_042"
    assert event["payload"]["demand_change"] == 500
    assert event["payload"]["confidence"] == 0.9


def test_port_closure_scenario_factory():
    """Port closure scenario creates correct event."""
    scenario = create_port_closure_scenario(
        scenario_id="scn_3",
        route_id="route_123",
        delay_days=14,
    )
    assert scenario.scenario_type == ScenarioType.PORT_CLOSURE
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "route_disruption"
    assert event["payload"]["delay_days"] == 14
    assert event["payload"]["disruption_type"] == "port_closure"


def test_factory_fire_scenario_factory():
    """Factory fire scenario creates correct event."""
    scenario = create_factory_fire_scenario(
        scenario_id="scn_4",
        factory_id="fac_001",
        capacity_pct=0.0,
        estimated_recovery_days=30,
    )
    assert scenario.scenario_type == ScenarioType.FACTORY_FIRE
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "factory_shutdown"
    assert event["payload"]["capacity_pct"] == 0.0
    assert event["payload"]["estimated_recovery_days"] == 30
    assert event["payload"]["cause"] == "fire"


def test_labor_strike_scenario_factory():
    """Labor strike scenario creates correct event."""
    scenario = create_labor_strike_scenario(
        scenario_id="scn_5",
        factory_id="fac_002",
        capacity_pct=50.0,
        estimated_recovery_days=14,
    )
    assert scenario.scenario_type == ScenarioType.LABOR_STRIKE
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "factory_shutdown"
    assert event["payload"]["capacity_pct"] == 50.0
    assert event["payload"]["cause"] == "labor_strike"


def test_cyber_attack_scenario_factory():
    """Cyber attack scenario creates correct event."""
    scenario = create_cyber_attack_scenario(
        scenario_id="scn_6",
        factory_id="fac_003",
        capacity_pct=0.0,
        estimated_recovery_days=21,
    )
    assert scenario.scenario_type == ScenarioType.CYBER_ATTACK
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "factory_shutdown"
    assert event["payload"]["capacity_pct"] == 0.0
    assert event["payload"]["cause"] == "cyber_attack"


def test_weather_scenario_factory():
    """Weather scenario creates multiple route disruption events."""
    scenario = create_weather_scenario(
        scenario_id="scn_7",
        affected_routes=["route_001", "route_002", "route_003"],
        delay_days=5,
    )
    assert scenario.scenario_type == ScenarioType.WEATHER
    assert len(scenario.events) == 3
    for event in scenario.events:
        assert event["event_type"] == "route_disruption"
        assert event["payload"]["delay_days"] == 5
        assert event["payload"]["disruption_type"] == "weather"


def test_pricing_shock_scenario_factory():
    """Pricing shock scenario creates price change event."""
    scenario = create_pricing_shock_scenario(
        scenario_id="scn_8",
        component_id="comp_042",
        price_multiplier=1.5,
    )
    assert scenario.scenario_type == ScenarioType.PRICING_SHOCK
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event["event_type"] == "price_changed"


def test_currency_shock_scenario_factory():
    """Currency shock scenario creates multiple price change events."""
    scenario = create_currency_shock_scenario(
        scenario_id="scn_9",
        affected_components=["comp_001", "comp_002", "comp_003"],
        exchange_rate_change=0.15,
    )
    assert scenario.scenario_type == ScenarioType.CURRENCY_SHOCK
    assert len(scenario.events) == 3


def test_all_scenario_types_covered():
    """All ScenarioType enum values have a factory function."""
    from app.modules.twin.twin_models import (
        create_capacity_reduction_scenario,
        create_currency_shock_scenario,
        create_inventory_shortage_scenario,
        create_pandemic_scenario,
        create_pricing_shock_scenario,
        create_route_disruption_scenario,
        create_supplier_delay_scenario,
        create_weather_scenario,
    )

    factories = {
        ScenarioType.SUPPLIER_FAILURE: create_supplier_failure_twin_scenario,
        ScenarioType.SUPPLIER_DELAY: create_supplier_delay_scenario,
        ScenarioType.INVENTORY_SHORTAGE: create_inventory_shortage_scenario,
        ScenarioType.DEMAND_SPIKE: create_demand_spike_twin_scenario,
        ScenarioType.ROUTE_DISRUPTION: create_route_disruption_scenario,
        ScenarioType.CAPACITY_REDUCTION: create_capacity_reduction_scenario,
        ScenarioType.PORT_CLOSURE: create_port_closure_scenario,
        ScenarioType.FACTORY_FIRE: create_factory_fire_scenario,
        ScenarioType.LABOR_STRIKE: create_labor_strike_scenario,
        ScenarioType.CYBER_ATTACK: create_cyber_attack_scenario,
        ScenarioType.WEATHER: create_weather_scenario,
        ScenarioType.PRICING_SHOCK: create_pricing_shock_scenario,
        ScenarioType.CURRENCY_SHOCK: create_currency_shock_scenario,
        ScenarioType.PANDEMIC: create_pandemic_scenario,
    }

    for scenario_type in ScenarioType:
        if scenario_type != ScenarioType.CUSTOM:
            assert scenario_type in factories, f"No factory for {scenario_type}"


# ─────────────────────────────────────────────────────────────────────────────
# Twin Execution Tests (in-memory, no DB)
# ─────────────────────────────────────────────────────────────────────────────


def test_twin_execution_determinism():
    """Same twin + same scenario = same final state."""
    from app.modules.world.world_models import StateVariableType

    # Create initial state
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.warehouse.wh_001": StateVariable(
                variable_id="inventory.warehouse.wh_001",
                variable_type=StateVariableType.INVENTORY,
                entity_id="wh_001",
                entity_type="warehouse",
                value=100,
            ),
            "lead_time.supplier.sup_001": StateVariable(
                variable_id="lead_time.supplier.sup_001",
                variable_type=StateVariableType.LEAD_TIME,
                entity_id="sup_001",
                entity_type="supplier",
                value=10,
            ),
        },
    )

    # Define a scenario
    events = [
        {
            "entity_type": "supplier",
            "entity_id": "sup_001",
            "event_type": "supplier_delayed",
            "payload": {"delay_days": 5, "disruption_type": "port_closure"},
        },
        {
            "entity_type": "warehouse",
            "entity_id": "wh_001",
            "event_type": "inventory_changed",
            "payload": {
                "warehouse_id": "wh_001",
                "component_id": "comp_042",
                "quantity_change": -20,
                "reason": "consumption",
            },
        },
    ]

    # Run twice
    def run_scenario(initial_state):
        s = initial_state
        for event_data in events:
            evt = make_fake_event(
                event_id=f"evt_{len(s.variables)}",
                world_id="twin_1",
                workspace_id="ws_1",
                entity_type=event_data["entity_type"],
                entity_id=event_data["entity_id"],
                event_type=event_data["event_type"],
                payload=event_data["payload"],
            )
            transition = project_event_to_transition(s, evt)
            if transition:
                s = apply_transition(s, transition)
        return s

    result_a = run_scenario(state)
    result_b = run_scenario(state)

    from app.modules.world.state_projection import create_state_snapshot

    snap_a = create_state_snapshot(result_a)
    snap_b = create_state_snapshot(result_b)
    assert snap_a.state_hash == snap_b.state_hash


def test_twin_isolation_context_creation():
    """IsolationContext holds all required fields."""
    from app.modules.twin.twin_isolation import IsolationContext
    from app.modules.world.world_models import WorldSnapshot

    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )

    snapshot = WorldSnapshot(
        snapshot_id="snap_1",
        world_id="world_1",
        workspace_id="ws_1",
        version=1,
        graph_version=1,
        state_hash="abc123",
        variable_count=0,
    )

    context = IsolationContext(
        twin_id="twin_1",
        workspace_id="ws_1",
        parent_world_id="world_1",
        parent_version=1,
        snapshot=snapshot,
        state=state,
    )

    assert context.twin_id == "twin_1"
    assert context.workspace_id == "ws_1"
    assert context.parent_world_id == "world_1"
    assert context.parent_version == 1
    assert context.snapshot == snapshot
    assert context.state == state
    assert context.twin_events == []


def test_twin_run_status_enum():
    """TwinRunStatus has all expected values."""
    assert TwinRunStatus.PENDING == "pending"
    assert TwinRunStatus.RUNNING == "running"
    assert TwinRunStatus.SUCCEEDED == "succeeded"
    assert TwinRunStatus.FAILED == "failed"
    assert TwinRunStatus.CANCELLED == "cancelled"


def test_twin_status_enum():
    """TwinStatus has all expected values."""
    from app.modules.twin.twin_models import TwinStatus

    assert TwinStatus.CREATED == "created"
    assert TwinStatus.READY == "ready"
    assert TwinStatus.RUNNING == "running"
    assert TwinStatus.COMPLETED == "completed"
    assert TwinStatus.FAILED == "failed"
    assert TwinStatus.ARCHIVED == "archived"


def test_scenario_type_enum():
    """ScenarioType has all Program J scenario types."""
    assert ScenarioType.SUPPLIER_FAILURE == "supplier_failure"
    assert ScenarioType.DEMAND_SPIKE == "demand_spike"
    assert ScenarioType.PORT_CLOSURE == "port_closure"
    assert ScenarioType.FACTORY_FIRE == "factory_fire"
    assert ScenarioType.LABOR_STRIKE == "labor_strike"
    assert ScenarioType.CYBER_ATTACK == "cyber_attack"
    assert ScenarioType.PANDEMIC == "pandemic"
    assert ScenarioType.WEATHER == "weather"
    assert ScenarioType.PRICING_SHOCK == "pricing_shock"
    assert ScenarioType.CURRENCY_SHOCK == "currency_shock"
    assert ScenarioType.CUSTOM == "custom"


# ─────────────────────────────────────────────────────────────────────────────
# Async Twin Service & Isolation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinServiceAndIsolation:
    async def test_twin_clone_fork_and_run_lifecycle(self, db_session) -> None:
        from app.common.ids import uuid7
        from app.modules.twin.twin_models import TwinStatus
        from app.modules.twin.twin_service import TwinService
        from app.modules.world.state_projection import (
            capacity_var_id,
            create_state_snapshot,
            lead_time_var_id,
        )
        from app.modules.world.state_repository import StateRepository
        from app.modules.world.world_models import StateVariableType

        repo = StateRepository(db_session)
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # 1. Setup production world state with v1 and snapshot
        inv_var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )
        lt_var = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=10,
        )
        cap_var = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=100.0,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={
                inv_var.variable_id: inv_var,
                lt_var.variable_id: lt_var,
                cap_var.variable_id: cap_var,
            },
        )
        snapshot = create_state_snapshot(state, created_by="operator")
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        service = TwinService(db_session)

        # 2. Clone twin from production snapshot
        twin = await service.clone(
            workspace_id=workspace_id,
            world_id=world_id,
            snapshot_id=snapshot.snapshot_id,
            name="Disruption Twin Alpha",
            description="Evaluating supplier failure shock",
        )
        assert twin.workspace_id == workspace_id
        assert twin.parent_world_id == world_id
        assert twin.parent_version == 1
        assert twin.snapshot_id == snapshot.snapshot_id
        assert twin.status == TwinStatus.READY

        # 3. Retrieve twin
        fetched = await service.get_twin(twin.twin_id)
        assert fetched is not None
        assert fetched.name == "Disruption Twin Alpha"

        # 4. Fork twin into a counterfactual branch
        fork = await service.fork(
            source_twin_id=twin.twin_id,
            fork_name="Disruption Twin Branch Beta",
            description="Evaluating mitigation on branch",
        )
        assert fork.twin_id != twin.twin_id
        assert fork.parent_world_id == world_id
        assert "fork" in fork.tags

        # 5. Run disruption scenario on twin
        scenario = service.create_supplier_failure_scenario(
            supplier_id="sup_1",
            delay_days=21,
            disruption_type="port_strike",
        )
        result = await service.run(twin, scenario)

        assert result.twin_id == twin.twin_id
        assert result.events_processed == 1
        assert result.metrics["total_inventory"] == 500.0
        assert result.metrics["avg_lead_time"] == 31.0
        assert result.comparison["variables_changed"] == 1

        # 6. Verify twin execution produced zero leakage in production tables
        iso_report = await service.enforcer.verify_isolation(twin.twin_id)
        assert iso_report["isolated"] is True
        assert len(iso_report["violations"]) == 0

        # 7. Check run results store
        results = await service.get_results(twin.twin_id)
        assert len(results) == 1

        # 8. Archive and Destroy
        archived = await service.archive(twin.twin_id)
        assert archived.status == TwinStatus.ARCHIVED

        destroyed = await service.destroy(twin.twin_id)
        assert destroyed is True
        assert await service.get_twin(twin.twin_id) is None


# ─────────────────────────────────────────────────────────────────────────────
# Twin REST API Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinAPIEndpoints:
    async def test_twin_api_full_lifecycle(self, db_session) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from app.api.v1.twin import router as twin_router
        from app.common.ids import uuid7
        from app.infrastructure.database import get_db
        from app.infrastructure.security import AuthContext, get_current_user
        from app.modules.world.state_projection import (
            create_state_snapshot,
        )
        from app.modules.world.state_repository import StateRepository
        from app.modules.world.world_models import StateVariableType

        # Setup production state & snapshot
        repo = StateRepository(db_session)
        workspace_id = f"ws_api_{uuid7()}"
        world_id = f"world_api_{uuid7()}"

        var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=1000,
        )
        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={var.variable_id: var},
        )
        snapshot = create_state_snapshot(state)
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        auth_user = AuthContext(
            user_id="operator_01",
            email="operator@cortex.internal",
            roles=["operator"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(twin_router, prefix="/api/v1")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create twin
            create_res = await client.post(
                "/api/v1/twin/create",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "name": "API Twin 1",
                    "description": "Created via REST API",
                    "tags": ["test"],
                },
            )
            assert create_res.status_code == 201, create_res.text
            twin_data = create_res.json()
            twin_id = twin_data["twin_id"]
            assert twin_data["name"] == "API Twin 1"

            # 2. List twins
            list_res = await client.get(f"/api/v1/twin/list?workspace_id={workspace_id}")
            assert list_res.status_code == 200
            assert list_res.json()["twin_count"] >= 1

            # 3. Get twin metadata
            get_res = await client.get(f"/api/v1/twin/{twin_id}?workspace_id={workspace_id}")
            assert get_res.status_code == 200
            assert get_res.json()["twin_id"] == twin_id

            # 4. Fork twin
            fork_res = await client.post(
                "/api/v1/twin/fork",
                json={
                    "workspace_id": workspace_id,
                    "source_twin_id": twin_id,
                    "name": "API Fork 1",
                },
            )
            assert fork_res.status_code == 201, fork_res.text
            fork_id = fork_res.json()["twin_id"]
            assert fork_id is not None and fork_id != twin_id

            # 5. Run scenario on twin
            run_res = await client.post(
                "/api/v1/twin/run",
                json={
                    "workspace_id": workspace_id,
                    "twin_id": twin_id,
                    "custom_scenario": {
                        "scenario_id": "scn_custom",
                        "name": "Custom Inventory Reduction",
                        "description": "Simulating inventory draw",
                        "scenario_type": "custom",
                        "events": [
                            {
                                "entity_type": "warehouse",
                                "entity_id": "wh_1",
                                "event_type": "inventory_changed",
                                "payload": {
                                    "warehouse_id": "wh_1",
                                    "component_id": "comp_a",
                                    "quantity_change": -300,
                                },
                            }
                        ],
                    },
                },
            )
            assert run_res.status_code == 200, run_res.text
            run_data = run_res.json()
            assert run_data["metrics"]["total_inventory"] == 700.0

            # 6. Get results
            res_res = await client.get(
                f"/api/v1/twin/{twin_id}/results?workspace_id={workspace_id}"
            )
            assert res_res.status_code == 200
            assert res_res.json()["results_count"] == 1

            # 7. Delete twin
            del_res = await client.delete(f"/api/v1/twin/{twin_id}?workspace_id={workspace_id}")
            assert del_res.status_code == 204
