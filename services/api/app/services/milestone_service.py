"""Milestone rules and transactions.

Planned and actual are separate facts. Every planned date, the first one
included, is a plan version; a re-plan appends a version and never rewrites
one. Version numbers are allocated while the milestone row is locked.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ErrorDetail, NotFoundError, ValidationFailedError
from app.db.session import transaction
from app.models.enums import CanonicalEntityType, MilestoneStatus, RowOutcome
from app.models.field_policy import milestone_state, milestone_state_is_consistent
from app.models.milestone import Milestone
from app.models.milestone_plan_version import MilestonePlanVersion
from app.models.purchase_order import PurchaseOrder
from app.repositories import milestone_repository, purchase_order_repository
from app.schemas.milestone import MilestoneCreate, MilestoneUpdate
from app.services import workspace_service
from app.services._support import duplicate_key_error, unique_key_guard
from app.services.results import Applied, Page

API_ACTOR = "api"

# How many plan versions a milestone response carries; the count is always complete.
PLAN_HISTORY_LIMIT = 50


@dataclass(frozen=True, slots=True)
class MilestoneHistory:
    """A milestone with its current plan and its (bounded) plan history."""

    milestone: Milestone
    current_plan: MilestonePlanVersion | None
    plan_versions: Sequence[MilestonePlanVersion]
    plan_version_count: int


def _not_found() -> NotFoundError:
    return NotFoundError("The milestone was not found.")


def _purchase_order_not_found() -> NotFoundError:
    return NotFoundError("The purchase order was not found.")


def _inconsistent_state() -> ValidationFailedError:
    return ValidationFailedError(
        "The supplied record is invalid.",
        details=[
            ErrorDetail(
                code="INCONSISTENT_MILESTONE_STATE",
                message="An actual date can be recorded only on a completed milestone.",
                field="actual_date",
            )
        ],
    )


def _histories(session: Session, milestones: Sequence[Milestone]) -> list[MilestoneHistory]:
    """Attach plan data to milestones with three queries, whatever their number."""
    ids = [milestone.id for milestone in milestones]
    current = milestone_repository.latest_plan_versions(session, ids)
    counts = milestone_repository.plan_version_counts(session, ids)
    recent = milestone_repository.recent_plan_versions(
        session, ids, per_milestone=PLAN_HISTORY_LIMIT
    )
    return [
        MilestoneHistory(
            milestone=milestone,
            current_plan=current.get(milestone.id),
            plan_versions=recent.get(milestone.id, []),
            plan_version_count=counts.get(milestone.id, 0),
        )
        for milestone in milestones
    ]


def record_plan(
    session: Session,
    milestone: Milestone,
    *,
    planned_date: date,
    recorded_by: str,
    source_row_id: UUID | None = None,
) -> tuple[MilestonePlanVersion, bool]:
    """Append a plan version unless the date is already the current plan.

    For an existing milestone the row must be locked in the running
    transaction. Returns the current version and whether it was created now.
    Does not commit.
    """
    latest = milestone_repository.latest_plan_version(session, milestone.id)
    if latest is not None and latest.planned_date == planned_date:
        return latest, False
    version = MilestonePlanVersion(
        milestone_id=milestone.id,
        version_no=(latest.version_no + 1) if latest is not None else 1,
        planned_date=planned_date,
        source_ingestion_row_id=source_row_id,
        recorded_by=recorded_by,
    )
    milestone_repository.add_plan_version(session, version)
    return version, True


def create_milestone(
    session: Session,
    workspace_id: UUID,
    purchase_order_id: UUID,
    payload: MilestoneCreate,
    source_row_id: UUID | None = None,
) -> MilestoneHistory:
    """Add a milestone to a purchase order together with its first plan version."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        if purchase_order_repository.get_by_id(session, workspace_id, purchase_order_id) is None:
            raise _purchase_order_not_found()
        if milestone_repository.get_by_identity(
            session, workspace_id, purchase_order_id, payload.milestone_type, payload.sequence_no
        ):
            raise duplicate_key_error("milestone", "sequence_no")

        status, actual_date = milestone_state(
            current_status=None,
            current_actual_date=None,
            supplied_status=payload.status,
            supplied_actual_date=payload.actual_date,
        )
        milestone = Milestone(
            workspace_id=workspace_id,
            purchase_order_id=purchase_order_id,
            milestone_type=payload.milestone_type,
            sequence_no=payload.sequence_no,
            status=status,
            actual_date=actual_date,
        )
        with unique_key_guard(session, "milestone", "sequence_no"):
            milestone_repository.add(session, milestone)
        record_plan(
            session,
            milestone,
            planned_date=payload.planned_date,
            recorded_by=payload.recorded_by or API_ACTOR,
            source_row_id=source_row_id,
        )
        return _histories(session, [milestone])[0]


def list_milestones(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, *, limit: int, offset: int
) -> Page[MilestoneHistory]:
    workspace_service.require_active_workspace(session, workspace_id)
    if purchase_order_repository.get_by_id(session, workspace_id, purchase_order_id) is None:
        raise _purchase_order_not_found()
    milestones, total = milestone_repository.list_for_purchase_order(
        session, workspace_id, purchase_order_id, limit=limit, offset=offset
    )
    return Page(items=_histories(session, milestones), total=total, limit=limit, offset=offset)


def get_milestone_history(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, milestone_id: UUID
) -> MilestoneHistory:
    workspace_service.require_active_workspace(session, workspace_id)
    milestone = milestone_repository.get_by_id(
        session, workspace_id, milestone_id, purchase_order_id=purchase_order_id
    )
    if milestone is None:
        raise _not_found()
    return _histories(session, [milestone])[0]


def append_plan_version(
    session: Session,
    workspace_id: UUID,
    purchase_order_id: UUID,
    milestone_id: UUID,
    planned_date: date,
    recorded_by: str | None = None,
    source_row_id: UUID | None = None,
) -> tuple[MilestoneHistory, bool]:
    """Record a new planned date. Returns the milestone and whether a version was created."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        milestone = milestone_repository.get_by_id(
            session,
            workspace_id,
            milestone_id,
            purchase_order_id=purchase_order_id,
            for_update=True,
        )
        if milestone is None:
            raise _not_found()
        _, created = record_plan(
            session,
            milestone,
            planned_date=planned_date,
            recorded_by=recorded_by or API_ACTOR,
            source_row_id=source_row_id,
        )
        return _histories(session, [milestone])[0], created


def record_actual_milestone(
    session: Session,
    workspace_id: UUID,
    purchase_order_id: UUID,
    milestone_id: UUID,
    patch: MilestoneUpdate,
) -> MilestoneHistory:
    """Record what actually happened: status and actual date. The plan is untouched."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        milestone = milestone_repository.get_by_id(
            session,
            workspace_id,
            milestone_id,
            purchase_order_id=purchase_order_id,
            for_update=True,
        )
        if milestone is None:
            raise _not_found()

        changes = patch.changes()
        clearing_date = "actual_date" in changes and changes["actual_date"] is None
        status, actual_date = milestone_state(
            current_status=milestone.status,
            current_actual_date=None if clearing_date else milestone.actual_date,
            supplied_status=changes.get("status"),
            supplied_actual_date=changes.get("actual_date"),
        )
        if not milestone_state_is_consistent(status, actual_date):
            raise _inconsistent_state()
        milestone.status = status
        milestone.actual_date = actual_date
        session.flush()
        return _histories(session, [milestone])[0]


def apply_source_record(
    session: Session,
    *,
    existing: Milestone | None,
    purchase_order: PurchaseOrder,
    values: Mapping[str, Any],
    recorded_by: str,
    source_row_id: UUID,
) -> Applied:
    """Create the milestone with plan version 1, or record a re-plan and the actual state.

    Writes inside the ingestion commit and never commits itself. An existing
    milestone must be locked by the caller.
    """
    supplied_status: MilestoneStatus | None = values.get("status")
    supplied_actual_date: date | None = values.get("actual_date")

    if existing is None:
        status, actual_date = milestone_state(
            current_status=None,
            current_actual_date=None,
            supplied_status=supplied_status,
            supplied_actual_date=supplied_actual_date,
        )
        milestone = Milestone(
            workspace_id=purchase_order.workspace_id,
            purchase_order_id=purchase_order.id,
            milestone_type=values["milestone_type"],
            sequence_no=values["sequence_no"],
            status=status,
            actual_date=actual_date,
        )
        milestone_repository.add(session, milestone)
        record_plan(
            session,
            milestone,
            planned_date=values["planned_date"],
            recorded_by=recorded_by,
            source_row_id=source_row_id,
        )
        return Applied(
            CanonicalEntityType.MILESTONE, milestone.id, RowOutcome.CREATED, versions_created=1
        )

    _, plan_created = record_plan(
        session,
        existing,
        planned_date=values["planned_date"],
        recorded_by=recorded_by,
        source_row_id=source_row_id,
    )
    status, actual_date = milestone_state(
        current_status=existing.status,
        current_actual_date=existing.actual_date,
        supplied_status=supplied_status,
        supplied_actual_date=supplied_actual_date,
    )
    state_changed = (status, actual_date) != (existing.status, existing.actual_date)
    if state_changed:
        existing.status = status
        existing.actual_date = actual_date
        session.flush()
    outcome = RowOutcome.UPDATED if (plan_created or state_changed) else RowOutcome.UNCHANGED
    return Applied(
        CanonicalEntityType.MILESTONE,
        existing.id,
        outcome,
        versions_created=1 if plan_created else 0,
    )
