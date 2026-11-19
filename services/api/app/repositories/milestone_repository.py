"""Milestone and plan-version queries, scoped to one workspace."""

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from app.models.enums import MilestoneType
from app.models.milestone import Milestone
from app.models.milestone_plan_version import MilestonePlanVersion
from app.repositories._pagination import fetch_page

MilestoneIdentity = tuple[UUID, MilestoneType, int]


def lifecycle_order() -> Any:
    """SQL expression that sorts milestone types in their lifecycle order."""
    return case(
        {member.value: position for position, member in enumerate(MilestoneType)},
        value=Milestone.milestone_type,
    )


def get_by_id(
    session: Session,
    workspace_id: UUID,
    milestone_id: UUID,
    *,
    purchase_order_id: UUID | None = None,
    for_update: bool = False,
) -> Milestone | None:
    """Load a milestone; with ``for_update`` its row stays locked until the transaction ends."""
    statement = select(Milestone).where(
        Milestone.workspace_id == workspace_id, Milestone.id == milestone_id
    )
    if purchase_order_id is not None:
        statement = statement.where(Milestone.purchase_order_id == purchase_order_id)
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_by_identity(
    session: Session,
    workspace_id: UUID,
    purchase_order_id: UUID,
    milestone_type: MilestoneType,
    sequence_no: int,
) -> Milestone | None:
    return session.scalar(
        select(Milestone).where(
            Milestone.workspace_id == workspace_id,
            Milestone.purchase_order_id == purchase_order_id,
            Milestone.milestone_type == milestone_type,
            Milestone.sequence_no == sequence_no,
        )
    )


def get_by_identities(
    session: Session,
    workspace_id: UUID,
    identities: Collection[MilestoneIdentity],
    *,
    for_update: bool = False,
) -> dict[MilestoneIdentity, Milestone]:
    """Milestones for the given (purchase order id, type, sequence) keys."""
    if not identities:
        return {}
    keys = [
        (po_id, milestone_type.value, sequence) for po_id, milestone_type, sequence in identities
    ]
    statement = (
        select(Milestone)
        .where(
            Milestone.workspace_id == workspace_id,
            tuple_(
                Milestone.purchase_order_id, Milestone.milestone_type, Milestone.sequence_no
            ).in_(keys),
        )
        .order_by(Milestone.purchase_order_id, Milestone.milestone_type, Milestone.sequence_no)
    )
    if for_update:
        statement = statement.with_for_update()
    return {
        (milestone.purchase_order_id, milestone.milestone_type, milestone.sequence_no): milestone
        for milestone in session.scalars(statement)
    }


def list_for_purchase_order(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, *, limit: int, offset: int
) -> tuple[list[Milestone], int]:
    statement = select(Milestone).where(
        Milestone.workspace_id == workspace_id, Milestone.purchase_order_id == purchase_order_id
    )
    return fetch_page(
        session,
        statement,
        order_by=(lifecycle_order(), Milestone.sequence_no, Milestone.id),
        limit=limit,
        offset=offset,
    )


def add(session: Session, milestone: Milestone) -> Milestone:
    session.add(milestone)
    session.flush()
    return milestone


# --- plan versions --------------------------------------------------------------------
# A plan version carries no workspace column: callers pass ids of milestones
# they loaded through a workspace-scoped query.


def latest_plan_version(session: Session, milestone_id: UUID) -> MilestonePlanVersion | None:
    """The current plan: the version with the greatest version number."""
    return session.scalar(
        select(MilestonePlanVersion)
        .where(MilestonePlanVersion.milestone_id == milestone_id)
        .order_by(MilestonePlanVersion.version_no.desc())
        .limit(1)
    )


def latest_plan_versions(
    session: Session, milestone_ids: Collection[UUID]
) -> dict[UUID, MilestonePlanVersion]:
    """The current plan of each given milestone, in one query."""
    if not milestone_ids:
        return {}
    statement = (
        select(MilestonePlanVersion)
        .where(MilestonePlanVersion.milestone_id.in_(milestone_ids))
        .ext(distinct_on(MilestonePlanVersion.milestone_id))
        .order_by(MilestonePlanVersion.milestone_id, MilestonePlanVersion.version_no.desc())
    )
    return {version.milestone_id: version for version in session.scalars(statement)}


def plan_version_counts(session: Session, milestone_ids: Collection[UUID]) -> dict[UUID, int]:
    if not milestone_ids:
        return {}
    rows = session.execute(
        select(MilestonePlanVersion.milestone_id, func.count())
        .where(MilestonePlanVersion.milestone_id.in_(milestone_ids))
        .group_by(MilestonePlanVersion.milestone_id)
    )
    return {milestone_id: int(count) for milestone_id, count in rows}


def recent_plan_versions(
    session: Session, milestone_ids: Collection[UUID], *, per_milestone: int
) -> dict[UUID, list[MilestonePlanVersion]]:
    """The latest ``per_milestone`` plan versions of each milestone, oldest first."""
    if not milestone_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=MilestonePlanVersion.milestone_id,
            order_by=MilestonePlanVersion.version_no.desc(),
        )
        .label("rank")
    )
    ranked = (
        select(MilestonePlanVersion, rank)
        .where(MilestonePlanVersion.milestone_id.in_(milestone_ids))
        .subquery()
    )
    version = aliased(MilestonePlanVersion, ranked)
    statement = (
        select(version)
        .where(ranked.c.rank <= per_milestone)
        .order_by(version.milestone_id, version.version_no)
    )
    grouped: dict[UUID, list[MilestonePlanVersion]] = {}
    for item in session.scalars(statement):
        grouped.setdefault(item.milestone_id, []).append(item)
    return grouped


def add_plan_version(session: Session, version: MilestonePlanVersion) -> MilestonePlanVersion:
    session.add(version)
    session.flush()
    return version
