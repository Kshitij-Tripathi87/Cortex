"""Import lifecycle: preview and commit.

Preview reads an upload, maps and validates every row against the canonical
data as it is now, and writes the result to the ingestion ledger: one batch,
one row per source row. It writes nothing else.

Commit is the only path from the ledger to canonical records. It locks the
batch, checks every valid row again against the database as it is at that
moment, and applies all of them in one transaction, or none. Each applied row
is linked to the record it produced. A committed batch is never applied
twice: asking again returns the recorded result.

    PREVIEWED --lock--> COMMITTING --+--> COMMITTED   (one transaction)
                                     +--> FAILED      (rolled back, then recorded)

COMMITTING exists only inside the commit transaction. Other sessions never
see it: until the transaction ends they wait on the batch row lock, and then
they see COMMITTED or, after a rollback, PREVIEWED followed by FAILED.

The pure work (reading, mapping, normalizing, validating) is done by
app/ingestion. This module supplies the database view those functions need
and persists what they return.
"""

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    DomainError,
    ErrorDetail,
    FileTooLargeError,
    InvalidStateError,
    NotFoundError,
    UnsupportedFileError,
    ValidationFailedError,
    ended_to_resolve_a_conflict,
)
from app.db.session import transaction
from app.ingestion import readers
from app.ingestion.column_mapping import (
    ENTITY_SPECS,
    HeaderMapping,
    decode_normalized,
    map_headers,
    map_row,
)
from app.ingestion.contracts import (
    CandidateRow,
    MappedRow,
    ParsedSheet,
    ReaderLimits,
    RecordRef,
    ReferenceSnapshot,
    RowAssessment,
    SourceFileError,
    ValidationIssue,
)
from app.ingestion.normalization import to_json
from app.ingestion.row_validation import assess_rows, candidate
from app.models import limits as field_limits
from app.models.enums import (
    BatchStatus,
    IngestionEntityType,
    PlannedAction,
    RowOutcome,
    RowStatus,
    SourceFormat,
)
from app.models.equipment import Equipment
from app.models.field_policy import SOURCE_OWNED_FIELDS
from app.models.ingestion import ACTIVE_CHECKSUM_INDEX, IngestionBatch, IngestionRow
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.repositories import (
    equipment_repository,
    ingestion_repository,
    milestone_repository,
    project_repository,
    purchase_order_repository,
    supplier_repository,
)
from app.services import (
    equipment_service,
    milestone_service,
    project_service,
    purchase_order_service,
    supplier_service,
    workspace_service,
)
from app.services.data_quality_service import count_by_dimension
from app.services.results import Applied, Page

_log = logging.getLogger("app.ingestion")

# How many row-level errors and warnings a preview response lists. The counts
# beside them are always complete, and every row is in the batch detail.
ISSUE_LIST_LIMIT = 100

# Key under which values beyond the last header are kept in a raw row.
EXTRA_CELLS_KEY = "__cells_beyond_header__"

# An XLSX file is a compressed archive; its content may be this many times larger.
UNCOMPRESSED_FACTOR = 10

# How many failing rows a COMMIT_CONFLICT response lists; all are in the batch detail.
COMMIT_FAILURE_DETAIL_LIMIT = 100

# Marks a finding that was made at commit time, on a row that was valid at preview.
COMMIT_STAGE = "commit"

_FILE_ERROR_STATUS: Mapping[str, type[DomainError]] = {
    "UNSUPPORTED_FILE": UnsupportedFileError,
    "FILE_TOO_LARGE": FileTooLargeError,
}


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """An upload as the service sees it: a display name, a media type and bounded bytes."""

    filename: str
    content_type: str | None
    data: bytes


@dataclass(frozen=True, slots=True)
class ImportLimits:
    max_upload_bytes: int
    max_rows: int
    max_columns: int
    max_cell_chars: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "ImportLimits":
        return cls(
            max_upload_bytes=settings.max_upload_size_bytes,
            max_rows=settings.max_import_rows,
            max_columns=settings.max_import_columns,
            max_cell_chars=settings.max_import_cell_chars,
        )

    def reader_limits(self) -> ReaderLimits:
        return ReaderLimits(
            max_rows=self.max_rows,
            max_columns=self.max_columns,
            max_cell_chars=self.max_cell_chars,
            max_uncompressed_bytes=self.max_upload_bytes * UNCOMPRESSED_FACTOR,
        )


@dataclass(frozen=True, slots=True)
class PreviewResult:
    batch: IngestionBatch
    # False when the upload matched a batch that already existed.
    created: bool
    duplicate_file: bool
    planned_actions: Mapping[str, int]
    errors: Sequence[Mapping[str, Any]]
    warnings: Sequence[Mapping[str, Any]]
    errors_count: int
    warnings_count: int
    quality: Mapping[str, int]
    truncated: bool


@dataclass(frozen=True, slots=True)
class CommitResult:
    batch: IngestionBatch
    # True when the batch was already committed and nothing was written now.
    replayed: bool


class _CommitRejected(Exception):
    """Rows that were valid at preview are not valid against the database as it is now."""

    def __init__(self, failures: Sequence[RowAssessment]) -> None:
        super().__init__(f"{len(failures)} row(s) failed revalidation")
        self.failures = tuple(failures)


@dataclass(frozen=True, slots=True)
class BatchDetail:
    batch: IngestionBatch
    rows: Page[IngestionRow]


@dataclass(frozen=True, slots=True)
class SourceRow:
    """A source row behind a canonical record, with the batch it came in."""

    row: IngestionRow
    batch: IngestionBatch


@dataclass(slots=True)
class LoadedRecords:
    """The canonical records a batch refers to, as ORM entities keyed by natural key."""

    projects: dict[str, Project] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    equipment: dict[str, Equipment] = field(default_factory=dict)
    purchase_orders: dict[str, PurchaseOrder] = field(default_factory=dict)
    line_items: dict[tuple[str, str], PurchaseOrderItem] = field(default_factory=dict)
    milestones: dict[tuple[str, str, int], Milestone] = field(default_factory=dict)
    current_plan_dates: dict[UUID, Any] = field(default_factory=dict)
    commitments: dict[str, SupplierCommitmentVersion] = field(default_factory=dict)

    def snapshot(self) -> ReferenceSnapshot:
        """The same records as plain values, for the pure validation."""

        def owned(record: Any, entity_type: IngestionEntityType) -> dict[str, Any]:
            return {name: getattr(record, name) for name in SOURCE_OWNED_FIELDS[entity_type]}

        return ReferenceSnapshot(
            projects={
                code: RecordRef(project.id, owned(project, IngestionEntityType.PROJECT))
                for code, project in self.projects.items()
            },
            suppliers={
                code: RecordRef(supplier.id, owned(supplier, IngestionEntityType.SUPPLIER))
                for code, supplier in self.suppliers.items()
            },
            equipment={
                code: RecordRef(
                    item.id,
                    {"project_id": item.project_id, **owned(item, IngestionEntityType.EQUIPMENT)},
                )
                for code, item in self.equipment.items()
            },
            purchase_orders={
                number: RecordRef(
                    order.id,
                    {
                        "project_id": order.project_id,
                        "supplier_id": order.supplier_id,
                        **owned(order, IngestionEntityType.PURCHASE_ORDER),
                    },
                )
                for number, order in self.purchase_orders.items()
            },
            line_items={
                key: RecordRef(item.id, owned(item, IngestionEntityType.PURCHASE_ORDER_ITEM))
                for key, item in self.line_items.items()
            },
            milestones={
                key: RecordRef(
                    milestone.id,
                    {
                        "status": milestone.status,
                        "actual_date": milestone.actual_date,
                        "planned_date": self.current_plan_dates.get(milestone.id),
                    },
                )
                for key, milestone in self.milestones.items()
            },
            commitments={
                number: RecordRef(
                    version.id,
                    {
                        "committed_delivery_date": version.committed_delivery_date,
                        "version_no": version.version_no,
                    },
                )
                for number, version in self.commitments.items()
            },
        )


# --- reading and assessing -------------------------------------------------------------


def _file_error(exc: SourceFileError) -> DomainError:
    """A reader failure as an API error: 415, 413 or 422 with the reader's code."""
    error_class = _FILE_ERROR_STATUS.get(exc.code, ValidationFailedError)
    return error_class(exc.message, code=exc.code)


def _parse(upload: UploadedFile, sheet_name: str | None, limits: ImportLimits) -> ParsedSheet:
    try:
        source_format = readers.detect_file_format(upload.filename, upload.content_type)
        if source_format is SourceFormat.CSV:
            return readers.read_csv(upload.data, limits.reader_limits())
        return readers.read_xlsx(upload.data, sheet_name, limits.reader_limits())
    except SourceFileError as exc:
        raise _file_error(exc) from None


def _values(candidates: Iterable[CandidateRow], name: str) -> set[Any]:
    return {row.values[name] for row in candidates if name in row.values}


def load_records(
    session: Session,
    workspace_id: UUID,
    entity_type: IngestionEntityType,
    candidates: Sequence[CandidateRow],
    *,
    for_update: bool = False,
) -> LoadedRecords:
    """Load, in this workspace only, every record the rows of a batch refer to.

    One query per kind of record, whatever the number of rows. With
    ``for_update`` the rows are locked in natural-key order until the
    transaction ends, so two commits that touch the same records cannot
    interleave and always take their locks in the same order.
    """
    loaded = LoadedRecords()
    project_codes = _values(
        candidates, "code" if entity_type is IngestionEntityType.PROJECT else "project_code"
    )
    supplier_codes = _values(candidates, "supplier_code")
    equipment_codes = _values(candidates, "equipment_code")
    po_numbers = _values(candidates, "po_number")

    if project_codes:
        loaded.projects = project_repository.get_by_codes(
            session, workspace_id, project_codes, for_update=for_update
        )
    if supplier_codes:
        loaded.suppliers = supplier_repository.get_by_codes(
            session, workspace_id, supplier_codes, for_update=for_update
        )
    if equipment_codes:
        loaded.equipment = equipment_repository.get_by_codes(
            session, workspace_id, equipment_codes, for_update=for_update
        )
    if po_numbers:
        loaded.purchase_orders = purchase_order_repository.get_by_numbers(
            session, workspace_id, po_numbers, for_update=for_update
        )

    if entity_type is IngestionEntityType.PURCHASE_ORDER_ITEM:
        pairs: dict[tuple[UUID, UUID], tuple[str, str]] = {}
        for row in candidates:
            order = loaded.purchase_orders.get(row.values.get("po_number", ""))
            item = loaded.equipment.get(row.values.get("equipment_code", ""))
            if order is not None and item is not None:
                pairs[(order.id, item.id)] = (order.po_number, item.equipment_code)
        found = purchase_order_repository.get_items_by_pairs(
            session, workspace_id, set(pairs), for_update=for_update
        )
        loaded.line_items = {pairs[key]: line for key, line in found.items()}

    elif entity_type is IngestionEntityType.MILESTONE:
        identities: dict[milestone_repository.MilestoneIdentity, tuple[str, str, int]] = {}
        for row in candidates:
            order = loaded.purchase_orders.get(row.values.get("po_number", ""))
            if (
                order is None
                or "milestone_type" not in row.values
                or "sequence_no" not in row.values
            ):
                continue
            milestone_type = row.values["milestone_type"]
            sequence_no = int(row.values["sequence_no"])
            identities[(order.id, milestone_type, sequence_no)] = (
                order.po_number,
                str(milestone_type),
                sequence_no,
            )
        milestones = milestone_repository.get_by_identities(
            session, workspace_id, set(identities), for_update=for_update
        )
        loaded.milestones = {identities[key]: milestone for key, milestone in milestones.items()}
        plans = milestone_repository.latest_plan_versions(
            session, [milestone.id for milestone in milestones.values()]
        )
        loaded.current_plan_dates = {
            milestone_id: version.planned_date for milestone_id, version in plans.items()
        }

    elif entity_type is IngestionEntityType.SUPPLIER_COMMITMENT:
        by_id = {order.id: number for number, order in loaded.purchase_orders.items()}
        latest = purchase_order_repository.latest_commitments(session, workspace_id, set(by_id))
        loaded.commitments = {by_id[order_id]: version for order_id, version in latest.items()}

    return loaded


def _assess(
    session: Session,
    workspace_id: UUID,
    entity_type: IngestionEntityType,
    mapped: Sequence[MappedRow],
) -> list[RowAssessment]:
    spec = ENTITY_SPECS[entity_type]
    candidates = [candidate(spec, row) for row in mapped]
    loaded = load_records(session, workspace_id, entity_type, candidates)
    return assess_rows(entity_type, candidates, loaded.snapshot())


# --- persistence of a preview ---------------------------------------------------------


def _raw_json(row: MappedRow, extra_cells: Sequence[Any]) -> dict[str, Any]:
    raw: dict[str, Any] = dict(row.raw_data)
    if extra_cells:
        raw[EXTRA_CELLS_KEY] = list(extra_cells)
    return raw


def _fill_row(record: IngestionRow, mapped: MappedRow, assessment: RowAssessment) -> None:
    """Write the verdict of the current assessment onto a ledger row."""
    record.normalized_data = {key: to_json(value) for key, value in mapped.normalized_data.items()}
    record.validation_errors = [issue.as_json() for issue in assessment.errors]
    record.warnings = [issue.as_json() for issue in assessment.warnings]
    record.status = RowStatus.INVALID if assessment.has_errors else RowStatus.VALID
    record.planned_action = assessment.planned_action


def _set_preview_counters(batch: IngestionBatch, assessments: Sequence[RowAssessment]) -> None:
    invalid = sum(1 for assessment in assessments if assessment.has_errors)
    batch.total_rows = len(assessments)
    batch.invalid_rows = invalid
    batch.valid_rows = len(assessments) - invalid


def _issue_entries(
    rows: Sequence[IngestionRow], attribute: str
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Row issues flattened for a response: bounded list, full count, all codes."""
    entries: list[dict[str, Any]] = []
    codes: list[str] = []
    for row in rows:
        for issue in getattr(row, attribute):
            codes.append(issue["code"])
            if len(entries) < ISSUE_LIST_LIMIT:
                entries.append({"row_number": row.row_number, **issue})
    return entries, len(codes), codes


def _preview_result(
    batch: IngestionBatch, rows: Sequence[IngestionRow], *, created: bool, duplicate_file: bool
) -> PreviewResult:
    errors, errors_count, error_codes = _issue_entries(rows, "validation_errors")
    row_warnings, row_warning_count, _ = _issue_entries(rows, "warnings")
    file_warnings = [{"row_number": None, **issue} for issue in batch.file_warnings]
    warnings = (file_warnings + row_warnings)[:ISSUE_LIST_LIMIT]
    warnings_count = len(file_warnings) + row_warning_count
    planned = {action.value: 0 for action in PlannedAction}
    for row in rows:
        if row.planned_action is not None:
            planned[row.planned_action.value] += 1
    return PreviewResult(
        batch=batch,
        created=created,
        duplicate_file=duplicate_file,
        planned_actions=planned,
        errors=errors,
        warnings=warnings,
        errors_count=errors_count,
        warnings_count=warnings_count,
        quality=count_by_dimension(error_codes),
        truncated=errors_count > len(errors) or warnings_count > len(warnings),
    )


def _file_warnings(
    sheet: ParsedSheet, header_warnings: Sequence[ValidationIssue]
) -> list[dict[str, Any]]:
    return [issue.as_json() for issue in (*sheet.warnings, *header_warnings)]


# --- public operations ----------------------------------------------------------------


def preview_import(
    session: Session,
    workspace_id: UUID,
    upload: UploadedFile,
    entity_type: IngestionEntityType,
    sheet_name: str | None = None,
    *,
    limits: ImportLimits,
) -> PreviewResult:
    """Read, map and validate an upload and record the verdict in the ledger.

    No canonical record is created or changed. The same bytes for the same
    entity type resolve to the batch that already holds them: a committed
    batch returns its recorded state, a previewed one is re-validated against
    the database as it is now.
    """
    if not upload.data:
        raise ValidationFailedError("The file is empty.", code="EMPTY_FILE")
    if len(upload.data) > limits.max_upload_bytes:
        megabytes = limits.max_upload_bytes // (1024 * 1024)
        raise FileTooLargeError(f"The file is larger than {megabytes} MB. Split it.")

    # File problems are reported before any database work, and leave no batch.
    sheet = _parse(upload, sheet_name, limits)
    spec = ENTITY_SPECS[entity_type]
    header_mapping = map_headers(spec, sheet)
    mapped = [map_row(spec, header_mapping, row) for row in sheet.rows]
    checksum = hashlib.sha256(upload.data).hexdigest()

    def record() -> PreviewResult:
        return _record_preview(
            session, workspace_id, upload, entity_type, sheet, header_mapping, mapped, checksum
        )

    try:
        return record()
    except IntegrityError as exc:
        if not _is_checksum_collision(exc):
            raise
        # Another request stored the same bytes for this entity type a moment
        # ago. The unique index made this insert wait until that batch was
        # committed, so it exists now: answer with it, as for any repeated upload.
        _log.info("Concurrent upload resolved to the existing batch")
        return record()


def _is_checksum_collision(exc: IntegrityError) -> bool:
    """True when the write was refused because the same file already has a batch."""
    diagnostics = getattr(exc.orig, "diag", None)
    return (
        isinstance(exc.orig, UniqueViolation)
        and getattr(diagnostics, "constraint_name", None) == ACTIVE_CHECKSUM_INDEX
    )


def _record_preview(
    session: Session,
    workspace_id: UUID,
    upload: UploadedFile,
    entity_type: IngestionEntityType,
    sheet: ParsedSheet,
    header_mapping: HeaderMapping,
    mapped: Sequence[MappedRow],
    checksum: str,
) -> PreviewResult:
    """Assess the mapped rows and write the verdict to the ledger, in one transaction."""
    extra_cells = {row.row_number: row.extra_cells for row in sheet.rows}
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        existing = ingestion_repository.get_by_checksum(
            session, workspace_id, entity_type, checksum, for_update=True
        )
        if existing is not None and existing.sheet_name != sheet.sheet_name:
            # One workbook, one entity type, one batch. Another worksheet of the
            # same file is a different table and cannot share that batch.
            raise ConflictError(
                "This workbook was already submitted for this entity type with another "
                "worksheet. Use the existing batch, or save the worksheet as its own file.",
                code="DUPLICATE_FILE",
            )
        if existing is not None and existing.status is not BatchStatus.PREVIEWED:
            # Already committed (or being committed): report it, write nothing.
            rows = ingestion_repository.list_rows(session, existing.id)
            return _preview_result(existing, rows, created=False, duplicate_file=True)

        assessments = _assess(session, workspace_id, entity_type, mapped)

        if existing is not None:
            # Same bytes, not committed yet: refresh the verdict in place.
            by_number = {
                row.row_number: row for row in ingestion_repository.list_rows(session, existing.id)
            }
            for mapped_row, assessment in zip(mapped, assessments, strict=True):
                _fill_row(by_number[mapped_row.row_number], mapped_row, assessment)
            existing.file_warnings = _file_warnings(sheet, header_mapping.warnings)
            _set_preview_counters(existing, assessments)
            session.flush()
            rows = ingestion_repository.list_rows(session, existing.id)
            return _preview_result(existing, rows, created=False, duplicate_file=True)

        batch = IngestionBatch(
            workspace_id=workspace_id,
            entity_type=entity_type,
            original_filename=_display_name(upload.filename),
            file_sha256=checksum,
            source_format=sheet.source_format,
            file_size_bytes=len(upload.data),
            sheet_name=sheet.sheet_name,
            file_warnings=_file_warnings(sheet, header_mapping.warnings),
            status=BatchStatus.UPLOADED,
        )
        ingestion_repository.add_batch(session, batch)

        rows = []
        for mapped_row, assessment in zip(mapped, assessments, strict=True):
            record = IngestionRow(
                batch_id=batch.id,
                row_number=mapped_row.row_number,
                raw_data=_raw_json(mapped_row, extra_cells[mapped_row.row_number]),
            )
            _fill_row(record, mapped_row, assessment)
            rows.append(record)
        ingestion_repository.add_rows(session, rows)

        _set_preview_counters(batch, assessments)
        batch.status = BatchStatus.PREVIEWED
        session.flush()

        _log.info(
            "Import previewed",
            extra={
                "batch_id": str(batch.id),
                "entity_type": entity_type.value,
                "total_rows": batch.total_rows,
                "valid_rows": batch.valid_rows,
                "invalid_rows": batch.invalid_rows,
            },
        )
        return _preview_result(batch, rows, created=True, duplicate_file=False)


def _display_name(filename: str) -> str:
    """The file name as display metadata: last path segment, printable, bounded.

    Never a path, and never a control character: the name comes from the
    client and is only ever shown, so anything that is not printable is dropped.
    """
    segment = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in segment if character.isprintable()).strip()
    return (name or "upload")[: field_limits.FILENAME_MAX]


def get_batch(
    session: Session,
    workspace_id: UUID,
    batch_id: UUID,
    *,
    limit: int,
    offset: int,
    status: RowStatus | None = None,
) -> BatchDetail:
    """A batch with one page of its source rows and their outcomes."""
    workspace_service.require_active_workspace(session, workspace_id)
    batch = ingestion_repository.get_by_id(session, workspace_id, batch_id)
    if batch is None:
        raise NotFoundError("The ingestion batch was not found.")
    rows, total = ingestion_repository.rows_page(
        session, batch.id, limit=limit, offset=offset, status=status
    )
    return BatchDetail(batch=batch, rows=Page(items=rows, total=total, limit=limit, offset=offset))


def list_batches(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: BatchStatus | None = None,
    entity_type: IngestionEntityType | None = None,
) -> Page[IngestionBatch]:
    workspace_service.require_active_workspace(session, workspace_id)
    items, total = ingestion_repository.list_for_workspace(
        session, workspace_id, limit=limit, offset=offset, status=status, entity_type=entity_type
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


def list_sources(
    session: Session,
    workspace_id: UUID,
    entity_type: str,
    entity_id: UUID,
    *,
    limit: int,
    offset: int,
) -> Page[SourceRow]:
    """The source rows behind one canonical record: which file, which row, what happened."""
    workspace_service.require_active_workspace(session, workspace_id)
    pairs, total = ingestion_repository.sources_for_entity(
        session, workspace_id, entity_type, entity_id, limit=limit, offset=offset
    )
    return Page(
        items=[SourceRow(row=row, batch=batch) for row, batch in pairs],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- commit ---------------------------------------------------------------------------


def _source_label(batch: IngestionBatch) -> str:
    """Who recorded a version that came from this batch."""
    return f"import:{batch.original_filename}"[: field_limits.ACTOR_MAX]


def _apply_row(
    session: Session,
    workspace_id: UUID,
    batch: IngestionBatch,
    row: IngestionRow,
    assessment: RowAssessment,
    loaded: LoadedRecords,
) -> Applied:
    """Hand one validated row to the service that owns its entity."""
    values = assessment.resolved
    entity_type = batch.entity_type

    if entity_type is IngestionEntityType.PROJECT:
        return project_service.apply_source_record(
            session, workspace_id, existing=loaded.projects.get(values["code"]), values=values
        )
    if entity_type is IngestionEntityType.SUPPLIER:
        return supplier_service.apply_source_record(
            session,
            workspace_id,
            existing=loaded.suppliers.get(values["supplier_code"]),
            values=values,
        )
    if entity_type is IngestionEntityType.EQUIPMENT:
        return equipment_service.apply_source_record(
            session,
            workspace_id,
            existing=loaded.equipment.get(values["equipment_code"]),
            values=values,
        )
    if entity_type is IngestionEntityType.PURCHASE_ORDER:
        return purchase_order_service.apply_source_record(
            session,
            workspace_id,
            existing=loaded.purchase_orders.get(values["po_number"]),
            values=values,
        )

    # The remaining kinds hang off a purchase order that validation resolved.
    purchase_order = loaded.purchase_orders[values["po_number"]]
    if entity_type is IngestionEntityType.PURCHASE_ORDER_ITEM:
        return purchase_order_service.apply_item_record(
            session,
            existing=loaded.line_items.get((values["po_number"], values["equipment_code"])),
            purchase_order=purchase_order,
            equipment=loaded.equipment[values["equipment_code"]],
            values=values,
        )
    if entity_type is IngestionEntityType.MILESTONE:
        key = (values["po_number"], str(values["milestone_type"]), int(values["sequence_no"]))
        return milestone_service.apply_source_record(
            session,
            existing=loaded.milestones.get(key),
            purchase_order=purchase_order,
            values=values,
            recorded_by=_source_label(batch),
            source_row_id=row.id,
        )
    return purchase_order_service.apply_commitment_record(
        session,
        purchase_order=purchase_order,
        values=values,
        recorded_by=_source_label(batch),
        source_row_id=row.id,
    )


# A milestone row may also append a plan version; that is counted under this key.
PLAN_VERSION_KEY = "milestone_plan_version"

_OUTCOME_KEY: Mapping[RowOutcome, str] = {
    RowOutcome.CREATED: "created",
    RowOutcome.UPDATED: "updated",
    RowOutcome.UNCHANGED: "unchanged",
}


def _apply_all(
    session: Session,
    workspace_id: UUID,
    batch: IngestionBatch,
    rows: Sequence[IngestionRow],
    assessments: Sequence[RowAssessment],
    loaded: LoadedRecords,
) -> dict[str, dict[str, int]]:
    """Apply every eligible row, link it to its record and tally what happened."""
    entities: dict[str, dict[str, int]] = {}
    applied_by_row: dict[int, Applied] = {}

    def tally(kind: str, key: str, amount: int = 1) -> None:
        counts = entities.setdefault(kind, {"created": 0, "updated": 0, "unchanged": 0})
        counts[key] += amount

    for row, assessment in zip(rows, assessments, strict=True):
        if assessment.duplicate_of is not None:
            # An exact repeat of an earlier row: nothing to apply, same record.
            first = applied_by_row[assessment.duplicate_of]
            row.status = RowStatus.SKIPPED
            row.outcome = RowOutcome.DUPLICATE_ROW
            row.canonical_entity_type = first.entity_type.value
            row.canonical_entity_id = first.entity_id
            continue

        applied = _apply_row(session, workspace_id, batch, row, assessment, loaded)
        applied_by_row[row.row_number] = applied
        row.canonical_entity_type = applied.entity_type.value
        row.canonical_entity_id = applied.entity_id
        row.outcome = applied.outcome
        row.status = (
            RowStatus.SKIPPED if applied.outcome is RowOutcome.UNCHANGED else RowStatus.COMMITTED
        )
        tally(applied.entity_type.value, _OUTCOME_KEY[applied.outcome])
        if batch.entity_type is IngestionEntityType.MILESTONE and applied.versions_created:
            tally(PLAN_VERSION_KEY, "created", applied.versions_created)
    return entities


def _record_failure(
    session: Session,
    workspace_id: UUID,
    batch_id: UUID,
    failure_code: str,
    failures: Sequence[RowAssessment],
) -> None:
    """After a rolled-back commit, record why, in a transaction of its own.

    The canonical writes are already gone. This marks the batch FAILED, the
    rows that were rejected, and the rows that were valid but went down with
    the batch. If the batch was finished by someone else in the meantime, it
    is left alone.
    """
    try:
        with transaction(session):
            batch = ingestion_repository.lock_for_commit(session, workspace_id, batch_id)
            if batch is None or batch.status is not BatchStatus.PREVIEWED:
                return
            rejected = {assessment.row_number: assessment for assessment in failures}
            rows = ingestion_repository.list_rows(session, batch.id, [RowStatus.VALID])
            for row in rows:
                assessment = rejected.get(row.row_number)
                if assessment is None:
                    row.status = RowStatus.SKIPPED
                    row.outcome = RowOutcome.ROLLED_BACK
                    continue
                row.status = RowStatus.FAILED
                row.outcome = RowOutcome.REJECTED
                row.validation_errors = [
                    *row.validation_errors,
                    *({**issue.as_json(), "stage": COMMIT_STAGE} for issue in assessment.errors),
                ]
            batch.status = BatchStatus.FAILED
            batch.failure_code = failure_code
            batch.failed_rows = len(rejected)
            batch.skipped_rows = len(rows) - len(rejected)
            batch.committed_rows = 0
    except SQLAlchemyError:
        # The database is not answering. The batch stays PREVIEWED, which is
        # true: nothing was committed, and it can be committed again.
        _log.exception("Could not record the failure of batch %s", batch_id)
        session.rollback()


def _commit_conflict(failures: Sequence[RowAssessment]) -> ConflictError:
    details = [
        ErrorDetail(
            code=issue.code,
            message=issue.message,
            row_number=assessment.row_number,
            column=issue.column,
        )
        for assessment in failures
        for issue in assessment.errors
    ]
    return ConflictError(
        "Rows that were valid at preview are no longer valid. Nothing was committed and the "
        "batch has failed. Fix the cause and upload the file again.",
        code="COMMIT_CONFLICT",
        details=details[:COMMIT_FAILURE_DETAIL_LIMIT],
    )


def commit_import(session: Session, workspace_id: UUID, batch_id: UUID) -> CommitResult:
    """Apply the valid rows of a previewed batch to the canonical records, all or none.

    * The batch row is locked first; a concurrent request for the same batch
      waits and then finds it committed.
    * Every valid row is assessed again against the records as they are now,
      which are locked while it happens. A row that no longer holds fails the
      whole batch: nothing is written and the batch becomes FAILED.
    * Rows, links, counters and the COMMITTED state are written in the same
      transaction as the canonical records.
    """
    try:
        with transaction(session):
            workspace_service.require_active_workspace(session, workspace_id)
            batch = ingestion_repository.lock_for_commit(session, workspace_id, batch_id)
            if batch is None:
                raise NotFoundError("The ingestion batch was not found.")
            if batch.status is BatchStatus.COMMITTED:
                return CommitResult(batch=batch, replayed=True)
            if batch.status is not BatchStatus.PREVIEWED:
                raise InvalidStateError(
                    f"The batch is {batch.status.value} and cannot be committed. "
                    "Preview a new or corrected file.",
                    code="BATCH_NOT_COMMITTABLE",
                )

            rows = ingestion_repository.list_rows(session, batch.id, [RowStatus.VALID])
            if not rows:
                raise InvalidStateError(
                    "The batch has no valid row to commit. Correct the file or its "
                    "dependencies and preview it again.",
                    code="BATCH_NOT_COMMITTABLE",
                )
            batch.status = BatchStatus.COMMITTING
            session.flush()

            spec = ENTITY_SPECS[batch.entity_type]
            candidates = [
                CandidateRow(row.row_number, decode_normalized(spec, row.normalized_data))
                for row in rows
            ]
            # What preview saw may have changed. The records are read again,
            # locked, and every row is judged against them once more.
            loaded = load_records(
                session, workspace_id, batch.entity_type, candidates, for_update=True
            )
            assessments = assess_rows(batch.entity_type, candidates, loaded.snapshot())
            failures = [assessment for assessment in assessments if assessment.has_errors]
            if failures:
                raise _CommitRejected(failures)

            entities = _apply_all(session, workspace_id, batch, rows, assessments, loaded)

            batch.committed_rows = sum(1 for row in rows if row.status is RowStatus.COMMITTED)
            batch.skipped_rows = sum(1 for row in rows if row.status is RowStatus.SKIPPED)
            batch.failed_rows = 0
            batch.commit_summary = {"entities": entities}
            batch.committed_at = utcnow()
            batch.status = BatchStatus.COMMITTED
            session.flush()

            _log.info(
                "Import committed",
                extra={
                    "batch_id": str(batch.id),
                    "entity_type": batch.entity_type.value,
                    "committed_rows": batch.committed_rows,
                    "skipped_rows": batch.skipped_rows,
                },
            )
            return CommitResult(batch=batch, replayed=False)
    except _CommitRejected as rejected:
        _record_failure(session, workspace_id, batch_id, "COMMIT_CONFLICT", rejected.failures)
        raise _commit_conflict(rejected.failures) from None
    except DomainError:
        # Not found, not committable, workspace not available: nothing was attempted.
        raise
    except IntegrityError:
        # A constraint refused a write, for example because another import
        # created the same record a moment earlier. Everything was rolled back.
        _record_failure(session, workspace_id, batch_id, "COMMIT_CONFLICT", [])
        raise ConflictError(
            "A database constraint rejected the batch. Nothing was committed and the batch "
            "has failed. Upload the file again.",
            code="COMMIT_CONFLICT",
        ) from None
    except OperationalError as exc:
        if not ended_to_resolve_a_conflict(exc):
            # The database went away. Recorded if it can be; otherwise the batch
            # stays PREVIEWED, which is true: nothing was committed.
            _record_failure(session, workspace_id, batch_id, "COMMIT_FAILED", [])
            raise
        # A deadlock with another writer: PostgreSQL undid this commit to let
        # the other one through. Nothing was written and what preview found
        # still stands, so the batch stays PREVIEWED and can be committed again.
        _log.warning(
            "Commit rolled back by PostgreSQL to resolve a conflict",
            extra={"batch_id": str(batch_id), "error_type": type(exc.orig).__name__},
        )
        raise ConflictError(
            "The commit collided with another change to the same records and was rolled "
            "back. Nothing was committed and the batch is unchanged. Send the commit again.",
            code="CONFLICT",
        ) from None
    except DataError as exc:
        # The database could not store a value that validation had accepted.
        # Everything was rolled back. Validation is meant to make this
        # impossible, so it is logged as an error; the caller is told what to do.
        _log.error(
            "The database refused a value of a validated batch",
            extra={"batch_id": str(batch_id), "error_type": type(exc.orig).__name__},
        )
        _record_failure(session, workspace_id, batch_id, "COMMIT_FAILED", [])
        raise ValidationFailedError(
            "The database could not store a value of this batch. Nothing was committed and "
            "the batch has failed. Correct the file and upload it again.",
            code="COMMIT_FAILED",
        ) from None
    except Exception:
        _record_failure(session, workspace_id, batch_id, "COMMIT_FAILED", [])
        raise
