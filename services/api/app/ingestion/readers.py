"""Safe, bounded readers for CSV and XLSX uploads.

The readers turn bytes into a ParsedSheet and nothing more. They do not
interpret a value, execute a formula or a macro, write to disk, or use the
file name as a path. Every size is capped before or while the content is
read. A file that cannot be read as a table raises SourceFileError.

A workbook is XML inside a ZIP archive, and both can ask for far more work
than their size suggests. The archive is bounded by the sizes it declares.
The XML is weighed before the workbook is opened (see workbook_scan) and is
parsed by defusedxml, which refuses a document that declares an entity: the
standard parser would fill such entities in, and a few kilobytes of upload
become gigabytes of cell text.

What a worksheet says about itself is not believed. The range it claims to
use is discarded, and rows or cells that are not numbered in ascending order
make the workbook malformed: the library would otherwise read a part of the
worksheet and say nothing about the rest.
"""

import csv
import io
import math
import posixpath
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped]
from openpyxl import DEFUSEDXML
from openpyxl.reader.excel import ExcelReader
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from app.ingestion.contracts import (
    JSONScalar,
    ParsedRow,
    ParsedSheet,
    ReaderLimits,
    SourceFileError,
    ValidationIssue,
    warning,
)
from app.ingestion.normalization import BYTE_ORDER_MARK, is_blank, normalize_header
from app.ingestion.workbook_scan import content_budget, probe_sheet_has_data, scan_parts
from app.models.enums import SourceFormat
from app.models.limits import SHEET_NAME_MAX

if not DEFUSEDXML:
    # openpyxl parses with defusedxml when it can import that package and
    # OPENPYXL_DEFUSEDXML does not say otherwise, and silently falls back to
    # the standard library when it cannot. This module does not read workbooks
    # with the fallback, so it does not load at all.
    raise ImportError(
        "openpyxl is not using defusedxml, so a workbook could make this service expand "
        "XML entities without limit. Install the locked dependencies (uv sync --locked) "
        "and do not set OPENPYXL_DEFUSEDXML."
    )

CSV_MEDIA_TYPES = frozenset(
    {
        "text/csv",
        "application/csv",
        "text/plain",
        # What some browsers send for a .csv file.
        "application/vnd.ms-excel",
    }
)
XLSX_MEDIA_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/x-zip-compressed",
    }
)
# Says nothing about the content; the extension and the content checks decide.
GENERIC_MEDIA_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})

ZIP_SIGNATURE = b"PK\x03\x04"
WORKBOOK_PART = "xl/workbook.xml"
WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"
CONTENT_TYPES_PART = "[Content_Types].xml"
MAX_ARCHIVE_ENTRIES = 5_000
MAX_METADATA_PART_BYTES = 4 * 1024 * 1024

# A worksheet may carry formatted but empty rows below its data. This many are
# scanned beyond the row limit before the sheet is refused.
BLANK_ROW_ALLOWANCE = 1_000
# Rows inspected to decide whether a worksheet holds data at all.
SHEET_PROBE_ROWS = 50
# Worksheet names quoted in an error message: this many, each cut to this length.
SHEET_NAMES_SHOWN = 10
SHEET_NAME_SHOWN_CHARS = 40

# A parsed record before headers are applied: row number, cells, formula flags.
_Record = tuple[int, list[JSONScalar], list[bool]]


def detect_file_format(filename: str, content_type: str | None) -> SourceFormat:
    """Decide CSV or XLSX from the extension and reject a contradicting media type.

    The name is inspected as text only. Whether the bytes really are what the
    name claims is checked by the reader.
    """
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension == ".csv":
        source_format, allowed = SourceFormat.CSV, CSV_MEDIA_TYPES
    elif extension == ".xlsx":
        source_format, allowed = SourceFormat.XLSX, XLSX_MEDIA_TYPES
    else:
        raise SourceFileError(
            "UNSUPPORTED_FILE", "Only .csv and .xlsx files are accepted. Save the file as one."
        )
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type and media_type not in GENERIC_MEDIA_TYPES and media_type not in allowed:
        raise SourceFileError(
            "UNSUPPORTED_FILE", "The media type of the upload does not match its file extension."
        )
    return source_format


# --- CSV ------------------------------------------------------------------------------


def read_csv(file_bytes: bytes, limits: ReaderLimits) -> ParsedSheet:
    """Parse a UTF-8, comma-separated file. Cell content is text and stays text."""
    if file_bytes.startswith(ZIP_SIGNATURE) or b"\x00" in file_bytes:
        raise SourceFileError("UNSUPPORTED_FILE", "The file is not a text CSV file.")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SourceFileError(
            "INVALID_ENCODING", "The file is not valid UTF-8. Save it as CSV UTF-8."
        ) from None
    if not text.strip():
        raise SourceFileError("EMPTY_FILE", "The file is empty.")
    return _build_sheet(_csv_records(text, limits), SourceFormat.CSV, None, limits)


def _csv_records(text: str, limits: ReaderLimits) -> Iterator[_Record]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    previous_line = 0
    try:
        for cells in reader:
            # A quoted cell may span lines; the row is numbered by its first line.
            row_number = previous_line + 1
            previous_line = reader.line_num
            yield row_number, list(cells), [False] * len(cells)
    except csv.Error:
        raise SourceFileError(
            "MALFORMED_FILE", "The file is not well-formed CSV (check quotes and line breaks)."
        ) from None


# --- XLSX -----------------------------------------------------------------------------


def read_xlsx(file_bytes: bytes, sheet_name: str | None, limits: ReaderLimits) -> ParsedSheet:
    """Read one selected worksheet after bounded package and worksheet scans.

    Workbook-global XML is weighed first. When no name is supplied, a
    bounded XML probe identifies candidate visible worksheets without asking
    openpyxl to parse their dimensions. Only the selected worksheet is then
    fully checked and materialised. Formula coordinates are collected during
    that scan, so openpyxl needs only one read-only workbook load.
    """
    worksheets = _check_workbook_container(file_bytes, limits)
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            selected = _select_sheet(archive, worksheets, sheet_name, limits)
            scanned = scan_parts(
                archive,
                [selected.path],
                cell_elements=content_budget(limits, _scanned_rows(limits)),
                max_rows=_scanned_rows(limits),
            )
            formula_cells = scanned.get(selected.path, frozenset())
    except SourceFileError:
        raise
    except Exception:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None

    try:
        workbook = _open_workbook(file_bytes, data_only=True, selected_path=selected.path)
        try:
            records = _xlsx_records(workbook[selected.name], formula_cells, limits)
            return _build_sheet(records, SourceFormat.XLSX, selected.name, limits)
        finally:
            workbook.close()
    except SourceFileError:
        raise
    except Exception:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None


class _BoundedReadOnlyWorksheet(ReadOnlyWorksheet):
    """Read-only worksheet that never trusts or scans declared dimensions."""

    def _get_size(self) -> None:
        # The selected sheet has been scanned separately; iteration is explicitly bounded.
        self._min_column = self._min_row = self._max_column = self._max_row = None


class _SelectedSheetReader(ExcelReader):
    """Openpyxl reader that constructs only the worksheet selected by our scan."""

    def __init__(self, filename: Any, *, selected_path: str, **kwargs: Any) -> None:
        super().__init__(filename, **kwargs)
        self._selected_path = selected_path

    def read_worksheets(self) -> None:
        for sheet, relationship in self.parser.find_sheets():
            if relationship.target != self._selected_path or "chartsheet" in relationship.Type:
                continue
            if relationship.target not in self.valid_files:
                raise ValueError("The selected worksheet part is missing.")
            worksheet = _BoundedReadOnlyWorksheet(
                self.wb, sheet.name, relationship.target, self.shared_strings
            )
            worksheet.sheet_state = sheet.state
            self.wb._sheets.append(worksheet)


def _open_workbook(file_bytes: bytes, *, data_only: bool, selected_path: str) -> Any:
    """Open one pre-validated worksheet; external workbook links are not read."""
    reader = _SelectedSheetReader(
        io.BytesIO(file_bytes),
        selected_path=selected_path,
        read_only=True,
        data_only=data_only,
        keep_links=False,
    )
    reader.read()
    if not reader.wb.worksheets:
        reader.wb.close()
        raise ValueError("The selected worksheet was not found.")
    return reader.wb


def _scanned_rows(limits: ReaderLimits) -> int:
    """Rows of a worksheet that are looked at before it is refused as too long."""
    return limits.max_rows + BLANK_ROW_ALLOWANCE + 1


@dataclass(frozen=True, slots=True)
class _WorksheetPart:
    name: str
    path: str
    state: str


def _worksheet_parts(
    archive: zipfile.ZipFile, names: set[str]
) -> tuple[_WorksheetPart, ...]:
    """Resolve worksheet names to safe package-relative XML paths."""
    workbook_info = archive.getinfo(WORKBOOK_PART)
    relationships_info = archive.getinfo(WORKBOOK_RELS_PART)
    if max(workbook_info.file_size, relationships_info.file_size) > MAX_METADATA_PART_BYTES:
        raise SourceFileError("FILE_TOO_LARGE", "Workbook metadata is too large to read safely.")
    workbook_root = SafeET.fromstring(archive.read(WORKBOOK_PART))
    relationships_root = SafeET.fromstring(archive.read(WORKBOOK_RELS_PART))
    by_id: dict[str, Any] = {}
    for relation in relationships_root.iter():
        if relation.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        identifier = relation.attrib.get("Id")
        if not identifier or identifier in by_id:
            raise SourceFileError(
                "MALFORMED_FILE", "The workbook relationships are invalid. Save it again as .xlsx."
            )
        by_id[identifier] = relation
    relationship_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    sheets: list[_WorksheetPart] = []
    seen_paths: set[str] = set()
    for element in workbook_root.iter():
        if element.tag.rsplit("}", 1)[-1] != "sheet":
            continue
        relation = by_id.get(element.attrib.get(relationship_id, ""))
        if relation is None:
            raise SourceFileError(
                "MALFORMED_FILE", "A worksheet relationship is missing. Save it again as .xlsx."
            )
        if not relation.attrib.get("Type", "").endswith("/worksheet"):
            continue
        target = relation.attrib.get("Target", "")
        if not target or relation.attrib.get("TargetMode") == "External" or "\\" in target:
            raise SourceFileError(
                "MALFORMED_FILE", "A worksheet path is invalid. Save the workbook again as .xlsx."
            )
        path = (
            posixpath.normpath(target.lstrip("/"))
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        if path in {".", ".."} or path.startswith("../") or path not in names:
            raise SourceFileError(
                "MALFORMED_FILE", "A worksheet path is outside the workbook package."
            )
        if path in seen_paths:
            raise SourceFileError(
                "MALFORMED_FILE", "Two worksheet names refer to the same package part."
            )
        seen_paths.add(path)
        sheets.append(
            _WorksheetPart(
                name=element.attrib.get("name", ""),
                path=path,
                state=element.attrib.get("state", "visible"),
            )
        )
    return tuple(sheets)


def _check_workbook_container(
    file_bytes: bytes, limits: ReaderLimits
) -> tuple[_WorksheetPart, ...]:
    """Check ZIP bounds and scan package-global parts, leaving sheets for selection."""
    not_a_workbook = SourceFileError(
        "UNSUPPORTED_FILE", "The file is not an .xlsx workbook. Save it as .xlsx or .csv."
    )
    if not file_bytes.startswith(ZIP_SIGNATURE):
        raise not_a_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            names_in_order = [entry.filename for entry in entries]
            names = set(names_in_order)
            required = {WORKBOOK_PART, WORKBOOK_RELS_PART, CONTENT_TYPES_PART}
            if not required.issubset(names):
                raise not_a_workbook
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise SourceFileError("MALFORMED_FILE", "The workbook has too many parts.")
            if len(names_in_order) != len(names):
                raise SourceFileError("MALFORMED_FILE", "The workbook repeats a ZIP package part.")
            if sum(entry.file_size for entry in entries) > limits.max_uncompressed_bytes:
                raise SourceFileError(
                    "FILE_TOO_LARGE", "The workbook is too large once uncompressed."
                )
            for metadata_name in required:
                if archive.getinfo(metadata_name).file_size > MAX_METADATA_PART_BYTES:
                    raise SourceFileError(
                        "FILE_TOO_LARGE", "Workbook metadata is too large to read safely."
                    )
            content_types = archive.read(CONTENT_TYPES_PART).decode("utf-8", errors="replace")
            worksheets = _worksheet_parts(archive, names)
            worksheet_paths = {sheet.path for sheet in worksheets}
            package_parts = [name for name in names_in_order if name not in worksheet_paths]
            scan_parts(
                archive,
                package_parts,
                cell_elements=content_budget(limits, _scanned_rows(limits)),
            )
    except SourceFileError:
        raise
    except zipfile.BadZipFile:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None
    except Exception:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None
    has_macros = any(name.lower().endswith("vbaproject.bin") for name in names)
    if has_macros or "macroEnabled" in content_types or "binary.macro" in content_types.lower():
        raise SourceFileError(
            "UNSUPPORTED_FILE",
            "Macro-enabled and binary workbooks are not accepted. Save the file as .xlsx.",
        )
    return worksheets


def _select_sheet(
    archive: zipfile.ZipFile,
    worksheets: tuple[_WorksheetPart, ...],
    requested: str | None,
    limits: ReaderLimits,
) -> _WorksheetPart:
    """Choose a named worksheet or the only visible worksheet with data in its first fifty rows."""
    available = [sheet.name for sheet in worksheets]
    if len(set(available)) != len(available):
        raise SourceFileError(
            "MALFORMED_FILE", "Two worksheets of the workbook have the same name."
        )
    if requested is not None:
        selected_name = _named_sheet(available, requested)
        selected = next(sheet for sheet in worksheets if sheet.name == selected_name)
    else:
        candidates: list[_WorksheetPart] = []
        probe_errors: list[SourceFileError] = []
        for sheet in worksheets:
            if sheet.state != "visible":
                continue
            try:
                has_data = probe_sheet_has_data(
                    archive,
                    sheet.path,
                    max_rows=SHEET_PROBE_ROWS,
                    max_columns=limits.max_columns + 1,
                )
            except SourceFileError as exc:
                probe_errors.append(exc)
                continue
            if has_data:
                candidates.append(sheet)
        if not candidates:
            if probe_errors:
                raise probe_errors[0]
            raise SourceFileError("EMPTY_FILE", "The workbook has no worksheet with data.")
        if len(candidates) > 1:
            raise SourceFileError(
                "AMBIGUOUS_WORKSHEET",
                "Several worksheets hold data. Name the one to import with sheet_name: "
                + _names_for_message([sheet.name for sheet in candidates]),
            )
        selected = candidates[0]
    if len(selected.name) > SHEET_NAME_MAX:
        raise SourceFileError(
            "MALFORMED_FILE",
            f"The name of the worksheet is longer than {SHEET_NAME_MAX} characters. Rename it.",
        )
    return selected


def _named_sheet(available: list[str], requested: str) -> str:
    """The worksheet with exactly this name, or the only one equal to it once trimmed."""
    if requested in available:
        return requested
    wanted = requested.strip()
    matches = [name for name in available if name.strip() == wanted]
    if len(matches) == 1:
        return matches[0]
    raise SourceFileError(
        "WORKSHEET_NOT_FOUND",
        "The workbook has no worksheet with that name. Available: " + _names_for_message(available),
    )


def _names_for_message(names: list[str]) -> str:
    """A few worksheet names in a form that is safe and short enough to show."""
    shown = []
    for name in names[:SHEET_NAMES_SHOWN]:
        printable = "".join(character for character in name if character.isprintable())
        if len(printable) > SHEET_NAME_SHOWN_CHARS:
            printable = printable[:SHEET_NAME_SHOWN_CHARS] + "..."
        shown.append(printable)
    text = ", ".join(shown)
    if len(names) > SHEET_NAMES_SHOWN:
        text += f" and {len(names) - SHEET_NAMES_SHOWN} more"
    return text



def _xlsx_records(
    values_sheet: Any, formula_cells: frozenset[tuple[int, int]], limits: ReaderLimits
) -> Iterator[_Record]:
    # The selected XML part was checked against _scanned_rows() before this
    # iterator starts. With no max_row, openpyxl streams only physical rows
    # (and row gaps) until EOF instead of manufacturing max_scanned empty rows.
    values_sheet.reset_dimensions()
    rows = values_sheet.iter_rows(max_col=limits.max_columns + 1)
    for position, value_row in enumerate(rows, start=1):
        row_number = next(
            (cell.row for cell in value_row if getattr(cell, "row", None) is not None), position
        )
        cells: list[JSONScalar] = []
        formula_flags: list[bool] = []
        for value_cell in value_row:
            coordinate = (
                getattr(value_cell, "row", 0),
                getattr(value_cell, "column", 0),
            )
            cells.append(_json_cell(value_cell.value))
            formula_flags.append(coordinate in formula_cells)
        yield row_number, cells, formula_flags
def _json_cell(value: Any) -> JSONScalar:
    """A spreadsheet value as a JSON-safe scalar. Dates become ISO text."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (Decimal, timedelta)):
        return str(value)
    return str(value)


# --- shared table assembly ------------------------------------------------------------


def _build_sheet(
    records: Iterable[_Record],
    source_format: SourceFormat,
    sheet_name: str | None,
    limits: ReaderLimits,
) -> ParsedSheet:
    """Find the header, apply it to the data rows and enforce the limits."""
    header: tuple[int, list[str]] | None = None
    data: list[_Record] = []
    blank_rows = 0  # blank rows between data rows; trailing ones are not worth a warning
    pending_blank_rows = 0
    cached_formulas = 0

    for row_number, cells, formula_flags in records:
        for cell in cells:
            if isinstance(cell, str) and len(cell) > limits.max_cell_chars:
                raise SourceFileError(
                    "CELL_TOO_LONG",
                    f"Row {row_number} has a cell longer than {limits.max_cell_chars} characters.",
                )
        if all(is_blank(cell) for cell in cells) and not any(formula_flags):
            if header is not None:
                pending_blank_rows += 1
            continue
        if header is None:
            header = (row_number, [_header_text(cell) for cell in cells])
            continue
        if len(data) >= limits.max_rows:
            raise SourceFileError(
                "ROW_LIMIT_EXCEEDED",
                f"The file has more than {limits.max_rows} data rows. Split the file.",
            )
        blank_rows += pending_blank_rows
        pending_blank_rows = 0
        data.append((row_number, cells, formula_flags))

    if header is None:
        raise SourceFileError("EMPTY_FILE", "The file is empty.")
    header_row_number, header_cells = header
    if not data:
        raise SourceFileError("EMPTY_FILE", "The file has a header row and no data rows.")

    columns = _usable_columns(header_cells, data, header_row_number)
    if len(columns) > limits.max_columns:
        raise SourceFileError(
            "COLUMN_LIMIT_EXCEEDED",
            f"The file has more than {limits.max_columns} columns.",
        )
    originals = tuple(header_cells[index] for index in columns)
    normalized = tuple(normalize_header(name) for name in originals)
    _reject_duplicate_headers(originals, normalized)

    rows: list[ParsedRow] = []
    width = len(header_cells)
    for row_number, cells, formula_flags in data:
        raw: dict[str, JSONScalar] = {}
        formula_cells: list[str] = []
        for name, index in zip(originals, columns, strict=True):
            value = cells[index] if index < len(cells) else None
            is_formula = index < len(formula_flags) and formula_flags[index]
            if is_formula and is_blank(value):
                formula_cells.append(name)
                value = None
            elif is_formula:
                cached_formulas += 1
            raw[name] = value
        extra = tuple(cell for cell in cells[width:] if not is_blank(cell))
        rows.append(ParsedRow(row_number, raw, extra, tuple(formula_cells)))

    warnings: list[ValidationIssue] = []
    if blank_rows:
        warnings.append(
            warning(
                "BLANK_ROWS_SKIPPED",
                f"{blank_rows} blank row(s) were skipped; row numbers refer to the source file.",
            )
        )
    if cached_formulas:
        warnings.append(
            warning(
                "FORMULA_CACHED_VALUE_USED",
                f"{cached_formulas} cell(s) hold a formula; the value stored in the workbook "
                "was read and the formula was not evaluated.",
            )
        )
    return ParsedSheet(
        source_format=source_format,
        sheet_name=sheet_name,
        header_row_number=header_row_number,
        headers_original=originals,
        headers_normalized=normalized,
        rows=tuple(rows),
        warnings=tuple(warnings),
    )


def _header_text(cell: JSONScalar) -> str:
    return "" if cell is None else str(cell).replace(BYTE_ORDER_MARK, "").strip()


def _usable_columns(header_cells: list[str], data: list[_Record], header_row: int) -> list[int]:
    """Indexes of the columns that have a header.

    A column without a header is ignored when it is empty in every row (a
    trailing separator, a formatted empty column). If it holds data, the file
    is refused: values that belong to no column cannot be imported.
    """
    usable: list[int] = []
    for index, name in enumerate(header_cells):
        if name:
            usable.append(index)
            continue
        has_data = any(
            index < len(cells) and not is_blank(cells[index]) for _, cells, _ in data
        ) or any(index < len(flags) and flags[index] for _, _, flags in data)
        if has_data:
            raise SourceFileError(
                "MISSING_HEADER",
                f"Column {index + 1} has values but no header in row {header_row}.",
            )
    if not usable:
        raise SourceFileError("MISSING_HEADER", "The file has no column headers.")
    return usable


def _reject_duplicate_headers(originals: tuple[str, ...], normalized: tuple[str, ...]) -> None:
    seen: dict[str, str] = {}
    for original, key in zip(originals, normalized, strict=True):
        if not key:
            raise SourceFileError(
                "MISSING_HEADER", "A column header contains no letters or digits."
            )
        if key in seen:
            raise SourceFileError(
                "DUPLICATE_HEADER",
                f'The headers "{seen[key]}" and "{original}" name the same column. '
                "Each column must appear once.",
            )
        seen[key] = original
