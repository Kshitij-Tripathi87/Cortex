"""Test Enterprise Execution Adapters — Program N.5.

Verifies:
- ERP, WMS, TMS, and Procurement adapter execution
- Idempotency key tracking and audit logging
- Rollback / compensation transaction support
"""

from __future__ import annotations

from app.modules.execution.adapters.erp_adapter import ERPAdapter
from app.modules.execution.adapters.procurement_adapter import ProcurementAdapter
from app.modules.execution.adapters.tms_adapter import TMSAdapter
from app.modules.execution.adapters.wms_adapter import WMSAdapter
from app.modules.execution.execution_models import ActionPlan, ExecutionSystem, PlanStatus
from app.modules.rl.rl_models import ActionType, MitigationAction


class TestExecutionAdapters:
    def test_all_enterprise_adapters_execution(self) -> None:
        """Each specialized enterprise adapter executes with idempotency and audit logs."""
        plan_erp = ActionPlan(
            plan_id="plan_erp",
            workspace_id="ws_adp",
            world_id="world_adp",
            objective="Adjust production",
            action=MitigationAction(ActionType.ADJUST_PRODUCTION, "fac_01"),
            target_system=ExecutionSystem.ERP,
            expected_cost_usd=2000.0,
            expected_benefit_usd=15000.0,
            expected_risk_score=0.1,
            affected_entities=["fac_01"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        plan_wms = ActionPlan(
            plan_id="plan_wms",
            workspace_id="ws_adp",
            world_id="world_adp",
            objective="Transfer stock",
            action=MitigationAction(
                ActionType.TRANSFER_INVENTORY, "wh_1", target_entity_id="wh_2", quantity=100.0
            ),
            target_system=ExecutionSystem.WMS,
            expected_cost_usd=800.0,
            expected_benefit_usd=20000.0,
            expected_risk_score=0.1,
            affected_entities=["wh_1", "wh_2"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        plan_tms = ActionPlan(
            plan_id="plan_tms",
            workspace_id="ws_adp",
            world_id="world_adp",
            objective="Reroute lane",
            action=MitigationAction(ActionType.REROUTE_SHIPMENT, "lane_1"),
            target_system=ExecutionSystem.TMS,
            expected_cost_usd=3000.0,
            expected_benefit_usd=25000.0,
            expected_risk_score=0.1,
            affected_entities=["lane_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        plan_proc = ActionPlan(
            plan_id="plan_proc",
            workspace_id="ws_adp",
            world_id="world_adp",
            objective="Rush purchase order",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_01", quantity=3.0),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=4500.0,
            expected_benefit_usd=30000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_01"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.APPROVED,
        )

        adapters = [
            (ERPAdapter(), plan_erp, ExecutionSystem.ERP),
            (WMSAdapter(), plan_wms, ExecutionSystem.WMS),
            (TMSAdapter(), plan_tms, ExecutionSystem.TMS),
            (ProcurementAdapter(), plan_proc, ExecutionSystem.PROCUREMENT),
        ]

        for adapter, plan, expected_system in adapters:
            res = adapter.execute(plan, idempotency_key=f"idem_{plan.plan_id}")
            assert res.success is True
            assert res.target_system == expected_system
            assert res.external_transaction_id is not None
            assert res.latency_ms > 0.0
            assert "idempotency_key" in res.audit_trace

            rollback_ok = adapter.rollback(res.execution_id, res.external_transaction_id)
            assert rollback_ok is True
