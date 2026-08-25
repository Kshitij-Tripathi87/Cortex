"""Test Multi-Agent REST API Endpoints — Program M.4.

Verifies:
- POST /api/v1/multi-agent/deliberate
- GET /api/v1/multi-agent/agents
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.multi_agent import router as multi_agent_router
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


class TestMultiAgentAPIEndpoints:
    async def test_multi_agent_api_full_suite(self, db_session) -> None:
        """Test all Multi-Agent REST API endpoints end-to-end."""
        repo = StateRepository(db_session)
        workspace_id = f"ws_ma_api_{uuid7()}"
        world_id = f"world_ma_api_{uuid7()}"

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_01", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=80,
        )
        w2 = StateVariable(
            variable_id=inventory_var_id("wh_02", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_02",
            entity_type="warehouse",
            value=800,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=14,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={w1.variable_id: w1, w2.variable_id: w2, s1.variable_id: s1},
        )
        await repo.create(state)

        auth_user = AuthContext(
            user_id="lead_01",
            email="lead@cortex.internal",
            roles=["lead"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(multi_agent_router, prefix="/api/v1/multi-agent")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Deliberate consensus plan
            delib_res = await client.post(
                "/api/v1/multi-agent/deliberate",
                json={"workspace_id": workspace_id, "world_id": world_id, "version": 1},
            )
            assert delib_res.status_code == 200, delib_res.text
            plan_data = delib_res.json()
            assert "plan_id" in plan_data
            assert len(plan_data["selected_actions"]) >= 1
            assert "trade_off_analysis" in plan_data

            # 2. List agents
            list_res = await client.get("/api/v1/multi-agent/agents")
            assert list_res.status_code == 200, list_res.text
            agents_data = list_res.json()
            assert agents_data["count"] >= 4
