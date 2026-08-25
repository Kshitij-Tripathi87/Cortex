"""Test Simulation Evaluation Bridge — Integration with Intelligence Foundation Harness.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 3.

Verifies:
- Evaluation of simulation trajectories against analytical ground truth
- Creation of auditable SimulationBenchmarkRecord
- Integration into the single evaluation harness
"""

from __future__ import annotations

from app.modules.evaluation.simulation_evaluation import (
    SimulationEvaluationHarness,
)
from app.modules.simulation.simulation_engine import SimulationEngine
from app.modules.simulation.simulation_models import SimulationConfig, TickGranularity
from app.modules.twin.twin_models import DigitalTwin, TwinScenario
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSimulationEvaluationBridge:
    async def test_simulation_evaluation_harness_scoring(self, db_session) -> None:
        """Simulation run is scored by SimulationEvaluationHarness and converted to BenchmarkRecord."""
        repo = StateRepository(db_session)
        workspace_id = "ws_eval_bridge"
        world_id = "world_eval_bridge"

        var_inv = StateVariable(
            variable_id=inventory_var_id("wh_01", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=600,
        )
        var_cap = StateVariable(
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
            initial_variables={var_inv.variable_id: var_inv, var_cap.variable_id: var_cap},
        )
        snapshot = create_state_snapshot(state)
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        twin = DigitalTwin(
            twin_id="twin_eval_01",
            organization_id="org_eval_01",
            workspace_id=workspace_id,
            parent_world_id=world_id,
            parent_version=1,
            snapshot_id=snapshot.snapshot_id,
            name="Evaluation Twin",
        )

        scenario = TwinScenario(
            scenario_id="scn_eval_test",
            name="Factory Disruption Scenario",
            events=[
                {
                    "entity_type": "factory",
                    "entity_id": "fac_01",
                    "event_type": "factory_shutdown",
                    "payload": {"capacity_pct": 0.0, "cause": "power_outage"},
                }
            ],
        )

        engine = SimulationEngine(db_session)
        config = SimulationConfig(
            config_id="cfg_eval",
            tick_granularity=TickGranularity.DAY,
            max_ticks=5,
            random_seed=101,
        )

        result = await engine.simulate(twin, scenario, config)
        assert result.status.value == "completed"

        # Evaluate against expected trajectory
        harness = SimulationEvaluationHarness()
        eval_score = harness.evaluate_trajectory(
            simulated_timeline=result.timeline,
            expected_trajectory=[
                {"tick": 0, "state_hash": result.timeline[0].state_hash},
                {"tick": 1, "state_hash": result.timeline[1].state_hash},
            ],
            expected_kpis={"total_inventory": 600.0, "avg_capacity": 0.0},
            actual_kpis=result.final_metrics,
        )

        assert eval_score.passed is True
        assert eval_score.trajectory_accuracy == 1.0
        assert eval_score.stability_score == 1.0

        # Create benchmark record
        record = harness.create_benchmark_record(
            simulation_result=result,
            dataset_id="golden_ds_01",
            dataset_version="v2.0",
            eval_result=eval_score,
        )

        assert record.passed_exit_gate is True
        assert record.engine_version == "simulation-v2.0"
        assert len(record.input_hash) == 64
        assert len(record.output_hash) == 64
        assert len(record.trajectory_hash) == 64
        assert len(record.kpi_hash) == 64
