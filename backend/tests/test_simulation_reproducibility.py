"""Test Simulation Reproducibility — Seed & Engine Version Invariance.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 1 & 3.

Verifies the reproducibility contract:
    (Snapshot_0 + Scenario_X + Seed_S + EngineVersion) -> (state_hash, timeline_hash, kpi_hash)
"""

from __future__ import annotations

from app.modules.evaluation.simulation_evaluation import SimulationEvaluationHarness
from app.modules.simulation.simulation_engine import SimulationEngine
from app.modules.simulation.simulation_models import SimulationConfig, TickGranularity
from app.modules.twin.twin_models import DigitalTwin, TwinScenario
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSimulationReproducibility:
    async def test_reproducibility_contract_across_repeated_runs(self, db_session) -> None:
        """Repeating simulation 5 times with same snapshot, scenario, and seed produces 100% identical outputs."""
        repo = StateRepository(db_session)
        workspace_id = "ws_repro_01"
        world_id = "world_repro_01"

        var1 = StateVariable(
            variable_id=inventory_var_id("wh_01", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=800,
        )
        var2 = StateVariable(
            variable_id=lead_time_var_id("sup_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=14,
        )
        var3 = StateVariable(
            variable_id=capacity_var_id("fac_01"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_01",
            entity_type="factory",
            value=100.0,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={
                var1.variable_id: var1,
                var2.variable_id: var2,
                var3.variable_id: var3,
            },
        )
        snapshot = create_state_snapshot(state)
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        twin = DigitalTwin(
            twin_id="twin_repro_01",
            organization_id="org_repro_01",
            workspace_id=workspace_id,
            parent_world_id=world_id,
            parent_version=1,
            snapshot_id=snapshot.snapshot_id,
            name="Reproducibility Twin",
        )

        scenario = TwinScenario(
            scenario_id="scn_multi_step_disruption",
            name="Multi-step disruption",
            events=[
                {
                    "entity_type": "supplier",
                    "entity_id": "sup_01",
                    "event_type": "supplier_delayed",
                    "payload": {"delay_days": 10, "disruption_type": "storm"},
                },
                {
                    "entity_type": "warehouse",
                    "entity_id": "wh_01",
                    "event_type": "inventory_changed",
                    "payload": {
                        "warehouse_id": "wh_01",
                        "component_id": "comp_a",
                        "quantity_change": -350,
                    },
                },
                {
                    "entity_type": "factory",
                    "entity_id": "fac_01",
                    "event_type": "factory_shutdown",
                    "payload": {"capacity_pct": 25.0, "cause": "maintenance"},
                },
            ],
        )

        engine = SimulationEngine(db_session)
        config = SimulationConfig(
            config_id="cfg_repro",
            tick_granularity=TickGranularity.DAY,
            max_ticks=10,
            random_seed=42,
        )

        results = []
        for _ in range(5):
            res = await engine.simulate(twin, scenario, config)
            assert res.status.value == "completed"
            results.append(res)

        # Verify reproducibility using Evaluation Harness
        harness = SimulationEvaluationHarness()
        repro_report = harness.verify_reproducibility(results)

        assert repro_report["reproducible"] is True
        assert repro_report["stability_score"] == 1.0
        assert repro_report["runs_evaluated"] == 5

        # Explicit assertion on hashes
        reference_state_hash = results[0].final_state_hash
        reference_timeline_hash = results[0].metadata["timeline_hash"]
        for res in results[1:]:
            assert res.final_state_hash == reference_state_hash
            assert res.metadata["timeline_hash"] == reference_timeline_hash
            assert res.metadata["engine_version"] == "simulation-v2.0"
            assert res.final_metrics == results[0].final_metrics
