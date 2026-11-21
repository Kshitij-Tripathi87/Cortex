"""Equipment rules and transactions.

Equipment needs a project of the same workspace and nothing else: no purchase
order and no supplier. Procurement status is a status, not a risk level.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ErrorDetail, NotFoundError, ValidationFailedError
from app.db.session import transaction
from app.models.enums import (
    CanonicalEntityType,
    Criticality,
    EquipmentCategory,
    IngestionEntityType,
    ProcurementStatus,
    RowOutcome,
)
from app.models.equipment import Equipment
from app.models.field_policy import SOURCE_OWNED_FIELDS, changed_fields, merged_specification
from app.repositories import equipment_repository, project_repository
from app.schemas.equipment import EquipmentCreate, EquipmentSpecification, EquipmentUpdate
from app.services import workspace_service
from app.services._support import apply_changes, duplicate_key_error, unique_key_guard
from app.services.results import Applied, Page

_SOURCE_OWNED = SOURCE_OWNED_FIELDS[IngestionEntityType.EQUIPMENT]


def _not_found() -> NotFoundError:
    return NotFoundError("The equipment was not found.")


def create_equipment(session: Session, workspace_id: UUID, payload: EquipmentCreate) -> Equipment:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        # A project of another workspace is reported exactly like a missing one.
        if project_repository.get_by_id(session, workspace_id, payload.project_id) is None:
            raise ValidationFailedError(
                "The supplied record is invalid.",
                details=[
                    ErrorDetail(
                        code="REFERENCE_NOT_FOUND",
                        message="The project does not exist in this workspace.",
                        field="project_id",
                    )
                ],
            )
        if equipment_repository.get_by_code(session, workspace_id, payload.equipment_code):
            raise duplicate_key_error("equipment record", "equipment_code")
        equipment = Equipment(
            workspace_id=workspace_id,
            project_id=payload.project_id,
            equipment_code=payload.equipment_code,
            name=payload.name,
            category=payload.category,
            criticality=payload.criticality,
            procurement_status=payload.procurement_status,
            required_on_site_date=payload.required_on_site_date,
            specification=payload.specification.as_stored() if payload.specification else None,
        )
        with unique_key_guard(session, "equipment record", "equipment_code"):
            equipment_repository.add(session, equipment)
        return equipment


def get_equipment(session: Session, workspace_id: UUID, equipment_id: UUID) -> Equipment:
    workspace_service.require_active_workspace(session, workspace_id)
    equipment = equipment_repository.get_by_id(session, workspace_id, equipment_id)
    if equipment is None:
        raise _not_found()
    return equipment


def list_equipment(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    project_id: UUID | None = None,
    category: EquipmentCategory | None = None,
    criticality: Criticality | None = None,
    procurement_status: ProcurementStatus | None = None,
) -> Page[Equipment]:
    workspace_service.require_active_workspace(session, workspace_id)
    items, total = equipment_repository.list_for_workspace(
        session,
        workspace_id,
        limit=limit,
        offset=offset,
        project_id=project_id,
        category=category,
        criticality=criticality,
        procurement_status=procurement_status,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


def update_equipment(
    session: Session, workspace_id: UUID, equipment_id: UUID, patch: EquipmentUpdate
) -> Equipment:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        # Locked: a second writer must not change the record between this read
        # and the commit, or one patch would silently overwrite the other.
        equipment = equipment_repository.get_by_id(
            session, workspace_id, equipment_id, for_update=True
        )
        if equipment is None:
            raise _not_found()
        changes = patch.changes()
        if "specification" in changes:
            specification: EquipmentSpecification | None = changes["specification"]
            changes["specification"] = specification.as_stored() if specification else None
        apply_changes(equipment, changes)
        session.flush()
        return equipment


def apply_source_record(
    session: Session, workspace_id: UUID, *, existing: Equipment | None, values: Mapping[str, Any]
) -> Applied:
    """Create the equipment record, or change its source-owned fields. Does not commit.

    ``values["project_id"]`` is the project resolved in this workspace. For an
    existing record the caller has already verified that it is unchanged.
    """
    if existing is None:
        equipment = Equipment(
            workspace_id=workspace_id,
            project_id=values["project_id"],
            equipment_code=values["equipment_code"],
            name=values["name"],
            category=values["category"],
            criticality=values["criticality"],
            procurement_status=values.get("procurement_status", ProcurementStatus.NOT_STARTED),
            required_on_site_date=values.get("required_on_site_date"),
            specification=merged_specification(None, values.get("specification")),
        )
        equipment_repository.add(session, equipment)
        return Applied(CanonicalEntityType.EQUIPMENT, equipment.id, RowOutcome.CREATED)

    incoming = dict(values)
    if "specification" in incoming:
        incoming["specification"] = merged_specification(
            existing.specification, incoming["specification"]
        )
    current = {name: getattr(existing, name) for name in _SOURCE_OWNED}
    changed = changed_fields(current, incoming, _SOURCE_OWNED)
    apply_changes(existing, {name: incoming[name] for name in changed})
    session.flush()
    outcome = RowOutcome.UPDATED if changed else RowOutcome.UNCHANGED
    return Applied(CanonicalEntityType.EQUIPMENT, existing.id, outcome)
