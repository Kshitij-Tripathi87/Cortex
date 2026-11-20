"""Bounded XML inspection for XLSX packages before openpyxl materialises objects."""

import zipfile
from collections.abc import Iterable
from typing import IO, Any
from xml.parsers import expat

from openpyxl.utils.cell import coordinate_to_tuple

from app.ingestion.contracts import ReaderLimits, SourceFileError

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_SEPARATOR = " "
_WORKSHEET = f"{MAIN_NS}{_SEPARATOR}worksheet"
_SHEET_DATA = f"{MAIN_NS}{_SEPARATOR}sheetData"
_ROW = f"{MAIN_NS}{_SEPARATOR}row"
_CELL = f"{MAIN_NS}{_SEPARATOR}c"
_SHARED_STRINGS = f"{MAIN_NS}{_SEPARATOR}sst"
_STRING_ITEM = f"{MAIN_NS}{_SEPARATOR}si"
_FORMULA = f"{MAIN_NS}{_SEPARATOR}f"
_VALUE = f"{MAIN_NS}{_SEPARATOR}v"
_TEXT = f"{MAIN_NS}{_SEPARATOR}t"

SHEET_MAX_ROW = 1_048_576
SHEET_MAX_COLUMN = 16_384
MAX_STRUCTURE_ELEMENTS = 250_000
ELEMENTS_PER_CELL = 4
MAX_DEPTH = 100
MAX_RUN_BYTES = 1024 * 1024
# openpyxl materialises the complete shared-string table, even for one selected sheet.
MAX_SHARED_STRING_ITEMS = 100_000
MAX_SHARED_STRING_CHARS = 8_000_000


def _too_much_content() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "A worksheet contains more cells than can be read safely. Split the worksheet into smaller files.",
    )


def _too_much_structure() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook contains too much formatting or structure to read safely. Save the data in a new workbook.",
    )


def _too_many_shared_strings() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook contains too many shared text values to read safely. Split the data across smaller workbooks.",
    )


def _run_too_long() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook contains a single XML tag or text run longer than one megabyte.",
    )


def _misnumbered() -> SourceFileError:
    return SourceFileError(
        "MALFORMED_FILE",
        "The rows or cells of the selected worksheet are not numbered in ascending order. Open and save the workbook again.",
    )


def _unreadable() -> SourceFileError:
    return SourceFileError("MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx.")


def content_budget(limits: ReaderLimits, scanned_rows: int) -> int:
    """Maximum XML elements in a selected sheet at the configured import bounds."""
    return ELEMENTS_PER_CELL * scanned_rows * (limits.max_columns + 1) + scanned_rows


def scan_parts(
    archive: zipfile.ZipFile,
    names: Iterable[str],
    *,
    cell_elements: int,
    max_rows: int | None = None,
) -> dict[str, frozenset[tuple[int, int]]]:
    """Scan XML package parts and collect selected-sheet formula coordinates.

    Callers first scan workbook-global parts, then scan the selected worksheet.
    A row limit is applied only to the selected worksheet. Shared-string count
    and text size have separate budgets because openpyxl materialises the table.
    """
    formulas: dict[str, frozenset[tuple[int, int]]] = {}
    for name in names:
        if not name.lower().endswith((".xml", ".rels")):
            continue
        scan = _PartScan(cell_elements, max_rows=max_rows)
        parser = expat.ParserCreate(namespace_separator=_SEPARATOR)
        parser.StartElementHandler = scan.start
        parser.EndElementHandler = scan.end
        parser.CharacterDataHandler = scan.characters
        parser.StartDoctypeDeclHandler = scan.document_type
        parser.EntityDeclHandler = scan.document_type
        try:
            with archive.open(name) as part:
                parser.ParseFile(_BoundedRuns(part))
        except (SourceFileError, zipfile.BadZipFile):
            raise
        except expat.ExpatError:
            raise _unreadable() from None
        except Exception:
            raise _unreadable() from None
        formulas[name] = frozenset(scan.formula_cells)
    return formulas


class _ProbeFound(Exception):
    """Raised to stop a worksheet probe as soon as a cell value is found."""


class _ProbeFinished(Exception):
    """Raised when the bounded worksheet-selection prefix contains no data."""


class _SheetProbe:
    """Inspect a bounded worksheet prefix without creating openpyxl cell objects."""

    __slots__ = (
        "_cell_depth", "_column", "_depth", "_max_columns", "_max_rows",
        "_row_depth", "_row_number", "_rows", "_sheet_data_depth", "_value_depth",
    )

    def __init__(self, max_rows: int, max_columns: int) -> None:
        self._max_rows = max_rows
        self._max_columns = max_columns
        self._depth = 0
        self._sheet_data_depth = 0
        self._row_depth = 0
        self._row_number = 0
        self._rows = 0
        self._column = 0
        self._cell_depth = 0
        self._value_depth = 0

    def document_type(self, *_: Any) -> None:
        raise _unreadable()

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise _unreadable()
        if name == _SHEET_DATA and self._depth == 2:
            self._sheet_data_depth = self._depth
            return
        if self._sheet_data_depth and not self._row_depth and name == _ROW:
            self._rows += 1
            if self._rows > self._max_rows:
                raise _ProbeFinished()
            try:
                self._row_number = int(attributes.get("r", self._rows))
            except (TypeError, ValueError):
                self._row_number = self._rows
            self._row_depth = self._depth
            self._column = 0
            return
        if not self._row_depth:
            return
        if self._depth == self._row_depth + 1 and name == _CELL:
            reference = attributes.get("r")
            try:
                row, column = coordinate_to_tuple(reference) if reference else (
                    self._row_number, self._column + 1
                )
            except ValueError:
                self._cell_depth = 0
                return
            self._column = column
            if row == self._row_number and row <= self._max_rows and column <= self._max_columns:
                self._cell_depth = self._depth
            return
        if self._cell_depth and (
            (name == _VALUE and self._depth == self._cell_depth + 1)
            or (name == _TEXT and self._depth > self._cell_depth)
        ):
            self._value_depth = self._depth

    def characters(self, value: str) -> None:
        if self._value_depth and value.strip():
            raise _ProbeFound()

    def end(self, _name: str) -> None:
        if self._depth == self._value_depth:
            self._value_depth = 0
        if self._depth == self._cell_depth:
            self._cell_depth = 0
        if self._depth == self._row_depth:
            self._row_depth = 0
        if self._depth == self._sheet_data_depth:
            self._sheet_data_depth = 0
        self._depth -= 1


def probe_sheet_has_data(
    archive: zipfile.ZipFile, name: str, *, max_rows: int, max_columns: int
) -> bool:
    """Return whether the bounded prefix has a non-empty cell value."""
    probe = _SheetProbe(max_rows, max_columns)
    parser = expat.ParserCreate(namespace_separator=_SEPARATOR)
    parser.StartElementHandler = probe.start
    parser.EndElementHandler = probe.end
    parser.CharacterDataHandler = probe.characters
    parser.StartDoctypeDeclHandler = probe.document_type
    parser.EntityDeclHandler = probe.document_type
    try:
        with archive.open(name) as part:
            parser.ParseFile(_BoundedRuns(part))
    except _ProbeFound:
        return True
    except _ProbeFinished:
        return False
    except (SourceFileError, zipfile.BadZipFile):
        raise
    except expat.ExpatError:
        raise _unreadable() from None
    except Exception:
        raise _unreadable() from None
    return False


class _BoundedRuns:
    """Stream XML to expat while limiting the size of any one tag or text run."""

    __slots__ = ("_part", "_run")

    def __init__(self, part: IO[bytes]) -> None:
        self._part = part
        self._run = 0

    def read(self, size: int = -1) -> bytes:
        piece = self._part.read(size)
        last = piece.rfind(b">")
        if last < 0:
            self._run += len(piece)
        else:
            if self._run + piece.find(b">") > MAX_RUN_BYTES:
                raise _run_too_long()
            self._run = len(piece) - last - 1
        if self._run > MAX_RUN_BYTES:
            raise _run_too_long()
        return piece


class _PartScan:
    """Streaming counts and spreadsheet coordinates for one XML part."""

    __slots__ = (
        "_cell_budget", "_cell_coordinates", "_cell_depth", "_column",
        "_container_depth", "_content", "_depth", "_formula_cells", "_max_rows",
        "_root", "_row_depth", "_row_number", "_shared_string_chars",
        "_shared_string_items", "_structure",
    )

    def __init__(self, cell_budget: int, *, max_rows: int | None = None) -> None:
        self._cell_budget = cell_budget
        self._max_rows = max_rows
        self._depth = 0
        self._root = ""
        self._container_depth = 0
        self._content = 0
        self._structure = 0
        self._row_depth = 0
        self._row_number = 0
        self._column = 0
        self._cell_depth = 0
        self._cell_coordinates: tuple[int, int] | None = None
        self._formula_cells: set[tuple[int, int]] = set()
        self._shared_string_items = 0
        self._shared_string_chars = 0

    @property
    def formula_cells(self) -> set[tuple[int, int]]:
        return self._formula_cells

    def characters(self, value: str) -> None:
        if self._root == _SHARED_STRINGS and self._container_depth and value:
            self._shared_string_chars += len(value)
            if self._shared_string_chars > MAX_SHARED_STRING_CHARS:
                raise _too_many_shared_strings()

    def document_type(self, *_: Any) -> None:
        raise _unreadable()

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self._depth += 1
        depth = self._depth
        if depth == 1:
            self._root = name
        elif depth > MAX_DEPTH:
            raise _unreadable()

        at_top = depth == 2 and not self._container_depth
        if at_top and name == _STRING_ITEM and self._root == _SHARED_STRINGS:
            self._shared_string_items += 1
            if self._shared_string_items > MAX_SHARED_STRING_ITEMS:
                raise _too_many_shared_strings()
            self._container_depth = depth
        if self._container_depth:
            self._content += 1
            if self._content > self._cell_budget:
                raise _too_much_content()
        else:
            self._structure += 1
            if self._structure > MAX_STRUCTURE_ELEMENTS:
                raise _too_much_structure()
            if at_top and name == _SHEET_DATA and self._root == _WORKSHEET:
                self._container_depth = depth

        if self._row_depth:
            if depth == self._row_depth + 1:
                self._cell(name, attributes, depth)
            elif name == _ROW:
                raise _misnumbered()
            elif (
                self._cell_depth
                and depth == self._cell_depth + 1
                and name == _FORMULA
                and self._cell_coordinates is not None
            ):
                self._formula_cells.add(self._cell_coordinates)
        elif name == _ROW:
            self._row(attributes, depth)

    def end(self, _name: str) -> None:
        depth = self._depth
        if depth == self._cell_depth:
            self._cell_depth = 0
            self._cell_coordinates = None
        if depth == self._row_depth:
            self._row_depth = 0
        if depth == self._container_depth:
            self._container_depth = 0
        self._depth = depth - 1

    def _row(self, attributes: dict[str, str], depth: int) -> None:
        stated = attributes.get("r")
        number = self._row_number + 1 if stated is None else int(stated)
        if number <= self._row_number or number > SHEET_MAX_ROW:
            raise _misnumbered()
        if self._max_rows is not None and number > self._max_rows:
            raise SourceFileError(
                "ROW_LIMIT_EXCEEDED",
                f"The worksheet has more than {self._max_rows} scanned rows. Split the file.",
            )
        self._row_number = number
        self._row_depth = depth
        self._column = 0

    def _cell(self, name: str, attributes: dict[str, str], depth: int) -> None:
        if name != _CELL:
            raise _misnumbered()
        reference = attributes.get("r")
        if reference:
            row, column = coordinate_to_tuple(reference)
        else:
            row, column = self._row_number, self._column + 1
        if row != self._row_number or column <= self._column or column > SHEET_MAX_COLUMN:
            raise _misnumbered()
        self._column = column
        self._cell_depth = depth
        self._cell_coordinates = (row, column)
