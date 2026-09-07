"""Nexus Ontology — Specialized Entity Types for Supply Chain.

Each class below is a typed view of an Entity for a specific supply-chain
domain. These carry domain-specific state fields (e.g. supplier has
`capacity_pct`, inventory has `on_hand_qty`, forecast has `p50`/`p80`/`p95`).

Design notes:
- All specialized entities are Pydantic models (not SQLAlchemy) so they can be
  serialized to JSON for the API, message bus, and evidence chain.
- Persistence is handled by the WorldModelRepository (DB-agnostic).
- State fields are deliberately flat — nested state should be split into
  separate entities with relationships rather than nested dicts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.nexus_spine.ontology.core_types import EntityKind
from app.modules.nexus_spine.ontology.entities import Entity


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ──────────────────────────────────────────────────────────────────────────────
# Supply-side
# ──────────────────────────────────────────────────────────────────────────────


class SupplierEntity(Entity):
    """A supplier of materials/components/products.

    Capacity is the key operational metric: capacity_pct=100 means operating
    at declared max; capacity_pct<100 means headroom available; >100 means
    backlog.
    """

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        capacity_pct: float = 100.0,
        lead_time_days: float = 14.0,
        on_time_rate: float = 0.95,
        risk_score: float = 0.0,
        country: str = "",
    ) -> "SupplierEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.SUPPLIER,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "capacity_pct": capacity_pct,
                "lead_time_days": lead_time_days,
                "on_time_rate": on_time_rate,
                "risk_score": risk_score,
                "country": country,
            },
        )


class WarehouseEntity(Entity):
    """A warehouse / DC holding inventory."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        capacity_pct: float = 80.0,
        location: str = "",
    ) -> "WarehouseEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.WAREHOUSE,
            natural_key=natural_key,
            name=name,
            source=source,
            state={"capacity_pct": capacity_pct, "location": location},
        )


class PlantEntity(Entity):
    """A manufacturing plant / factory."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        utilization_pct: float = 75.0,
        capacity_units_per_day: float = 0.0,
    ) -> "PlantEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.PLANT,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "utilization_pct": utilization_pct,
                "capacity_units_per_day": capacity_units_per_day,
            },
        )


# ──────────────────────────────────────────────────────────────────────────────
# Product
# ──────────────────────────────────────────────────────────────────────────────


class ProductEntity(Entity):
    """A finished product (sellable SKU or product family)."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        unit_price: float = 0.0,
        is_perishable: bool = False,
    ) -> "ProductEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.PRODUCT,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "unit_price": unit_price,
                "is_perishable": is_perishable,
            },
        )


class ComponentEntity(Entity):
    """A component or raw material used in a product's bill of materials."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        unit_cost: float = 0.0,
    ) -> "ComponentEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.COMPONENT,
            natural_key=natural_key,
            name=name,
            source=source,
            state={"unit_cost": unit_cost},
        )


# ──────────────────────────────────────────────────────────────────────────────
# Flow
# ──────────────────────────────────────────────────────────────────────────────


class PurchaseOrderEntity(Entity):
    """A purchase order placed with a supplier."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        quantity: float,
        supplier_id: UUID,
        expected_delivery: datetime,
        unit_cost: float = 0.0,
    ) -> "PurchaseOrderEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.PURCHASE_ORDER,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "quantity": quantity,
                "supplier_id": str(supplier_id),
                "expected_delivery": expected_delivery.isoformat(),
                "unit_cost": unit_cost,
                "status": "open",
            },
        )


class SalesOrderEntity(Entity):
    """A customer sales order."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        quantity: float,
        customer_id: UUID,
        promised_delivery: datetime,
        revenue: float = 0.0,
        sla_risk_pct: float = 0.0,
    ) -> "SalesOrderEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.SALES_ORDER,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "quantity": quantity,
                "customer_id": str(customer_id),
                "promised_delivery": promised_delivery.isoformat(),
                "revenue": revenue,
                "sla_risk_pct": sla_risk_pct,
                "status": "open",
            },
        )


class InventoryPositionEntity(Entity):
    """Inventory position for a SKU at a warehouse."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        sku: str,
        warehouse_id: UUID,
        on_hand_qty: float,
        safety_stock_qty: float,
    ) -> "InventoryPositionEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.INVENTORY_POSITION,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "sku": sku,
                "warehouse_id": str(warehouse_id),
                "on_hand_qty": on_hand_qty,
                "safety_stock_qty": safety_stock_qty,
                "coverage_days": 0.0,
            },
        )


# ──────────────────────────────────────────────────────────────────────────────
# Operational intelligence
# ──────────────────────────────────────────────────────────────────────────────


class SignalEntity(Entity):
    """An operational signal about an entity — capacity drop, demand surge, etc.

    Signals carry severity, confidence, and a `severity_score` (0-1) that the
    truth-loop and Vanessa use to triage what needs attention.
    """

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        affected_entity_id: UUID,
        severity_score: float,
        signal_type: str,
        confidence: float = 0.85,
        description: str = "",
    ) -> "SignalEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.SIGNAL,
            natural_key=natural_key,
            name=name,
            description=description,
            source=source,
            confidence=confidence,
            state={
                "affected_entity_id": str(affected_entity_id),
                "severity_score": severity_score,
                "signal_type": signal_type,
                "acknowledged": False,
            },
        )


class DisruptionEntity(Entity):
    """A disruption event — supplier outage, port closure, etc.

    Disruptions are signals whose impact has been confirmed (typically by an
    agent or operator). They trigger risk recalculation and may invalidate
    pending decisions.
    """

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        disruption_type: str,
        affected_entity_ids: list[UUID],
        severity: str,
        expected_duration_hours: float,
    ) -> "DisruptionEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.DISRUPTION,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "disruption_type": disruption_type,
                "affected_entity_ids": [str(e) for e in affected_entity_ids],
                "severity": severity,
                "expected_duration_hours": expected_duration_hours,
                "active": True,
            },
        )


class ForecastEntity(Entity):
    """A probabilistic demand forecast.

    Carries P50/P80/P95 quantiles, primary drivers, model version, and
    a backtest WAPE so the truth-loop can compare prediction vs reality.
    """

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        horizon_days: int,
        forecast_timestamp: datetime,
        p50: float,
        p80: float,
        p95: float,
        confidence: float,
        primary_drivers: list[str],
        model_version: str,
        backtest_wape: float = 0.0,
    ) -> "ForecastEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.FORECAST,
            natural_key=natural_key,
            name=name,
            source=source,
            confidence=confidence,
            state={
                "horizon_days": horizon_days,
                "forecast_timestamp": forecast_timestamp.isoformat(),
                "p50": p50,
                "p80": p80,
                "p95": p95,
                "primary_drivers": primary_drivers,
                "model_version": model_version,
                "backtest_wape": backtest_wape,
                "actual": None,
                "actual_observation_at": None,
            },
        )


class DecisionEntity(Entity):
    """A decision made (or proposed) by Nexus.

    Carries the situation, recommendation, chosen option, evidence references,
    and outcome once observed.
    """

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
        name: str,
        source: str,
        situation: str,
        options: list[dict[str, Any]],
        recommended_option_id: str,
        evidence_ids: list[UUID],
        policy_id: str,
        chosen_option_id: str | None = None,
    ) -> "DecisionEntity":
        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=EntityKind.DECISION,
            natural_key=natural_key,
            name=name,
            source=source,
            state={
                "situation": situation,
                "options": options,
                "recommended_option_id": recommended_option_id,
                "chosen_option_id": chosen_option_id,
                "evidence_ids": [str(e) for e in evidence_ids],
                "policy_id": policy_id,
                "status": "proposed",
                "outcome": None,
                "financial_impact": None,
            },
        )
