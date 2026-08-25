"""Test Decision Lifecycle & Net Economic Value Engine — Program P.10.

Verifies:
- Complete synthesis of the unified CortexDecisionLifecycle object
- Net economic value created calculation: (Protected Revenue - Intervention Cost)
"""

from __future__ import annotations

from app.modules.execution.execution_models import (
    ExecutionResult,
    ExecutionSystem,
    OperatorDecision,
)
from app.modules.production_validation.decision_lifecycle import DecisionLifecycleManager
from app.modules.production_validation.validation_models import AutonomyLevel
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestDecisionLifecycleEngine:
    def test_synthesize_cortex_decision_lifecycle(self) -> None:
        """Constructs unified decision lifecycle record and calculates net value created."""
        mgr = DecisionLifecycleManager()

        exec_res = ExecutionResult(
            execution_id="exec_99",
            plan_id="p_99",
            target_system=ExecutionSystem.PROCUREMENT,
            idempotency_key="idem_99",
            success=True,
            external_transaction_id="SAP_PO_483921",
            latency_ms=42.0,
        )

        rec_action = MitigationAction(
            action_type=ActionType.EXPEDITE_SUPPLIER,
            entity_id="sup_104",
            quantity=3.0,
            cost_usd=38000.0,
        )

        lifecycle = mgr.build_decision_lifecycle(
            workspace_id="ws_life",
            incident_description="Supplier S-104 delayed 9 days",
            affected_entities=["sup_104", "fac_3", "prod_ev_battery"],
            revenue_at_risk_usd=4700000.0,
            margin_at_risk_usd=1100000.0,
            customers_exposed=17,
            hours_to_first_stockout=42.0,
            recommended_action=rec_action,
            alternative_actions=[
                {
                    "name": "Transfer Inventory",
                    "cost_usd": 21000.0,
                    "revenue_protected_usd": 3500000.0,
                },
                {"name": "Do Nothing", "cost_usd": 0.0, "revenue_protected_usd": 0.0},
            ],
            twin_simulation_id="twin_sim_8f31",
            gnn_model_version="gnn-v1.2",
            rl_policy_version="rl-policy-v1.1",
            agent_consensus_score=0.84,
            policy_status="PASS",
            autonomy_level=AutonomyLevel.L3_HUMAN_APPROVE,
            operator_decision=OperatorDecision.APPROVE,
            operator_id="coo_executive",
            execution_result=exec_res,
            actual_revenue_protected_usd=3900000.0,
            intervention_cost_usd=38000.0,
            decision_memory_record_id="mem_rec_483921",
        )

        assert lifecycle.decision_id.startswith("cortex_dec_")
        assert lifecycle.net_economic_value_created_usd == 3862000.0  # $3.9M - $38k
        assert lifecycle.prediction_error_pct > 0.0
        assert lifecycle.policy_status == "PASS"
        assert lifecycle.autonomy_level == AutonomyLevel.L3_HUMAN_APPROVE
        assert lifecycle.execution_result.external_transaction_id == "SAP_PO_483921"
