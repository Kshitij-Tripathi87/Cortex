"""Value objects passed between the ingestion stages.

Plain immutable data: no ORM entity, no session, no HTTP type. A parsed file
becomes a ParsedSheet, each of its rows a MappedRow, and each of those a
RowAssessment once it has been checked against a ReferenceSnapshot.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.models.enums import PlannedAction, SourceFormat

# What a source cell can hold once it is JSON-safe.
JSONScalar = str | int | float | bool | None


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class SourceFileError(Exception):
    """The upload cannot be read as a bounded table. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ReaderLimits:
    """Bounds enforced while a file is read."""

    max_rows: int
    max_columns: int
    max_cell_chars: int
    max_uncompressed_bytes: int
    # openpyxl materializes shared strings even when the selected sheet does not use them.
    max_shared_string_items: int = 250_000
    max_shared_string_chars: int = 8_000_000


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding about a row or a file. Never carries a source-cell value."""

    code: str
    message: str
    severity: Severity
    row_number: int | None = None
    column: str | None = None

    def as_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.column is not None:
            body["column"] = self.column
        return body


def error(code: str, message: str, *, column: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=Severity.ERROR, column=column)


def warning(code: str, message: str, *, column: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=Severity.WARNING, column=column)


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One data row of the source, under the original headers."""

    row_number: int  # physical row in the file
    raw_data: Mapping[str, JSONScalar]
    # Values found beyond the last header: they belong to no column.
    extra_cells: tuple[JSONScalar, ...] = ()
    # Headers of spreadsheet cells that hold a formula without a stored result.
    formula_cells: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedSheet:
    """A CSV file or one worksheet, safely parsed and not yet interpreted."""

    source_format: SourceFormat
    sheet_name: str | None
    header_row_number: int
    headers_original: tuple[str, ...]
    headers_normalized: tuple[str, ...]
    rows: tuple[ParsedRow, ...]
    warnings: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class MappedRow:
    """A source row after header mapping and value normalization.

    ``raw_data`` is the untouched source; ``normalized_data`` is a new
    representation with typed values (date, Decimal, int, enum, str).
    """

    row_number: int
    raw_data: Mapping[str, JSONScalar]
    normalized_data: Mapping[str, Any]
    unknown_columns: tuple[str, ...]
    mapping_errors: tuple[ValidationIssue, ...]
    mapping_warnings: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class RecordRef:
    """A canonical record as the validation needs to see it: id plus current values."""

    id: UUID
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    """The canonical records a batch refers to, read in one workspace at one moment.

    Keys are natural keys. A record that is absent here does not exist as far
    as validation is concerned, which is also true of records in other
    workspaces: the snapshot is always built by workspace-scoped queries.
    """

    projects: Mapping[str, RecordRef] = field(default_factory=dict)
    suppliers: Mapping[str, RecordRef] = field(default_factory=dict)
    equipment: Mapping[str, RecordRef] = field(default_factory=dict)
    purchase_orders: Mapping[str, RecordRef] = field(default_factory=dict)
    # (po_number, equipment_code)
    line_items: Mapping[tuple[str, str], RecordRef] = field(default_factory=dict)
    # (po_number, milestone type, sequence number)
    milestones: Mapping[tuple[str, str, int], RecordRef] = field(default_factory=dict)
    # po_number -> current commitment version
    commitments: Mapping[str, RecordRef] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """A row entering the batch-level assessment."""

    row_number: int
    values: Mapping[str, Any]
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is Severity.ERROR for issue in self.issues)


@dataclass(frozen=True, slots=True)
class RowAssessment:
    """The verdict on one row against the batch and the reference snapshot."""

    row_number: int
    issues: tuple[ValidationIssue, ...]
    # None when the row has errors.
    planned_action: PlannedAction | None
    # Row number of the earlier identical row this one repeats, if any.
    duplicate_of: int | None = None
    # The values a commit applies: normalized fields plus resolved record ids.
    resolved: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)
