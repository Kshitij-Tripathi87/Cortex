"""V2.2 Acceptance Tests — Agent Proposal → Twin → Policy Decision.

Proves the V2.2 contract:
1. Determinism — same world → same proposal_hash; same inputs → same option_hash
2. Sensitivity — different world_state_version → different proposal_hash
3. Proposal→Twin flow — twin_comparison has simulation_hash, options reference proposals
4. Twin→Policy flow — policy gate verifies provenance; policy_version = "v2"
5. Denied decisions cannot execute
6. Mutation→invalidation — world advances past decision version → STALE_DECISION
7. Proposal provenance — every proposal carries world_state_version, correlation_id, proposal_hash
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.nexus_spine.canonical_schema import EntityType
from app.modules.nexus_spine.models import (
    AgentProposal,
    SwarmTask,
    SwarmTaskContext,
    compute_proposal_hash,
    compute_world_state_hash,
)
from app.modules.nexus_spine.pipeline_stages import (
    ExecutionGateError,
    execution_gate_fn,
    policy_gate_fn,
    real_supervisor_fn,
    twin_simulation_fn,
)
from app.modules.nexus_spine.proposal_simulator import (
    ProposalOption,
    ProposalSimulator,
    SimulationResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_proposal(
    *,
    agent_id: str = "test_agent",
    agent_family: str = "PROCUREMENT",
    action: str = "switch_supplier",
    world_state_version: int = 100,
    cost: float = 5000.0,
    delay: float = 2.0,
    risk: float = 0.3,
    payload: dict | None = None,
) -> AgentProposal:
    """Build a minimal proposal with V2.2 provenance fields."""
    if payload is None:
        payload = {"affected_orders": 100, "avg_order_value_usd": 500}
    p = AgentProposal(
        agent_id=agent_id,
        agent_family=agent_family,
        action=action,
        expected_cost_usd=cost,
        expected_delay_days=delay,
        expected_risk_score=risk,
        payload=payload,
        world_state_version=world_state_version,
    )
    return replace(p, proposal_hash=compute_proposal_hash(p))


def _make_swarm_task(
    *,
    world_state_version: int = 100,
    world_state_hash: str = "",
) -> SwarmTask:
    """Build a SwarmTask for supervisor tests."""
    if not world_state_hash:
        world_state_hash = compute_world_state_hash("ws_test", world_state_version)
    ctx = SwarmTaskContext(
        world_state_version=world_state_version,
        world_state_hash=world_state_hash,
        graph_version="gv_1",
        incident_entity_id="sup_001",
        incident_entity_type=EntityType.SUPPLIER,
        affected_entity_ids=["ord_001", "ord_002"],
        signals=[{
            "signal_id": "sig_001",
            "entity_id": "sup_001",
            "entity_type": "SUPPLIER",
            "signal_type": "SUPPLIER_DEGRADATION",
            "severity": "HIGH",
        }],
        blast_radius={
            "root_cause_entity_id": "sup_001",
            "affected_orders_count": 10,
            "affected_entity_ids": ["ord_001", "ord_002"],
            "geographic_exposure_regions": ["US-WEST"],
            "total_revenue_at_risk_usd": 100000.0,
        },
        workspace_id="ws_test",
        organization_id="org_test",
    )
    return SwarmTask.create(
        organization_id="org_test",
        workspace_id="ws_test",
        world_id="world_test",
        world_state_version=world_state_version,
        incident_id="sup_001",
        incident_entity_type=EntityType.SUPPLIER,
        signal_type="SUPPLIER_DEGRADATION",
        signal_severity="HIGH",
        context=ctx,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Determinism
# ─────────────────────────────────────────────────────────────────────────────


class TestProposalDeterminism:
    """Same world → same proposal_hash; same inputs → same option_hash."""

    def test_same_proposal_inputs_produce_same_hash(self):
        """Two proposals with identical fields produce identical proposal_hash."""
        p1 = _make_proposal(agent_id="agent_a", world_state_version=42)
        p2 = _make_proposal(agent_id="agent_a", world_state_version=42)
        assert p1.proposal_hash == p2.proposal_hash
        assert p1.proposal_hash != ""

    def test_proposal_hash_is_sha256_hex(self):
        """proposal_hash is a 64-char hex string (SHA-256)."""
        p = _make_proposal()
        assert len(p.proposal_hash) == 64
        assert all(c in "0123456789abcdef" for c in p.proposal_hash)

    def test_same_simulation_inputs_produce_same_option_hash(self):
        """ProposalSimulator: same inputs → identical option_hash."""
        sim = ProposalSimulator()
        proposals = [_make_proposal(agent_id="a1"), _make_proposal(agent_id="a2")]

        r1 = sim.simulate(proposals)
        r2 = sim.simulate(proposals)

        assert r1.simulation_hash == r2.simulation_hash
        assert len(r1.options) == len(r2.options)
        for o1, o2 in zip(r1.options, r2.options):
            assert o1.option_hash == o2.option_hash

    def test_simulation_hash_is_deterministic_across_instances(self):
        """Different ProposalSimulator instances produce same hashes for same inputs."""
        sim1 = ProposalSimulator()
        sim2 = ProposalSimulator()
        proposals = [_make_proposal(agent_id="x")]

        r1 = sim1.simulate(proposals)
        r2 = sim2.simulate(proposals)
        assert r1.simulation_hash == r2.simulation_hash

    def test_world_state_hash_determinism(self):
        """Same (workspace_id, version) → same hash."""
        h1 = compute_world_state_hash("ws_1", 42)
        h2 = compute_world_state_hash("ws_1", 42)
        assert h1 == h2
        assert len(h1) == 64


# ─────────────────────────────────────────────────────────────────────────────
# 2. Sensitivity
# ─────────────────────────────────────────────────────────────────────────────


class TestProposalSensitivity:
    """Different world_state_version → different proposal_hash."""

    def test_different_version_produces_different_hash(self):
        p1 = _make_proposal(world_state_version=100)
        p2 = _make_proposal(world_state_version=101)
        assert p1.proposal_hash != p2.proposal_hash

    def test_different_agent_produces_different_hash(self):
        p1 = _make_proposal(agent_id="agent_a")
        p2 = _make_proposal(agent_id="agent_b")
        assert p1.proposal_hash != p2.proposal_hash

    def test_different_action_produces_different_hash(self):
        p1 = _make_proposal(action="switch_supplier")
        p2 = _make_proposal(action="reroute_shipment")
        assert p1.proposal_hash != p2.proposal_hash

    def test_different_cost_produces_different_hash(self):
        p1 = _make_proposal(cost=5000.0)
        p2 = _make_proposal(cost=6000.0)
        assert p1.proposal_hash != p2.proposal_hash

    def test_different_world_state_hash_differs(self):
        h1 = compute_world_state_hash("ws_1", 42)
        h2 = compute_world_state_hash("ws_2", 42)
        h3 = compute_world_state_hash("ws_1", 43)
        assert h1 != h2
        assert h1 != h3

    def test_simulation_options_differ_for_different_proposals(self):
        """Different proposal params → different option_hashes."""
        sim = ProposalSimulator()
        r1 = sim.simulate([_make_proposal(cost=5000)])
        r2 = sim.simulate([_make_proposal(cost=6000)])
        assert r1.options[0].option_hash != r2.options[0].option_hash


# ─────────────────────────────────────────────────────────────────────────────
# 3. Proposal → Twin Flow
# ─────────────────────────────────────────────────────────────────────────────


class TestProposalToTwinFlow:
    """twin_simulation_fn produces results with simulation_hash; options reference proposals."""

    def test_twin_result_contains_simulation_hash(self):
        proposals = [_make_proposal(agent_id="a1"), _make_proposal(agent_id="a2")]
        result = twin_simulation_fn(proposals, None, world_state_version=100)
        assert "simulation_hash" in result
        assert result["simulation_hash"] != ""

    def test_twin_options_reference_proposal_agents(self):
        proposals = [
            _make_proposal(agent_id="procurement_agent"),
            _make_proposal(agent_id="booking_agent"),
        ]
        result = twin_simulation_fn(proposals, None, world_state_version=100)
        agent_ids = {o["agent_id"] for o in result["options"]}
        assert "procurement_agent" in agent_ids
        assert "booking_agent" in agent_ids

    def test_twin_result_has_world_state_version(self):
        proposals = [_make_proposal()]
        result = twin_simulation_fn(proposals, None, world_state_version=42)
        assert result["world_state_version"] == 42

    def test_twin_result_has_recommended(self):
        proposals = [_make_proposal(agent_id="a1"), _make_proposal(agent_id="a2")]
        result = twin_simulation_fn(proposals, None)
        assert result["recommended"] is not None
        assert "option_hash" in result["recommended"]

    def test_twin_empty_proposals_returns_no_proposals(self):
        result = twin_simulation_fn([], None)
        assert result["status"] == "NO_PROPOSALS"
        assert result["options"] == []

    def test_twin_with_world_variables(self):
        """twin_simulation_fn uses world.variables when available."""
        class _FakeWorld:
            variables = {"workspace.revenue": {"value": {"total_revenue_at_risk_usd": 50000}}}

        proposals = [_make_proposal()]
        result = twin_simulation_fn(proposals, _FakeWorld(), world_state_version=10)
        assert result["status"] == "COMPLETED"
        assert result["simulation_hash"] != ""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Twin → Policy Flow
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinToPolicyFlow:
    """Policy gate receives and verifies provenance; policy_version = v2."""

    def test_policy_passes_with_valid_proposals(self):
        proposals = [_make_proposal()]
        twin_result = twin_simulation_fn(proposals, None)
        result = policy_gate_fn(proposals, twin_result)
        assert result["approved"] is True
        assert result["policy_version"] == "v2"

    def test_policy_reports_simulation_hash(self):
        proposals = [_make_proposal()]
        twin_result = twin_simulation_fn(proposals, None)
        result = policy_gate_fn(proposals, twin_result)
        assert result["simulation_hash"] == twin_result["simulation_hash"]

    def test_policy_rejects_missing_proposal_hash(self):
        """Proposals without proposal_hash trigger PROPOSAL_HASH_MISSING."""
        p = AgentProposal(
            agent_id="a1",
            agent_family="PROCUREMENT",
            action="test",
            world_state_version=1,
            # proposal_hash intentionally empty
        )
        twin_result = {"status": "COMPLETED", "simulation_hash": "abc", "recommended": {"risk_score": 0.1, "nev_usd": 100}}
        result = policy_gate_fn([p], twin_result)
        assert result["approved"] is False
        assert any("PROPOSAL_HASH_MISSING" in v for v in result["violations"])

    def test_policy_rejects_version_mismatch(self):
        """Proposals with different world_state_version → VERSION_MISMATCH."""
        p1 = _make_proposal(agent_id="a1", world_state_version=10)
        p2 = _make_proposal(agent_id="a2", world_state_version=11)
        twin_result = {"status": "COMPLETED", "simulation_hash": "abc", "recommended": {"risk_score": 0.1, "nev_usd": 100}}
        result = policy_gate_fn([p1, p2], twin_result)
        assert result["approved"] is False
        assert any("VERSION_MISMATCH" in v for v in result["violations"])

    def test_policy_rejects_no_proposals(self):
        result = policy_gate_fn([], {})
        assert result["approved"] is False
        assert result["reason"] == "NO_PROPOSALS"

    def test_policy_rejects_no_simulation(self):
        proposals = [_make_proposal()]
        twin_result = {"status": "NO_PROPOSALS"}
        result = policy_gate_fn(proposals, twin_result)
        assert result["approved"] is False
        assert result["reason"] == "NO_SIMULATION"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Denied Decisions Cannot Execute
# ─────────────────────────────────────────────────────────────────────────────


class TestDeniedDecisionCannotExecute:
    """Execution gate blocks proposals that were not approved."""

    def test_no_policy_approval_blocked(self):
        p = _make_proposal()
        with pytest.raises(ExecutionGateError) as exc:
            execution_gate_fn(
                p, {"approved": False},
                organization_id="org",
                twin_result={"simulation_hash": "abc"},
            )
        assert "NO_POLICY_APPROVAL" in exc.value.reason

    def test_missing_proposal_hash_blocked(self):
        """Proposal without hash is blocked even with approval."""
        p = AgentProposal(
            agent_id="a1",
            agent_family="PROCUREMENT",
            action="test",
            world_state_version=1,
        )
        with pytest.raises(ExecutionGateError) as exc:
            execution_gate_fn(
                p, {"approved": True},
                organization_id="org",
                twin_result={"simulation_hash": "abc"},
            )
        assert "PROPOSAL_HASH_MISSING" in exc.value.reason

    def test_missing_simulation_hash_blocked(self):
        """Approved proposal with no simulation_hash is blocked."""
        p = _make_proposal()
        with pytest.raises(ExecutionGateError) as exc:
            execution_gate_fn(
                p, {"approved": True},
                organization_id="org",
                twin_result={},  # no simulation_hash
            )
        assert "SIMULATION_MISMATCH" in exc.value.reason

    def test_full_approval_passes_all_gates(self):
        """All gates pass with proper approval, hash, and simulation."""
        p = _make_proposal()
        result = execution_gate_fn(
            p,
            {"approved": True},
            organization_id="org_A",
            workspace_id="ws_A",
            world_state_version=100,
            current_world_version=100,
            twin_result={"simulation_hash": "abc123"},
        )
        assert result["status"] == "EXECUTED"
        assert result["proposal_hash"] == p.proposal_hash
        assert result["simulation_hash"] == "abc123"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Mutation → Invalidation
# ─────────────────────────────────────────────────────────────────────────────


class TestMutationInvalidation:
    """Decision at v1042, world advances to v1044 → STALE_DECISION."""

    def test_stale_decision_when_world_advances(self):
        """Decision made at v1042, world at v1044 → blocked."""
        p = _make_proposal(world_state_version=1042)
        with pytest.raises(ExecutionGateError) as exc:
            execution_gate_fn(
                p,
                {"approved": True},
                organization_id="org",
                world_state_version=1042,
                current_world_version=1044,  # world advanced by 2
                twin_result={"simulation_hash": "abc"},
            )
        assert "STALE_DECISION" in exc.value.reason

    def test_one_version_ahead_is_allowed(self):
        """Decision at v100, world at v101 → still valid (within tolerance)."""
        p = _make_proposal(world_state_version=100)
        result = execution_gate_fn(
            p,
            {"approved": True},
            organization_id="org",
            world_state_version=100,
            current_world_version=101,
            twin_result={"simulation_hash": "abc"},
        )
        assert result["status"] == "EXECUTED"

    def test_same_version_is_allowed(self):
        """Decision and world at same version → passes."""
        p = _make_proposal(world_state_version=50)
        result = execution_gate_fn(
            p,
            {"approved": True},
            organization_id="org",
            world_state_version=50,
            current_world_version=50,
            twin_result={"simulation_hash": "abc"},
        )
        assert result["status"] == "EXECUTED"

    def test_large_version_gap_is_stale(self):
        """Decision at v10, world at v100 → blocked (both STALE_DECISION and legacy)."""
        p = _make_proposal(world_state_version=10)
        with pytest.raises(ExecutionGateError) as exc:
            execution_gate_fn(
                p,
                {"approved": True},
                organization_id="org",
                world_state_version=10,
                current_world_version=100,
                twin_result={"simulation_hash": "abc"},
            )
        # STALE_DECISION fires first (tighter check)
        assert "STALE_DECISION" in exc.value.reason

    def test_execution_result_carries_provenance(self):
        """Successful execution returns proposal_hash and simulation_hash."""
        p = _make_proposal(world_state_version=100)
        result = execution_gate_fn(
            p,
            {"approved": True},
            organization_id="org",
            workspace_id="ws",
            world_state_version=100,
            current_world_version=100,
            twin_result={"simulation_hash": "sim_abc"},
        )
        assert result["proposal_hash"] == p.proposal_hash
        assert result["simulation_hash"] == "sim_abc"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Proposal Provenance (via supervisor)
# ─────────────────────────────────────────────────────────────────────────────


class TestProposalProvenance:
    """Every AgentProposal from real_supervisor_fn carries provenance when stamped."""

    def test_supervisor_produces_proposals(self):
        """real_supervisor_fn produces proposals from SwarmTask."""
        task = _make_swarm_task()
        proposals = real_supervisor_fn(task)
        assert len(proposals) > 0

    def test_stamped_proposals_carry_provenance(self):
        """After orchestrator stamps, proposals have version, hash, correlation_id."""
        task = _make_swarm_task(world_state_version=42)
        raw_proposals = real_supervisor_fn(task)

        ws_hash = compute_world_state_hash("ws_test", 42)
        # Simulate orchestrator stamping
        stamped = [
            replace(
                p,
                world_state_version=42,
                world_state_hash=ws_hash,
                correlation_id=task.task_id,
            )
            for p in raw_proposals
        ]
        stamped = [
            replace(p, proposal_hash=compute_proposal_hash(p))
            for p in stamped
        ]

        for p in stamped:
            assert p.world_state_version == 42
            assert p.world_state_hash == ws_hash
            assert p.correlation_id == task.task_id
            assert p.proposal_hash != ""
            assert len(p.proposal_hash) == 64

    def test_proposal_hash_reproducible_from_dict(self):
        """compute_proposal_hash is reproducible from the same proposal."""
        p = _make_proposal(agent_id="test", world_state_version=99)
        h1 = compute_proposal_hash(p)
        h2 = compute_proposal_hash(p)
        assert h1 == h2

    def test_proposal_to_dict_includes_provenance(self):
        """to_dict() surfaces all V2.2 fields."""
        p = _make_proposal()
        d = p.to_dict()
        assert "world_state_version" in d
        assert "world_state_hash" in d
        assert "correlation_id" in d
        assert "proposal_hash" in d

    def test_swarm_task_context_carries_world_state_hash(self):
        """SwarmTaskContext exposes world_state_hash."""
        ctx = SwarmTaskContext(
            world_state_version=42,
            world_state_hash="abc123",
        )
        assert ctx.world_state_hash == "abc123"
        d = ctx.to_dict()
        assert d["world_state_hash"] == "abc123"


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: ProposalSimulator edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestProposalSimulatorEdgeCases:
    """Edge cases and invariants for the ProposalSimulator."""

    def test_empty_proposals(self):
        sim = ProposalSimulator()
        result = sim.simulate([])
        assert result.options == []
        assert result.recommended is None
        assert result.simulation_hash != ""

    def test_single_proposal(self):
        sim = ProposalSimulator()
        result = sim.simulate([_make_proposal(agent_id="solo")])
        assert len(result.options) == 1
        assert result.recommended is not None
        assert result.recommended.agent_id == "solo"

    def test_options_sorted_by_nev_descending(self):
        """Options are sorted by NEV descending, then agent_id."""
        sim = ProposalSimulator()
        proposals = [
            _make_proposal(agent_id="high_risk", risk=0.9, cost=50000),
            _make_proposal(agent_id="low_risk", risk=0.1, cost=100),
        ]
        result = sim.simulate(proposals)
        nevs = [o.nev_usd for o in result.options]
        assert nevs == sorted(nevs, reverse=True)

    def test_nev_computation_is_deterministic(self):
        """Same inputs produce same NEV values."""
        sim = ProposalSimulator()
        proposals = [_make_proposal(cost=1000, risk=0.2, delay=1.0)]
        r1 = sim.simulate(proposals)
        r2 = sim.simulate(proposals)
        assert r1.options[0].nev_usd == r2.options[0].nev_usd

    def test_simulation_result_to_dict(self):
        sim = ProposalSimulator()
        result = sim.simulate([_make_proposal()])
        d = result.to_dict()
        assert d["status"] == "COMPLETED"
        assert "simulation_hash" in d
        assert "world_state_version" in d
        assert len(d["options"]) == 1
        assert d["recommended"] is not None
