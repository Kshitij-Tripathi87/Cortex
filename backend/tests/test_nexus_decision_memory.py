"""Tests for the Nexus Decision Memory subsystem.

Covers:
- DecisionRecord creation + serialization
- Recording, retrieval, outcome update
- Analogous-decision retrieval (Jaccard similarity)
- Workspace isolation
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.nexus_spine.memory import (
    DecisionMemory,
    DecisionRecord,
    get_decision_memory,
    reset_decision_memory,
)


@pytest.fixture
def mem() -> DecisionMemory:
    reset_decision_memory()
    return get_decision_memory()


def _record(
    decision_id: str,
    situation: str,
    *,
    tenant: str = "tenant-1",
    workspace: str = "ws-1",
    outcome: str = "succeeded",
    financial_impact: float | None = None,
    chosen: str = "B",
    tags: list[str] | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        tenant_id=tenant,
        workspace_id=workspace,
        situation=situation,
        evidence_ids=["ev-1"],
        world_state_version=42,
        options=[
            {"id": "A", "description": "Air freight"},
            {"id": "B", "description": "Alternate supplier"},
        ],
        recommended_option_id="B",
        chosen_option_id=chosen,
        policy_id="pol-v1",
        approval_id="apr-1",
        executed_at=datetime.now(UTC),
        outcome_status=outcome,
        financial_impact=financial_impact,
        actual_result="Recovered SLA within 2.8 days",
        tags=tags or [],
    )


def test_record_and_get(mem: DecisionMemory):
    r = _record("dec-1", "Supplier S-142 outage")
    mem.record(r)
    fetched = mem.get("dec-1")
    assert fetched is not None
    assert fetched.situation == "Supplier S-142 outage"
    assert fetched.tenant_id == "tenant-1"


def test_update_outcome_changes_status_and_impact(mem: DecisionMemory):
    r = _record("dec-1", "Situation X")
    mem.record(r)
    updated = mem.update_outcome(
        "dec-1",
        outcome_status="failed",
        financial_impact=-12000.0,
        actual_result="SLA missed by 1.4 days",
    )
    assert updated is not None
    assert updated.outcome_status == "failed"
    assert updated.financial_impact == -12000.0
    assert updated.actual_result == "SLA missed by 1.4 days"
    assert updated.situation == "Situation X"  # immutable


def test_update_outcome_unknown_decision_returns_none(mem: DecisionMemory):
    assert mem.update_outcome("missing", outcome_status="failed") is None


def test_find_analogous_returns_similar_decisions(mem: DecisionMemory):
    mem.record(_record("d1", "Supplier S-142 capacity outage affected orders"))
    mem.record(_record("d2", "Port P-07 congestion delays shipments"))
    mem.record(_record("d3", "Annual safety stock audit review"))
    analogues = mem.find_analogous(
        tenant_id="tenant-1",
        workspace_id="ws-1",
        situation="Supplier S-188 capacity outage affecting orders",
    )
    assert len(analogues) >= 1
    assert analogues[0].decision.decision_id == "d1"
    assert analogues[0].similarity > 0


def test_find_analogous_respects_min_similarity(mem: DecisionMemory):
    mem.record(_record("d1", "Supplier S-142 capacity outage"))
    analogues = mem.find_analogous(
        tenant_id="tenant-1",
        workspace_id="ws-1",
        situation="Audit review safety stock",
        min_similarity=0.5,
    )
    assert all(a.similarity >= 0.5 for a in analogues)


def test_find_analogous_isolated_by_workspace(mem: DecisionMemory):
    mem.record(_record("d1", "Supplier outage scenario", tenant="t-1", workspace="w-1"))
    mem.record(_record("d2", "Supplier outage scenario", tenant="t-2", workspace="w-2"))
    analogues = mem.find_analogous(
        tenant_id="t-1",
        workspace_id="w-1",
        situation="Supplier outage scenario",
    )
    assert all(a.decision.tenant_id == "t-1" for a in analogues)
    assert not any(a.decision.decision_id == "d2" for a in analogues)


def test_recent_returns_decisions_in_executed_at_order(mem: DecisionMemory):
    mem.record(_record("d1", "First"))
    mem.record(_record("d2", "Second"))
    recent = mem.recent(tenant_id="tenant-1", workspace_id="ws-1", limit=10)
    assert len(recent) == 2


def test_analogous_decision_to_dict_includes_similarity(mem: DecisionMemory):
    mem.record(_record("d1", "Supplier S-142 capacity outage"))
    analogues = mem.find_analogous(
        tenant_id="tenant-1",
        workspace_id="ws-1",
        situation="Supplier S-142 capacity outage",
    )
    if analogues:
        d = analogues[0].to_dict()
        assert "decision" in d
        assert "similarity" in d
        assert "outcome_summary" in d


def test_decision_record_to_dict_is_complete():
    r = _record("d1", "Test", outcome="succeeded", financial_impact=1000.0)
    d = r.to_dict()
    assert d["decision_id"] == "d1"
    assert d["outcome_status"] == "succeeded"
    assert d["financial_impact"] == 1000.0
    assert d["evidence_ids"] == ["ev-1"]
