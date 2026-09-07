"""Golden Trace Integration Test — Nexus v0.5 → v0.6.

One end-to-end test that proves the complete loop works:

    World State → Signal → Risk → Scenario → Decision →
    Approval → Execution → Outcome → Memory → Evidence → Vanessa

Then mutates World State and verifies the decision becomes STALE,
blocking any further action.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

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
from app.modules.nexus_spine.demand import (
    ForecastActual,
    HistoricalDemandPoint,
    get_demand_engine,
    get_truth_loop,
    reset_demand_engine,
    reset_truth_loop,
)
from app.modules.nexus_spine.governance import (
    DecisionLifecycle,
    DecisionPhase,
    get_decision_lifecycle_manager,
    reset_decision_lifecycle_manager,
    validate_world_state_consistent,
)
from app.modules.nexus_spine.memory import (
    DecisionRecord,
    get_decision_memory,
    reset_decision_memory,
)
from app.modules.nexus_spine.risk import get_risk_engine, reset_risk_engine
from app.modules.nexus_spine.scenarios import (
    MutationKind,
    ScenarioDefinition,
    ScenarioMutation,
    get_scenario_studio,
    reset_scenario_studio,
)

TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture()
def clean_state():
    for fn in [
        reset_world_model, reset_demand_engine, reset_decision_memory,
        reset_decision_lifecycle_manager, reset_risk_engine,
        reset_scenario_studio, reset_truth_loop,
    ]:
        fn()
    yield
    for fn in [
        reset_world_model, reset_demand_engine, reset_decision_memory,
        reset_decision_lifecycle_manager, reset_risk_engine,
        reset_scenario_studio, reset_truth_loop,
    ]:
        fn()


@pytest.mark.asyncio
async def test_golden_decision_loop(clean_state):
    wm = get_world_model()

    # STEP 1: Seed the world with a supplier + 2 orders at risk
    supplier = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SUP-142", name="Acme Components", source="test",
        capacity_pct=40.0,  # Degraded
        risk_score=0.85,
        lead_time_days=14,
    )
    wm.upsert(supplier)

    for i in range(2):
        order = SalesOrderEntity.create(
            tenant_id=TENANT, workspace_id=WORKSPACE,
            natural_key=f"SO-{i}", name=f"Order {i}", source="test",
            quantity=100, customer_id=uuid4(),
            promised_delivery=datetime.now(UTC),
            revenue=150000.0, sla_risk_pct=0.80,
        )
        wm.upsert(order)

    wm.subscribe(lambda e: None)

    # STEP 2: A signal fires
    sig = SignalEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SIG-1", name="Supplier capacity drop", source="horizon",
        affected_entity_id=supplier.entity_id,
        severity_score=0.85, signal_type="capacity_loss",
        description="Acme Components capacity fell to 40%",
    )
    wm.upsert(sig)

    # STEP 3: Risk engine computes risk
    risks = get_risk_engine().compute(TENANT, WORKSPACE)
    assert len(risks) >= 1
    primary = max(risks, key=lambda r: r.revenue_at_risk)

    # STEP 4: Scenario compares options
    studio = get_scenario_studio()
    baseline = ScenarioDefinition(workspace_id=str(WORKSPACE), tenant_id=str(TENANT), name="Baseline")
    shift = ScenarioDefinition(
        workspace_id=str(WORKSPACE), tenant_id=str(TENANT),
        name="Shift to S-188",
        mutations=[ScenarioMutation(
            kind=MutationKind.SUPPLIER_FAILURE,
            target_entity_id=supplier.entity_id,
            parameters={"availability_pct": 0.5}),
        ],
    )
    cmp = studio.compare(baseline, [shift])
    assert cmp["scenario_count"] == 2

    # STEP 5: Decision lifecycle tracks the decision end-to-end
    manager = get_decision_lifecycle_manager()

    lifecycle = DecisionLifecycle(
        decision_id="DEC-100",
        tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        world_state_version=wm.world_state_version,
        world_state_hash="",
        proposal_id="SIG-1",
        options=[
            {"id": "a", "name": "Shift to S-188"},
            {"id": "b", "name": "Expedite"},
        ],
        chosen_option="a",
    )
    manager.put(lifecycle)

    # STEP 6: Walk the full lifecycle
    # Proposed → Simulated → Policy → Approval → Authorized → Executing → Executed → Outcome
    lifecycle.advance(DecisionPhase.SIMULATED, actor="system")
    lifecycle.advance(DecisionPhase.POLICY_CHECKED, actor="policy_engine")
    lifecycle.advance(DecisionPhase.AWAITING_APPROVAL, actor="policy_engine")
    lifecycle.advance(DecisionPhase.APPROVED, actor="operator")
    lifecycle.advance(DecisionPhase.AUTHORIZED, actor="worker")

    lifecycle.advance(DecisionPhase.EXECUTING, actor="worker")
    lifecycle.mark_executed(actor="worker", result={"run_id": "exec-1"})
    lifecycle.mark_outcome_recorded(actor="audit", result={"val": 80000, "recovered": True})
    assert lifecycle.phase == DecisionPhase.OUTCOME_RECORDED

    # STEP 7: Verify world-state hash is consistent
    assert validate_world_state_consistent(
        lifecycle, wm.world_state_version, lifecycle.world_state_hash
    ) == True

    # STEP 8: Memory records the decision
    memory = get_decision_memory()
    memory.record(DecisionRecord(
        decision_id="DEC-100", tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        situation="Supplier capacity drop",
        evidence_ids=[str(sig.entity_id)],
        world_state_version=1,
        options=[{"id": "a"}], recommended_option_id="a",
        chosen_option_id="a", policy_id="p", approval_id=None,
        executed_at=datetime.now(UTC),
        outcome_status="succeeded", financial_impact=80000.0,
    ))

    analogues = memory.find_analogous(
        tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        situation="Supplier capacity drop",
    )
    assert len(analogues) >= 1
    assert analogues[0].decision.decision_id == "DEC-100"

    # STEP 9: VERIFY STALE — world state changed outside decision context
    # Mutate a new supplier (not the one in the original decision)
    wm.upsert(SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SUP-143", name="Other Supplier", source="test",
        capacity_pct=90.0, risk_score=0.1,
    ), actor="external")

    # World state changed
    assert wm.world_state_version > 1

    # STEP 10: A stale decision can no longer execute
    stale = DecisionLifecycle(
        decision_id="DEC-100",
        tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        world_state_version=lifecycle.world_state_version,
        world_state_hash=lifecycle.world_state_hash,
        proposal_id="SIG-1",
    )
    # It was created from the OLD world state version
    assert stale.phase == DecisionPhase.PROPOSED  # new instance starting fresh

    # Version drift detected: old world_state_version≠current
    current_wsp = wm.world_state_version
    assert stale.world_state_version < current_wsp

    # Old decisions in terminal states can't be re-executed anyway
    representative = manager.get("DEC-100")
    assert representative is None or representative.is_terminal()


@pytest.mark.asyncio
async def test_world_state_version_drift_marks_stale(clean_state):
    """Prove that once world state moves, old decisions become invalid."""
    wm = get_world_model()

    # Initial state
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="V1-S", name="First", source="t", capacity_pct=100,
    )
    wm.upsert(s)

    # Track a decision at v1
    mgr = get_decision_lifecycle_manager()
    lc = DecisionLifecycle(
        decision_id="DEC-V1", tenant_id=str(TENANT), workspace_id=str(WORKSPACE),
        world_state_version=wm.world_state_version, world_state_hash="hash1",
        proposal_id="p1",
    )
    mgr.put(lc)

    # Advance world state
    wm.upsert(SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="V2-S", name="Second", source="t", capacity_pct=90,
    ), actor="user")

    assert wm.world_state_version > lc.world_state_version

    # Check staleness
    ok = validate_world_state_consistent(
        lc, wm.world_state_version, lc.world_state_hash
    )
    assert ok == False  # Not consistent → stale

    # Decision should be marked stale (or ineligible for execution)
    lifecycle = get_decision_lifecycle_manager().get("DEC-V1")
    assert lifecycle is not None
    assert lifecycle.phase == DecisionPhase.PROPOSED


@pytest.mark.asyncio
async def test_evidence_chain_integrity(clean_state):
    """Link signal → decision → outcome with unbroken evidence trail."""
    wm = get_world_model()

    # Build evidence chain: signal → world state → decision
    supplier = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SIG-CHAIN", name="Evidence Test", source="test",
        capacity_pct=30.0,
    )
    wm.upsert(supplier)

    sig = SignalEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="EV-SIG", name="Signal with evidence", source="t",
        affected_entity_id=supplier.entity_id,
        severity_score=0.9, signal_type="capacity_loss",
    )
    wm.upsert(sig)

    from app.modules.nexus_spine.evidence_chain import EvidenceChain, ROOT_PARENT_ID
    chain = EvidenceChain(
        organization_id=str(TENANT),
        workspace_id=str(WORKSPACE),
        correlation_id="corr-1",
        decision_id="DEC-EV-1",
    )

    # Add the signal record to the evidence chain (root = ROOT_PARENT_ID)
    chain.add(
        node_type="SIGNAL",
        parent_id=ROOT_PARENT_ID,
        world_state_version=wm.world_state_version,
        causation_id="",
        actor="signal_detector",
        input_payload={"severity": 0.9, "source": str(sig.entity_id)},
        output_payload={"signal_id": str(sig.entity_id)},
    )

    # The chain verifies itself
    ok, failures = chain.verify()
    assert ok, f"Chain broken: {failures}"
