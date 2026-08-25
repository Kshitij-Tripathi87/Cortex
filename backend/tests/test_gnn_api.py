"""Test GNN REST API Endpoints — Program K.8.

Verifies:
- POST /api/v1/gnn/embeddings
- POST /api/v1/gnn/similar-suppliers
- POST /api/v1/gnn/critical-nodes
- POST /api/v1/gnn/hidden-dependencies
- POST /api/v1/gnn/risk-propagation
- POST /api/v1/gnn/benchmark
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.gnn import router as gnn_router
from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
    supplier_health_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


class TestGNNAPIEndpoints:
    async def test_gnn_api_full_suite(self, db_session) -> None:
        """Test all GNN REST API endpoints end-to-end."""
        repo = StateRepository(db_session)
        workspace_id = f"ws_gnn_api_{uuid7()}"
        world_id = f"world_gnn_api_{uuid7()}"

        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=7,
        )
        s1_h = StateVariable(
            variable_id=supplier_health_var_id("sup_01"),
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_01",
            entity_type="supplier",
            value=0.95,
        )
        s2 = StateVariable(
            variable_id=lead_time_var_id("sup_02"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_02",
            entity_type="supplier",
            value=9,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_01"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_01",
            entity_type="factory",
            value=100.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_01", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=500,
        )
        c1 = StateVariable(
            variable_id=demand_var_id("cust_01"),
            variable_type=StateVariableType.DEMAND,
            entity_id="cust_01",
            entity_type="customer",
            value=250,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={
                s1.variable_id: s1,
                s1_h.variable_id: s1_h,
                s2.variable_id: s2,
                f1.variable_id: f1,
                w1.variable_id: w1,
                c1.variable_id: c1,
            },
        )
        await repo.create(state)

        auth_user = AuthContext(
            user_id="analyst_01",
            email="analyst@cortex.internal",
            roles=["analyst"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(gnn_router, prefix="/api/v1/gnn")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Compute embeddings
            emb_res = await client.post(
                "/api/v1/gnn/embeddings",
                json={"workspace_id": workspace_id, "world_id": world_id, "version": 1},
            )
            assert emb_res.status_code == 200, emb_res.text
            emb_data = emb_res.json()
            assert emb_data["num_embeddings"] >= 4
            assert emb_data["dim"] == 32

            # 2. Similar suppliers
            sim_res = await client.post(
                "/api/v1/gnn/similar-suppliers",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "target_supplier_id": "sup_01",
                    "top_k": 5,
                },
            )
            assert sim_res.status_code == 200, sim_res.text
            sim_data = sim_res.json()
            assert sim_data["target_supplier_id"] == "sup_01"
            assert len(sim_data["candidates"]) >= 1

            # 3. Critical nodes
            crit_res = await client.post(
                "/api/v1/gnn/critical-nodes",
                json={"workspace_id": workspace_id, "world_id": world_id, "top_k": 5},
            )
            assert crit_res.status_code == 200, crit_res.text
            crit_data = crit_res.json()
            assert crit_data["total_nodes_analyzed"] >= 4
            assert len(crit_data["critical_nodes"]) >= 1

            # 4. Hidden dependencies
            hid_res = await client.post(
                "/api/v1/gnn/hidden-dependencies",
                json={"workspace_id": workspace_id, "world_id": world_id, "max_discoveries": 10},
            )
            assert hid_res.status_code == 200, hid_res.text
            assert "discovered_dependencies" in hid_res.json()

            # 5. Risk propagation
            prop_res = await client.post(
                "/api/v1/gnn/risk-propagation",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "epicenter_entity_id": "sup_01",
                    "horizon_ticks": 5,
                },
            )
            assert prop_res.status_code == 200, prop_res.text
            prop_data = prop_res.json()
            assert prop_data["epicenter_node_id"] == "sup_01"
            assert len(prop_data["predicted_impacts"]) >= 1

            # 6. Benchmark
            bench_res = await client.post(
                "/api/v1/gnn/benchmark",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "task_type": "supplier_similarity",
                    "target_entity_id": "sup_01",
                },
            )
            assert bench_res.status_code == 200, bench_res.text
            bench_data = bench_res.json()
            assert bench_data["task_type"] == "supplier_similarity"
            assert "lift_pct" in bench_data
