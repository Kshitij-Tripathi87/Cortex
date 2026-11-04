"""Pydantic schemas for CSV ingestion rows (per dataset_type).

Each schema validates one row of a CSV. The ingestion service instantiates
the correct schema from the `dataset_type` query parameter and uses it to
validate rows. Failed validations are logged to `error_log` but don't
necessarily abort the run (partial-accept, default per Question F).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    quantity: Annotated[Decimal, Field(ge=0)]
    safety_stock: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    reserved_quantity: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    blocked_quantity: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    quantity_basis: Literal["physical_on_hand", "available_to_use", "free_stock"] = (
        "physical_on_hand"
    )
    basis_excludes_reserved: bool | None = None
    basis_excludes_blocked: bool | None = None

    @model_validator(mode="after")
    def _validate_basis_semantics(self) -> InventoryRow:
        if self.quantity_basis != "physical_on_hand" and (
            self.basis_excludes_reserved is None or self.basis_excludes_blocked is None
        ):
            raise ValueError(
                "available/free inventory must declare reserved and blocked semantics"
            )
        return self


class BomRow(BaseModel):
    product_sku: str
    component_sku: str
    quantity_per_unit: Annotated[Decimal, Field(gt=0)]



class BOMRevisionRow(BaseModel):
    parent_item_type: Literal["product", "component"]
    parent_item_ref: Annotated[str, Field(min_length=1, max_length=128)]
    revision_code: Annotated[str, Field(min_length=1, max_length=64)]
    factory_code: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    active: bool = True
    source_ref: str | None = None


class BOMLineRow(BaseModel):
    parent_item_type: Literal["product", "component"]
    parent_item_ref: Annotated[str, Field(min_length=1, max_length=128)]
    revision_code: Annotated[str, Field(min_length=1, max_length=64)]
    factory_code: str | None = None
    line_code: Annotated[str, Field(min_length=1, max_length=64)]
    child_item_type: Literal["product", "component"]
    child_item_ref: Annotated[str, Field(min_length=1, max_length=128)]
    usage_quantity: Annotated[Decimal, Field(gt=0)]
    usage_uom: Annotated[str, Field(min_length=1, max_length=32)]
    child_base_uom: Annotated[str, Field(min_length=1, max_length=32)]
    child_is_assembly: bool = False
    scrap_factor: Annotated[Decimal, Field(gt=0)] | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    source_ref: str | None = None


class ProductionOrderRow(BaseModel):
    order_number: Annotated[str, Field(min_length=1, max_length=128)]
    factory_code: Annotated[str, Field(min_length=1, max_length=64)]
    warehouse_code: Annotated[str, Field(min_length=1, max_length=64)]
    item_type: Literal["product", "component"]
    item_ref: Annotated[str, Field(min_length=1, max_length=128)]
    quantity: Annotated[Decimal, Field(gt=0)]
    order_uom: Annotated[str, Field(min_length=1, max_length=32)]
    item_base_uom: Annotated[str, Field(min_length=1, max_length=32)]
    material_need_at: date
    status: Annotated[str, Field(min_length=1, max_length=32)]
    bom_revision_code: str | None = None
    source_ref: str | None = None


class PurchaseOrderLineRow(BaseModel):
    po_number: Annotated[str, Field(min_length=1, max_length=128)]
    line_number: Annotated[str, Field(min_length=1, max_length=32)]
    supplier_name: Annotated[str, Field(min_length=1, max_length=256)]
    warehouse_code: Annotated[str, Field(min_length=1, max_length=64)]
    component_sku: Annotated[str, Field(min_length=1, max_length=128)]
    ordered_quantity: Annotated[Decimal, Field(gt=0)]
    received_quantity: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    open_quantity: Annotated[Decimal, Field(ge=0)] | None = None
    expected_date: date | None = None
    status: Annotated[str, Field(min_length=1, max_length=32)] = "open"
    confirmed: bool = False
    uom: Annotated[str, Field(min_length=1, max_length=32)]
    source_ref: str | None = None

    @model_validator(mode="after")
    def _validate_receipt_quantities(self) -> PurchaseOrderLineRow:
        if self.received_quantity > self.ordered_quantity:
            raise ValueError("received_quantity cannot exceed ordered_quantity")
        if (
            self.open_quantity is not None
            and self.open_quantity > self.ordered_quantity - self.received_quantity
        ):
            raise ValueError("open_quantity cannot exceed ordered_quantity - received_quantity")
        return self


class UOMConversionRow(BaseModel):
    from_uom: Annotated[str, Field(min_length=1, max_length=32)]
    to_uom: Annotated[str, Field(min_length=1, max_length=32)]
    factor: Annotated[Decimal, Field(gt=0)]
    source_ref: str | None = None


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
    "bom_revisions": BOMRevisionRow,
    "bom_lines": BOMLineRow,
    "production_orders": ProductionOrderRow,
    "purchase_order_lines": PurchaseOrderLineRow,
    "uom_conversions": UOMConversionRow,
}


__all__ = [
    "BOMLineRow",
    "BOMRevisionRow",
    "BomRow",
    "ComponentRow",
    "CustomerRow",
    "DisruptionEventRow",
    "EdgeRow",
    "FactoryRow",
    "InventoryRow",
    "OrderRow",
    "ProductionOrderRow",
    "PurchaseOrderLineRow",
    "ProductRow",
    "ROW_SCHEMA_BY_DATASET",
    "SupplierRow",
    "UOMConversionRow",
    "WarehouseRow",
]
