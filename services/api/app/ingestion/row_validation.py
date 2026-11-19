"""Row validation: fields, uniqueness within the batch, references and consistency.

Pure functions. They decide nothing by reading a database: the caller hands in
a ReferenceSnapshot of the canonical records the batch refers to, taken in one
workspace. The same assessment runs at preview and again at commit, against
the state of that moment, so a preview is never trusted beyond its time.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.ingestion.column_mapping import ENTITY_SPECS, EntitySpec
from app.ingestion.contracts import (
    CandidateRow,
    MappedRow,
    RecordRef,
    ReferenceSnapshot,
    RowAssessment,
    ValidationIssue,
    error,
    warning,
)
from app.models.enums import IngestionEntityType, MilestoneStatus, PlannedAction, SupplierStatus
from app.models.field_policy import (
    IDENTITY_REFERENCES,
    SOURCE_OWNED_FIELDS,
    changed_fields,
    merged_specification,
    milestone_state,
    milestone_state_is_consistent,
)

SPECIFICATION_FIELDS: Mapping[str, str] = {
    "spec_description": "description",
    "spec_manufacturer": "manufacturer",
    "spec_model": "model",
    "spec_notes": "notes",
}


# --- field level ----------------------------------------------------------------------


def validate_fields(spec: EntitySpec, row: MappedRow) -> tuple[ValidationIssue, ...]:
    """Required fields and value ranges of one row, added to its mapping issues."""
    issues: list[ValidationIssue] = [*row.mapping_errors, *row.mapping_warnings]
    failed = {issue.column for issue in row.mapping_errors}
    values = row.normalized_data
    for field_spec in spec.fields:
        name = field_spec.name
        if name in failed:
            continue  # the mapping stage already said why this field has no value
        if name not in values:
            if field_spec.required:
                issues.append(
                    error("REQUIRED_FIELD_MISSING", "A required value is missing.", column=name)
                )
            continue
        value = values[name]
        if field_spec.positive and value <= 0:
            issues.append(
                error("MUST_BE_POSITIVE", "The value must be greater than zero.", column=name)
            )
        if field_spec.non_negative and value < 0:
            issues.append(
                error("MUST_BE_NON_NEGATIVE", "The value must not be negative.", column=name)
            )
    return tuple(issues)


def candidate(spec: EntitySpec, row: MappedRow) -> CandidateRow:
    """A mapped row with its field-level verdict, ready for the batch assessment."""
    return CandidateRow(
        row_number=row.row_number,
        values=dict(row.normalized_data),
        issues=validate_fields(spec, row),
    )


# --- batch level ----------------------------------------------------------------------


def assess_rows(
    entity_type: IngestionEntityType,
    rows: Sequence[CandidateRow],
    snapshot: ReferenceSnapshot,
) -> list[RowAssessment]:
    """Check every row against the other rows of the batch and against the snapshot.

    Rows that already have errors keep them and gain nothing else, except that
    they still take part in duplicate detection: a second row with the same
    natural key is a collision whichever of the two is otherwise broken.
    """
    spec = ENTITY_SPECS[entity_type]
    duplicates = _duplicate_verdicts(spec, rows)
    assessments: list[RowAssessment] = []
    for row in rows:
        issues = list(row.issues)
        verdict = duplicates.get(row.row_number)
        if isinstance(verdict, ValidationIssue):
            issues.append(verdict)
        resolved: dict[str, Any] = {}
        action: PlannedAction | None = None
        if not any(issue.severity.value == "ERROR" for issue in issues):
            problems, resolved, action = _ASSESSORS[entity_type](row.values, snapshot)
            issues.extend(problems)
        duplicate_of = verdict if isinstance(verdict, int) else None
        has_errors = any(issue.severity.value == "ERROR" for issue in issues)
        if duplicate_of is not None and not has_errors:
            issues.append(
                warning(
                    "DUPLICATE_ROW",
                    f"The row repeats row {duplicate_of} exactly and will be skipped.",
                )
            )
            action = PlannedAction.NO_CHANGE
        assessments.append(
            RowAssessment(
                row_number=row.row_number,
                issues=tuple(issues),
                planned_action=None if has_errors else action,
                duplicate_of=None if has_errors else duplicate_of,
                resolved={} if has_errors else resolved,
            )
        )
    return assessments


def _duplicate_verdicts(
    spec: EntitySpec, rows: Sequence[CandidateRow]
) -> dict[int, ValidationIssue | int]:
    """Per row: an error (colliding key, different values) or the row it repeats.

    Rows that share a natural key and all values are harmless repeats: the
    first one stands, the others refer to it. Rows that share a key and differ
    in anything are all rejected; row order never chooses a winner.
    """
    groups: dict[tuple[Any, ...], list[CandidateRow]] = {}
    for row in rows:
        if all(name in row.values for name in spec.natural_key):
            groups.setdefault(tuple(row.values[name] for name in spec.natural_key), []).append(row)

    verdicts: dict[int, ValidationIssue | int] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        first = group[0]
        identical = all(
            row.values == first.values and not row.has_errors and not first.has_errors
            for row in group[1:]
        )
        if identical:
            for row in group[1:]:
                verdicts[row.row_number] = first.row_number
            continue
        others = ", ".join(str(row.row_number) for row in group)
        for row in group:
            verdicts[row.row_number] = error(
                "DUPLICATE_NATURAL_KEY",
                f"Rows {others} share one natural key with different values. "
                "Resolve the conflict in the source; no row is preferred.",
                column=spec.natural_key[-1],
            )
    return verdicts


_Assessment = tuple[list[ValidationIssue], dict[str, Any], PlannedAction | None]


def _not_found(column: str, what: str) -> ValidationIssue:
    # A record of another workspace gets this same answer: the snapshot is
    # workspace-scoped, and saying more would disclose that the record exists.
    return error(
        "REFERENCE_NOT_FOUND",
        f"The {what} does not exist in this workspace. Import it first or correct the reference.",
        column=column,
    )


def _planned(
    existing: RecordRef | None, incoming: Mapping[str, Any], entity_type: IngestionEntityType
) -> PlannedAction:
    if existing is None:
        return PlannedAction.CREATE
    changed = changed_fields(existing.values, incoming, SOURCE_OWNED_FIELDS[entity_type])
    return PlannedAction.UPDATE if changed else PlannedAction.NO_CHANGE


def _identity_conflicts(
    existing: RecordRef | None, resolved: Mapping[str, Any], entity_type: IngestionEntityType
) -> list[ValidationIssue]:
    """An existing record whose project or supplier differs from the row's."""
    if existing is None:
        return []
    columns = {"project_id": "project_code", "supplier_id": "supplier_code"}
    return [
        error(
            "IMMUTABLE_FIELD_CONFLICT",
            "The record exists with a different value here. An import does not move a "
            "record to another project or supplier.",
            column=columns[name],
        )
        for name in IDENTITY_REFERENCES.get(entity_type, ())
        if name in resolved and existing.values.get(name) != resolved[name]
    ]


def _assess_project(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    existing = snapshot.projects.get(values["code"])
    resolved = dict(values)
    return [], resolved, _planned(existing, resolved, IngestionEntityType.PROJECT)


def _assess_supplier(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    existing = snapshot.suppliers.get(values["supplier_code"])
    resolved = dict(values)
    return [], resolved, _planned(existing, resolved, IngestionEntityType.SUPPLIER)


def _assess_equipment(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    project = snapshot.projects.get(values["project_code"])
    if project is None:
        return [_not_found("project_code", "project")], {}, None
    existing = snapshot.equipment.get(values["equipment_code"])
    resolved = {
        name: value
        for name, value in values.items()
        if name not in SPECIFICATION_FIELDS and name != "project_code"
    }
    resolved["project_id"] = project.id
    supplied_specification = {
        key: values[name] for name, key in SPECIFICATION_FIELDS.items() if name in values
    }
    if supplied_specification:
        current = existing.values.get("specification") if existing else None
        resolved["specification"] = merged_specification(current, supplied_specification)
    problems = _identity_conflicts(existing, resolved, IngestionEntityType.EQUIPMENT)
    if problems:
        return problems, {}, None
    return [], resolved, _planned(existing, resolved, IngestionEntityType.EQUIPMENT)


def _assess_purchase_order(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    problems: list[ValidationIssue] = []
    project = snapshot.projects.get(values["project_code"])
    supplier = snapshot.suppliers.get(values["supplier_code"])
    if project is None:
        problems.append(_not_found("project_code", "project"))
    if supplier is None:
        problems.append(_not_found("supplier_code", "supplier"))
    if project is None or supplier is None:
        return problems, {}, None

    existing = snapshot.purchase_orders.get(values["po_number"])
    resolved = {
        name: value
        for name, value in values.items()
        if name not in {"project_code", "supplier_code"}
    }
    resolved["project_id"] = project.id
    resolved["supplier_id"] = supplier.id
    problems = _identity_conflicts(existing, resolved, IngestionEntityType.PURCHASE_ORDER)
    if existing is None and supplier.values.get("status") != SupplierStatus.ACTIVE:
        # Existing purchase orders of an inactive supplier stay valid; new ones do not start.
        problems.append(
            error(
                "REFERENCE_INACTIVE",
                "The supplier is inactive. A new purchase order cannot name it.",
                column="supplier_code",
            )
        )
    if problems:
        return problems, {}, None
    return [], resolved, _planned(existing, resolved, IngestionEntityType.PURCHASE_ORDER)


def _assess_line_item(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    problems: list[ValidationIssue] = []
    purchase_order = snapshot.purchase_orders.get(values["po_number"])
    equipment = snapshot.equipment.get(values["equipment_code"])
    if purchase_order is None:
        problems.append(_not_found("po_number", "purchase order"))
    if equipment is None:
        problems.append(_not_found("equipment_code", "equipment"))
    if purchase_order is None or equipment is None:
        return problems, {}, None
    if purchase_order.values.get("project_id") != equipment.values.get("project_id"):
        return (
            [
                error(
                    "CROSS_PROJECT_REFERENCE",
                    "The purchase order and the equipment belong to different projects.",
                    column="equipment_code",
                )
            ],
            {},
            None,
        )
    existing = snapshot.line_items.get((values["po_number"], values["equipment_code"]))
    resolved = {
        name: value for name, value in values.items() if name not in {"po_number", "equipment_code"}
    }
    resolved["po_number"] = values["po_number"]
    resolved["equipment_code"] = values["equipment_code"]
    return [], resolved, _planned(existing, resolved, IngestionEntityType.PURCHASE_ORDER_ITEM)


def _assess_milestone(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    if snapshot.purchase_orders.get(values["po_number"]) is None:
        return [_not_found("po_number", "purchase order")], {}, None
    key = (values["po_number"], str(values["milestone_type"]), int(values["sequence_no"]))
    existing = snapshot.milestones.get(key)
    supplied_status: MilestoneStatus | None = values.get("status")
    supplied_actual: date | None = values.get("actual_date")
    status, actual_date = milestone_state(
        current_status=existing.values.get("status") if existing else None,
        current_actual_date=existing.values.get("actual_date") if existing else None,
        supplied_status=supplied_status,
        supplied_actual_date=supplied_actual,
    )
    if not milestone_state_is_consistent(status, actual_date):
        return (
            [
                error(
                    "INCONSISTENT_MILESTONE_STATE",
                    "An actual date can be recorded only on a completed milestone.",
                    column="actual_date",
                )
            ],
            {},
            None,
        )
    resolved = dict(values)
    if existing is None:
        return [], resolved, PlannedAction.CREATE
    replanned = existing.values.get("planned_date") != values["planned_date"]
    state_changed = (status, actual_date) != (
        existing.values.get("status"),
        existing.values.get("actual_date"),
    )
    action = PlannedAction.UPDATE if (replanned or state_changed) else PlannedAction.NO_CHANGE
    return [], resolved, action


def _assess_commitment(values: Mapping[str, Any], snapshot: ReferenceSnapshot) -> _Assessment:
    if snapshot.purchase_orders.get(values["po_number"]) is None:
        return [_not_found("po_number", "purchase order")], {}, None
    current = snapshot.commitments.get(values["po_number"])
    resolved = dict(values)
    unchanged = (
        current is not None
        and current.values.get("committed_delivery_date") == values["committed_delivery_date"]
    )
    # A different date is a new version, never an update of the current one.
    return [], resolved, PlannedAction.NO_CHANGE if unchanged else PlannedAction.CREATE


_ASSESSORS = {
    IngestionEntityType.PROJECT: _assess_project,
    IngestionEntityType.SUPPLIER: _assess_supplier,
    IngestionEntityType.EQUIPMENT: _assess_equipment,
    IngestionEntityType.PURCHASE_ORDER: _assess_purchase_order,
    IngestionEntityType.PURCHASE_ORDER_ITEM: _assess_line_item,
    IngestionEntityType.MILESTONE: _assess_milestone,
    IngestionEntityType.SUPPLIER_COMMITMENT: _assess_commitment,
}
