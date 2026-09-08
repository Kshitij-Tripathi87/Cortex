"""Agent Capability Manifests & Permissions Specification.

Defines strict operational boundaries:
- Read permissions
- Propose permissions
- Simulate permissions
- Execute permissions (Strictly False for all analytical/specialist agents; only ExecutionService has True)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentCapabilityManifest:
    agent_id: str
    agent_name: str
    domain_group: str  # "BOOKING" | "COMPLIANCE" | "OPTIMIZATION" | "PROCUREMENT" | "SUPERVISOR"
    version: str
    read_scopes: list[str]
    propose_scopes: list[str]
    simulate_scopes: list[str]
    can_execute: bool = False
    can_block_execution: bool = False
    allowed_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "domain_group": self.domain_group,
            "version": self.version,
            "read_scopes": self.read_scopes,
            "propose_scopes": self.propose_scopes,
            "simulate_scopes": self.simulate_scopes,
            "can_execute": self.can_execute,
            "can_block_execution": self.can_block_execution,
            "allowed_tools": self.allowed_tools,
        }


# Canonical Capability Manifests
CAPABILITY_MANIFESTS: dict[str, AgentCapabilityManifest] = {
    # Group A: Booking & Negotiation
    "capacity_booking_agent": AgentCapabilityManifest(
        agent_id="capacity_booking_agent",
        agent_name="Capacity Booking Agent",
        domain_group="BOOKING",
        version="v4.2",
        read_scopes=[
            "routes",
            "shipment_volume",
            "carrier_schedules",
            "rate_cards",
            "capacity",
            "sla_requirements",
            "signals",
        ],
        propose_scopes=["booking_option", "lane_reservation"],
        simulate_scopes=["booking_transit_cost"],
        can_execute=False,
        allowed_tools=["search_capacity", "get_carrier_rates", "get_lane_schedule", "check_cutoff"],
    ),
    "carrier_negotiation_agent": AgentCapabilityManifest(
        agent_id="carrier_negotiation_agent",
        agent_name="Carrier Negotiation Agent",
        domain_group="BOOKING",
        version="v4.0",
        read_scopes=["carrier_bids", "historical_rates", "rate_cards", "spend_policies"],
        propose_scopes=["negotiation_range", "pricing_proposal"],
        simulate_scopes=["rate_variance_impact"],
        can_execute=False,
        allowed_tools=[
            "get_historical_rate_variance",
            "calculate_target_pricing",
            "draft_negotiation_proposal",
        ],
    ),
    "freight_tender_agent": AgentCapabilityManifest(
        agent_id="freight_tender_agent",
        agent_name="Freight Tender Agent",
        domain_group="BOOKING",
        version="v4.1",
        read_scopes=["preferred_bookings", "lanes", "equipment", "carrier_ratings"],
        propose_scopes=["tender_document", "booking_instruction"],
        simulate_scopes=["tender_acceptance_rate"],
        can_execute=False,
        allowed_tools=["create_tender", "validate_lane_equipment", "verify_carrier_authorization"],
    ),
    "booking_exception_agent": AgentCapabilityManifest(
        agent_id="booking_exception_agent",
        agent_name="Booking Exception Agent",
        domain_group="BOOKING",
        version="v4.0",
        read_scopes=["rejections", "missed_cutoffs", "route_closures", "live_telemetry"],
        propose_scopes=["re_route_reprice", "exception_recovery"],
        simulate_scopes=["recovery_delay_mitigation"],
        can_execute=False,
        allowed_tools=["search_alternate_carrier", "reprice_lane", "trigger_reroute_simulation"],
    ),
    # Group B: Back-Office & Compliance (Control Plane)
    "documentation_agent": AgentCapabilityManifest(
        agent_id="documentation_agent",
        agent_name="Documentation Agent",
        domain_group="COMPLIANCE",
        version="v4.0",
        read_scopes=["commercial_invoices", "shipping_docs", "packing_lists", "purchase_orders"],
        propose_scopes=["documentation_checklist", "doc_validation_verdict"],
        simulate_scopes=[],
        can_execute=False,
        can_block_execution=False,
        allowed_tools=[
            "verify_commercial_invoice",
            "check_packing_list",
            "validate_customs_declarations",
        ],
    ),
    "compliance_agent": AgentCapabilityManifest(
        agent_id="compliance_agent",
        agent_name="Compliance & Regulatory Agent",
        domain_group="COMPLIANCE",
        version="v5.0",
        read_scopes=[
            "supplier_registry",
            "blacklist",
            "certifications",
            "trade_rules",
            "route_sanctions",
        ],
        propose_scopes=["compliance_verdict", "execution_block_notice"],
        simulate_scopes=[],
        can_execute=False,
        can_block_execution=True,  # HARD VETO AUTHORITY
        allowed_tools=[
            "check_supplier_blacklist",
            "verify_trade_compliance",
            "validate_hazmat_certifications",
        ],
    ),
    "finance_validation_agent": AgentCapabilityManifest(
        agent_id="finance_validation_agent",
        agent_name="Finance Validation Agent",
        domain_group="COMPLIANCE",
        version="v4.1",
        read_scopes=["budgets", "spend_authorities", "payment_terms", "cost_variance"],
        propose_scopes=["financial_approval_verdict", "budget_exception"],
        simulate_scopes=["cash_flow_impact"],
        can_execute=False,
        can_block_execution=True,
        allowed_tools=["check_spend_budget", "validate_payment_terms", "verify_roi_threshold"],
    ),
    "audit_agent": AgentCapabilityManifest(
        agent_id="audit_agent",
        agent_name="Audit & Provenance Agent",
        domain_group="COMPLIANCE",
        version="v4.2",
        read_scopes=["evidence_dag", "provenance_tuples", "decision_traces", "merkle_roots"],
        propose_scopes=["audit_certification", "provenance_seal"],
        simulate_scopes=[],
        can_execute=False,
        allowed_tools=[
            "verify_merkle_dag",
            "validate_decision_evidence_tuple",
            "generate_audit_trail",
        ],
    ),
    # Group C: Load Planning & Optimization
    "load_planning_agent": AgentCapabilityManifest(
        agent_id="load_planning_agent",
        agent_name="Load Planning Agent",
        domain_group="OPTIMIZATION",
        version="v4.5",
        read_scopes=[
            "order_volumes",
            "dimensions",
            "weights",
            "equipment_types",
            "carrier_capacities",
        ],
        propose_scopes=["load_manifest", "cube_utilization_plan"],
        simulate_scopes=["load_stability_simulation"],
        can_execute=False,
        allowed_tools=[
            "calculate_3d_cube_utilization",
            "optimize_axle_weights",
            "generate_load_manifest",
        ],
    ),
    "route_optimization_agent": AgentCapabilityManifest(
        agent_id="route_optimization_agent",
        agent_name="Route Optimization Agent",
        domain_group="OPTIMIZATION",
        version="v4.3",
        read_scopes=["topology_graph", "corridor_latencies", "tolls", "weather_traffic_signals"],
        propose_scopes=["multi_hop_itinerary", "delay_optimized_route"],
        simulate_scopes=["twin_route_traversal"],
        can_execute=False,
        allowed_tools=[
            "compute_dijkstra_delay_cost",
            "query_gnn_corridor_risk",
            "simulate_corridor_delay",
        ],
    ),
    "consolidation_agent": AgentCapabilityManifest(
        agent_id="consolidation_agent",
        agent_name="Consolidation Agent",
        domain_group="OPTIMIZATION",
        version="v4.0",
        read_scopes=["ltl_orders", "regional_hubs", "delivery_windows", "co_loading_rules"],
        propose_scopes=["consolidation_bundle", "hub_cross_dock_plan"],
        simulate_scopes=["consolidation_freight_savings"],
        can_execute=False,
        allowed_tools=[
            "find_coloading_clusters",
            "calculate_freight_savings",
            "generate_consolidation_manifest",
        ],
    ),
    "network_rebalancing_agent": AgentCapabilityManifest(
        agent_id="network_rebalancing_agent",
        agent_name="Network Rebalancing Agent",
        domain_group="OPTIMIZATION",
        version="v4.1",
        read_scopes=["hub_inventories", "lane_imbalances", "safety_stock_thresholds"],
        propose_scopes=["inter_hub_transfer", "capacity_rebalance_order"],
        simulate_scopes=["network_stockout_mitigation"],
        can_execute=False,
        allowed_tools=[
            "calculate_hub_imbalance",
            "generate_rebalancing_transfer",
            "simulate_stock_exhaustion",
        ],
    ),
    # Group D: Procurement & Sourcing
    "supplier_discovery_agent": AgentCapabilityManifest(
        agent_id="supplier_discovery_agent",
        agent_name="Supplier Discovery Agent",
        domain_group="PROCUREMENT",
        version="v4.2",
        read_scopes=["product_catalog", "supplier_graph", "gnn_embeddings", "geographic_regions"],
        propose_scopes=["candidate_suppliers", "qualification_dossier"],
        simulate_scopes=["supplier_lead_time_profile"],
        can_execute=False,
        allowed_tools=[
            "query_gnn_supplier_similarity",
            "search_qualified_suppliers",
            "filter_by_region",
        ],
    ),
    "supplier_evaluation_agent": AgentCapabilityManifest(
        agent_id="supplier_evaluation_agent",
        agent_name="Supplier Evaluation Agent",
        domain_group="PROCUREMENT",
        version="v4.0",
        read_scopes=["supplier_scorecards", "historical_otif", "defect_rates", "financial_health"],
        propose_scopes=["supplier_scorecard_verdict", "risk_ranking"],
        simulate_scopes=[],
        can_execute=False,
        allowed_tools=[
            "calculate_supplier_scorecard",
            "query_historical_otif",
            "evaluate_supplier_risk",
        ],
    ),
    "strategic_sourcing_agent": AgentCapabilityManifest(
        agent_id="strategic_sourcing_agent",
        agent_name="Strategic Sourcing Agent",
        domain_group="PROCUREMENT",
        version="v4.4",
        read_scopes=[
            "sourcing_strategies",
            "volume_commitments",
            "split_sourcing_rules",
            "rate_tiers",
        ],
        propose_scopes=["split_allocation_plan", "sourcing_strategy_recommendation"],
        simulate_scopes=["twin_sourcing_monte_carlo"],
        can_execute=False,
        allowed_tools=[
            "calculate_split_sourcing_allocation",
            "evaluate_expedite_vs_switch",
            "simulate_sourcing_scenario",
        ],
    ),
    "purchase_reorder_agent": AgentCapabilityManifest(
        agent_id="purchase_reorder_agent",
        agent_name="Purchase & Reorder Agent",
        domain_group="PROCUREMENT",
        version="v4.1",
        read_scopes=["stock_levels", "reorder_points", "economic_order_quantities", "lead_times"],
        propose_scopes=["purchase_order_proposal", "replenishment_schedule"],
        simulate_scopes=["holding_vs_stockout_cost"],
        can_execute=False,
        allowed_tools=["calculate_eoq", "draft_purchase_order", "verify_replenishment_window"],
    ),
    # Group E: Nexus Supervisor
    "nexus_supervisor": AgentCapabilityManifest(
        agent_id="nexus_supervisor",
        agent_name="Nexus Swarm Supervisor",
        domain_group="SUPERVISOR",
        version="v5.0",
        read_scopes=["*"],
        propose_scopes=["task_decomposition", "consensus_synthesis", "counterfactual_batch"],
        simulate_scopes=["multi_agent_system_simulation"],
        can_execute=False,
        can_block_execution=True,
        allowed_tools=[
            "decompose_operational_incident",
            "route_to_specialists",
            "synthesize_consensus",
            "dispatch_to_digital_twin",
        ],
    ),
}
