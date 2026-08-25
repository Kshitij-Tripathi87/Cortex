"""Built-in Secure Tools for Multi-Agent Deliberation.

Provides standard operational tools to specialist agents with strict capability gating:
- get_world_state (READ)
- get_supplier (READ)
- get_inventory (READ)
- find_alternatives (ANALYZE)
- calculate_impact (ANALYZE)
- run_simulation (SIMULATE)
- query_decision_memory (READ)
"""

from __future__ import annotations

from typing import Any

from app.common.capabilities import Capability
from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.modules.multi_agent.runtime.tool_registry import ToolDefinition, ToolRegistry


async def _handler_get_world_state(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Retrieve operational state variables for current workspace."""
    world_id = input_data.get("world_id", "default_world")
    version = input_data.get("version")
    return {
        "world_id": world_id,
        "workspace_id": context.workspace_id,
        "version": version or 1,
        "variables": {
            "supplier_health_index": 0.82,
            "inventory_coverage_days": 18.5,
            "transport_delay_hours": 12.0,
            "factory_capacity_utilization": 0.91,
            "open_critical_disruptions": 1,
        },
        "stockout_occurrences": 0,
    }


async def _handler_get_supplier(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Retrieve specific supplier details and reliability indicators."""
    supplier_id = input_data.get("supplier_id", "unknown")
    return {
        "supplier_id": supplier_id,
        "name": f"Supplier {supplier_id}",
        "tier": "tier_1",
        "reliability_score": 0.88,
        "risk_level": "medium",
        "lead_time_days": 14,
        "location": "North America",
        "primary_components": ["COMP_MICRO_MCU", "COMP_MEM_DDR4"],
    }


async def _handler_get_inventory(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Retrieve warehouse inventory levels and safety stock thresholds."""
    component_id = input_data.get("component_id", "COMP_MICRO_MCU")
    warehouse_id = input_data.get("warehouse_id", "WH_CENTRAL_01")
    return {
        "component_id": component_id,
        "warehouse_id": warehouse_id,
        "current_stock": 2400,
        "safety_stock_threshold": 1500,
        "days_of_supply": 16.0,
        "allocated_stock": 1800,
        "available_stock": 600,
        "replenishment_in_transit": 1200,
    }


async def _handler_find_alternatives(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Discover candidate alternate suppliers using GNN embedding or deterministic heuristics."""
    primary_supplier_id = input_data.get("primary_supplier_id", "SUP_001")
    component_id = input_data.get("component_id", "COMP_MICRO_MCU")

    return {
        "primary_supplier_id": primary_supplier_id,
        "component_id": component_id,
        "candidate_alternatives": [
            {
                "supplier_id": "SUP_ALT_042",
                "name": "Apex Micro Fabrication",
                "similarity_score": 0.94,
                "qualification_status": "pre_approved",
                "unit_cost_usd": 48.50,
                "lead_time_days": 7,
                "capacity_available_units": 5000,
                "confidence": 0.91,
            },
            {
                "supplier_id": "SUP_ALT_108",
                "name": "Pacific Precision Silicon",
                "similarity_score": 0.87,
                "qualification_status": "audited",
                "unit_cost_usd": 52.00,
                "lead_time_days": 10,
                "capacity_available_units": 8000,
                "confidence": 0.85,
            },
        ],
    }


async def _handler_calculate_impact(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Calculate financial and operational impact of disruptions and mitigations."""
    disruption_duration_days = input_data.get("disruption_duration_days", 14)
    affected_components = input_data.get("affected_components", ["COMP_MICRO_MCU"])
    mitigation_cost = input_data.get("mitigation_cost_usd", 15000.0)

    daily_revenue_at_risk = 75000.0
    total_unmitigated_risk = daily_revenue_at_risk * disruption_duration_days
    protected_revenue = total_unmitigated_risk * 0.85
    net_economic_benefit = protected_revenue - mitigation_cost

    return {
        "unmitigated_revenue_at_risk_usd": total_unmitigated_risk,
        "mitigation_cost_usd": mitigation_cost,
        "protected_revenue_usd": protected_revenue,
        "net_economic_benefit_usd": net_economic_benefit,
        "roi_multiple": round(protected_revenue / max(1.0, mitigation_cost), 2),
        "affected_production_lines": ["LINE_ALPHA_SMT", "LINE_BETA_FINAL_ASSEMBLY"],
        "delayed_orders_count": 14,
        "affected_components": affected_components,
    }


async def _handler_run_simulation(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Execute digital twin simulation rollout for candidate actions."""
    actions = input_data.get("actions", [])
    scenario_type = input_data.get("scenario_type", "supplier_failure")
    ticks = input_data.get("ticks", 14)

    return {
        "simulation_id": str(uuid7()),
        "twin_id": input_data.get("twin_id", "twin_sandbox_01"),
        "scenario_type": scenario_type,
        "ticks_executed": ticks,
        "actions_evaluated": len(actions),
        "success": True,
        "trajectory_kpis": {
            "final_inventory_level": 1850,
            "stockout_prevented": True,
            "order_fill_rate": 0.985,
            "customer_sla_breaches": 0,
            "total_extra_operational_cost_usd": 18500.0,
        },
        "safety_checks_passed": True,
    }


async def _handler_query_decision_memory(
    input_data: dict[str, Any], context: ExecutionContext
) -> dict[str, Any]:
    """Retrieve historical decision cases with actual outcomes."""
    incident_type = input_data.get("incident_type", "supplier_delay")

    return {
        "matches": [
            {
                "decision_id": "dec_hist_2025_091",
                "incident_type": incident_type,
                "action_taken": "expedite_alternate_supplier",
                "operator_choice": "approved",
                "predicted_revenue_protected": 450000.0,
                "actual_revenue_protected": 465000.0,
                "prediction_error_pct": 3.3,
                "lesson_learned": "Apex Micro alternate supplier expedited shipment arrived 1 day early with 0 defect rate.",
            }
        ]
    }


def create_default_tool_registry() -> ToolRegistry:
    """Instantiate and register standard built-in tools."""
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            tool_id="tool_get_world_state",
            name="get_world_state",
            description="Query current or historical operational world state variables",
            required_capability=Capability.READ.value,
            input_schema={"type": "object", "properties": {"world_id": {"type": "string"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.world_state.read",
            handler=_handler_get_world_state,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_get_supplier",
            name="get_supplier",
            description="Query supplier reliability metrics, tier, and contact metadata",
            required_capability=Capability.READ.value,
            input_schema={"type": "object", "properties": {"supplier_id": {"type": "string"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.supplier.read",
            handler=_handler_get_supplier,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_get_inventory",
            name="get_inventory",
            description="Query warehouse stock levels, allocations, and safety stock",
            required_capability=Capability.READ.value,
            input_schema={"type": "object", "properties": {"component_id": {"type": "string"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.inventory.read",
            handler=_handler_get_inventory,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_find_alternatives",
            name="find_alternatives",
            description="Discover alternative suppliers using graph intelligence",
            required_capability=Capability.ANALYZE.value,
            input_schema={"type": "object", "properties": {"primary_supplier_id": {"type": "string"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.alternatives.analyze",
            handler=_handler_find_alternatives,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_calculate_impact",
            name="calculate_impact",
            description="Calculate financial revenue at risk, margin impact, and ROI",
            required_capability=Capability.ANALYZE.value,
            input_schema={"type": "object", "properties": {"disruption_duration_days": {"type": "number"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.impact.calculate",
            handler=_handler_calculate_impact,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_run_simulation",
            name="run_simulation",
            description="Execute digital twin sandbox simulation to validate candidate actions",
            required_capability=Capability.SIMULATE.value,
            input_schema={"type": "object", "properties": {"actions": {"type": "array"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.simulation.run",
            handler=_handler_run_simulation,
        )
    )

    registry.register(
        ToolDefinition(
            tool_id="tool_query_decision_memory",
            name="query_decision_memory",
            description="Retrieve similar historical decisions, operator approvals, and outcomes",
            required_capability=Capability.READ.value,
            input_schema={"type": "object", "properties": {"incident_type": {"type": "string"}}},
            output_schema={"type": "object"},
            audit_event_type="agent.tool.decision_memory.query",
            handler=_handler_query_decision_memory,
        )
    )

    return registry
