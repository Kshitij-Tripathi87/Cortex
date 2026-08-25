"""Supply-chain entity models (MVP wedge) — operational+inventory+orders schemas.

Tables (all under their respective PostgreSQL schemas per ADR-0006):

operational.suppliers         — upstream supply nodes
operational.components        — parts a supplier ships
operational.warehouses        — storage nodes
operational.factories         — manufacturing nodes
operational.products          — sellable items
operational.customers         — demand sources
operational.edges             — single generic edge table (ADR-0007 alternative)
inventory.inventory           — (warehouse, component) stock levels
inventory.bom                 — product/component bill of materials
orders.orders                 — customer demand
orders.disruption_events      — a supplier/disruption declaration (input to propagation)

All tables carry `workspace_id` (UUID, non-null, indexed) per ADR-0006 —
queries go through `WorkspaceScopedRepository` which filters on it.

Native UUID PKs per ADR-0001. Decimal `Numeric(18, 4)` for all monetary and
scoring values per MVP execution plan §3.4.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import (
    DisruptionEventType,
    DisruptionSeverity,
    DisruptionStatus,
    EdgeType,
    NodeType,
    OrderStatus,
    SupplierStatus,
    SupplierTier,
)
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# operational.* — supply-chain graph nodes
# ─────────────────────────────────────────────────────────────────────────────


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_suppliers_workspace_name"),
        Index("ix_suppliers_workspace_tier", "workspace_id", "tier"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, comment="ISO-3166 alpha-2")
    tier: Mapped[SupplierTier] = mapped_column(String(16), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    status: Mapped[SupplierStatus] = mapped_column(
        String(32), nullable=False, default=SupplierStatus.ACTIVE
    )
    risk_score: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sku", name="uq_components_workspace_sku"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False, default="EA")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_warehouses_workspace_code"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Factory(Base):
    __tablename__ = "factories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_factories_workspace_code"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    throughput_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sku", name="uq_products_workspace_sku"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    factory_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.factories.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_customers_workspace_name"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, comment="ISO-3166 alpha-2")
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contract_value_annual: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class Edge(Base):
    """Relationship row in the supply-chain graph (ADR-0007 default H2 alternative).

    Polymorphic UUIDs reference one of: suppliers, components, warehouses,
    factories, products, customers. FKs are not declared at the DB level
    because each (from_type, to_type) pair would need its own constraint;
    application-level validation in ingestion enforces referential integrity.
    """

    __tablename__ = "edges"
    __table_args__ = (
        Index("ix_edges_workspace_from", "workspace_id", "from_type", "from_id"),
        Index("ix_edges_workspace_to", "workspace_id", "to_type", "to_id"),
        Index("ix_edges_workspace_type", "workspace_id", "edge_type"),
        {"schema": "operational"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_type: Mapped[NodeType] = mapped_column(String(32), nullable=False)
    from_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    to_type: Mapped[NodeType] = mapped_column(String(32), nullable=False)
    to_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    edge_type: Mapped[EdgeType] = mapped_column(String(32), nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# inventory.* — stock and BOM
# ─────────────────────────────────────────────────────────────────────────────


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "warehouse_id",
            "component_id",
            name="uq_inventory_workspace_warehouse_component",
        ),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.components.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class BillOfMaterials(Base):
    __tablename__ = "bom"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "product_id",
            "component_id",
            name="uq_bom_workspace_product_component",
        ),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.products.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.components.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity_per_unit: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# orders.* — customer demand
# ─────────────────────────────────────────────────────────────────────────────


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_workspace_status", "workspace_id", "status"),
        Index("ix_orders_workspace_customer", "workspace_id", "customer_id"),
        {"schema": "orders"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operational.products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        String(32), nullable=False, default=OrderStatus.PENDING
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DisruptionEvent(Base):
    """The triggering event for a Morning Brief run — e.g., "ACME supplier failed"."""

    __tablename__ = "disruption_events"
    __table_args__ = (
        Index("ix_disruption_events_workspace_status", "workspace_id", "status"),
        Index("ix_disruption_events_workspace_started_at", "workspace_id", "started_at"),
        {"schema": "orders"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[DisruptionEventType] = mapped_column(String(48), nullable=False)
    source_node_type: Mapped[NodeType] = mapped_column(String(32), nullable=False)
    source_node_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    severity: Mapped[DisruptionSeverity] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DisruptionStatus] = mapped_column(
        String(32), nullable=False, default=DisruptionStatus.OPEN
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


__all__ = [
    "BillOfMaterials",
    "Component",
    "Customer",
    "DisruptionEvent",
    "Edge",
    "Factory",
    "Inventory",
    "Order",
    "Product",
    "Supplier",
    "Warehouse",
]
