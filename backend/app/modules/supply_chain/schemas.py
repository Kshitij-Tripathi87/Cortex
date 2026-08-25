"""Pydantic schemas for CSV ingestion rows (per dataset_type).

Each schema validates one row of a CSV. The ingestion service instantiates
the correct schema from the `dataset_type` query parameter and uses it to
validate rows. Failed validations are logged to `error_log` but don't
necessarily abort the run (partial-accept, default per Question F).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.common.enums import (
    DisruptionEventType,
    DisruptionSeverity,
    EdgeType,
    NodeType,
    OrderStatus,
    SupplierStatus,
    SupplierTier,
)


class SupplierRow(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=256)]
    country: Annotated[str, Field(min_length=2, max_length=2)]
    tier: SupplierTier
    lead_time_days: Annotated[int, Field(ge=0, le=365)]
    status: SupplierStatus = SupplierStatus.ACTIVE
    risk_score: Decimal | None = None


class ComponentRow(BaseModel):
    sku: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    category: str | None = None
    unit_of_measure: str = "EA"


class WarehouseRow(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    location: str | None = None
    capacity_units: int | None = None


class FactoryRow(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    location: str | None = None
    throughput_per_day: int | None = None


class ProductRow(BaseModel):
    sku: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    factory_code: str | None = None
    unit_price: Decimal | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=365)] = 7


class CustomerRow(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=256)]
    country: Annotated[str, Field(min_length=2, max_length=2)]
    tier: str | None = None
    contract_value_annual: Decimal | None = None


class EdgeRow(BaseModel):
    from_type: NodeType
    from_ref: str = Field(
        description="Sku/code/name of the source — resolved to UUID during ingestion"
    )
    to_type: NodeType
    to_ref: str = Field(
        description="Sku/code/name of the target — resolved to UUID during ingestion"
    )
    edge_type: EdgeType
    weight: Decimal | None = None

    @field_validator("from_type", "to_type", "edge_type", mode="before")
    @classmethod
    def _coerce_enum(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class InventoryRow(BaseModel):
    warehouse_code: str
    component_sku: str
    quantity: Annotated[int, Field(ge=0)]
    safety_stock: Annotated[int, Field(ge=0)] = 0


class BomRow(BaseModel):
    product_sku: str
    component_sku: str
    quantity_per_unit: Annotated[Decimal, Field(gt=0)]


class OrderRow(BaseModel):
    customer_name: str
    product_sku: str
    quantity: Annotated[int, Field(gt=0)]
    status: OrderStatus = OrderStatus.PENDING
    order_date: date
    requested_delivery_date: date
    actual_delivery_date: date | None = None


class DisruptionEventRow(BaseModel):
    event_type: DisruptionEventType
    source_node_type: NodeType
    source_node_ref: str = Field(
        description="Sku/code/name of the source — resolved to UUID during ingestion"
    )
    severity: DisruptionSeverity
    description: str | None = None
    started_at: date


ROW_SCHEMA_BY_DATASET: dict[str, type[BaseModel]] = {
    "suppliers": SupplierRow,
    "components": ComponentRow,
    "warehouses": WarehouseRow,
    "factories": FactoryRow,
    "products": ProductRow,
    "customers": CustomerRow,
    "edges": EdgeRow,
    "inventory": InventoryRow,
    "bom": BomRow,
    "orders": OrderRow,
}


__all__ = [
    "BomRow",
    "ComponentRow",
    "CustomerRow",
    "DisruptionEventRow",
    "EdgeRow",
    "FactoryRow",
    "InventoryRow",
    "OrderRow",
    "ProductRow",
    "ROW_SCHEMA_BY_DATASET",
    "SupplierRow",
    "WarehouseRow",
]
