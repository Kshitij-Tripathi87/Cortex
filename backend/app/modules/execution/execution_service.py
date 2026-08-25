"""Execution Service Layer — Orchestrates Closed-Loop Supervised Operations.

Program N (Supervised Execution & Closed-Loop Operations):
Provides the end-to-end orchestration pipeline:
1. ActionPlan formulation from Multi-Agent consensus
2. Policy & safety engine validation
3. Digital Twin sandbox dry-run gate
4. Human operator briefing & decision card processing
5. External enterprise adapter dispatch (ERP / WMS / TMS / Procurement)
6. Closed-loop decision memory capture
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.execution.adapters.base_adapter import EnterpriseAdapter
from app.modules.execution.adapters.erp_adapter import ERPAdapter
from app.modules.execution.adapters.procurement_adapter import ProcurementAdapter
from app.modules.execution.adapters.tms_adapter import TMSAdapter
from app.modules.execution.adapters.wms_adapter import WMSAdapter
from app.modules.execution.approval_service import ApprovalService
from app.modules.execution.decision_memory import DecisionMemoryStore
from app.modules.execution.execution_models import (
    ActionPlan,
    DecisionCard,
    DecisionMemoryRecord,
    ExecutionResult,
    ExecutionSystem,
    OperatorDecision,
    PlanStatus,
    SimulationGateResult,
)
from app.modules.execution.policy_engine import PolicyEngine
from app.modules.execution.simulation_gate import SimulationGate
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.world_models import WorldState


class ExecutionService:
    """Unified service orchestrating the supervised execution lifecycle."""

    def __init__(
        self,
        policy_engine: PolicyEngine | None = None,
        simulation_gate: SimulationGate | None = None,
        approval_service: ApprovalService | None = None,
        memory_store: DecisionMemoryStore | None = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.simulation_gate = simulation_gate or SimulationGate()
        self.approval_service = approval_service or ApprovalService()
        self.memory_store = memory_store or DecisionMemoryStore()

        # Connector adapter registry
        self._adapters: dict[ExecutionSystem, EnterpriseAdapter] = {
            ExecutionSystem.ERP: ERPAdapter(),
            ExecutionSystem.WMS: WMSAdapter(),
            ExecutionSystem.TMS: TMSAdapter(),
            ExecutionSystem.PROCUREMENT: ProcurementAdapter(),
        }

    def create_plan_from_action(
        self,
        workspace_id: str,
        world_id: str,
        action: MitigationAction,
        objective: str,
        world_state: WorldState,
        expected_cost_usd: float | None = None,
        expected_benefit_usd: float | None = None,
        operator_role: str = "operator",
    ) -> ActionPlan:
        """Construct an immutable ActionPlan and evaluate it against policy rules."""
        plan_id = f"plan_{uuid7()}"

        cost = expected_cost_usd if expected_cost_usd is not None else action.cost_usd
        benefit = expected_benefit_usd if expected_benefit_usd is not None else 35000.0

        # Infer target system from action type
        target_sys = ExecutionSystem.ERP
        if action.action_type == ActionType.TRANSFER_INVENTORY:
            target_sys = ExecutionSystem.WMS
        elif action.action_type == ActionType.REROUTE_SHIPMENT:
            target_sys = ExecutionSystem.TMS
        elif action.action_type == ActionType.EXPEDITE_SUPPLIER:
            target_sys = ExecutionSystem.PROCUREMENT

        initial_plan = ActionPlan(
            plan_id=plan_id,
            workspace_id=workspace_id,
            world_id=world_id,
            objective=objective,
            action=action,
            target_system=target_sys,
            expected_cost_usd=cost,
            expected_benefit_usd=benefit,
            expected_risk_score=0.15,
            affected_entities=[action.entity_id]
            + ([action.target_entity_id] if action.target_entity_id else []),
            prerequisites=["world_state_synchronized"],
            policy_version="cortex-policy-v1.0",
            simulation_id=None,
            status=PlanStatus.DRAFT,
        )

        # Validate against policy engine
        is_allowed, violations = self.policy_engine.validate(
            initial_plan, world_state, operator_role
        )

        status = PlanStatus.SIMULATION_PENDING if is_allowed else PlanStatus.POLICY_REJECTED

        return ActionPlan(
            plan_id=initial_plan.plan_id,
            workspace_id=initial_plan.workspace_id,
            world_id=initial_plan.world_id,
            objective=initial_plan.objective,
            action=initial_plan.action,
            target_system=initial_plan.target_system,
            expected_cost_usd=initial_plan.expected_cost_usd,
            expected_benefit_usd=initial_plan.expected_benefit_usd,
            expected_risk_score=initial_plan.expected_risk_score,
            affected_entities=initial_plan.affected_entities,
            prerequisites=initial_plan.prerequisites,
            policy_version=initial_plan.policy_version,
            simulation_id=None,
            status=status,
            violations=violations,
        )

    def run_simulation_gate(
        self,
        plan: ActionPlan,
        world_state: WorldState,
    ) -> tuple[ActionPlan, SimulationGateResult]:
        """Run pre-execution dry run and update plan status."""
        gate_res = self.simulation_gate.verify_plan(plan, world_state)

        new_status = (
            PlanStatus.PENDING_APPROVAL
            if gate_res.simulation_passed
            else PlanStatus.SIMULATION_FAILED
        )

        updated_plan = ActionPlan(
            plan_id=plan.plan_id,
            workspace_id=plan.workspace_id,
            world_id=plan.world_id,
            objective=plan.objective,
            action=plan.action,
            target_system=plan.target_system,
            expected_cost_usd=plan.expected_cost_usd,
            expected_benefit_usd=plan.expected_benefit_usd,
            expected_risk_score=plan.expected_risk_score,
            affected_entities=plan.affected_entities,
            prerequisites=plan.prerequisites,
            policy_version=plan.policy_version,
            simulation_id=gate_res.twin_id,
            status=new_status,
            violations=plan.violations,
        )

        return updated_plan, gate_res

    def get_decision_card(
        self,
        plan: ActionPlan,
        world_state: WorldState,
    ) -> DecisionCard:
        """Generate human-in-the-loop decision card."""
        return self.approval_service.generate_decision_card(plan, world_state)

    def record_operator_decision(
        self,
        plan: ActionPlan,
        decision: OperatorDecision,
        operator_id: str,
        modifications: dict[str, Any] | None = None,
    ) -> ActionPlan:
        """Record human review action on the plan."""
        return self.approval_service.process_decision(plan, decision, operator_id, modifications)

    def execute_plan(
        self,
        plan: ActionPlan,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Dispatch approved plan to target enterprise adapter."""
        if plan.status != PlanStatus.APPROVED:
            return ExecutionResult(
                execution_id=f"exec_err_{uuid7()}",
                plan_id=plan.plan_id,
                target_system=plan.target_system,
                idempotency_key=idempotency_key,
                success=False,
                external_transaction_id=None,
                latency_ms=0.0,
                error_message=f"Plan status '{plan.status.value}' is not APPROVED.",
            )

        adapter = self._adapters.get(plan.target_system)
        if not adapter:
            adapter = self._adapters[ExecutionSystem.ERP]

        return adapter.execute(plan, idempotency_key)

    def close_decision_loop(
        self,
        workspace_id: str,
        world_id: str,
        plan: ActionPlan,
        operator_decision: OperatorDecision,
        operator_id: str,
        execution_result: ExecutionResult | None = None,
        actual_outcome_revenue_saved_usd: float | None = None,
    ) -> DecisionMemoryRecord:
        """Capture executed action and outcome in immutable Decision Memory."""
        return self.memory_store.capture_decision_outcome(
            workspace_id=workspace_id,
            world_id=world_id,
            plan=plan,
            operator_decision=operator_decision,
            operator_id=operator_id,
            execution_result=execution_result,
            actual_outcome_revenue_saved_usd=actual_outcome_revenue_saved_usd,
        )
