"""Purchase-order header: one project, one supplier, both of the same workspace."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import PurchaseOrderStatus

if TYPE_CHECKING:
    from app.models.purchase_order_item import PurchaseOrderItem
    from app.models.supplier import Supplier


class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_purchase_orders_workspace_project",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_purchase_orders_workspace_supplier",
        ),
        UniqueConstraint(
            "workspace_id", "po_number", name="uq_purchase_orders_workspace_id_po_number"
        ),
        # Targets of the composite foreign keys of milestones, commitments and line items.
        UniqueConstraint("workspace_id", "id", name="uq_purchase_orders_workspace_id_id"),
        UniqueConstraint(
            "workspace_id", "project_id", "id", name="uq_purchase_orders_workspace_id_project_id_id"
        ),
        CheckConstraint("length(btrim(po_number)) > 0", name="po_number_not_blank"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("total_value IS NULL OR total_value >= 0", name="total_value_not_negative"),
        Index("ix_purchase_orders_workspace_id_project_id", "workspace_id", "project_id"),
        Index("ix_purchase_orders_workspace_id_supplier_id", "workspace_id", "supplier_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column()
    supplier_id: Mapped[UUID] = mapped_column()
    po_number: Mapped[str] = mapped_column(String(limits.PO_NUMBER_MAX))
    issue_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    total_value: Mapped[Decimal | None] = mapped_column(
        Numeric(limits.MONEY_PRECISION, limits.MONEY_SCALE)
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        enum_type(PurchaseOrderStatus, "status"), default=PurchaseOrderStatus.DRAFT
    )

    # Read-only conveniences. Nothing is loaded unless a query asks for it
    # (lazy="raise"), and nothing is written through them: foreign keys are
    # set explicitly, so the composite keys stay the single source of truth.
    supplier: Mapped["Supplier"] = relationship(
        primaryjoin="PurchaseOrder.supplier_id == Supplier.id",
        foreign_keys="PurchaseOrder.supplier_id",
        viewonly=True,
        lazy="raise",
    )
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        primaryjoin="PurchaseOrder.id == PurchaseOrderItem.purchase_order_id",
        foreign_keys="PurchaseOrderItem.purchase_order_id",
        viewonly=True,
        lazy="raise",
        order_by="PurchaseOrderItem.created_at, PurchaseOrderItem.id",
    )
