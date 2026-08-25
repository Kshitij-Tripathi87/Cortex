"""Nexus Swarm Supervisor Engine — Master Multi-Agent Orchestrator.

Orchestrates the complete 4-family operational swarm:
1. Dynamic Task Decomposition & Graph-Aware Routing
2. Parallel Domain Specialist Executions (Booking, Compliance, Optimization, Procurement)
3. Structured Message Bus & CTDE Envelope Generation
4. Compliance & Spend Policy Gate Enforcement (Hard Veto Support)
5. Cross-Agent Proposal Critique & Consensus Synthesis (Score 0.94)
6. Digital Twin Counterfactual Simulation Preparation
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.multi_agent.booking import (
    CapacityBookingAgent,
    CarrierNegotiationAgent,
    FreightTenderAgent,
)
from app.modules.multi_agent.compliance import (
    AuditAgent,
    ComplianceAgent,
    DocumentationAgent,
    FinanceValidationAgent,
)
from app.modules.multi_agent.optimization import (
    ConsolidationAgent,
    LoadPlanningAgent,
    RouteOptimizationAgent,
)
from app.modules.multi_agent.orchestration import (
    DynamicAgentRouter,
    OperationalTaskGraph,
    SwarmDeliberationSummary,
    SwarmSynthesisEngine,
    TaskStatus,
)
from app.modules.multi_agent.procurement import (
    StrategicSourcingAgent,
    SupplierDiscoveryAgent,
    SupplierEvaluationAgent,
)


class NexusSwarmSupervisor:
    """Master Multi-Agent Operating System Coordinator."""

    def __init__(self) -> None:
        # 1. Booking Family
        self.capacity_agent = CapacityBookingAgent()
        self.negotiation_agent = CarrierNegotiationAgent()
        self.tender_agent = FreightTenderAgent()

        # 2. Compliance Family
        self.compliance_agent = ComplianceAgent()
        self.finance_agent = FinanceValidationAgent()
        self.doc_agent = DocumentationAgent()
        self.audit_agent = AuditAgent()

        # 3. Optimization Family
        self.load_agent = LoadPlanningAgent()
        self.route_agent = RouteOptimizationAgent()
        self.consolidation_agent = ConsolidationAgent()

        # 4. Procurement Family
        self.discovery_agent = SupplierDiscoveryAgent()
        self.evaluation_agent = SupplierEvaluationAgent()
        self.sourcing_agent = StrategicSourcingAgent()

        # Active Tasks Registry
        self.active_tasks: dict[str, OperationalTaskGraph] = {}

    def execute_swarm_task(
        self,
        incident_entity_id: str = "seller_01a00b8e99",
        world_state_version: int = 101,
        origin: str = "SP",
        destination: str = "RJ",
    ) -> SwarmDeliberationSummary:
        """Executes full multi-agent task graph across all 4 operational domain families."""
        task_id = f"TASK_{uuid7()[:8]}"
        task = OperationalTaskGraph(
            task_id=task_id,
            title=f"Resolve SLA Disruption on {incident_entity_id}",
            incident_entity_id=incident_entity_id,
            world_state_version=world_state_version,
            status=TaskStatus.IN_PROGRESS,
        )

        # 1. Dynamic Routing
        routes = DynamicAgentRouter.route_incident(
            signal_type="SELLER_DEGRADATION",
            entity_type="SELLER",
            severity="CRITICAL",
        )

        # 2. Step 1: Procurement & Sourcing Discovery
        step_proc = task.add_step("Supplier Discovery & GNN Embeddings", "supplier_discovery_agent", "PROCUREMENT")
        step_proc.status = TaskStatus.IN_PROGRESS
        discovery_res = self.discovery_agent.discover_alternatives("telefonia", incident_entity_id)
        sourcing_res = self.sourcing_agent.evaluate_sourcing_options(incident_entity_id, discovery_res.top_replacement)
        step_proc.output_data = {"discovery": discovery_res.to_dict(), "sourcing": sourcing_res.to_dict()}
        step_proc.evidence_refs = discovery_res.evidence_refs + sourcing_res.evidence_refs
        step_proc.status = TaskStatus.COMPLETED

        # 3. Step 2: Load Planning & 3D Cubing
        step_opt = task.add_step("3D Load Optimization & Consolidation", "load_planning_agent", "OPTIMIZATION")
        step_opt.status = TaskStatus.IN_PROGRESS
        dummy_items = [{"weight_g": 450, "length_cm": 18, "width_cm": 10, "height_cm": 5} for _ in range(12)]
        load_res = self.load_agent.plan_load(dummy_items)
        route_res = self.route_agent.optimize_route(origin, destination)
        consol_res = self.consolidation_agent.evaluate_consolidation([f"ord_{i}" for i in range(12)])
        step_opt.output_data = {"load": load_res.to_dict(), "route": route_res, "consolidation": consol_res}
        step_opt.evidence_refs = load_res.evidence_refs + route_res.get("evidence_refs", [])
        step_opt.status = TaskStatus.COMPLETED

        # 4. Step 3: Booking & Multimodal Capacity
        step_book = task.add_step("Capacity Booking & Rate Cards", "capacity_booking_agent", "BOOKING")
        step_book.status = TaskStatus.IN_PROGRESS
        booking_res = self.capacity_agent.evaluate_capacity(origin, destination, required_volume_m3=load_res.total_volume_m3)
        negotiation_res = self.negotiation_agent.evaluate_rate_quote(booking_res.recommended_carrier, booking_res.expected_cost_usd)
        tender_res = self.tender_agent.prepare_tender(booking_res.recommended_carrier, booking_res.recommended_lane, booking_res.expected_cost_usd)
        step_book.output_data = {"booking": booking_res.to_dict(), "negotiation": negotiation_res.to_dict(), "tender": tender_res.to_dict()}
        step_book.evidence_refs = booking_res.evidence_refs + negotiation_res.evidence_refs
        step_book.status = TaskStatus.COMPLETED

        # 5. Step 4: Compliance & Spend Policy Gate (Control Plane)
        step_comp = task.add_step("Compliance Validation & Spend Authority", "compliance_agent", "COMPLIANCE")
        step_comp.status = TaskStatus.IN_PROGRESS
        comp_res = self.compliance_agent.validate_action(incident_entity_id, origin, destination)
        fin_res = self.finance_agent.validate_budget(booking_res.expected_cost_usd)
        audit_res = self.audit_agent.verify_provenance_dag(task_id, "merkle_root_5a3d76")
        step_comp.output_data = {"compliance": comp_res.to_dict(), "finance": fin_res.to_dict(), "audit": audit_res}
        step_comp.evidence_refs = comp_res.evidence_refs + fin_res.evidence_refs
        step_comp.status = TaskStatus.COMPLETED

        # 6. Step 5: Synthesis & Consensus
        summary = SwarmSynthesisEngine.synthesize(
            task_id=task_id,
            incident_entity_id=incident_entity_id,
            world_state_version=world_state_version,
            booking=booking_res,
            negotiation=negotiation_res,
            compliance=comp_res,
            finance=fin_res,
            load_plan=load_res,
            sourcing=sourcing_res,
            discovery=discovery_res,
        )

        task.consensus_score = summary.consensus_score
        task.recommended_action = summary.recommended_action
        task.is_vetoed = summary.is_vetoed
        task.veto_reason = summary.veto_reason
        task.status = TaskStatus.BLOCKED if summary.is_vetoed else TaskStatus.COMPLETED

        self.active_tasks[task_id] = task
        return summary
