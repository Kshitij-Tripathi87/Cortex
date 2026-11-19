"""Which fields an import may change, per entity.

An import resolves a record by its natural key. It may then change only the
fields listed here as source-owned; identity fields are never rewritten by a
file. This table is the single statement of that policy
(docs/architecture/domain-model.md, "Field ownership for imports"); the row
validation uses it to predict what a commit will do, and the services use it
to do it.
"""

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from app.models.enums import IngestionEntityType, MilestoneStatus

SOURCE_OWNED_FIELDS: Mapping[IngestionEntityType, tuple[str, ...]] = {
    IngestionEntityType.PROJECT: ("name", "location", "status", "target_completion_date"),
    IngestionEntityType.SUPPLIER: ("name", "country", "city", "status"),
    IngestionEntityType.EQUIPMENT: (
        "name",
        "category",
        "specification",
        "required_on_site_date",
        "criticality",
        "procurement_status",
    ),
    IngestionEntityType.PURCHASE_ORDER: ("issue_date", "currency", "total_value", "status"),
    IngestionEntityType.PURCHASE_ORDER_ITEM: ("quantity", "unit_price"),
    # The planned date is not here: it changes only through a new plan version.
    IngestionEntityType.MILESTONE: ("actual_date", "status"),
    # A commitment is never updated; a different date is a new version.
    IngestionEntityType.SUPPLIER_COMMITMENT: (),
}

# Fields that identify a record or tie it to its parents. A source row that
# disagrees with the stored value is rejected (IMMUTABLE_FIELD_CONFLICT).
IDENTITY_REFERENCES: Mapping[IngestionEntityType, tuple[str, ...]] = {
    IngestionEntityType.EQUIPMENT: ("project_id",),
    IngestionEntityType.PURCHASE_ORDER: ("project_id", "supplier_id"),
}


def changed_fields(
    current: Mapping[str, Any], incoming: Mapping[str, Any], fields: Iterable[str]
) -> list[str]:
    """Source-owned fields whose supplied value differs from the stored one.

    A field that is absent from ``incoming`` was not supplied (a blank cell)
    and is therefore never a change: a blank never clears a stored value.
    """
    return [name for name in fields if name in incoming and incoming[name] != current.get(name)]


def merged_specification(
    current: Mapping[str, Any] | None, supplied: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Stored specification with the supplied attributes laid over it."""
    merged = {**(current or {}), **(supplied or {})}
    return merged or None


def milestone_state(
    *,
    current_status: MilestoneStatus | None,
    current_actual_date: date | None,
    supplied_status: MilestoneStatus | None,
    supplied_actual_date: date | None,
) -> tuple[MilestoneStatus, date | None]:
    """The status and actual date a milestone has after a source record is applied.

    A supplied value wins over the stored one; a missing value keeps it. When
    no status is supplied, an actual date implies COMPLETED: a completion date
    is an explicit statement that the step happened. The reverse is never
    assumed: a COMPLETED status does not produce a date.
    """
    actual_date = supplied_actual_date if supplied_actual_date is not None else current_actual_date
    if supplied_status is not None:
        status = supplied_status
    elif supplied_actual_date is not None:
        status = MilestoneStatus.COMPLETED
    elif current_status is not None:
        status = current_status
    else:
        status = MilestoneStatus.PENDING
    return status, actual_date


def milestone_state_is_consistent(status: MilestoneStatus, actual_date: date | None) -> bool:
    """An actual date belongs to a completed milestone only."""
    return actual_date is None or status == MilestoneStatus.COMPLETED
