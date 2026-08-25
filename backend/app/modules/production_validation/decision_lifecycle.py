"""Decision Lifecycle Manager & Economic Value Engine — Program P.10.

Synthesizes the complete Cortex Decision Lifecycle Object:
Event -> Impact -> Options A/B/C -> Simulation -> Intelligence -> Policy -> Approval -> Execution -> Outcome -> Memory

Implements the primary commercial metric:
Net Economic Value Created = Loss_without - Loss_with - Cost_intervention
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.execution.execution_models import (
    ExecutionResult,
    OperatorDecision,
)
from app.modules.production_validation.validation_models import (
    AutonomyLevel,
    CortexDecisionLifecycle,
)
from app.modules.rl.rl_models import MitigationAction


class DecisionLifecycleManager:
    """Orchestrates the unified end-to-end decision lifecycle and value calculation."""

    def build_decision_lifecycle(
        self,
        workspace_id: str,
        incident_description: str,
        affected_entities: list[str],
        revenue_at_risk_usd: float,
        margin_at_risk_usd: float,
        customers_exposed: int,
        hours_to_first_stockout: float,
        recommended_action: MitigationAction,
        alternative_actions: list[dict[str, Any]],
        twin_simulation_id: str,
        gnn_model_version: str,
        rl_policy_version: str,
        agent_consensus_score: float,
        policy_status: str,
        autonomy_level: AutonomyLevel,
        operator_decision: OperatorDecision,
        operator_id: str,
        execution_result: ExecutionResult | None,
        actual_revenue_protected_usd: float,
        intervention_cost_usd: float,
        decision_memory_record_id: str,
    ) -> CortexDecisionLifecycle:
        """Synthesize the complete decision lifecycle record."""
        dec_id = f"cortex_dec_{uuid7()}"

        # Commercial formula:
        # Net Economic Value Created = Protected Revenue - Intervention Cost
        net_value = max(0.0, actual_revenue_protected_usd - intervention_cost_usd)

        # Prediction error %
        predicted = revenue_at_risk_usd
        error_pct = (abs(actual_revenue_protected_usd - predicted) / max(1.0, predicted)) * 100.0

        return CortexDecisionLifecycle(
            decision_id=dec_id,
            workspace_id=workspace_id,
            incident_description=incident_description,
            affected_entities=affected_entities,
            revenue_at_risk_usd=revenue_at_risk_usd,
            margin_at_risk_usd=margin_at_risk_usd,
            customers_exposed=customers_exposed,
            hours_to_first_stockout=hours_to_first_stockout,
            recommended_action=recommended_action,
            alternative_actions=alternative_actions,
            twin_simulation_id=twin_simulation_id,
            gnn_model_version=gnn_model_version,
            rl_policy_version=rl_policy_version,
            agent_consensus_score=agent_consensus_score,
            policy_status=policy_status,
            autonomy_level=autonomy_level,
            operator_decision=operator_decision,
            operator_id=operator_id,
            execution_result=execution_result,
            actual_revenue_protected_usd=actual_revenue_protected_usd,
            intervention_cost_usd=intervention_cost_usd,
            net_economic_value_created_usd=net_value,
            prediction_error_pct=error_pct,
            decision_memory_record_id=decision_memory_record_id,
        )
