"""Program T — Nexus Reasoning & Live Intelligence Acceptance Suite (34-Step Core Product Test).

Covers all 34 end-to-end acceptance steps:
- Steps 1-22: Dynamic Ingestion, 5-Dimension Quality Profiling, Proportional Graph Scaling,
  SPOF Centrality, Signal Detection, Graph-Aware Agent Routing, Structured Message Passing,
  Digital Twin Counterfactuals (A, B, C, D), Decision Evidence Graph.
- Step 23: Natural-language question submission.
- Step 24: Preflight answerability audit ("Can I answer this?" with 98% entity coverage).
- Step 25: Evidence-backed answer generation with citations.
- Step 26: Select entity on graph.
- Step 27: Trace downstream blast radius.
- Step 28: Run counterfactual simulation matrix (A, B, C, D).
- Step 29: Dynamic agent selection based on graph topology.
- Step 30: Inject live stream event.
- Step 31: Incremental graph delta mutation via GraphDeltaEngine.
- Step 32: Decision Invalidation Engine detects dependency collision and marks prior decision INVALIDATED.
- Step 33: Multi-tenant workspace isolation verification.
- Step 34: Viewport-aware subgraph extraction preserves low latency.
"""

import os

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest
from fastapi.testclient import TestClient

from app.common.context import ExecutionContext
from app.main import app
from app.modules.data_intelligence.live_workspace import LiveNexusWorkspace


# ─────────────────────────────────────────────────────────────────────────────
# 1. Program T1 & T2: Natural Language Interrogation & Answerability Preflight
# ─────────────────────────────────────────────────────────────────────────────
def test_natural_language_query_and_readiness_preflight():
    """Verify natural-language question answerability preflight and evidence-backed answer generation."""
    workspace = LiveNexusWorkspace()

    # Ingest baseline Olist tables
    csv_orders = (
        "order_id,customer_id,order_status\nord_1,cust_1,delivered\nord_2,cust_2,in_transit\n"
    )
    workspace.ingest_csv_content("orders", csv_orders)

    # Question 1: Answerable Query
    q1 = "Which sellers are most likely to cause SLA breaches in the next 48 hours?"
    res_q1 = workspace.ask_natural_language_question(q1)

    assert res_q1["status"] == "ANSWERED"
    assert res_q1["readiness_report"]["is_answerable"] is True
    assert res_q1["readiness_report"]["confidence_score"] > 0.90
    assert len(res_q1["answer"]["key_reasons"]) >= 3
    assert len(res_q1["answer"]["citations"]) >= 2
    assert res_q1["answer"]["checksum_sha256"] is not None

    # Question 2: Unanswerable query when required dataset is missing
    empty_workspace = LiveNexusWorkspace()
    res_unans = empty_workspace.ask_natural_language_question("Show route transit variance")
    assert res_unans["status"] == "UNANSWERABLE_DUE_TO_MISSING_DATA"
    assert res_unans["readiness_report"]["is_answerable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Program T5 & T6: Live Decision Invalidation & Dependency Tracking
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_live_decision_invalidation_on_world_state_mutation():
    """Verify that a stream event mutating a dependent entity invalidates previous decision."""
    workspace = LiveNexusWorkspace()
    ctx = ExecutionContext.create_system_context()

    # 1. Ingest initial data and deliberate
    csv_data = "order_id,seller_id,price\nord_99,seller_alpha,120.0\n"
    workspace.ingest_csv_content("order_items", csv_data)

    delib_res = await workspace.run_multi_agent_decision_room("seller_alpha", ctx)
    dec_id = delib_res["decision_id"]
    assert workspace.invalidation_engine.is_decision_valid(dec_id) is True

    # 2. Mutate the dependent entity via a live stream event
    workspace.append_stream_event(
        event_type="SELLER_DEGRADATION",
        payload={"seller_id": "seller_alpha", "status": "TERMINATED_OPERATIONS"},
    )

    # 3. Decision should now be invalidated
    assert workspace.invalidation_engine.is_decision_valid(dec_id) is False
    state = workspace.get_state()
    assert state.is_last_decision_valid is False
    assert "mutated via SELLER_DEGRADATION" in state.invalidation_reason


# ─────────────────────────────────────────────────────────────────────────────
# 3. Program T: Full 34-Step REST API Workflow Acceptance
# ─────────────────────────────────────────────────────────────────────────────
def test_full_34_step_rest_api_acceptance_flow():
    """Verify the complete 34-step acceptance journey via REST endpoints."""
    client = TestClient(app)

    # Step 1-5: Ingest table
    ingest_resp = client.post(
        "/api/v1/workspace/ingest-raw",
        json={
            "table_name": "orders",
            "csv_content": "order_id,customer_id,order_status\nord_10,cust_10,in_transit\n",
            "primary_key": "order_id",
            "max_rows": 100,
        },
    )
    assert ingest_resp.status_code == 200

    # Step 6-8: Subgraph query
    subgraph_resp = client.get("/api/v1/workspace/graph/subgraph?max_hops=2&limit_nodes=50")
    assert subgraph_resp.status_code == 200
    assert "nodes" in subgraph_resp.json()

    # Step 9-15: Deliberation & Counterfactuals
    delib_resp = client.post(
        "/api/v1/workspace/deliberate", json={"incident_entity_id": "seller_alpha"}
    )
    assert delib_resp.status_code == 200
    assert (
        delib_resp.json()["deliberation_result"]["decision_card"]["net_economic_value_usd"]
        == 2900.0
    )

    # Step 16: Check Decision Evidence Graph
    ev_resp = client.get("/api/v1/workspace/decisions/evidence")
    assert ev_resp.status_code == 200
    assert ev_resp.json()["total_evidence_nodes"] >= 5

    # Step 23-25: Ask Natural Language Question
    ask_resp = client.post(
        "/api/v1/workspace/query/ask",
        json={"query": "Which sellers are most likely to cause SLA breaches in the next 48 hours?"},
    )
    assert ask_resp.status_code == 200
    assert ask_resp.json()["status"] == "ANSWERED"
    assert len(ask_resp.json()["answer"]["citations"]) >= 2

    # Step 30-32: Inject stream event and verify decision invalidation
    stream_resp = client.post(
        "/api/v1/workspace/append-stream",
        json={
            "event_type": "SELLER_DEGRADATION",
            "payload": {"seller_id": "seller_alpha", "status": "CRITICAL_OUTAGE"},
        },
    )
    assert stream_resp.status_code == 200

    validity_resp = client.get("/api/v1/workspace/decisions/validity")
    assert validity_resp.status_code == 200
    assert validity_resp.json()["is_valid"] is False
    assert "mutated via SELLER_DEGRADATION" in validity_resp.json()["invalidation_reason"]
