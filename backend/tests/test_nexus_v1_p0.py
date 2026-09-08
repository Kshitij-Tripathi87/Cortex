"""Nexus v1.0 P0 — Production persistence, AuthZ, Realtime, Vanessa pipeline tests.

Validates the five P0 requirements:
  1. PG-backed DecisionLifecycleManager / DecisionMemory / TruthLoop survive
     simulated multi-worker restarts (one authority, not in-memory truth).
  2. Every persisted table has an AUTHORITATIVE/PROJECTION/CACHE/TEMPORARY
     classification.
  3. Realtime bus delivers events across in-process subscribers with
     sequence numbers, gap detection, and replay (works without Redis).
  4. AuthZ enforces role -> tool permission, including LLM pipeline
     permission denials (viewer cannot approve/execute).
  5. Vanessa pipeline never writes DB directly; all actions go through
     registered tool executors that are auth-checked.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Eagerly import nexus_spine models so they register in Base.metadata
# before db_engine builds the SQLite-compatible metadata copy.
from app.modules.nexus_spine.persistence import models as _spine_models  # noqa: F401

# ─────────────────────────────────────────────────────────────────────
# 1. Multi-worker persistence simulation
# ─────────────────────────────────────────────────────────────────────


class TestP0MultiWorkerPersistence:
    """Simulates independent API worker processes hitting a shared DB.
    The invariant: after any sequence of create/advance across workers
    the final state is consistent — no in-memory state leaks."""

    @pytest.mark.asyncio
    async def test_decision_survives_simulated_restart(self, db_engine):
        from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
        from app.modules.nexus_spine.p0_migration import (
            AuthoritativeDecisionMemory,
            AuthoritativeDecisionService,
            AuthoritativeTruthLoop,
        )

        TENANT = "T-ACME"
        WS = "WS-PRIMARY"
        DID = f"D-{uuid.uuid4().hex[:8]}"
        WS_HASH = "hash-v1"

        sf = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        # Worker A creates decision
        svc_a = AuthoritativeDecisionService()
        async with sf() as s:
            await svc_a.create(
                s,
                decision_id=DID,
                tenant_id=TENANT,
                workspace_id=WS,
                proposal_id="P-1",
                world_state_version=1,
                world_state_hash=WS_HASH,
                options=[{"option_id": "O1", "nev": 100.0, "sla": 0.95, "cost": 50.0}],
                recommended_option_id="O1",
                situation="Initial stockout risk for SKU-42",
            )
            await s.commit()
        del svc_a

        # Worker B (fresh cache) walks to APPROVED
        svc_b = AuthoritativeDecisionService()
        async with sf() as s:
            fetched = await svc_b.get(s, decision_id=DID)
            assert fetched is not None
            assert fetched["phase"] == DecisionPhase.PROPOSED.value
            await svc_b.advance(
                s, DID, DecisionPhase.SIMULATED, actor="analyst", reason="sim complete"
            )
            await svc_b.advance(
                s, DID, DecisionPhase.POLICY_CHECKED, actor="policy", reason="passed"
            )
            await svc_b.advance(
                s, DID, DecisionPhase.AWAITING_APPROVAL, actor="system", reason="queued"
            )
            await svc_b.advance(s, DID, DecisionPhase.APPROVED, actor="operator", reason="approved")
            await s.commit()
        del svc_b

        # Worker C authorizes + executes
        svc_c = AuthoritativeDecisionService()
        async with sf() as s:
            await svc_c.advance(
                s, DID, DecisionPhase.AUTHORIZED, actor="policy", reason="authorized"
            )
            await svc_c.advance(s, DID, DecisionPhase.EXECUTING, actor="executor", reason="start")
            await svc_c.advance(s, DID, DecisionPhase.EXECUTED, actor="executor", reason="done")
            await s.commit()
        del svc_c

        # Worker D (fresh) records outcome, memory entry, forecast, observation
        svc_d = AuthoritativeDecisionService()
        truth_d = AuthoritativeTruthLoop()
        mem_d = AuthoritativeDecisionMemory()
        async with sf() as s:
            final = await svc_d.get(s, decision_id=DID)
            assert final["phase"] == DecisionPhase.EXECUTED.value

            await svc_d.record_outcome(
                s,
                DID,
                actor="operator",
                outcome_payload={"result": "delivered"},
                actual_nev=95.0,
                actual_sla=0.97,
                actual_cost=48.0,
                outcome_status="succeeded",
                financial_impact=42.5,
                actual_result_text="Restock succeeded within SLA",
            )

            await mem_d.record(
                s,
                decision_id=DID,
                tenant_id=TENANT,
                workspace_id=WS,
                situation="Initial stockout risk for SKU-42",
                evidence_ids=[],
                world_state_version=1,
                options=[{"option_id": "O1", "nev": 100.0, "sla": 0.95, "cost": 50.0}],
                recommended_option_id="O1",
                chosen_option_id="O1",
                policy_id="POL-1",
            )
            await mem_d.update_outcome(
                s,
                DID,
                outcome_status="successful",
                financial_impact=42.5,
                human_feedback="good outcome",
            )

            fid = f"F-{uuid.uuid4().hex[:8]}"
            await truth_d.record_forecast(
                s,
                forecast_id=fid,
                tenant_id=TENANT,
                workspace_id=WS,
                sku="SKU-42",
                p50=100.0,
                p80=120.0,
                p95=140.0,
                mean=100.0,
                std_dev=20.0,
                world_state_version=1,
            )
            obs = await truth_d.observe(
                s,
                forecast_id=fid,
                tenant_id=TENANT,
                workspace_id=WS,
                sku="SKU-42",
                actual_value=110.0,
            )
            await s.commit()
            assert obs is not None
            assert obs["absolute_error"] == pytest.approx(10.0, abs=0.01)

            calib = await truth_d.calibration_for(s, TENANT, WS)
            assert len(calib) >= 1
            assert calib[0]["sku"] == "SKU-42"
            assert calib[0]["sample_count"] >= 1

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, db_engine):
        from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
        from app.modules.nexus_spine.p0_migration import (
            AuthoritativeDecisionService,
            InvalidTransitionError,
        )

        sf = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
        svc = AuthoritativeDecisionService()
        async with sf() as s:
            did = f"D-{uuid.uuid4().hex[:8]}"
            await svc.create(
                s,
                decision_id=did,
                tenant_id="T",
                workspace_id="W",
                proposal_id="P",
                world_state_version=1,
                world_state_hash="h",
                options=[],
            )
            await s.commit()
            # cannot jump proposed -> executed (invalid per ALLOWED_TRANSITIONS)
            with pytest.raises(InvalidTransitionError):
                await svc.advance(s, did, DecisionPhase.EXECUTED, actor="x", reason="nope")
            await s.rollback()

    @pytest.mark.asyncio
    async def test_append_only_transitions_persist(self, db_engine):
        from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
        from app.modules.nexus_spine.p0_migration import AuthoritativeDecisionService

        sf = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
        svc = AuthoritativeDecisionService()
        async with sf() as s:
            did = f"D-{uuid.uuid4().hex[:8]}"
            await svc.create(
                s,
                decision_id=did,
                tenant_id="T",
                workspace_id="W",
                proposal_id="P",
                world_state_version=1,
                world_state_hash="h",
                options=[],
            )
            await svc.advance(s, did, DecisionPhase.SIMULATED, actor="a")
            await svc.advance(s, did, DecisionPhase.POLICY_CHECKED, actor="a")
            await svc.advance(s, did, DecisionPhase.AWAITING_APPROVAL, actor="a")
            await svc.advance(s, did, DecisionPhase.APPROVED, actor="a")
            await svc.advance(s, did, DecisionPhase.AUTHORIZED, actor="a")
            await svc.advance(s, did, DecisionPhase.EXECUTING, actor="a")
            await svc.advance(s, did, DecisionPhase.EXECUTED, actor="a")
            await svc.record_outcome(
                s, did, actor="a", outcome_payload={}, outcome_status="succeeded"
            )
            await s.commit()
            final = await svc.get(s, decision_id=did)
            assert final["phase"] == DecisionPhase.OUTCOME_RECORDED.value


# ─────────────────────────────────────────────────────────────────────
# 2. Table classification
# ─────────────────────────────────────────────────────────────────────


class TestP0TableClassification:
    def test_all_nexus_and_world_tables_classified(self):
        from app.modules.nexus_spine.p0_migration import (
            TABLE_CLASSIFICATION,
            DataClassification,
        )

        expected = {
            "world_states",
            "world_state_events",
            "nexus_entities",
            "nexus_relationships",
            "nexus_decisions",
            "nexus_decision_transitions",
            "nexus_approvals",
            "nexus_executions",
            "nexus_outcomes",
            "nexus_evidence_nodes",
            "nexus_evidence_edges",
            "nexus_forecasts",
            "nexus_observations",
            "nexus_recommendations",
            "nexus_model_registry",
            "nexus_vanessa_sessions",
            "nexus_vanessa_messages",
            "nexus_risks",
            "nexus_scenarios",
            "nexus_events",
        }
        for t in expected:
            assert t in TABLE_CLASSIFICATION, f"Missing classification for {t}"
            assert isinstance(TABLE_CLASSIFICATION[t], DataClassification)

    def test_exactly_one_authoritative_world(self):
        from app.modules.nexus_spine.p0_migration import (
            TABLE_CLASSIFICATION,
            DataClassification,
        )

        assert TABLE_CLASSIFICATION["world_states"] == DataClassification.AUTHORITATIVE
        assert TABLE_CLASSIFICATION["nexus_decisions"] == DataClassification.AUTHORITATIVE
        assert TABLE_CLASSIFICATION["nexus_entities"] == DataClassification.AUTHORITATIVE
        assert TABLE_CLASSIFICATION["nexus_forecasts"] == DataClassification.AUTHORITATIVE
        assert TABLE_CLASSIFICATION["nexus_risks"] == DataClassification.PROJECTION
        assert TABLE_CLASSIFICATION["nexus_scenarios"] == DataClassification.PROJECTION


# ─────────────────────────────────────────────────────────────────────
# 3. Realtime bus — sequence numbers, gap detection, replay (no Redis needed)
# ─────────────────────────────────────────────────────────────────────


class TestP0RealtimeBus:
    @pytest.mark.asyncio
    async def test_subscribers_receive_events(self):
        from app.infrastructure.realtime_bus import get_realtime_bus

        bus = get_realtime_bus()
        q = bus.subscribe("WS-RT-1")
        try:
            evt = await bus.publish(
                tenant_id="T",
                workspace_id="WS-RT-1",
                event_type="decision.proposed",
                entity_type="decision",
                entity_id="D1",
                payload={"phase": "proposed"},
                world_state_version=1,
            )
            received = await asyncio.wait_for(q.get(), timeout=2.0)
            assert received.event_id == evt.event_id
            assert received.seq == evt.seq
        finally:
            bus.unsubscribe("WS-RT-1", q)

    @pytest.mark.asyncio
    async def test_sequence_numbers_monotonic(self):
        from app.infrastructure.realtime_bus import get_realtime_bus

        bus = get_realtime_bus()
        q = bus.subscribe("WS-RT-2")
        try:
            await bus.publish(tenant_id="T", workspace_id="WS-RT-2", event_type="a")
            await bus.publish(tenant_id="T", workspace_id="WS-RT-2", event_type="b")
            await bus.publish(tenant_id="T", workspace_id="WS-RT-2", event_type="c")
            r1 = await asyncio.wait_for(q.get(), timeout=2.0)
            r2 = await asyncio.wait_for(q.get(), timeout=2.0)
            r3 = await asyncio.wait_for(q.get(), timeout=2.0)
            assert r1.seq < r2.seq < r3.seq
        finally:
            bus.unsubscribe("WS-RT-2", q)

    @pytest.mark.asyncio
    async def test_gap_detection_in_sse_stream_logic(self):
        """The sse_stream generator yields a resync_needed event when it
        observes a jump in seq numbers. We test the generator's logic
        directly by giving it a queue with a gap injected."""
        import asyncio

        # Don't go through subscribe() — drive sse_stream logic manually.
        # We use a dedicated workspace and replace the queue it listens on
        # by monkeypatching bus.subscribe to return a queue we control.
        from app.infrastructure.realtime_bus import Event, get_realtime_bus, sse_stream

        bus = get_realtime_bus()
        WS = "WS-RT-3"
        test_q: asyncio.Queue = asyncio.Queue()
        original_sub = bus.subscribe
        bus.subscribe = lambda ws: test_q  # type: ignore
        try:
            stream = sse_stream(WS, last_seen_seq=0)
            connected = await stream.__anext__()
            assert "connected" in connected
            await test_q.put(
                Event(
                    event_id="E1",
                    seq=1,
                    event_type="a",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=1,
                )
            )
            ev1 = await stream.__anext__()
            assert "E1" in ev1
            # Gap: seq 3 without seq 2
            await test_q.put(
                Event(
                    event_id="E3",
                    seq=3,
                    event_type="b",
                    entity_type=None,
                    entity_id=None,
                    payload={},
                    world_state_version=1,
                )
            )
            resync = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
            assert "resync_needed" in resync
            await stream.aclose()
        finally:
            bus.subscribe = original_sub


# ─────────────────────────────────────────────────────────────────────
# 4. AuthZ — role hierarchy enforcement
# ─────────────────────────────────────────────────────────────────────


class TestP0AuthZ:
    def test_viewer_can_read_cannot_execute(self):
        from app.modules.nexus_spine.p0_migration import (
            AuthorizationService,
            NexusRole,
            PermissionDenied,
            Principal,
        )

        authz = AuthorizationService()
        viewer = Principal(
            user_id="u1",
            tenant_id="T1",
            organization_id=None,
            workspace_id="WS1",
            role=NexusRole.VIEWER,
        )
        assert authz.can(viewer, "nexus.state.read")
        assert authz.can(viewer, "nexus.cockpit.read")
        assert not authz.can(viewer, "nexus.decision.approve")
        assert not authz.can(viewer, "nexus.decision.execute")
        with pytest.raises(PermissionDenied):
            authz.check(viewer, "nexus.decision.execute")

    def test_analyst_can_simulate_cannot_execute(self):
        from app.modules.nexus_spine.p0_migration import (
            AuthorizationService,
            NexusRole,
            Principal,
        )

        authz = AuthorizationService()
        analyst = Principal(
            user_id="u2",
            tenant_id="T1",
            organization_id=None,
            workspace_id="WS1",
            role=NexusRole.ANALYST,
        )
        assert authz.can(analyst, "nexus.rl.simulate")
        assert authz.can(analyst, "nexus.demand.run")
        assert authz.can(analyst, "nexus.recommend")
        assert not authz.can(analyst, "nexus.decision.execute")
        assert not authz.can(analyst, "nexus.decision.approve")

    def test_operator_full_operational(self):
        from app.modules.nexus_spine.p0_migration import (
            AuthorizationService,
            NexusRole,
            Principal,
        )

        authz = AuthorizationService()
        op = Principal(
            user_id="u3",
            tenant_id="T1",
            organization_id=None,
            workspace_id="WS1",
            role=NexusRole.OPERATOR,
        )
        assert authz.can(op, "nexus.decision.approve")
        assert authz.can(op, "nexus.decision.execute")
        assert authz.can(op, "nexus.rl.simulate")
        assert authz.can(op, "nexus.state.read")
        assert not authz.can(op, "nexus.admin.configure")

    def test_tenant_isolation(self):
        from app.modules.nexus_spine.p0_migration import (
            AuthorizationService,
            NexusRole,
            PermissionDenied,
            Principal,
        )

        authz = AuthorizationService()
        op = Principal(
            user_id="u3",
            tenant_id="T1",
            organization_id=None,
            workspace_id="WS1",
            role=NexusRole.OPERATOR,
        )
        with pytest.raises(PermissionDenied):
            authz.check(op, "nexus.state.read", data_tenant="T2")


# ─────────────────────────────────────────────────────────────────────
# 5. Vanessa pipeline — no DB writes; AuthZ enforced; intent classification
# ─────────────────────────────────────────────────────────────────────


class TestP0VanessaPipeline:
    @pytest.mark.asyncio
    async def test_viewer_cannot_approve_via_pipeline(self):
        """LLM must not manufacture authority. Viewer cannot approve."""
        from app.modules.nexus_spine.p0_migration import (
            DeterministicLLMAdapter,
            NexusRole,
            Principal,
            VanessaPipeline,
        )

        pipeline = VanessaPipeline(llm=DeterministicLLMAdapter())
        calls: list[str] = []
        pipeline.register_tool_executor(
            "nexus.decision.approve",
            lambda tc, p: calls.append(tc.tool) or {"approved": True},
        )
        viewer = Principal(
            user_id="u1",
            tenant_id="T",
            organization_id=None,
            workspace_id="WS",
            role=NexusRole.VIEWER,
        )
        resp = await pipeline.handle(viewer, "approve decision D-42 please")
        assert resp.permission_denied is not None, "Viewer must be denied approval"
        assert calls == [], "Tool executor must NOT be invoked when permission is denied"

    @pytest.mark.asyncio
    async def test_operator_can_read_state_via_pipeline(self):
        from app.modules.nexus_spine.p0_migration import (
            DeterministicLLMAdapter,
            NexusRole,
            Principal,
            VanessaPipeline,
        )

        pipeline = VanessaPipeline(llm=DeterministicLLMAdapter())
        state_data = {"summary": "World state v12: 5 SKUs healthy, 1 at risk", "version": 12}
        pipeline.register_tool_executor("nexus.cockpit.read", lambda tc, p: state_data)
        op = Principal(
            user_id="op",
            tenant_id="T",
            organization_id=None,
            workspace_id="WS",
            role=NexusRole.OPERATOR,
        )
        resp = await pipeline.handle(op, "what is the state of the world?")
        assert resp.permission_denied is None
        assert "nexus.cockpit.read" in resp.actions_taken
        assert len(resp.evidence) >= 1
        assert resp.trace_id.startswith("TRC-")

    @pytest.mark.asyncio
    async def test_pipeline_never_writes_db_directly(self):
        """Static check: pipeline source must never touch a DB session directly."""
        import inspect

        from app.modules.nexus_spine.p0_migration import vanessa_pipeline

        src = inspect.getsource(vanessa_pipeline)
        assert "AsyncSession" not in src
        assert "session.add" not in src
        assert "session.commit" not in src

    @pytest.mark.asyncio
    async def test_intent_classification_priority(self):
        """Operational verbs must beat generic nouns: 'execute the decision'
        is EXECUTE, not DECISION_QUERY."""
        from app.modules.nexus_spine.p0_migration import (
            DeterministicLLMAdapter,
            IntentType,
        )

        llm = DeterministicLLMAdapter()
        i = await llm.classify_intent("what is the forecast for SKU-42?")
        assert i.intent == IntentType.FORECAST_QUERY
        assert i.entities.get("sku") == "SKU-42"

        i2 = await llm.classify_intent("execute the decision now")
        assert i2.intent == IntentType.EXECUTE, f"got {i2.intent.value}"

        i3 = await llm.classify_intent("approve D-42")
        assert i3.intent == IntentType.APPROVE

        i4 = await llm.classify_intent("asdf qwerty zxcv")
        assert i4.intent == IntentType.UNKNOWN

        i5 = await llm.classify_intent("compare scenario A vs B")
        assert i5.intent == IntentType.COMPARE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
