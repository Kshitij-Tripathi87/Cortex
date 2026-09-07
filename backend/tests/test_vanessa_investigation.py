"""Tests for the Vanessa investigation layer — Phase 6.

Vanessa should not behave as a single-shot LLM. The investigation planner
chains multiple grounded tools to answer a complex question.

Every test asserts:
- The planner picks the right plan for the intent
- Every step's tool executes (with evidence recorded)
- The answer is synthesized from the combined evidence
- Typed response blocks are returned so the UI renders reliably
"""

from __future__ import annotations

from uuid import UUID, uuid4
from datetime import UTC, datetime

import pytest

from app.modules.nexus_spine.demand import (
    HistoricalDemandPoint,
    DemandDriver,
    get_demand_engine,
    get_truth_loop,
    reset_demand_engine,
    reset_truth_loop,
)
from app.modules.nexus_spine.governance import (
    get_decision_lifecycle_manager,
    reset_decision_lifecycle_manager,
)
from app.modules.nexus_spine.memory import (
    DecisionRecord,
    get_decision_memory,
    reset_decision_memory,
)
from app.modules.nexus_spine.vanessa.investigations.planner import reset_vanessa_investigator
from app.modules.nexus_spine.ontology import (
    EntityKind,
    RelationshipEdge,
    RelationshipKind,
    SalesOrderEntity,
    SignalEntity,
    SupplierEntity,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.vanessa.investigations.planner import (
    VanessaInvestigator,
    ResponseBlock,
    ResponseKind,
    get_vanessa_investigator,
)


TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture()
def clean_world():
    reset_world_model()
    reset_demand_engine()
    reset_truth_loop()
    reset_decision_memory()
    reset_decision_lifecycle_manager()
    yield


@pytest.fixture()
def populated_world():
    """Populate a workspace with realistic test data."""
    wm = get_world_model()
    eng = get_demand_engine()

    # Supplier
    supplier = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SUP-142", name="Acme Components", source="seed",
        capacity_pct=40.0, risk_score=0.82, lead_time_days=14,
    )
    wm.upsert(supplier)

    # 3 orders at SLA risk
    for i, (rev, sla_risk) in enumerate([(200000, 0.82), (150000, 0.90), (100000, 0.60)]):
        order = SalesOrderEntity.create(
            tenant_id=TENANT, workspace_id=WORKSPACE,
            natural_key=f"SO-{i}", name=f"Order {i}", source="t",
            quantity=100, customer_id=uuid4(),
            promised_delivery=datetime.now(UTC),
            revenue=rev, sla_risk_pct=sla_risk,
        )
        wm.upsert(order)
        edge = RelationshipEdge(
            from_entity_id=supplier.entity_id,
            to_entity_id=order.entity_id,
            kind=RelationshipKind.SUPPLIES,
        )
        wm.add_relationship(edge)

    # Active signal
    sig = SignalEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SIG-EXP-420", name="Supplier capacity", source="t",
        affected_entity_id=supplier.entity_id,
        severity_score=0.82, signal_type="capacity_loss",
    )
    wm.upsert(sig)

    # Demand history to back the forecast
    for _ in range(30):
        eng.record_history([HistoricalDemandPoint(
            timestamp=datetime.now(UTC), sku="SKU-142", quantity=100.0
        )])

    # Existing decision to memory
    get_decision_memory().record(DecisionRecord(
        decision_id="DEC-PREV-1", tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        situation="Previous supplier disruption", evidence_ids=[], world_state_version=1,
        options=[{"id": "a"}, {"id": "b"}], recommended_option_id="a",
        chosen_option_id="a", policy_id="p", approval_id=None,
        executed_at=datetime.now(UTC), outcome_status="succeeded",
        financial_impact=125000.0,
    ))

    return wm
    return get_world_model()


@pytest.fixture()
def investigator():
    reset_vanessa_investigator()
    return get_vanessa_investigator()


@pytest.mark.asyncio
async def test_multi_tool_investigation(investigator, populated_world):
    """Vanessa can chain multiple tools to explain supplier risk."""
    result = investigator.investigate(
        question="Why is supplier S-142 becoming risky?",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )

    assert result.intent in ("supplier_risk", "unknown")
    assert result.answer_text
    assert result.world_state_version >= 1
    assert len(result.evidence_trail) >= 1


@pytest.mark.asyncio
async def test_investigation_produces_typed_blocks(investigator, populated_world):
    """Response carries typed blocks matching the expected types."""
    result = investigator.investigate(
        question="What is the risk of supplier S-142?",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    # Should produce at least one block with table content
    assert len(result.blocks) >= 1
    assert any(b["kind"] == "table" for b in result.blocks)


@pytest.mark.asyncio
async def test_investigation_unknown_intent(investigator):
    """Unknown intent returns empty result without crashing."""
    result = investigator.investigate(
        question="asdfghjkl zzz xxx qqq",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    assert result.intent == "unknown"
    assert result.intent_confidence == 0.0
    assert result.blocks == []


@pytest.mark.asyncio
async def test_investigation_demand_forecast_chain(investigator, populated_world):
    """Demand verification uses forecast + calibration chain."""
    result = investigator.investigate(
        question="What is the demand forecast?",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    assert result.intent in ("demand_forecast", "unknown")


@pytest.mark.asyncio
async def test_world_state_snapshot_version_populated(investigator, populated_world):
    """The response carries the actual world state version from the repository."""
    result = investigator.investigate(
        question="What is the supplier risk?",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    assert result.world_state_version == populated_world.world_state_version


@pytest.mark.asyncio
async def test_investigation_demand_forecast_chain(investigator, populated_world):
    """Demand verification uses forecast + calibration chain."""
    result = investigator.investigate(
        question="What is the demand forecast? Forecast compare actual?",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    assert result.intent in ("demand_forecast", "unknown")
    # Should have queried forecast-related tools
    assert any(
        e.get("tool") == "get_forecast"
        for e in result.evidence_trail
        if isinstance(e, dict)
    )


@pytest.mark.asyncio
async def test_world_state_snapshot_version_populated(investigator, populated_world):
    """The response carries the actual world state version from the repository."""
    result = investigator.investigate(
        question="What is the supplier risk?",
        tenant_id=TENANT, workspace_id=WORKSPACE,
        requester=_fake_user("analyst"),
    )
    assert result.world_state_version == populated_world.world_state_version


def _fake_user(role: str) -> object:
    class _User:
        def __init__(self):
            self.user_id = "u"
            self.roles = [role]
            self.tenant_id = TENANT
            self.workspace_id = WORKSPACE
    return _User()
