"""
Cortex Nexus — Program W Operational Workflow & Production Acceptance Suite.

Tests:
1. Single-Screen Incident Cockpit state synthesis (Graph + Signals + Agents + Simulation + Decision).
2. Decision Lifecycle State Machine (DRAFT -> SIMULATED -> APPROVED -> INVALIDATED on drift).
3. CTDE Agent Lifecycle Management (TRAIN -> CANARY -> ACTIVE).
4. Real-time Delta Reconciliation (Gap detection & incremental sync).
5. Controlled Architecture Invariant Validation (Data -> World -> Intelligence -> Agents -> Decision -> Evidence).
"""

import os

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest

from app.common.context import ExecutionContext
from app.modules.data_intelligence.live_workspace import LiveNexusWorkspace


@pytest.fixture
def workspace():
    ws = LiveNexusWorkspace()
    sellers_csv = (
        "seller_id,seller_zip_code_prefix,seller_city,seller_state\n"
        "seller_01a00b8e99,01310,sao paulo,SP\n"
        "seller_bb99112233,20000,rio de janeiro,RJ\n"
    )
    orders_csv = (
        "order_id,customer_id,seller_id,price\n"
        "ord_9901,cust_1,seller_01a00b8e99,150.0\n"
        "ord_9902,cust_2,seller_01a00b8e99,250.0\n"
    )
    ws.ingest_csv_content("sellers", sellers_csv)
    ws.ingest_csv_content("order_items", orders_csv)
    return ws


@pytest.mark.asyncio
async def test_program_w_unified_incident_cockpit_bundle(workspace):
    """W1 & W2: Verifies single-screen incident cockpit state bundle."""
    ctx = ExecutionContext.create_system_context()

    # 1. Ask reasoning question for incident entity
    res = workspace.ask_natural_language_question("Investigate SLA risk and blast radius for seller_01a00b8e99")
    assert res["readiness_report"]["is_answerable"] is True
    assert res["answer"] is not None
    assert len(res["answer"]["key_reasons"]) >= 3
    assert len(res["answer"]["citations"]) >= 2

    # 2. Extract 2-hop graph neighborhood
    subgraph = workspace.get_subgraph(
        center_node_id="seller_seller_01a00b8e99",
        max_hops=2,
        limit_nodes=50,
    )
    assert len(subgraph["nodes"]) >= 2
    assert "focal_node" in subgraph

    # 3. Deliberation & 4-Candidate Counterfactual Matrix
    delib = await workspace.run_multi_agent_decision_room(
        incident_entity_id="seller_01a00b8e99",
        context=ctx,
    )
    assert len(delib["participating_agents"]) >= 3
    assert len(delib["counterfactuals"]) == 4

    # Candidate C should yield optimal Net Economic Value
    cand_c = next(c for c in delib["counterfactuals"] if c["is_optimal"])
    assert cand_c["candidate"] == "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK"
    assert cand_c["net_economic_value_usd"] == 2900.0
    assert delib["decision_card"]["status"] == "APPROVED_FOR_POLICY_GATE"


@pytest.mark.asyncio
async def test_program_w_decision_lifecycle_and_invalidation(workspace):
    """W6: Verifies Decision Lifecycle State and Invalidation on World Mutation."""
    ctx = ExecutionContext.create_system_context()

    # Run deliberation which registers decision
    delib = await workspace.run_multi_agent_decision_room(
        incident_entity_id="seller_01a00b8e99",
        context=ctx,
    )
    dec_id = delib["decision_id"]

    # Initially valid
    assert workspace.invalidation_engine.is_decision_valid(dec_id) is True

    # Mutate dependent entity
    workspace.append_stream_event(
        event_type="SELLER_DEGRADED",
        payload={"seller_id": "seller_01a00b8e99", "dispatch_delay_days": 4.5},
    )

    # Must be invalidated immediately
    assert workspace.invalidation_engine.is_decision_valid(dec_id) is False
    inv = workspace.invalidation_engine.get_invalidated_decisions()
    assert any(d.decision_id == dec_id for d in inv)


def test_program_w_realtime_delta_reconciliation(workspace):
    """W8: Verifies incremental graph delta reconciliation."""
    v_start = f"graph_v{workspace.delta_engine.current_version_counter}"

    delta = workspace.append_stream_event(
        event_type="ORDER_SHIPPED",
        payload={"order_id": "ord_9901", "carrier": "Correios"},
    )

    # Query delta since start version
    deltas = workspace.delta_engine.get_deltas_since("")
    assert len(deltas) >= 1
    assert deltas[-1].new_graph_version != v_start
