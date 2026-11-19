"""Equipment inventory.

Equipment has no supplier and no purchase-order column on purpose: a critical
item that nobody has ordered yet must be representable. Procurement is
expressed by purchase-order line items.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import Criticality, EquipmentCategory, ProcurementStatus


class Equipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "equipment"
    __table_args__ = (
        # The project must belong to the same workspace.
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_equipment_workspace_project",
        ),
        UniqueConstraint(
            "workspace_id", "equipment_code", name="uq_equipment_workspace_id_equipment_code"
        ),
        # Target of the line-item foreign key that enforces "same workspace, same project".
        UniqueConstraint(
            "workspace_id", "project_id", "id", name="uq_equipment_workspace_id_project_id_id"
        ),
        CheckConstraint("length(btrim(equipment_code)) > 0", name="equipment_code_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "specification IS NULL OR jsonb_typeof(specification) = 'object'",
            name="specification_is_object",
        ),
        Index("ix_equipment_workspace_id_project_id", "workspace_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column()
    equipment_code: Mapped[str] = mapped_column(String(limits.CODE_MAX))
    name: Mapped[str] = mapped_column(String(limits.NAME_MAX))
    category: Mapped[EquipmentCategory] = mapped_column(enum_type(EquipmentCategory, "category"))
    # none_as_null: Python None is stored as SQL NULL, not as the JSON value "null".
    specification: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    required_on_site_date: Mapped[date | None] = mapped_column(Date)
    criticality: Mapped[Criticality] = mapped_column(enum_type(Criticality, "criticality"))
    procurement_status: Mapped[ProcurementStatus] = mapped_column(
        enum_type(ProcurementStatus, "procurement_status"), default=ProcurementStatus.NOT_STARTED
    )
