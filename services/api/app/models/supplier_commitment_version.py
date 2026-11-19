"""Supplier delivery-commitment history of a purchase order. Append-only."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.models import limits
from app.models._columns import UUIDPrimaryKeyMixin


class SupplierCommitmentVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_commitment_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "purchase_order_id"],
            ["purchase_orders.workspace_id", "purchase_orders.id"],
            name="fk_supplier_commitment_versions_workspace_purchase_order",
        ),
        UniqueConstraint(
            "purchase_order_id",
            "version_no",
            name="uq_supplier_commitment_versions_purchase_order_id_version_no",
        ),
        CheckConstraint("version_no > 0", name="version_no_positive"),
    )

    workspace_id: Mapped[UUID] = mapped_column()
    purchase_order_id: Mapped[UUID] = mapped_column()
    version_no: Mapped[int] = mapped_column(Integer)
    committed_delivery_date: Mapped[date] = mapped_column(Date)
    source_reference: Mapped[str | None] = mapped_column(String(limits.SOURCE_REFERENCE_MAX))
    source_ingestion_row_id: Mapped[UUID | None] = mapped_column(ForeignKey("ingestion_rows.id"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    recorded_by: Mapped[str] = mapped_column(String(limits.ACTOR_MAX))
