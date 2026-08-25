"""SLAs — Service Level Agreement Definitions and Tracking.

Program J (World State & Digital Twin) SLA module:

Provides factory functions for common SLAs:
- Delivery time
- Order fulfillment rate
- Inventory availability
- Supplier on-time delivery
- Production uptime
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.knowledge.knowledge_models import SLA, RuleAction


def delivery_time_sla(
    workspace_id: str,
    max_days: float = 5.0,
    percentile: float = 95.0,
    customer_facing: bool = True,
) -> SLA:
    """SLA: 95% of orders delivered within max_days."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Delivery Time ({percentile}%)",
        description=f"{percentile}% of orders delivered within {max_days} days",
        metric_name="delivery_time",
        target_value=max_days,
        comparison="le",
        measurement_window="daily",
        breach_action=RuleAction.ESCALATE,
        customer_facing=customer_facing,
    )


def inventory_availability_sla(
    workspace_id: str,
    target_pct: float = 99.0,
    customer_facing: bool = True,
) -> SLA:
    """SLA: target_pct% of SKUs in stock."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Inventory Availability ({target_pct}%)",
        description=f"{target_pct}% of SKUs must be in stock",
        metric_name="inventory_availability",
        target_value=target_pct,
        comparison="ge",
        measurement_window="daily",
        breach_action=RuleAction.ESCALATE,
        customer_facing=customer_facing,
    )


def supplier_on_time_sla(
    workspace_id: str,
    supplier_id: str,
    target_pct: float = 95.0,
) -> SLA:
    """SLA: supplier delivers on time at target_pct% rate."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Supplier {supplier_id} On-Time Delivery",
        description=f"Supplier {supplier_id} on-time delivery rate must be >= {target_pct}%",
        metric_name=f"supplier_{supplier_id}_on_time",
        target_value=target_pct,
        comparison="ge",
        measurement_window="monthly",
        breach_action=RuleAction.ESCALATE,
        customer_facing=False,
    )


def production_uptime_sla(
    workspace_id: str,
    factory_id: str,
    target_pct: float = 99.5,
) -> SLA:
    """SLA: factory uptime must be >= target_pct%."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Factory {factory_id} Uptime",
        description=f"Factory {factory_id} uptime must be >= {target_pct}%",
        metric_name=f"factory_{factory_id}_uptime",
        target_value=target_pct,
        comparison="ge",
        measurement_window="weekly",
        breach_action=RuleAction.ESCALATE,
        customer_facing=False,
    )


def order_fulfillment_rate_sla(
    workspace_id: str,
    target_pct: float = 98.0,
    customer_facing: bool = True,
) -> SLA:
    """SLA: order fulfillment rate must be >= target_pct%."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Order Fulfillment Rate ({target_pct}%)",
        description=f"{target_pct}% of orders must be fulfilled without backorder",
        metric_name="order_fulfillment_rate",
        target_value=target_pct,
        comparison="ge",
        measurement_window="daily",
        breach_action=RuleAction.ESCALATE,
        customer_facing=customer_facing,
    )


def platinum_customer_delivery_sla(
    workspace_id: str,
    max_days: float = 2.0,
) -> SLA:
    """SLA: Platinum-tier customers get expedited delivery."""
    return SLA(
        sla_id=str(uuid7()),
        workspace_id=workspace_id,
        name="Platinum Customer Delivery",
        description=f"Platinum customers must receive delivery within {max_days} days",
        metric_name="platinum_customer_delivery",
        target_value=max_days,
        comparison="le",
        measurement_window="daily",
        breach_action=RuleAction.EXPEDITE,
        customer_facing=True,
    )
