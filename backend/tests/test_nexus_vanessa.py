"""Tests for the Nexus Vanessa grounded AI interface.

Covers:
- Intent classification (keyword-based router)
- Tool registry + permission enforcement
- All built-in tools (query, traverse, signal, blast radius, forecast,
  calibration, supplier risk, orders at risk, decision lookup, analogous)
- Orchestrator end-to-end (intent → tool → answer)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

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
    EntityKind,
    SalesOrderEntity,
    SupplierEntity,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.vanessa import (
    Intent,
    Tool,
    ToolCall,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    VanessaAnswer,
    VanessaOrchestrator,
    VanessaQuery,
    build_default_registry,
    classify_intent,
    get_vanessa,
    reset_tool_registry,
    reset_vanessa,
)
from app.modules.nexus_spine.vanessa.builtin_tools import (
    GetBlastRadiusTool,
    GetForecastTool,
    GetOrdersAtRiskTool,
    GetSignalTool,
    GetSupplierRiskTool,
    QueryWorldStateTool,
    TraverseGraphTool,
)

TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def orchestrator() -> VanessaOrchestrator:
    reset_world_model()
    reset_demand_engine()
    reset_decision_memory()
    reset_tool_registry()
    reset_vanessa()
    wm = get_world_model()
    # Seed a supplier → PO → SO chain
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SUP-142",
        name="Acme Components",
        source="test",
        capacity_pct=60.0,
        risk_score=0.7,
    )
    wm.upsert(s)
    so = SalesOrderEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SO-1",
        name="Big Order",
        source="test",
        quantity=100,
        customer_id=uuid4(),
        promised_delivery=datetime.now(UTC),
        revenue=250000.0,
        sla_risk_pct=0.8,
    )
    wm.upsert(so)
    # Seed demand history
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
    # Seed decision memory
    mem = get_decision_memory()
    mem.record(
        DecisionRecord(
            decision_id="dec-historical-1",
            tenant_id=str(TENANT),
            workspace_id=str(WORKSPACE),
            situation="Supplier S-142 capacity outage affecting orders",
            evidence_ids=["ev-1"],
            world_state_version=10,
            options=[{"id": "A"}, {"id": "B"}],
            recommended_option_id="B",
            chosen_option_id="B",
            policy_id="pol-1",
            approval_id="apr-1",
            executed_at=datetime.now(UTC),
            outcome_status="succeeded",
            financial_impact=8400.0,
            actual_result="Recovered SLA in 2.8 days",
            tags=["supplier-outage"],
        )
    )
    return get_vanessa()


# ──────────────────────────────────────────────────────────────────────────────
# Intent classification
# ──────────────────────────────────────────────────────────────────────────────


def test_classify_intent_recognizes_supplier_risk():
    registry = ToolRegistry()
    c = classify_intent("What is supplier S-142 risk score?", registry)
    assert c.intent == Intent.SUPPLIER_RISK


def test_classify_intent_recognizes_demand_forecast():
    c = classify_intent("What is the demand forecast for next week?", ToolRegistry())
    assert c.intent == Intent.DEMAND_FORECAST


def test_classify_intent_recognizes_calibration():
    c = classify_intent("Where is Nexus systematically wrong? Bias check.", ToolRegistry())
    assert c.intent == Intent.FORECAST_CALIBRATION


def test_classify_intent_recognizes_blast_radius():
    c = classify_intent("What is the blast radius if supplier S-188 fails?", ToolRegistry())
    assert c.intent == Intent.BLAST_RADIUS


def test_classify_intent_recognizes_signal_triage():
    c = classify_intent("Show me signals and alerts above 0.5", ToolRegistry())
    assert c.intent == Intent.SIGNAL_TRIAGE


def test_classify_intent_recognizes_order_risk():
    c = classify_intent("Which orders will miss SLA?", ToolRegistry())
    assert c.intent == Intent.ORDER_RISK


def test_classify_intent_recognizes_analogous_decisions():
    c = classify_intent("Have we seen similar past decision?", ToolRegistry())
    assert c.intent == Intent.ANALOGOUS_DECISIONS


def test_classify_intent_returns_unknown_for_garbage():
    c = classify_intent("asdfghjkl zzzz qqq", ToolRegistry())
    assert c.intent == Intent.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry + permissions
# ──────────────────────────────────────────────────────────────────────────────


class _EchoTool(Tool):
    name = "_echo"
    description = "test tool"
    permission = ToolPermission.AUTHENTICATED
    input_schema = type(
        "EchoInput",
        (),
        {
            "__annotations__": {"x": int},
        },
    )

    def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={"x": call.arguments.get("x")},
        )


def test_tool_registry_rejects_unknown_tool():
    r = ToolRegistry()
    r.register(_EchoTool())
    result = r.invoke(
        ToolCall(
            tool_name="nonexistent",
            arguments={},
            requester_role="analyst",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False
    assert "unknown tool" in (result.error or "")


def test_tool_registry_rejects_insufficient_role():
    r = ToolRegistry()

    class _AdminTool(_EchoTool):
        name = "_admin"
        permission = ToolPermission.ADMIN

    r.register(_AdminTool())
    result = r.invoke(
        ToolCall(
            tool_name="_admin",
            arguments={"x": 1},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False
    assert "insufficient" in (result.error or "")


def test_tool_registry_rejects_invalid_arguments():
    r = ToolRegistry()
    r.register(_EchoTool())
    result = r.invoke(
        ToolCall(
            tool_name="_echo",
            arguments={"x": "not_an_int"},
            requester_role="analyst",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False


def test_tool_registry_handles_exceptions_gracefully():
    from pydantic import BaseModel as _BM

    class _In(_BM):
        pass

    r = ToolRegistry()

    class _Boom(Tool):
        name = "_boom"
        description = "always fails"
        permission = ToolPermission.AUTHENTICATED
        input_schema = _In

        def invoke(self, call: ToolCall) -> ToolResult:
            raise RuntimeError("kaboom")

    r.register(_Boom())
    result = r.invoke(
        ToolCall(
            tool_name="_boom",
            arguments={},
            requester_role="analyst",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False
    assert "kaboom" in (result.error or "")


# ──────────────────────────────────────────────────────────────────────────────
# Built-in tools
# ──────────────────────────────────────────────────────────────────────────────


def test_query_world_state_tool(orchestrator):
    result = QueryWorldStateTool().invoke(
        ToolCall(
            tool_name="query_world_state",
            arguments={"limit": 10},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert result.payload["count"] >= 2


def test_query_world_state_rejects_unknown_kind(orchestrator):
    result = QueryWorldStateTool().invoke(
        ToolCall(
            tool_name="query_world_state",
            arguments={"kinds": ["banana"]},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False


def test_traverse_graph_tool(orchestrator):
    wm = get_world_model()
    entities = list(wm.iter_entities(TENANT, WORKSPACE))
    seed = next(e for e in entities if e.kind == EntityKind.SUPPLIER)
    result = TraverseGraphTool().invoke(
        ToolCall(
            tool_name="traverse_graph",
            arguments={"seed_entity_id": str(seed.entity_id), "max_depth": 2},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok


def test_traverse_graph_rejects_unknown_seed(orchestrator):
    result = TraverseGraphTool().invoke(
        ToolCall(
            tool_name="traverse_graph",
            arguments={"seed_entity_id": str(uuid4())},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok is False
    assert "not found" in (result.error or "")


def test_get_signal_tool_returns_empty_when_no_signals(orchestrator):
    result = GetSignalTool().invoke(
        ToolCall(
            tool_name="get_signal",
            arguments={"min_severity": 0.5},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert result.payload["count"] == 0


def test_get_blast_radius_returns_revenue_at_risk(orchestrator):
    wm = get_world_model()
    seed = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
    result = GetBlastRadiusTool().invoke(
        ToolCall(
            tool_name="get_blast_radius",
            arguments={"seed_entity_id": str(seed.entity_id), "max_depth": 3},
            requester_role="analyst",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert "revenue_exposed" in result.payload


def test_get_forecast_produces_probabilistic_output(orchestrator):
    result = GetForecastTool().invoke(
        ToolCall(
            tool_name="get_forecast",
            arguments={"sku": "SKU-1", "horizon_days": 7},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert result.payload["p50"] > 0
    assert result.payload["p95"] >= result.payload["p80"] >= result.payload["p50"]


def test_get_supplier_risk_returns_suppliers(orchestrator):
    result = GetSupplierRiskTool().invoke(
        ToolCall(
            tool_name="get_supplier_risk",
            arguments={"min_risk": 0.0},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert result.payload["count"] >= 1
    assert any(s["name"] == "Acme Components" for s in result.payload["suppliers"])


def test_get_orders_at_risk_returns_revenue_exposed(orchestrator):
    result = GetOrdersAtRiskTool().invoke(
        ToolCall(
            tool_name="get_orders_at_risk",
            arguments={"min_revenue": 0.0},
            requester_role="viewer",
            requester_id="u",
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
        )
    )
    assert result.ok
    assert result.payload["count"] >= 1
    assert result.payload["total_revenue_at_risk"] >= 250000.0


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator end-to-end
# ──────────────────────────────────────────────────────────────────────────────


def test_orchestrator_ask_returns_grounded_answer(orchestrator):
    q = VanessaQuery(
        query="What is the risk of supplier SUP-142?",
        requester_id="alice",
        requester_role="analyst",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
    )
    answer = orchestrator.ask(q)
    assert isinstance(answer, VanessaAnswer)
    assert answer.intent == Intent.SUPPLIER_RISK
    assert answer.intent_confidence > 0.0
    assert answer.rendered_answer  # non-empty
    assert any("Acme Components" in r.rendered_answer for r in [answer])
    assert answer.tool_calls  # at least one tool was invoked


def test_orchestrator_unknown_intent_returns_help(orchestrator):
    q = VanessaQuery(
        query="asdfghjkl random words that mean nothing",
        requester_id="alice",
        requester_role="analyst",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
    )
    answer = orchestrator.ask(q)
    assert answer.intent == Intent.UNKNOWN
    assert (
        "could not" in answer.rendered_answer.lower()
        or "try asking" in answer.rendered_answer.lower()
    )


def test_orchestrator_extracts_sku_from_query(orchestrator):
    q = VanessaQuery(
        query="What is the demand forecast for SKU-1?",
        requester_id="alice",
        requester_role="analyst",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
    )
    answer = orchestrator.ask(q)
    assert answer.tool_calls[0].ok
    assert answer.tool_calls[0].payload["sku"] == "SKU-1"


def test_orchestrator_grounded_answer_includes_citations(orchestrator):
    q = VanessaQuery(
        query="What are the orders at risk?",
        requester_id="alice",
        requester_role="analyst",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
    )
    answer = orchestrator.ask(q)
    assert answer.citations
    assert all(call.evidence for call in answer.tool_calls)


def test_default_registry_has_all_expected_tools():
    registry = build_default_registry()
    names = {t["name"] for t in registry.list_tools()}
    assert {
        "query_world_state",
        "traverse_graph",
        "get_signal",
        "get_blast_radius",
        "get_forecast",
        "compare_forecast_actual",
        "get_supplier_risk",
        "get_orders_at_risk",
        "get_decision",
        "find_analogous_decisions",
    } <= names
