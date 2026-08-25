"""Test Supervised Execution & Closed-Loop REST APIs — Programs N & O.

Verifies the complete closed-loop lifecycle:
1. POST /execution/plan
2. POST /execution/simulate-gate
3. POST /execution/decision-card
4. POST /execution/decide
5. POST /execution/dispatch
6. POST /execution/close-loop
7. GET /execution/memory
8. GET /governance/flywheel
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.execution import router as exec_router
from app.api.v1.governance import router as gov_router
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


class TestExecutionAPIEndpoints:
    async def test_full_execution_and_closed_loop_lifecycle(self, db_session) -> None:
        """Test full supervised execution from plan creation to closed-loop memory capture."""
        repo = StateRepository(db_session)
        workspace_id = f"ws_exec_api_{uuid7()}"
        world_id = f"world_exec_api_{uuid7()}"

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=800,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=12,
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
        test_app.include_router(exec_router, prefix="/api/v1/execution")
        test_app.include_router(gov_router, prefix="/api/v1/governance")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create plan
            create_res = await client.post(
                "/api/v1/execution/plan",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "action_type": "expedite_supplier",
                    "entity_id": "sup_1",
                    "quantity": 3.0,
                    "cost_usd": 4500.0,
                    "objective": "Compress lead time by 3 days",
                },
            )
            assert create_res.status_code == 200, create_res.text
            plan_data = create_res.json()
            assert plan_data["status"] == "simulation_pending"

            # 2. Simulation Gate
            sim_res = await client.post(
                "/api/v1/execution/simulate-gate",
                json={"workspace_id": workspace_id, "world_id": world_id, "plan": plan_data},
            )
            assert sim_res.status_code == 200, sim_res.text
            sim_data = sim_res.json()
            assert sim_data["simulation_result"]["simulation_passed"] is True
            updated_plan = sim_data["plan"]
            assert updated_plan["status"] == "pending_approval"

            # 3. Decision Card
            card_res = await client.post(
                "/api/v1/execution/decision-card",
                json={"workspace_id": workspace_id, "world_id": world_id, "plan": updated_plan},
            )
            assert card_res.status_code == 200, card_res.text
            card_data = card_res.json()
            assert "incident_summary" in card_data
            assert len(card_data["options"]) >= 2

            # 4. Human Decision (Approve)
            decide_res = await client.post(
                "/api/v1/execution/decide",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "plan": updated_plan,
                    "decision": "approve",
                },
            )
            assert decide_res.status_code == 200, decide_res.text
            approved_plan = decide_res.json()
            assert approved_plan["status"] == "approved"

            # 5. Dispatch to Enterprise Adapter
            dispatch_res = await client.post(
                "/api/v1/execution/dispatch",
                json={"workspace_id": workspace_id, "plan": approved_plan},
            )
            assert dispatch_res.status_code == 200, dispatch_res.text
            dispatch_data = dispatch_res.json()
            assert dispatch_data["success"] is True

            # 6. Close Decision Loop
            close_res = await client.post(
                "/api/v1/execution/close-loop",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "plan": approved_plan,
                    "operator_decision": "approve",
                    "actual_outcome_revenue_saved_usd": 34000.0,
                },
            )
            assert close_res.status_code == 200, close_res.text
            close_data = close_res.json()
            assert close_data["flywheel_feedback_applied"] is True

            # 7. Query Memory
            mem_res = await client.get(f"/api/v1/execution/memory?workspace_id={workspace_id}")
            assert mem_res.status_code == 200, mem_res.text
            mem_data = mem_res.json()
            assert len(mem_data["records"]) >= 1

            # 8. Governance Flywheel Report
            gov_res = await client.get(f"/api/v1/governance/flywheel?workspace_id={workspace_id}")
            assert gov_res.status_code == 200, gov_res.text
            gov_data = gov_res.json()
            assert gov_data["total_decisions_executed"] >= 1
            assert gov_data["flywheel_health_score"] > 0.80
