"""Nexus v0.7 — Golden trace validation for Production Intelligence & Learning.

Tests the full decision-intelligence loop with new v0.7 components:

  World State → Signal → Risk (+GNN) → Forecast (+Learning) → Scenario
    → RL Candidates → Recommendation → Decision → Approval → Execution
    → Outcome → Memory → Evidence → Vanessa (contextual sessions)

Plus validates:
  - Model Registry lifecycle (no model jumps dev→prod)
  - Forecast metrics tracking (MAE/WAPE/bias/drift)
  - Bounded RL (never directly executes)
  - Recommendation evaluation (accuracy/regret)
  - Explanation engine (WHAT/WHY/IMPACT/CONFIDENCE/EVIDENCE/WHAT NEXT)
  - Vanessa sessions (anaphora resolution, context)
  - Intelligence health dashboard
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestNexusV07ModelRegistry:
    """Model Registry (item 2) — no model jumps directly to production."""

    def test_seeded_models(self):
        from app.modules.nexus_spine import get_model_registry, ModelLifecycleStatus
        mr = get_model_registry()
        models = mr.list()
        assert len(models) >= 4, "Should seed baseline models"
        # Baseline forecast deployed
        forecast = mr.get_deployed("forecast")
        assert forecast is not None
        assert forecast.status == ModelLifecycleStatus.DEPLOYED

    def test_lifecycle_transitions_enforced(self):
        from app.modules.nexus_spine import get_model_registry, ModelLifecycleStatus
        mr = get_model_registry()
        m = mr.register(name="test-model", version="v0.1", model_type="forecast")
        assert m.status == ModelLifecycleStatus.TRAINING
        # Cannot jump directly to deployed
        with pytest.raises(ValueError):
            mr.transition(m.model_id, ModelLifecycleStatus.DEPLOYED)
        # Can go training → evaluating
        mr.transition(m.model_id, ModelLifecycleStatus.EVALUATING)
        assert m.status == ModelLifecycleStatus.EVALUATING
        # Can go evaluating → shadow
        mr.transition(m.model_id, ModelLifecycleStatus.SHADOW)
        assert m.status == ModelLifecycleStatus.SHADOW

    def test_health_summary(self):
        from app.modules.nexus_spine import get_model_registry
        mr = get_model_registry()
        health = mr.health_summary()
        assert "Demand forecast" in health
        assert "Supplier risk" in health
        assert "Scenario accuracy" in health


class TestNexusV07ForecastLearning:
    """Forecast learning metrics (item 3) — MAE/RMSE/WAPE/bias/drift segmented."""

    def test_tracker_initial_state(self):
        from app.modules.nexus_spine import get_forecast_metrics_tracker
        ft = get_forecast_metrics_tracker()
        health = ft.overall_health()
        assert health["samples"] >= 0
        assert "accuracy" in health
        assert "wape" in health

    def test_recording_evaluations(self):
        from app.modules.nexus_spine.learning import ForecastMetricsTracker
        from app.modules.nexus_spine.demand.engine import ForecastEvaluation
        ft = ForecastMetricsTracker()
        # Record several points
        for i, (predicted, actual) in enumerate([
            (100, 105), (100, 98), (100, 103), (100, 97), (100, 102),
            (100, 110), (100, 108), (100, 112),  # recent drift upward
        ]):
            fe = ForecastEvaluation(
                forecast_id=f"F-{i}",
                sku="SKU-TEST",
                predicted_p50=predicted,
                actual=actual,
                absolute_error=actual - predicted,
                percentage_error=(actual - predicted) / predicted,
                bias=actual - predicted,
                is_within_p80=abs(actual - predicted) < 15,
                is_within_p95=abs(actual - predicted) < 25,
            )
            ft.record(fe, sku="SKU-TEST", supplier_id="S-1", region="NA", horizon_days=14, model_version="v1")
        metrics = ft.get_metrics(sku="SKU-TEST")
        assert len(metrics) >= 1
        m = metrics[0]
        assert m.mae >= 0
        assert m.sample_count == 8
        wrong = ft.where_is_forecast_wrong(min_samples=3, min_abs_mpe=0.01)
        assert isinstance(wrong, list)

    def test_overall_health_aggregates(self):
        from app.modules.nexus_spine.learning import ForecastMetricsTracker
        ft = ForecastMetricsTracker()
        health = ft.overall_health()
        assert health["status"] in ("healthy", "degraded", "insufficient_data")


class TestNexusV07GNN:
    """GNN integration (item 4) — critical nodes, hidden deps, risk augmentation."""

    def test_engine_creation(self):
        from app.modules.nexus_spine import get_gnn_engine
        gnn = get_gnn_engine()
        assert gnn is not None
        h = gnn.health()
        assert "nodes" in h and "edges" in h

    def test_empty_graph_doesnt_crash(self):
        from app.modules.nexus_spine.gnn import GNNEngine
        gnn = GNNEngine()
        nodes = gnn.get_critical_nodes(5)
        assert isinstance(nodes, list)


class TestNexusV07BoundedRL:
    """Bounded RL (item 5) — never executes directly, always requires human approval."""

    def test_candidates_require_human_approval(self):
        from app.modules.nexus_spine import get_candidate_generator
        gen = get_candidate_generator()
        candidates = gen.generate_candidates(
            situation={},
            risk_score=0.8,
            entity_id="S-TEST",
            entity_kind="supplier",
            revenue_exposure=100000,
            current_delay_days=3,
        )
        assert len(candidates) >= 1
        for c in candidates:
            d = c.to_dict()
            assert d["bounded"] is True, "RL candidates must be bounded"
            assert d["requires_human_approval"] is True, "RL must never bypass human approval"
            assert d["requires_simulation"] is True, "RL candidates must be simulated first"

    def test_candidates_dont_include_blocked_actions(self):
        from app.modules.nexus_spine import get_candidate_generator
        gen = get_candidate_generator()
        candidates = gen.generate_candidates(
            situation={}, risk_score=0.5, entity_id="X", entity_kind="supplier",
        )
        for c in candidates:
            assert "cancel" not in c.action_type
            assert "delete" not in c.action_type
            assert "auto_execute" not in c.action_type

    def test_baseline_option_always_present(self):
        """Conservative hold/do-nothing option is always included for comparison."""
        from app.modules.nexus_spine import get_candidate_generator
        gen = get_candidate_generator()
        candidates = gen.generate_candidates(
            situation={}, risk_score=0.5, entity_id="X", entity_kind="supplier",
        )
        types = [c.action_type for c in candidates]
        assert "hold_order_consolidate" in types, "Baseline must always be an option"

    def test_candidate_ranking(self):
        from app.modules.nexus_spine import get_candidate_generator
        gen = get_candidate_generator()
        candidates = gen.generate_candidates(
            situation={}, risk_score=0.9, entity_id="S-142", entity_kind="supplier",
            revenue_exposure=5000000, current_delay_days=7,
        )
        ranked = gen.evaluate_candidates(candidates)
        assert len(ranked) == len(candidates)
        if len(ranked) > 1:
            assert ranked[0]["composite_score"] >= ranked[-1]["composite_score"]
            assert ranked[0]["is_optimal"] is True


class TestNexusV07RecommendationEvaluation:
    """Recommendation evaluation (item 6) — measure actual outcomes vs predicted."""

    def test_create_and_evaluate(self):
        from app.modules.nexus_spine import get_recommendation_evaluator
        ev = get_recommendation_evaluator()
        rec = ev.create(
            tenant_id="t", workspace_id="w",
            recommended_action="expedite",
            alternative_actions=[{"action": "hold"}],
            predicted_nev=100000, predicted_sla=0.95, predicted_cost=15000,
            confidence=0.8,
        )
        assert rec.outcome is None
        evaluated = ev.evaluate(
            rec.recommendation_id,
            actual_nev=90000, actual_sla=0.93, actual_cost=16000,
            outcome="success",
        )
        assert evaluated is not None
        assert evaluated.outcome == "success"
        assert evaluated.recommendation_accuracy is not None
        assert evaluated.recommendation_regret is not None
        assert 0 <= evaluated.recommendation_accuracy <= 1

    def test_performance_summary(self):
        from app.modules.nexus_spine.recommendations import RecommendationEvaluator
        ev = RecommendationEvaluator()
        rec = ev.create(
            tenant_id="t", workspace_id="w",
            recommended_action="test", alternative_actions=[],
            predicted_nev=50, predicted_sla=0.9, predicted_cost=10, confidence=0.8,
        )
        ev.evaluate(rec.recommendation_id, actual_nev=45, actual_sla=0.88, actual_cost=11, outcome="success")
        summary = ev.performance_summary("t", "w")
        assert summary["evaluated"] == 1
        assert summary["decision_success_rate"] == 1.0


class TestNexusV07ExplanationEngine:
    """WHAT/WHY/IMPACT/CONFIDENCE/EVIDENCE/WHAT NEXT (item 10)."""

    def test_risk_explanation_has_all_fields(self):
        from app.modules.nexus_spine import get_explanation_engine
        eng = get_explanation_engine()
        exp = eng.explain_risk(
            entity_id="S-142", entity_name="Supplier S-142", entity_kind="supplier",
            severity="CRITICAL", risk_score=0.71, gnn_risk_score=0.88,
            title="Revenue exposure increased ₹8.7L",
            description="Capacity fell 31%",
            root_causes=["Port congestion", "Labor strike"],
            revenue_exposure=870000, sla_risk_pct=0.82,
            affected_orders=37, affected_skus=["SKU-1", "SKU-2"],
            affected_plants=["P-1", "P-2"], blast_radius_count=12,
            confidence=0.91,
        )
        assert exp.what
        assert exp.why
        assert exp.impact
        assert 0 <= exp.confidence <= 1
        assert exp.evidence_count >= 0
        assert len(exp.what_next) >= 1
        assert len(exp.what_next_actions) >= 1
        assert len(exp.blocks) >= 1
        d = exp.to_dict()
        assert "subject_id" in d

    def test_forecast_explanation(self):
        from app.modules.nexus_spine import get_explanation_engine
        eng = get_explanation_engine()
        exp = eng.explain_forecast(
            sku="SKU-102", p50=14200, p80=15700, p95=17900,
            actual=15100, wape=0.087, bias=-0.041,
        )
        assert "P50" in exp.what or "14,200" in exp.what
        assert len(exp.blocks) >= 1

    def test_intelligence_health_explanation(self):
        from app.modules.nexus_spine import get_explanation_engine, get_model_registry
        eng = get_explanation_engine()
        mr = get_model_registry()
        health = mr.health_summary()
        exp = eng.explain_intelligence_health(health)
        assert exp.subject_kind == "health"
        assert exp.confidence > 0
        assert len(exp.blocks) >= 1


class TestNexusV07VanessaSessions:
    """Production Vanessa (items 7, 8) — contextual sessions + multimodal blocks."""

    def test_create_session(self):
        from app.modules.nexus_spine import get_vanessa_session_manager
        mgr = get_vanessa_session_manager()
        sid, ctx = mgr.get_or_create_session(tenant_id="t", workspace_id="w", user_id="u")
        assert sid.startswith("VSESS-")
        assert ctx.user_id == "u"

    def test_update_context(self):
        from app.modules.nexus_spine import get_vanessa_session_manager
        mgr = get_vanessa_session_manager()
        sid, _ = mgr.get_or_create_session(tenant_id="t2", workspace_id="w2", user_id="u2")
        mgr.update_context(sid, selected_entity_id="S-142", selected_entity_name="Supplier 142", selected_entity_kind="supplier")
        ctx = mgr.get_context(sid)
        assert ctx.selected_entity_id == "S-142"
        assert ctx.selected_entity_name == "Supplier 142"

    def test_contextual_suggestions(self):
        from app.modules.nexus_spine import get_vanessa_session_manager
        mgr = get_vanessa_session_manager()
        sid, _ = mgr.get_or_create_session(tenant_id="t3", workspace_id="w3", user_id="u3")
        mgr.update_context(sid, selected_entity_id="S-142", last_topic="supplier")
        # Ask an anaphoric question
        resp = mgr.ask(sid, "Why is it risky?")
        assert resp.answer
        assert resp.intent
        assert resp.confidence >= 0
        assert len(resp.response_blocks) >= 1
        assert len(resp.suggestions) >= 1

    def test_multimodal_response_blocks(self):
        from app.modules.nexus_spine import get_vanessa_session_manager, ResponseBlockType
        mgr = get_vanessa_session_manager()
        sid, _ = mgr.get_or_create_session(tenant_id="t4", workspace_id="w4", user_id="u4")
        resp = mgr.ask(sid, "Which suppliers are at risk?")
        block_types = {b["type"] for b in resp.response_blocks}
        assert ResponseBlockType.TEXT.value in block_types, "Every response must include a text block"

    def test_history_recorded(self):
        from app.modules.nexus_spine import get_vanessa_session_manager
        mgr = get_vanessa_session_manager()
        sid, _ = mgr.get_or_create_session(tenant_id="t5", workspace_id="w5", user_id="u5")
        mgr.ask(sid, "Hello world")
        history = mgr.get_history(sid)
        assert len(history) >= 2  # user + assistant


class TestNexusV07RealtimeEvents:
    """Realtime event types (item 11)."""

    def test_event_types_exist(self):
        from app.modules.nexus_spine import NexusEventType
        expected = {
            "world_state_changed", "signal_created", "risk_changed",
            "forecast_updated", "scenario_completed",
            "decision_created", "decision_invalidated",
            "approval_granted", "execution_started", "execution_completed",
            "outcome_recorded", "drift_detected", "recommendation_made",
        }
        for name in expected:
            assert hasattr(NexusEventType, name.upper()) or any(e.value == name for e in NexusEventType), f"Missing event type: {name}"

    def test_sse_format(self):
        from app.modules.nexus_spine import NexusEventType, event_to_sse
        msg = event_to_sse(NexusEventType.RISK_CHANGED, {"entity_id": "S-142"})
        assert msg.startswith("event: risk_changed")
        assert "data:" in msg


class TestNexusV07EndToEndGoldenTrace:
    """Full golden trace through the v0.7 loop.

    World State → Signal → Risk(+GNN) → RL candidates → Recommendation
    → Decision → Approval → Execution → Outcome → Evaluate recommendation
    → Explanation → Vanessa
    """

    def test_full_v07_loop(self):
        """Run through the complete v0.7 decision intelligence loop."""
        from app.modules.nexus_spine import (
            get_candidate_generator,
            get_explanation_engine,
            get_gnn_engine,
            get_model_registry,
            get_recommendation_evaluator,
            get_vanessa_session_manager,
            get_forecast_metrics_tracker,
        )

        # 1. Model registry — verify deployed models exist
        mr = get_model_registry()
        forecast_model = mr.get_deployed("forecast")
        assert forecast_model is not None
        gnn_model = mr.get_deployed("gnn")
        assert gnn_model is not None

        # 2. GNN engine ready
        gnn = get_gnn_engine()
        assert gnn is not None

        # 3. Bounded RL generates candidates for a risky supplier
        gen = get_candidate_generator()
        candidates = gen.generate_candidates(
            situation={"signal": "supplier capacity drop"},
            risk_score=0.71,
            entity_id="S-142",
            entity_kind="supplier",
            revenue_exposure=4500000,
            current_delay_days=5,
            blast_radius_count=12,
            gnn_features={"critical_node_probability": 0.88, "bottleneck_score": 0.6},
        )
        assert len(candidates) >= 2
        for c in candidates:
            assert c.to_dict()["requires_human_approval"]

        # 4. Rank candidates (simulation step)
        ranked = gen.evaluate_candidates(candidates)
        best = ranked[0]
        assert best["is_optimal"]

        # 5. Create recommendation
        rec_eval = get_recommendation_evaluator()
        rec = rec_eval.create(
            tenant_id="t", workspace_id="w",
            recommended_action=best["action_type"],
            alternative_actions=[{"action": c["action_type"], "nev": c["predicted_nev"]} for c in ranked[1:]],
            predicted_nev=best["predicted_nev"],
            predicted_sla=best["predicted_sla_pct"],
            predicted_cost=best["predicted_cost"],
            confidence=best["confidence"],
        )
        assert rec.recommendation_id

        # 6. Explain the risk with the WHY engine
        explainer = get_explanation_engine()
        exp = explainer.explain_risk(
            entity_id="S-142", entity_name="S-142", entity_kind="supplier",
            severity="CRITICAL", risk_score=0.71, gnn_risk_score=0.88,
            title="Supplier capacity fell 31%",
            description="Labor strike at tier-2",
            root_causes=["Port congestion", "Labor strike"],
            revenue_exposure=4500000, sla_risk_pct=0.82,
            affected_orders=37, affected_skus=["SKU-101", "SKU-102"],
            affected_plants=["P-1", "P-2"], blast_radius_count=12,
            confidence=0.91,
            candidate_actions=[c.to_dict() for c in candidates[:3]],
        )
        assert exp.what and exp.why and exp.impact
        assert len(exp.what_next_actions) > 0

        # 7. Vanessa contextual session
        mgr = get_vanessa_session_manager()
        sid, _ = mgr.get_or_create_session(tenant_id="golden", workspace_id="test", user_id="operator")
        mgr.update_context(sid, selected_entity_id="S-142", selected_entity_name="S-142", selected_entity_kind="supplier")
        resp = mgr.ask(sid, "Why is it risky?")
        assert resp.answer
        assert resp.context["selected_entity_id"] == "S-142"
        # Follow up
        resp2 = mgr.ask(sid, "What happens if we lose it?")
        assert resp2.answer

        # 8. Record outcome and evaluate recommendation
        evald = rec_eval.evaluate(
            rec.recommendation_id,
            actual_nev=best["predicted_nev"] * 0.9,  # Came in 10% below forecast
            actual_sla=0.93,
            actual_cost=best["predicted_cost"] * 1.05,
            outcome="success",
        )
        assert evald.recommendation_accuracy is not None
        assert evald.recommendation_accuracy > 0

        # 9. Performance summary
        perf = rec_eval.performance_summary("t", "w")
        assert perf["evaluated"] >= 1

        # 10. Intelligence health
        health = mr.health_summary()
        assert "Demand forecast" in health
        assert "Supplier risk" in health

        # 11. Forecast metrics
        ft = get_forecast_metrics_tracker()
        fh = ft.overall_health()
        assert "accuracy" in fh

        # THE LOOP IS COMPLETE
        assert True, "v0.7 golden trace completed successfully"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
