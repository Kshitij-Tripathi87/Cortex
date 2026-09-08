"""Tests for the Nexus /v1/* API surface.

Covers the stable Nexus API:
- /v1/world                - world state metadata
- /v1/entities             - CRUD + query
- /v1/graph/blast-radius    - blast radius
- /v1/graph/traverse        - graph traversal
- /v1/signals              - signal triage
- /v1/risks/suppliers       - supplier risk
- /v1/risks/orders-at-risk  - orders at SLA risk
- /v1/forecasts            - probabilistic forecasts
- /v1/forecasts/observe    - truth-loop closure
- /v1/calibration/{sku}    - forecast vs reality
- /v1/decisions            - record decision
- /v1/decisions/analogous  - similar past decisions
- /v1/vanessa/ask           - grounded AI
- /v1/vanessa/tools         - tool registry listing
- /v1/realtime/events       - world state change events

Auth is set up to use header identity (dev mode) — every endpoint still
verifies workspace_id consistency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.nexus import router as nexus_router
from app.modules.nexus_spine.demand import (
    HistoricalDemandPoint,
    get_demand_engine,
    reset_demand_engine,
)
from app.modules.nexus_spine.memory import (
    DecisionRecord,
    get_decision_memory,
    reset_decision_memory,
)
from app.modules.nexus_spine.ontology import (
    SalesOrderEntity,
    SupplierEntity,
    get_world_model,
    reset_world_model,
)

TENANT = uuid4()
WORKSPACE = uuid4()


@pytest.fixture
async def app_and_client():
    reset_world_model()
    reset_demand_engine()
    reset_decision_memory()
    from app.modules.nexus_spine.vanessa import reset_tool_registry, reset_vanessa

    reset_tool_registry()
    reset_vanessa()

    wm = get_world_model()
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SUP-1",
        name="Acme",
        source="t",
        capacity_pct=60.0,
        risk_score=0.7,
    )
    wm.upsert(s)
    so = SalesOrderEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SO-1",
        name="Big",
        source="t",
        quantity=100,
        customer_id=uuid4(),
        promised_delivery=datetime.now(UTC),
        revenue=200000.0,
        sla_risk_pct=0.7,
    )
    wm.upsert(so)
    eng = get_demand_engine()
    for d in range(30):
        eng.record_history(
            [
                HistoricalDemandPoint(
                    timestamp=datetime.now(UTC) - timedelta(days=d),
                    sku="SKU-1",
                    quantity=100.0,
                )
            ]
        )

    app = FastAPI()
    app.include_router(nexus_router, prefix="/api/v1")

    # Auth override that returns a fixed AuthContext (simulating header identity)
    from app.infrastructure.security import AuthContext

    async def _fake_user() -> AuthContext:
        return AuthContext(
            user_id=str(TENANT),
            email="tester@example.com",
            roles=["analyst", "operator"],
            workspace_ids=[str(WORKSPACE)],
            is_anonymous=False,
        )

    # Override the dependency
    from app.infrastructure.security import get_current_user as real_get_current_user

    app.dependency_overrides[real_get_current_user] = _fake_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client, wm


@pytest.mark.asyncio
async def test_world_endpoint_returns_metadata(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(f"/api/v1/world?workspace_id={WORKSPACE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["workspace_id"] == str(WORKSPACE)
    assert body["data"]["world_state_version"] >= 1
    assert "entity_counts" in body["data"]


@pytest.mark.asyncio
async def test_entities_query(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(
        f"/api/v1/entities?workspace_id={WORKSPACE}&kinds=supplier",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] >= 1


@pytest.mark.asyncio
async def test_entities_upsert(app_and_client):
    _, client, _ = app_and_client
    resp = await client.post(
        "/api/v1/entities",
        json={
            "workspace_id": str(WORKSPACE),
            "natural_key": "WH-1",
            "name": "Central DC",
            "kind": "warehouse",
            "state": {"capacity_pct": 70.0, "location": "BLR"},
            "source": "test",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["entity"]["kind"] == "warehouse"
    assert body["data"]["world_state_version"] >= 1


@pytest.mark.asyncio
async def test_entities_get_by_id(app_and_client):
    _, client, wm = app_and_client
    s = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind.value == "supplier")
    resp = await client.get(
        f"/api/v1/entities/{s.entity_id}?workspace_id={WORKSPACE}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["entity"]["name"] == "Acme"


@pytest.mark.asyncio
async def test_graph_blast_radius(app_and_client):
    _, client, wm = app_and_client
    s = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind.value == "supplier")
    resp = await client.post(
        "/api/v1/graph/blast-radius",
        json={
            "workspace_id": str(WORKSPACE),
            "seed_entity_id": str(s.entity_id),
            "max_depth": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "revenue_exposed" in data


@pytest.mark.asyncio
async def test_graph_traverse(app_and_client):
    _, client, wm = app_and_client
    s = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind.value == "supplier")
    resp = await client.post(
        "/api/v1/graph/traverse",
        json={
            "workspace_id": str(WORKSPACE),
            "seed_entity_id": str(s.entity_id),
            "max_depth": 2,
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_signals_endpoint(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(f"/api/v1/signals?workspace_id={WORKSPACE}")
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0


@pytest.mark.asyncio
async def test_supplier_risk(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(f"/api/v1/risks/suppliers?workspace_id={WORKSPACE}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 1
    assert data["suppliers"][0]["name"] == "Acme"


@pytest.mark.asyncio
async def test_orders_at_risk(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(f"/api/v1/risks/orders-at-risk?workspace_id={WORKSPACE}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 1
    assert data["total_revenue_at_risk"] >= 200000.0


@pytest.mark.asyncio
async def test_forecasts_produce(app_and_client):
    _, client, _ = app_and_client
    resp = await client.post(
        "/api/v1/forecasts",
        json={"workspace_id": str(WORKSPACE), "sku": "SKU-1", "horizon_days": 7},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["p50"] > 0
    assert data["p95"] >= data["p80"] >= data["p50"]
    return data["forecast_id"]


@pytest.mark.asyncio
async def test_forecasts_observe_closes_truth_loop(app_and_client):
    _, client, _ = app_and_client
    forecast_id = await test_forecasts_produce(app_and_client)
    resp = await client.post(
        "/api/v1/forecasts/observe",
        json={
            "workspace_id": str(WORKSPACE),
            "forecast_id": forecast_id,
            "sku": "SKU-1",
            "horizon_days": 7,
            "observed_at": datetime.now(UTC).isoformat(),
            "actual_quantity": 750.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "absolute_error" in data


@pytest.mark.asyncio
async def test_calibration_endpoint(app_and_client):
    _, client, _ = app_and_client
    await test_forecasts_produce(app_and_client)
    resp = await client.get(
        f"/api/v1/calibration/SKU-1?workspace_id={WORKSPACE}",
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_decisions_record_and_analogous(app_and_client):
    _, client, _ = app_and_client
    # Seed a historical decision
    mem = get_decision_memory()
    mem.record(
        DecisionRecord(
            decision_id="dec-hist",
            tenant_id=str(TENANT),
            workspace_id=str(WORKSPACE),
            situation="Supplier outage affected orders",
            evidence_ids=[],
            world_state_version=1,
            options=[],
            recommended_option_id="A",
            chosen_option_id="A",
            policy_id="p1",
            approval_id=None,
            executed_at=datetime.now(UTC),
            outcome_status="succeeded",
        )
    )

    resp = await client.post(
        "/api/v1/decisions",
        json={
            "workspace_id": str(WORKSPACE),
            "decision_id": "dec-new",
            "situation": "Port outage affected orders",
            "evidence_ids": [],
            "world_state_version": 2,
            "options": [{"id": "A"}],
            "recommended_option_id": "A",
            "chosen_option_id": "A",
            "policy_id": "p1",
        },
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/decisions/analogous",
        json={
            "workspace_id": str(WORKSPACE),
            "situation": "Port outage affected orders",
            "limit": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_vanessa_ask(app_and_client):
    _, client, _ = app_and_client
    resp = await client.post(
        "/api/v1/vanessa/ask",
        json={
            "workspace_id": str(WORKSPACE),
            "query": "What is the supplier risk?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "rendered_answer" in body
    assert body["intent"] in {"supplier_risk", "unknown"}


@pytest.mark.asyncio
async def test_vanessa_list_tools(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get("/api/v1/vanessa/tools")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 5


@pytest.mark.asyncio
async def test_realtime_events(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(f"/api/v1/realtime/events?workspace_id={WORKSPACE}")
    assert resp.status_code == 200
    assert "events" in resp.json()["data"]


@pytest.mark.asyncio
async def test_invalid_workspace_id_rejected(app_and_client):
    _, client, _ = app_and_client
    # Invalid workspace_id is rejected at the auth layer (workspace access
    # check) before UUID parsing — this is fail-closed: never reveal that
    # a workspace_id is well-formed but unauthorized.
    resp = await client.get("/api/v1/world?workspace_id=not-a-uuid")
    assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_unknown_entity_returns_404(app_and_client):
    _, client, _ = app_and_client
    resp = await client.get(
        f"/api/v1/entities/{uuid4()}?workspace_id={WORKSPACE}",
    )
    assert resp.status_code == 404
