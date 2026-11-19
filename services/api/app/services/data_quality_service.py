"""Data quality: what is missing or invalid, counted and named.

Two kinds of observation, kept apart:

* about source rows (this module, pure): every validation code belongs to
  one quality dimension, and a batch reports how many blocking findings fall
  into each;
* about stored records (functions further down, database-backed): facts that
  are not recorded, such as a purchase order without an acknowledgement
  milestone.

Nothing here produces a score, a percentage or a judgement. "Not recorded"
is a statement about the data, not about a supplier.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import BatchStatus, QualityDimension, RowStatus
from app.repositories import ingestion_repository, world_state_repository

# Which dimension a validation code speaks about. A code that is not listed
# is a validity problem: the value itself breaks a type, range or format rule.
DIMENSION_BY_CODE: Mapping[str, QualityDimension] = {
    "REQUIRED_FIELD_MISSING": QualityDimension.COMPLETENESS,
    "FORMULA_WITHOUT_CACHED_VALUE": QualityDimension.COMPLETENESS,
    "REQUIRED_ON_SITE_DATE_NOT_RECORDED": QualityDimension.COMPLETENESS,
    "INVALID_DATE": QualityDimension.VALIDITY,
    "INVALID_ENUM": QualityDimension.VALIDITY,
    "INVALID_DECIMAL": QualityDimension.VALIDITY,
    "INVALID_INTEGER": QualityDimension.VALIDITY,
    "INVALID_CURRENCY": QualityDimension.VALIDITY,
    "INVALID_VALUE": QualityDimension.VALIDITY,
    "VALUE_TOO_LONG": QualityDimension.VALIDITY,
    "MUST_BE_POSITIVE": QualityDimension.VALIDITY,
    "MUST_BE_NON_NEGATIVE": QualityDimension.VALIDITY,
    "ROW_SHAPE_MISMATCH": QualityDimension.VALIDITY,
    "AMBIGUOUS_COLUMN_MAPPING": QualityDimension.CONSISTENCY,
    "CROSS_PROJECT_REFERENCE": QualityDimension.CONSISTENCY,
    "IMMUTABLE_FIELD_CONFLICT": QualityDimension.CONSISTENCY,
    "INCONSISTENT_MILESTONE_STATE": QualityDimension.CONSISTENCY,
    "DUPLICATE_NATURAL_KEY": QualityDimension.UNIQUENESS,
    "DUPLICATE_ROW": QualityDimension.UNIQUENESS,
    "REFERENCE_NOT_FOUND": QualityDimension.REFERENTIAL_INTEGRITY,
    "REFERENCE_INACTIVE": QualityDimension.REFERENTIAL_INTEGRITY,
}


def dimension_of(code: str) -> QualityDimension:
    return DIMENSION_BY_CODE.get(code, QualityDimension.VALIDITY)


def count_by_dimension(codes: Iterable[str]) -> dict[str, int]:
    """Number of findings per dimension. Every dimension is present, zero included.

    The five numbers are reported side by side and are never combined.
    """
    counts = {dimension.value: 0 for dimension in QualityDimension}
    for code in codes:
        counts[dimension_of(code).value] += 1
    return counts


# --- stored records: what is not recorded ---------------------------------------------

# How many warnings a response lists; the counts beside them are always complete.
WARNING_LIST_LIMIT = 100

# code -> (kind of record, the stated fact). Every one is a completeness
# observation. None says that anything is late, at risk or anyone's fault.
RECORD_WARNINGS: Mapping[str, tuple[str, str]] = {
    "EQUIPMENT_REQUIRED_DATE_NOT_RECORDED": (
        "equipment",
        "No required-on-site date is recorded for this equipment.",
    ),
    "EQUIPMENT_WITHOUT_PO_LINE_ITEM": (
        "equipment",
        "No purchase order line item is recorded for this equipment.",
    ),
    "MILESTONE_COMPLETED_WITHOUT_ACTUAL_DATE": (
        "milestone",
        "The milestone is completed and no actual date is recorded.",
    ),
    "PO_ACKNOWLEDGEMENT_NOT_RECORDED": (
        "purchase_order",
        "No acknowledgement milestone is recorded for this purchase order.",
    ),
    "PO_WITHOUT_LINE_ITEMS": (
        "purchase_order",
        "No line item is recorded for this purchase order.",
    ),
    "PO_WITHOUT_SUPPLIER_COMMITMENT": (
        "purchase_order",
        "No supplier commitment is recorded for this purchase order.",
    ),
}


@dataclass(frozen=True, slots=True)
class RecordWarning:
    dimension: QualityDimension
    code: str
    entity_type: str
    entity_id: UUID
    reference: str
    project_id: UUID
    message: str


@dataclass(frozen=True, slots=True)
class RecordQualityReport:
    warning_counts: dict[str, int]
    warnings: list[RecordWarning]
    truncated: bool


@dataclass(frozen=True, slots=True)
class LedgerQualityReport:
    batches: dict[str, int]
    rows: dict[str, int]
    valid_records: int
    invalid_records: int


def record_quality(
    session: Session, workspace_id: UUID, project_id: UUID | None = None
) -> RecordQualityReport:
    """Missing information on the stored records of a workspace or of one project.

    Counts are complete. The list holds at most WARNING_LIST_LIMIT entries,
    ordered by code and then by the natural key of the record.
    """
    queries = world_state_repository.missing_information_queries(workspace_id, project_id)
    counts: dict[str, int] = {}
    warnings: list[RecordWarning] = []
    for code in sorted(queries):
        found = world_state_repository.count_of(session, queries[code])
        if not found:
            continue
        counts[code] = found
        room = WARNING_LIST_LIMIT - len(warnings)
        if room <= 0:
            continue
        entity_type, message = RECORD_WARNINGS[code]
        warnings.extend(
            RecordWarning(
                dimension=QualityDimension.COMPLETENESS,
                code=code,
                entity_type=entity_type,
                entity_id=record.entity_id,
                reference=record.reference,
                project_id=record.project_id,
                message=message,
            )
            for record in world_state_repository.first_missing(session, queries[code], limit=room)
        )
    return RecordQualityReport(
        warning_counts=counts,
        warnings=warnings,
        truncated=sum(counts.values()) > len(warnings),
    )


def ledger_quality(session: Session, workspace_id: UUID) -> LedgerQualityReport:
    """How the source rows received so far fared: by batch status and by row status."""
    batches = ingestion_repository.batch_status_counts(session, workspace_id)
    rows = ingestion_repository.row_status_counts(session, workspace_id)
    accepted = (RowStatus.VALID, RowStatus.COMMITTED, RowStatus.SKIPPED)
    refused = (RowStatus.INVALID, RowStatus.FAILED)
    return LedgerQualityReport(
        batches={status.value: batches.get(status, 0) for status in BatchStatus},
        rows={status.value: rows.get(status, 0) for status in RowStatus},
        valid_records=sum(rows.get(status, 0) for status in accepted),
        invalid_records=sum(rows.get(status, 0) for status in refused),
    )
