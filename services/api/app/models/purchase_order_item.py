"""Purchase-order line item: the link between a purchase order and equipment.

Two composite foreign keys make PostgreSQL enforce what the service checks:
the purchase order and the equipment belong to the same workspace and to the
same project as the line.
"""

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.equipment import Equipment


class PurchaseOrderItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "purchase_order_id"],
            ["purchase_orders.workspace_id", "purchase_orders.project_id", "purchase_orders.id"],
            name="fk_purchase_order_items_purchase_order",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "equipment_id"],
            ["equipment.workspace_id", "equipment.project_id", "equipment.id"],
            name="fk_purchase_order_items_equipment",
        ),
        UniqueConstraint(
            "purchase_order_id",
            "equipment_id",
            name="uq_purchase_order_items_purchase_order_id_equipment_id",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_not_negative"),
        Index("ix_purchase_order_items_equipment_id", "equipment_id"),
        Index("ix_purchase_order_items_workspace_id_project_id", "workspace_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column()
    purchase_order_id: Mapped[UUID] = mapped_column()
    equipment_id: Mapped[UUID] = mapped_column()
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(limits.QUANTITY_PRECISION, limits.QUANTITY_SCALE)
    )
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(limits.MONEY_PRECISION, limits.MONEY_SCALE)
    )

    equipment: Mapped["Equipment"] = relationship(
        primaryjoin="PurchaseOrderItem.equipment_id == Equipment.id",
        foreign_keys="PurchaseOrderItem.equipment_id",
        viewonly=True,
        lazy="raise",
    )
