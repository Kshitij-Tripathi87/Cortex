"""Test Program P Enterprise Production Validation REST APIs.

Verifies:
1. POST /validation/ingest-contract
2. POST /validation/backtest
3. POST /validation/intelligence-comparison
4. POST /validation/agent-audit
5. GET /validation/observability
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.validation import router as val_router
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


class TestProgramPValidationAPI:
    async def test_full_validation_api_pipeline(self, db_session) -> None:
        """Test the complete Program P validation REST API surface."""
        repo = StateRepository(db_session)
        workspace_id = f"ws_val_api_{uuid7()}"
        world_id = f"world_val_api_{uuid7()}"

        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_104"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_104",
            entity_type="supplier",
            value=8,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={s1.variable_id: s1, w1.variable_id: w1},
        )
        await repo.create(state)

        auth_user = AuthContext(
            user_id="lead_validator",
            email="validator@cortex.internal",
            roles=["operator"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(val_router, prefix="/api/v1/validation")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Ingest Minimal Contract
            ingest_res = await client.post(
                "/api/v1/validation/ingest-contract",
                json={
                    "workspace_id": workspace_id,
                    "world_id": f"world_ingest_{uuid7()}",
                    "suppliers": [{"supplier_id": "sup_alpha", "lead_time_days": 10.0}],
                    "inventory_levels": [
                        {"warehouse_id": "wh_1", "component_id": "c1", "quantity": 1000.0}
                    ],
                },
            )
            assert ingest_res.status_code == 200, ingest_res.text
            ingest_data = ingest_res.json()
            assert ingest_data["variables_count"] >= 2

            # 2. Historical Backtest
            backtest_res = await client.post(
                "/api/v1/validation/backtest",
                json={
                    "workspace_id": workspace_id,
                    "pre_event_world_id": world_id,
                    "incident_name": "Supplier S-104 Semiconductor Delay",
                    "disruption_type": "supplier_delay",
                    "disrupted_entity_id": "sup_104",
                    "ground_truth_actual_revenue_loss_usd": 50000.0,
                    "ground_truth_affected_products": ["sup_104"],
                    "ground_truth_stockout_hours": 48.0,
                    "ground_truth_recovery_days": 14.0,
                },
            )
            assert backtest_res.status_code == 200, backtest_res.text
            backtest_data = backtest_res.json()
            assert backtest_data["actual_revenue_loss_usd"] == 50000.0

            # 3. Intelligence Comparison
            comp_res = await client.post(
                f"/api/v1/validation/intelligence-comparison?workspace_id={workspace_id}"
            )
            assert comp_res.status_code == 200, comp_res.text
            comp_data = comp_res.json()
            assert comp_data["gnn_lift_pct"] > 0.0

            # 4. Agent Grounding Audit
            audit_res = await client.post(
                "/api/v1/validation/agent-audit",
                json={
                    "workspace_id": workspace_id,
                    "world_id": world_id,
                    "proposal": {
                        "proposal_id": "prop_aud_1",
                        "agent_role": "sourcing",
                        "proposed_action": {
                            "action_type": "expedite_supplier",
                            "entity_id": "sup_104",
                            "quantity": 2.0,
                            "cost_usd": 2000.0,
                        },
                        "rationale": "Mitigate component delay",
                        "estimated_cost_usd": 2000.0,
                        "estimated_revenue_protected_usd": 30000.0,
                        "confidence_score": 0.90,
                        "supporting_evidence": ["Supplier lead time increased to 8 days."],
                    },
                },
            )
            assert audit_res.status_code == 200, audit_res.text
            audit_data = audit_res.json()
            assert audit_data["audit_passed"] is True

            # 5. Observability Dashboard
            obs_res = await client.get(
                f"/api/v1/validation/observability?workspace_id={workspace_id}"
            )
            assert obs_res.status_code == 200, obs_res.text
            obs_data = obs_res.json()
            assert "system_verdict" in obs_data
