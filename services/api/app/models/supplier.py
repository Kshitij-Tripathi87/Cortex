"""Supplier master record. No rating, score or reliability figure lives here."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import SupplierStatus


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "supplier_code", name="uq_suppliers_workspace_id_supplier_code"
        ),
        UniqueConstraint("workspace_id", "id", name="uq_suppliers_workspace_id_id"),
        CheckConstraint("length(btrim(supplier_code)) > 0", name="supplier_code_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    supplier_code: Mapped[str] = mapped_column(String(limits.CODE_MAX))
    name: Mapped[str] = mapped_column(String(limits.NAME_MAX))
    country: Mapped[str | None] = mapped_column(String(limits.PLACE_MAX))
    city: Mapped[str | None] = mapped_column(String(limits.PLACE_MAX))
    status: Mapped[SupplierStatus] = mapped_column(
        enum_type(SupplierStatus, "status"), default=SupplierStatus.ACTIVE
    )
