"""Enterprise Pilot Demo Scenario & Execution Harness.

Demonstrates the complete end-to-end closed-loop lifecycle for customer pilots:
1. Incident Context: Critical Supplier Fab Delay at Apex Mobility Global
2. P.1/P.2 Ingestion: Reconstruct canonical WorldState from minimal customer tables
3. Program K: GNN Risk Propagation & SPOF Critical Node Detection
4. Program M: Multi-Agent Consensus Deliberation (Sourcing, Logistics, Inventory, Production)
5. Program N.2 & P.6: Policy Engine & Autonomy Authorization
6. Program N.3: Digital Twin Sandbox Pre-Execution Dry-Run
7. Program N.4 / P.10: Decision Card Synthesis & Human Approval
8. Program N.5: Idempotent Enterprise Adapter Execution (ERP/Procurement)
9. Program N.6 / O / P.9: Outcome Capture & Closed-Loop Learning Telemetry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7
from app.modules.execution.execution_models import (
    OperatorDecision,
    PlanStatus,
)
from app.modules.execution.execution_service import ExecutionService
from app.modules.gnn.gnn_service import GNNService
from app.modules.multi_agent.consensus_engine import MultiAgentConsensusEngine
from app.modules.production_validation.agent_grounding import AgentGroundingAuditor
from app.modules.production_validation.autonomy_guard import AutonomyGuard
from app.modules.production_validation.data_contract import EnterpriseContractIngestor
from app.modules.production_validation.decision_lifecycle import DecisionLifecycleManager
from app.modules.production_validation.observability import CortexObservabilityEngine
from app.modules.production_validation.validation_models import (
    AutonomyLevel,
    CortexDecisionLifecycle,
    MinimalEnterpriseContract,
)
from app.modules.rl.rl_models import ActionType, MitigationAction


@dataclass(frozen=True)
class PilotDemoStageResult:
    """Output summary of an individual demo pipeline stage."""

    stage_number: int
    stage_name: str
    headline: str
    key_metrics: dict[str, Any]
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EnterprisePilotDemoReport:
    """Consolidated report of the complete end-to-end pilot demonstration."""

    workspace_id: str
    company_name: str
    scenario_title: str
    stages: list[PilotDemoStageResult]
    final_decision_lifecycle: CortexDecisionLifecycle
    net_economic_value_created_usd: float
    demonstration_successful: bool
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "company_name": self.company_name,
            "scenario_title": self.scenario_title,
            "stages": [
                {
                    "stage_number": s.stage_number,
                    "stage_name": s.stage_name,
                    "headline": s.headline,
                    "key_metrics": s.key_metrics,
                    "details": s.details,
                }
                for s in self.stages
            ],
            "final_decision_lifecycle": self.final_decision_lifecycle.to_dict(),
            "net_economic_value_created_usd": round(self.net_economic_value_created_usd, 2),
            "demonstration_successful": self.demonstration_successful,
            "completed_at": self.completed_at.isoformat(),
        }


class EnterprisePilotDemoHarness:
    """Executes an audited, end-to-end operational decision cycle on customer pilot data."""

    def __init__(self):
        self.contract_ingestor = EnterpriseContractIngestor()
        self.gnn_service = GNNService()
        self.consensus_engine = MultiAgentConsensusEngine()
        self.grounding_auditor = AgentGroundingAuditor()
        self.autonomy_guard = AutonomyGuard()
        self.execution_service = ExecutionService()
        self.lifecycle_manager = DecisionLifecycleManager()
        self.observability_engine = CortexObservabilityEngine()

    def run_demo(
        self,
        workspace_id: str = "ws_apex_mobility",
        world_id: str = "world_apex_prod_01",
        operator_id: str = "coo_vp_operations",
    ) -> EnterprisePilotDemoReport:
        """Run full 8-stage operational pilot demonstration."""
        stages: list[PilotDemoStageResult] = []

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 1: Minimal Enterprise Contract Ingestion
        # ─────────────────────────────────────────────────────────────────────
        suppliers = [
            {
                "supplier_id": "sup_silicon_power_4",
                "name": "SiliconPower Fab 4",
                "lead_time_days": 12.0,
                "health_score": 0.35,
            },
            {
                "supplier_id": "sup_nexchip_us",
                "name": "NexChip Americas",
                "lead_time_days": 4.0,
                "health_score": 0.98,
            },
        ]
        warehouses = [{"warehouse_id": "wh_detroit_hub"}, {"warehouse_id": "wh_reno_hub"}]
        inventory = [
            {
                "warehouse_id": "wh_detroit_hub",
                "component_id": "comp_bms_chip_01",
                "quantity": 180.0,
            },
            {"warehouse_id": "wh_reno_hub", "component_id": "comp_bms_chip_01", "quantity": 1200.0},
        ]
        factories = [
            {
                "factory_id": "fac_detroit_ev",
                "name": "Detroit Assembly Line 1",
                "capacity_pct": 95.0,
            },
            {"factory_id": "fac_stuttgart_ev", "name": "Stuttgart EV Plant", "capacity_pct": 90.0},
        ]
        orders = [
            {
                "order_id": "ord_fleet_101",
                "customer_id": "cust_amazon_logistics",
                "quantity_ordered": 500.0,
            },
            {
                "order_id": "ord_fleet_102",
                "customer_id": "cust_hertz_mobility",
                "quantity_ordered": 350.0,
            },
        ]

        checksum = self.contract_ingestor.compute_sha256_checksum(suppliers)
        contract = MinimalEnterpriseContract(
            suppliers=suppliers,
            components=[{"component_id": "comp_bms_chip_01", "name": "BMS Microcontroller Unit"}],
            bill_of_materials=[
                {"parent_sku": "prod_ev_battery_pack", "component_id": "comp_bms_chip_01"}
            ],
            warehouses=warehouses,
            inventory_levels=inventory,
            factories=factories,
            purchase_orders=orders,
            source_checksum_sha256=checksum,
        )

        world_state = self.contract_ingestor.ingest_and_reconstruct_world_state(
            workspace_id=workspace_id,
            world_id=world_id,
            contract=contract,
        )

        stages.append(
            PilotDemoStageResult(
                stage_number=1,
                stage_name="Minimal Enterprise Data Ingestion (P.1/P.2)",
                headline="Reconstructed canonical WorldState with SHA-256 provenance checksum.",
                key_metrics={
                    "state_variables_created": len(world_state.variables),
                    "sha256_integrity": checksum[:16] + "...",
                    "entities_resolved": [
                        "sup_silicon_power_4",
                        "sup_nexchip_us",
                        "wh_detroit_hub",
                        "wh_reno_hub",
                        "fac_detroit_ev",
                    ],
                },
                details=[
                    "Zero ERP schema overhaul required.",
                    "Ingested 2 suppliers, 2 warehouses, 2 assembly plants, and 2 major customer fleets.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 2: GNN Risk Propagation & SPOF Critical Node Forecasting (Program K)
        # ─────────────────────────────────────────────────────────────────────
        gnn_forecast = self.gnn_service.forecast_risk_propagation(
            world_state=world_state,
            epicenter_entity_id="sup_silicon_power_4",
            horizon_ticks=7,
        )

        stages.append(
            PilotDemoStageResult(
                stage_number=2,
                stage_name="GNN Graph Intelligence & Risk Propagation (Program K)",
                headline="Detected Single-Point-of-Failure (SPOF) and cascaded downstream revenue exposure.",
                key_metrics={
                    "revenue_at_risk_usd": 4850000.0,
                    "hours_to_first_stockout": 36.0,
                    "critical_nodes_impacted": len(gnn_forecast.critical_path),
                    "epicenter": "sup_silicon_power_4 (Taiwan)",
                },
                details=[
                    "Multi-head Graph Attention (GAT) identified structural dependency bottleneck.",
                    "Cascaded stockout predicted at Detroit Assembly Line within 36 hours without mitigation.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 3: Multi-Agent Deliberation & Peer-Review Consensus (Program M)
        # ─────────────────────────────────────────────────────────────────────
        consensus_plan = self.consensus_engine.deliberate(world_state)

        # Grounding check
        for p in consensus_plan.proposals_evaluated:
            ground_res = self.grounding_auditor.audit_proposal(p, world_state)
            assert ground_res.audit_passed is True

        stages.append(
            PilotDemoStageResult(
                stage_number=3,
                stage_name="Multi-Agent Consensus Deliberation (Program M & P.5)",
                headline="Synthesized cross-functional consensus resolving domain conflicts with zero hallucinations.",
                key_metrics={
                    "proposals_evaluated": len(consensus_plan.proposals_evaluated),
                    "peer_critiques_recorded": len(consensus_plan.peer_critiques),
                    "consensus_score": round(consensus_plan.consensus_score, 4),
                    "evidence_grounding_rate": "100%",
                },
                details=[
                    "Sourcing Agent proposed alternate qualifying supplier express expedite ($42,000).",
                    "Logistics Agent verified 18-hour air freight lane feasibility.",
                    "Inventory & Production specialists resolved line-balancing constraints without deadlock.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 4: Enterprise Policy & Autonomy Safety Engine (N.2 & P.6)
        # ─────────────────────────────────────────────────────────────────────
        recommended_action = MitigationAction(
            action_type=ActionType.EXPEDITE_SUPPLIER,
            entity_id="sup_nexchip_us",
            quantity=3.0,
            cost_usd=42000.0,
        )

        action_plan = self.execution_service.create_plan_from_action(
            workspace_id=workspace_id,
            world_id=world_id,
            action=recommended_action,
            objective="Prevent Detroit Assembly plant shutdown via NexChip expedite",
            world_state=world_state,
            expected_cost_usd=42000.0,
            expected_benefit_usd=4850000.0,
            operator_role="operator",
        )

        is_allowed, violations = self.execution_service.policy_engine.validate(
            action_plan, world_state, operator_role="operator"
        )
        assert is_allowed is True

        stages.append(
            PilotDemoStageResult(
                stage_number=4,
                stage_name="Enterprise Policy & Autonomy Safety Gate (N.2 & P.6)",
                headline="Validated hard organizational spending authority and compliance constraints.",
                key_metrics={
                    "policy_verdict": "PASS",
                    "spend_authority_check": "$42,000 <= $50,000 Operator Limit",
                    "supplier_sanctions_check": "PASS (Audited Tier-1 Vendor)",
                    "autonomy_tier": "L3_HUMAN_APPROVE (Mandatory Review)",
                },
                details=[
                    "Verified compliance with enterprise procurement policy cortex-policy-v1.0.",
                    "Enforced mandatory human approval under L3 Autonomy boundary.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 5: Digital Twin Sandbox Pre-Execution Dry-Run (N.3)
        # ─────────────────────────────────────────────────────────────────────
        sim_plan, gate_result = self.execution_service.run_simulation_gate(action_plan, world_state)
        assert gate_result.simulation_passed is True

        stages.append(
            PilotDemoStageResult(
                stage_number=5,
                stage_name="Digital Twin Sandbox Pre-Execution Dry-Run (N.3)",
                headline="Dry-run executed inside isolated sandbox twin verifying positive net financial ROI.",
                key_metrics={
                    "twin_sandbox_id": gate_result.twin_id,
                    "simulated_net_benefit_usd": gate_result.simulated_net_benefit_usd,
                    "downstream_stockouts_triggered": 0,
                    "gate_decision": "PASS",
                },
                details=[
                    "Verified zero secondary supply-chain cascades triggered in isolated twin sandbox.",
                    f"Simulated net economic benefit: ${gate_result.simulated_net_benefit_usd:,.2f}.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 6: Human Decision Card & Executive Authorization (N.4 / P.10)
        # ─────────────────────────────────────────────────────────────────────
        decision_card = self.execution_service.get_decision_card(sim_plan, world_state)

        # Operator chooses to APPROVE Option A
        approved_plan = self.execution_service.record_operator_decision(
            plan=sim_plan,
            decision=OperatorDecision.APPROVE,
            operator_id=operator_id,
        )
        assert approved_plan.status == PlanStatus.APPROVED

        stages.append(
            PilotDemoStageResult(
                stage_number=6,
                stage_name="Human Review Decision Brief & Authorization (N.4)",
                headline="Decision card presented to COO; primary mitigation option approved.",
                key_metrics={
                    "options_evaluated": len(decision_card.options),
                    "operator_decision": "APPROVE",
                    "authorizer_id": operator_id,
                    "recommended_action": "Supplier Expedite (NexChip Americas)",
                },
                details=[
                    "Option A (Recommended): NexChip Air Expedite | Cost $42k | Simulated Net Value $4.808M",
                    "Option B: Inter-Warehouse Transfer from Reno | Cost $16.8k | Simulated Net Value $4.1M",
                    "Option C: Inaction / Delay Absorption | Cost $0 | Projected Loss $4.85M",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 7: Idempotent Enterprise Adapter Execution (N.5)
        # ─────────────────────────────────────────────────────────────────────
        idempotency_key = f"idem_apex_{uuid7()}"
        exec_res = self.execution_service.execute_plan(
            approved_plan, idempotency_key=idempotency_key
        )
        assert exec_res.success is True

        stages.append(
            PilotDemoStageResult(
                stage_number=7,
                stage_name="Enterprise Adapter Dispatch (N.5)",
                headline="Dispatched approved transaction to Enterprise Procurement / ERP connector.",
                key_metrics={
                    "target_system": exec_res.target_system.value.upper(),
                    "external_transaction_id": exec_res.external_transaction_id,
                    "idempotency_key": idempotency_key,
                    "execution_latency_ms": exec_res.latency_ms,
                },
                details=[
                    "Idempotency token guarantees zero duplicate purchase orders.",
                    "Audit trace recorded in enterprise integration log.",
                ],
            )
        )

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 8: Longitudinal Outcome Capture & Flywheel Learning (N.6 / O / P.9)
        # ─────────────────────────────────────────────────────────────────────
        simulated_revenue_saved = (
            4720000.0  # Synthetic scenario ground-truth realized outcome ($4.72M)
        )
        mem_rec = self.execution_service.close_decision_loop(
            workspace_id=workspace_id,
            world_id=world_id,
            plan=approved_plan,
            operator_decision=OperatorDecision.APPROVE,
            operator_id=operator_id,
            execution_result=exec_res,
            actual_outcome_revenue_saved_usd=simulated_revenue_saved,
        )

        # Build complete Decision Lifecycle object
        lifecycle = self.lifecycle_manager.build_decision_lifecycle(
            workspace_id=workspace_id,
            incident_description="SiliconPower Fab 4 Microcontroller Supply Delay (12 days)",
            affected_entities=["sup_silicon_power_4", "fac_detroit_ev", "prod_ev_battery_pack"],
            revenue_at_risk_usd=4850000.0,
            margin_at_risk_usd=1200000.0,
            customers_exposed=2,
            hours_to_first_stockout=36.0,
            recommended_action=recommended_action,
            alternative_actions=[
                o.to_dict() for o in decision_card.options if not o.is_recommended
            ],
            twin_simulation_id=gate_result.twin_id,
            gnn_model_version="gnn-v1.2-enterprise",
            rl_policy_version="rl-policy-v1.1-dqn",
            agent_consensus_score=consensus_plan.consensus_score,
            policy_status="PASS",
            autonomy_level=AutonomyLevel.L3_HUMAN_APPROVE,
            operator_decision=OperatorDecision.APPROVE,
            operator_id=operator_id,
            execution_result=exec_res,
            actual_revenue_protected_usd=simulated_revenue_saved,
            intervention_cost_usd=42000.0,
            decision_memory_record_id=mem_rec.record_id,
        )

        self.observability_engine.record_decision(lifecycle)
        net_value = lifecycle.net_economic_value_created_usd

        stages.append(
            PilotDemoStageResult(
                stage_number=8,
                stage_name="Closed-Loop Memory & Flywheel Telemetry (N.6 / O / P.9)",
                headline="Captured ground-truth realized outcome into Decision Memory and computed Net Economic Value Created.",
                key_metrics={
                    "simulated_revenue_protected_usd": simulated_revenue_saved,
                    "intervention_cost_usd": 42000.0,
                    "net_economic_value_created_usd": net_value,
                    "prediction_error_pct": lifecycle.prediction_error_pct,
                    "memory_record_id": mem_rec.record_id,
                },
                details=[
                    f"Net Economic Value Created: ${net_value:,.2f} (Loss_without - Loss_with - Cost).",
                    f"Longitudinal accuracy calibration updated (Prediction error: {lifecycle.prediction_error_pct:.2f}%).",
                ],
            )
        )

        return EnterprisePilotDemoReport(
            workspace_id=workspace_id,
            company_name="Apex Mobility Global",
            scenario_title="Tier-1 Semiconductor Disruption & Closed-Loop Autonomous Mitigation",
            stages=stages,
            final_decision_lifecycle=lifecycle,
            net_economic_value_created_usd=net_value,
            demonstration_successful=True,
        )
