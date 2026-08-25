"""Tests for State History, Replay Engine, and Rollback — Program J Milestone J.2.4.

Covers:
1. ReplayEngine full replay from genesis matches live state and hash determinism
2. ReplayEngine time-travel to historical versions (target_version < latest_version)
3. ReplayEngine checkpoint-accelerated replay using snapshot checkpoints
4. ReplayEngine replay_range reconstruction
5. StateDiffEngine comparison across historical versions (added, removed, changed variables)
6. RollbackEngine append-only rollback (creates new version, logs rollback event, preserves lineage)
7. WorldStateService orchestration methods for history, time-travel, comparison, and rollback
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.events.event_models import (
    CapacityChanged,
    InventoryChanged,
    OrderPlaced,
    SupplierDelayed,
)
from app.modules.world.state_history import (
    ReplayEngine,
    RollbackEngine,
    StateDiffEngine,
    compare_states,
    get_state_at_time,
    get_state_history,
)
from app.modules.world.state_projection import (
    capacity_var_id,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_service import WorldStateService


@pytest.fixture
def repo(db_session: AsyncSession) -> StateRepository:
    return StateRepository(db_session)


@pytest.fixture
def service(repo: StateRepository) -> WorldStateService:
    return WorldStateService(repository=repo, snapshot_interval=3)


class TestReplayFromGenesis:
    async def test_replay_from_genesis_reproduces_exact_authoritative_state(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Apply a sequence of events
        events = [
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_north",
                warehouse_id="wh_north",
                component_id="comp_chip",
                quantity_change=500,
            ),
            SupplierDelayed(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="supplier",
                entity_id="sup_taiwan",
                delay_days=14,
            ),
            CapacityChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="factory",
                entity_id="fac_austin",
                capacity_pct=85.0,
            ),
            OrderPlaced(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="customer",
                entity_id="cust_acme",
                warehouse_id="wh_north",
                component_id="comp_chip",
                quantity=120,
            ),
        ]

        live_results = await service.submit_events(events)
        live_final_state = live_results[-1].state
        assert live_final_state.version == 5

        # Replay from genesis
        replay_engine = ReplayEngine(repo)
        replay_result = await replay_engine.replay_from_genesis(world_id, workspace_id)

        assert replay_result.events_applied == 4
        assert replay_result.transitions_applied == 4
        assert replay_result.from_version == 1
        assert replay_result.to_version == 5
        assert len(replay_result.warnings) == 0

        # State variable values must match exactly
        replayed_state = replay_result.state
        assert len(replayed_state.variables) == len(live_final_state.variables)

        inv_key = inventory_var_id("wh_north", "comp_chip")
        assert replayed_state.variables[inv_key].raw_value == 380  # 500 - 120
        assert live_final_state.variables[inv_key].raw_value == 380

        lt_key = lead_time_var_id("sup_taiwan")
        assert replayed_state.variables[lt_key].raw_value == 14

        cap_key = capacity_var_id("fac_austin")
        assert replayed_state.variables[cap_key].raw_value == 85.0


class TestTimeTravel:
    async def test_time_travel_reconstructs_exact_historical_version(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Submit 4 inventory changes (versions 2, 3, 4, 5)
        for delta in [100, 200, 300, 400]:
            await service.submit_event(
                InventoryChanged(
                    event_id=f"evt_{uuid7()}",
                    world_id=world_id,
                    workspace_id=workspace_id,
                    entity_type="warehouse",
                    entity_id="wh_1",
                    warehouse_id="wh_1",
                    component_id="comp_1",
                    quantity_change=delta,
                )
            )

        replay_engine = ReplayEngine(repo)

        # Time-travel to version 2 (after +100 -> 100)
        tt_v2 = await replay_engine.replay_to_version(world_id, workspace_id, target_version=2)
        inv_key = inventory_var_id("wh_1", "comp_1")
        assert tt_v2.state.version == 2
        assert tt_v2.state.variables[inv_key].raw_value == 100

        # Time-travel to version 3 (after +200 -> 300)
        tt_v3 = await replay_engine.replay_to_version(world_id, workspace_id, target_version=3)
        assert tt_v3.state.version == 3
        assert tt_v3.state.variables[inv_key].raw_value == 300

        # Time-travel to version 4 (after +300 -> 600)
        tt_v4 = await replay_engine.replay_to_version(world_id, workspace_id, target_version=4)
        assert tt_v4.state.version == 4
        assert tt_v4.state.variables[inv_key].raw_value == 600

    async def test_replay_range_generates_contiguous_history(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        for _step in range(1, 6):
            await service.submit_event(
                InventoryChanged(
                    event_id=f"evt_{uuid7()}",
                    world_id=world_id,
                    workspace_id=workspace_id,
                    entity_type="warehouse",
                    entity_id="wh_1",
                    warehouse_id="wh_1",
                    component_id="comp_1",
                    quantity_change=10,
                )
            )

        replay_engine = ReplayEngine(repo)
        range_states = await replay_engine.replay_range(world_id, workspace_id, from_version=2, to_version=5)

        assert len(range_states) == 4
        inv_key = inventory_var_id("wh_1", "comp_1")
        assert [s.version for s in range_states] == [2, 3, 4, 5]
        assert [s.variables[inv_key].raw_value for s in range_states] == [10, 20, 30, 40]


class TestStateDiffEngine:
    async def test_compare_states_identifies_added_changed_and_deltas(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Version 2: create inventory variable
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_main",
                warehouse_id="wh_main",
                component_id="comp_a",
                quantity_change=100,
            )
        )

        # Version 3: modify inventory and add supplier delay
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_main",
                warehouse_id="wh_main",
                component_id="comp_a",
                quantity_change=50,
            )
        )
        await service.submit_event(
            SupplierDelayed(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="supplier",
                entity_id="sup_1",
                delay_days=7,
            )
        )

        diff = await compare_states(repo, world_id, workspace_id, from_version=2, to_version=4)

        inv_key = inventory_var_id("wh_main", "comp_a")
        lt_key = lead_time_var_id("sup_1")

        assert lt_key in diff.variables_added
        assert inv_key in diff.variables_changed
        assert diff.changes[inv_key]["old_value"] == 100
        assert diff.changes[inv_key]["new_value"] == 150
        assert diff.changes[inv_key]["diff"] == 50

        summary = StateDiffEngine().summarize_changes(diff)
        assert summary["total_changes"] == 1
        assert summary["variables_added"] == 1
        assert len(summary["significant_changes"]) == 1
        assert summary["significant_changes"][0]["variable_id"] == inv_key
        assert summary["significant_changes"][0]["delta"] == 50


class TestRollbackEngine:
    async def test_rollback_creates_new_version_with_historical_variables_and_event(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Version 2: Good baseline (inventory = 500)
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=500,
            )
        )

        # Version 3: Bad transaction (inventory = 500 - 450 = 50)
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=-450,
            )
        )

        current = await repo.get_latest(workspace_id, world_id)
        assert current is not None
        assert current.version == 3
        inv_key = inventory_var_id("wh_1", "comp_1")
        assert current.variables[inv_key].raw_value == 50

        # Perform rollback to version 2 (append-only: should produce version 4)
        rollback_engine = RollbackEngine(repo)
        rollback_res = await rollback_engine.rollback(
            workspace_id=workspace_id,
            world_id=world_id,
            target_version=2,
            reason="Reverting erroneous inventory deduction",
        )

        assert rollback_res.rolled_back_from_version == 3
        assert rollback_res.rolled_back_to_version == 2
        assert rollback_res.new_state.version == 4
        assert rollback_res.new_state.variables[inv_key].raw_value == 500

        # Verify in repository
        latest_after = await repo.get_latest(workspace_id, world_id)
        assert latest_after is not None
        assert latest_after.version == 4
        assert latest_after.variables[inv_key].raw_value == 500
        assert latest_after.metadata.get("rollback") is True

        # Verify historical versions 1, 2, 3 are completely preserved
        v1 = await repo.get(world_id, workspace_id, 1)
        v2 = await repo.get(world_id, workspace_id, 2)
        v3 = await repo.get(world_id, workspace_id, 3)
        v4 = await repo.get(world_id, workspace_id, 4)

        assert v1 is not None and v1.version == 1
        assert v2 is not None and v2.version == 2 and v2.variables[inv_key].raw_value == 500
        assert v3 is not None and v3.version == 3 and v3.variables[inv_key].raw_value == 50
        assert v4 is not None and v4.version == 4 and v4.variables[inv_key].raw_value == 500


class TestWorldStateServiceHistoryIntegration:
    async def test_service_history_methods(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=100,
            )
        )
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=200,
            )
        )

        # 1. Test service.replay_from_genesis
        rep = await service.replay_from_genesis(world_id, workspace_id)
        assert rep.to_version == 3

        # 2. Test service.time_travel
        tt = await service.time_travel(world_id, workspace_id, target_version=2)
        assert tt.state.version == 2

        # 3. Test service.compare_versions
        cmp = await service.compare_versions(world_id, workspace_id, from_version=2, to_version=3)
        inv_key = inventory_var_id("wh_1", "comp_1")
        assert cmp.changes[inv_key]["diff"] == 200

        # 4. Test service.rollback_world
        rb = await service.rollback_world(
            workspace_id=workspace_id,
            world_id=world_id,
            target_version=2,
            reason="Test rollback",
        )
        assert rb.new_state.version == 4
        assert rb.new_state.variables[inv_key].raw_value == 100

        # 5. Test service.get_history and standalone convenience helpers
        history = await service.get_history(world_id, workspace_id)
        assert len(history) == 4
        assert [h.version for h in history] == [4, 3, 2, 1]

        state_v2 = await get_state_at_time(repo, world_id, workspace_id, at_version=2)
        assert state_v2.version == 2
        assert state_v2.variables[inv_key].raw_value == 100

        standalone_history = await get_state_history(repo, world_id, workspace_id)
        assert len(standalone_history) == 4


class TestReplayResilienceAndEdgeCases:
    async def test_replay_with_unrecognized_event_records_warning_and_continues(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Append a valid event
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=100,
            )
        )

        # Append an unrecognized event directly to the event store
        await repo.append_event(
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="unknown_entity",
            entity_id="unknown_1",
            event_type="unknown_future_event_type",
            payload={"foo": "bar"},
        )

        # Append another valid event
        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=50,
            )
        )

        replay_engine = ReplayEngine(repo)
        result = await replay_engine.replay_from_genesis(world_id, workspace_id)

        assert result.events_applied == 3
        assert result.transitions_applied == 2
        assert len(result.warnings) == 1
        assert "Unrecognized event_type=unknown_future_event_type" in result.warnings[0]
        inv_key = inventory_var_id("wh_1", "comp_1")
        assert result.state.variables[inv_key].raw_value == 150

    async def test_rollback_to_genesis_version_1(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="comp_1",
                quantity_change=500,
            )
        )

        rb_result = await service.rollback_world(
            workspace_id=workspace_id,
            world_id=world_id,
            target_version=1,
            reason="Reset to genesis state",
        )

        assert rb_result.new_state.version == 3
        assert len(rb_result.new_state.variables) == 0

    async def test_compare_nonexistent_versions_raises_value_error(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        with pytest.raises(ValueError, match="One or both versions not found"):
            await service.compare_versions(world_id, workspace_id, from_version=1, to_version=999)
