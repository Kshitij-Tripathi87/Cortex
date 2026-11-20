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
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from openpyxl import DEFUSEDXML, load_workbook

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
from app.ingestion.workbook_scan import FormulaBitmap, content_budget, scan_parts
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
CONTENT_TYPES_PART = "[Content_Types].xml"
MAX_ARCHIVE_ENTRIES = 5_000

# A worksheet may carry formatted but empty rows below its data. This many are
# scanned beyond the row limit before the sheet is refused.
BLANK_ROW_ALLOWANCE = 1_000
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
    """Parse one worksheet after bounding the workbook parts openpyxl materializes.

    Global parts (notably styles and shared strings) are scanned before the
    workbook is opened. Worksheet XML is scanned only for the selected sheet:
    unrelated and hidden sheets are not part of this import and cannot make it
    fail or consume an unbounded amount of work.
    """
    worksheet_parts = _check_workbook_container(file_bytes, limits)
    try:
        values = _open_workbook(file_bytes, data_only=True)
    except Exception:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None
    try:
        name = _select_sheet(values, sheet_name)
        selected = values[name]
        sheet_path = str(getattr(selected, "_worksheet_path", "")).lstrip("/")
        if not sheet_path.startswith("xl/worksheets/") or sheet_path not in worksheet_parts:
            raise SourceFileError(
                "MALFORMED_FILE",
                "The selected worksheet is not stored in a supported workbook location.",
            )
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            formula_bitmap = scan_parts(
                archive,
                [sheet_path],
                cell_elements=content_budget(limits, _scanned_rows(limits)),
                max_rows=_scanned_rows(limits),
                max_shared_string_items=limits.max_shared_string_items,
                max_shared_string_chars=limits.max_shared_string_chars,
                formula_part=sheet_path,
                formula_columns=limits.max_columns + 1,
            )
        # Formula locations come from the bounded XML scan. We open the
        # workbook once in data_only mode so cached results are preserved.
        records = _xlsx_records(selected, formula_bitmap, limits)
        sheet = _build_sheet(records, SourceFormat.XLSX, name, limits)
    except SourceFileError:
        raise
    except Exception:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None
    finally:
        values.close()
    return sheet


def _open_workbook(file_bytes: bytes, *, data_only: bool) -> Any:
    """The workbook for streaming, row by row. Links to other workbooks are not read."""
    return load_workbook(
        io.BytesIO(file_bytes), read_only=True, data_only=data_only, keep_links=False
    )


def _scanned_rows(limits: ReaderLimits) -> int:
    """Rows of a worksheet that are looked at before it is refused as too long."""
    return limits.max_rows + BLANK_ROW_ALLOWANCE + 1


def _check_workbook_container(file_bytes: bytes, limits: ReaderLimits) -> set[str]:
    """Bound global workbook parts and return worksheet paths for later selection."""
    not_a_workbook = SourceFileError(
        "UNSUPPORTED_FILE", "The file is not an .xlsx workbook. Save it as .xlsx or .csv."
    )
    if not file_bytes.startswith(ZIP_SIGNATURE):
        raise not_a_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if WORKBOOK_PART not in names or CONTENT_TYPES_PART not in names:
                raise not_a_workbook
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise SourceFileError("MALFORMED_FILE", "The workbook has too many parts.")
            if len(set(names)) != len(names):
                raise SourceFileError(
                    "MALFORMED_FILE", "The workbook contains duplicate archive part names."
                )
            if sum(entry.file_size for entry in entries) > limits.max_uncompressed_bytes:
                raise SourceFileError(
                    "FILE_TOO_LARGE", "The workbook is too large once uncompressed."
                )
            worksheet_parts = {
                name
                for name in names
                if name.startswith("xl/worksheets/") and name.lower().endswith(".xml")
            }
            # openpyxl materializes global parts while opening the workbook.
            # It does not need to parse the contents of every worksheet.
            # These are the workbook-level parts openpyxl materializes for
            # a normal XLSX read. Other worksheets, drawings, custom XML and
            # metadata not used by this ingestion path are deliberately ignored.
            global_xml_parts = [
                name
                for name in (
                    CONTENT_TYPES_PART,
                    "_rels/.rels",
                    WORKBOOK_PART,
                    "xl/_rels/workbook.xml.rels",
                    "xl/styles.xml",
                    "xl/sharedStrings.xml",
                    "xl/theme/theme1.xml",
                )
                if name in names
            ]
            content_types_info = archive.getinfo(CONTENT_TYPES_PART)
            if content_types_info.file_size > 2 * 1024 * 1024:
                raise SourceFileError(
                    "FILE_TOO_LARGE", "The workbook's package metadata is too large to read."
                )
            content_types = archive.read(CONTENT_TYPES_PART).decode("utf-8", errors="replace")
            scan_parts(
                archive,
                global_xml_parts,
                cell_elements=content_budget(limits, _scanned_rows(limits)),
                max_rows=_scanned_rows(limits),
                max_shared_string_items=limits.max_shared_string_items,
                max_shared_string_chars=limits.max_shared_string_chars,
            )
    except zipfile.BadZipFile:
        raise SourceFileError(
            "MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx."
        ) from None
    has_macros = any(name.lower().endswith("vbaproject.bin") for name in names)
    if has_macros or "macroEnabled" in content_types or "binary.macro" in content_types.lower():
        raise SourceFileError(
            "UNSUPPORTED_FILE",
            "Macro-enabled and binary workbooks are not accepted. Save the file as .xlsx.",
        )
    return worksheet_parts


def _select_sheet(workbook: Any, requested: str | None) -> str:
    """Choose the named worksheet, or the only visible worksheet.

    A workbook with several visible sheets requires an explicit selection;
    probing every sheet to infer intent would read unselected content before
    its resource limits have been applied.
    """
    available = [str(sheet.title) for sheet in workbook.worksheets]
    if len(set(available)) != len(available):
        # No spreadsheet program writes this, and a name would no longer say
        # which worksheet is meant.
        raise SourceFileError(
            "MALFORMED_FILE", "Two worksheets of the workbook have the same name."
        )
    if requested is not None:
        selected = _named_sheet(available, requested)
    else:
        visible = [
            str(sheet.title) for sheet in workbook.worksheets if sheet.sheet_state == "visible"
        ]
        if not visible:
            raise SourceFileError("EMPTY_FILE", "The workbook has no visible worksheet.")
        if len(visible) > 1:
            raise SourceFileError(
                "AMBIGUOUS_WORKSHEET",
                "The workbook has several visible worksheets. Specify sheet_name: "
                + _names_for_message(visible),
            )
        selected = visible[0]
    if len(selected) > SHEET_NAME_MAX:
        # The name is recorded with the batch. Spreadsheet programs stop at 31.
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
    values_sheet: Any, formula_bitmap: FormulaBitmap | None, limits: ReaderLimits
) -> Iterator[_Record]:
    max_scanned = _scanned_rows(limits)
    # The range a worksheet claims to use is a hint, and some programs write
    # "A1" whatever the worksheet holds. The library would stop at the last
    # row claimed; without the claim it reads the rows that are there.
    values_sheet.reset_dimensions()
    # One column beyond the limit is read so that an over-wide sheet is noticed.
    bounds = {"max_col": limits.max_columns + 1}
    for position, value_row in enumerate(values_sheet.iter_rows(**bounds), start=1):
        if position > max_scanned:
            raise SourceFileError(
                "ROW_LIMIT_EXCEEDED",
                f"The worksheet has more than {limits.max_rows} rows. Split the file.",
            )
        row_number = next(
            (cell.row for cell in value_row if getattr(cell, "row", None) is not None), position
        )
        cells: list[JSONScalar] = []
        formula_flags: list[bool] = []
        for column, value_cell in enumerate(value_row, start=1):
            is_formula = (
                formula_bitmap.contains(position, column) if formula_bitmap is not None else False
            )
            cells.append(_json_cell(value_cell.value))
            formula_flags.append(is_formula)
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
