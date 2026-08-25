"""Test RL REST API Endpoints — Program L.4.

Verifies:
- POST /api/v1/rl/recommend-action
- POST /api/v1/rl/rollout
- POST /api/v1/rl/benchmark
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.rl import router as rl_router
from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRLAPIEndpoints:
    async def test_rl_api_full_suite(self, db_session) -> None:
        """Test all RL REST API endpoints end-to-end."""
        repo = StateRepository(db_session)
        workspace_id = f"ws_rl_api_{uuid7()}"
        world_id = f"world_rl_api_{uuid7()}"

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_01", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=800,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=10,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )
        await repo.create(state)

        auth_user = AuthContext(
            user_id="operator_01",
            email="operator@cortex.internal",
            roles=["operator"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(rl_router, prefix="/api/v1/rl")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Recommend action
            rec_res = await client.post(
                "/api/v1/rl/recommend-action",
                json={"workspace_id": workspace_id, "world_id": world_id, "version": 1},
            )
            assert rec_res.status_code == 200, rec_res.text
            rec_data = rec_res.json()
            assert "recommended_action" in rec_data
            assert rec_data["confidence"] > 0.0

            # 2. Trajectory rollout
            roll_res = await client.post(
                "/api/v1/rl/rollout",
                json={"workspace_id": workspace_id, "world_id": world_id, "max_steps": 3},
            )
            assert roll_res.status_code == 200, roll_res.text
            roll_data = roll_res.json()
            assert roll_data["steps_executed"] == 3

            # 3. Benchmark
            bench_res = await client.post(
                "/api/v1/rl/benchmark",
                json={"workspace_id": workspace_id, "world_id": world_id, "episodes": 2},
            )
            assert bench_res.status_code == 200, bench_res.text
            bench_data = bench_res.json()
            assert "reward_lift_pct" in bench_data
