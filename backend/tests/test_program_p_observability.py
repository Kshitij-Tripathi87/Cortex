"""Test Observability Engine — Program P.9.

Verifies:
- Operational dashboard generation tracking "Is Cortex Becoming More Correct?"
- Longitudinal prediction error trend calculation
- Cumulative net economic value created aggregation
"""

from __future__ import annotations

from app.modules.execution.execution_models import OperatorDecision
from app.modules.production_validation.decision_lifecycle import DecisionLifecycleManager
from app.modules.production_validation.observability import CortexObservabilityEngine
from app.modules.production_validation.validation_models import AutonomyLevel
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestObservabilityEngine:
    def test_observability_dashboard_error_reduction_trend(self) -> None:
        """Dashboard proves prediction error decreases and cumulative value grows over time."""
        mgr = DecisionLifecycleManager()
        engine = CortexObservabilityEngine()

        action = MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_1", cost_usd=2000.0)

        # Early cycle: 15% error
        d1 = mgr.build_decision_lifecycle(
            workspace_id="ws_obs",
            incident_description="Incident 1",
            affected_entities=["sup_1"],
            revenue_at_risk_usd=50000.0,
            margin_at_risk_usd=10000.0,
            customers_exposed=2,
            hours_to_first_stockout=24.0,
            recommended_action=action,
            alternative_actions=[],
            twin_simulation_id="twin_1",
            gnn_model_version="v1.0",
            rl_policy_version="v1.0",
            agent_consensus_score=0.8,
            policy_status="PASS",
            autonomy_level=AutonomyLevel.L3_HUMAN_APPROVE,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="op_1",
            execution_result=None,
            actual_revenue_protected_usd=42500.0,  # 15% error
            intervention_cost_usd=2000.0,
            decision_memory_record_id="mem_1",
        )

        # Later cycle: 5% error (model improved)
        d2 = mgr.build_decision_lifecycle(
            workspace_id="ws_obs",
            incident_description="Incident 2",
            affected_entities=["sup_1"],
            revenue_at_risk_usd=50000.0,
            margin_at_risk_usd=10000.0,
            customers_exposed=2,
            hours_to_first_stockout=24.0,
            recommended_action=action,
            alternative_actions=[],
            twin_simulation_id="twin_2",
            gnn_model_version="v1.1",
            rl_policy_version="v1.1",
            agent_consensus_score=0.9,
            policy_status="PASS",
            autonomy_level=AutonomyLevel.L3_HUMAN_APPROVE,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="op_1",
            execution_result=None,
            actual_revenue_protected_usd=47500.0,  # 5% error
            intervention_cost_usd=2000.0,
            decision_memory_record_id="mem_2",
        )

        engine.record_decision(d1)
        engine.record_decision(d2)

        dash = engine.generate_dashboard("ws_obs")

        assert dash.workspace_id == "ws_obs"
        assert dash.total_decisions_tracked == 2
        assert dash.cumulative_net_economic_value_created_usd == (40500.0 + 45500.0)
        assert dash.error_reduction_trend_pct > 0.0  # Positive error reduction trend
        assert "actively learning" in dash.system_verdict
