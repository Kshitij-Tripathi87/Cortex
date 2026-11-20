"""Weighs the XML of a workbook archive before the workbook is opened.

A workbook is small XML documents and a few large ones. The library that
reads it turns elements into objects, and how much that costs has little to do
with how many bytes the elements take: a megabyte of empty cell formats
becomes hundreds of megabytes of style objects. It also places rows and cells
by the numbers they carry and leaves out what does not fit, so a worksheet
that numbers two rows alike is read with one of them missing.

This scan reads every part of the archive once, as a stream of element names,
and builds nothing. It refuses the workbook when a part

* declares a document type, and with it possibly entities or default
  attributes;
* is nested deeper than any spreadsheet program writes;
* holds more elements than the reader is prepared to turn into objects;
* holds a single tag or a single text longer than a megabyte, which is where
  a million attributes on one element would be;
* numbers the rows of a worksheet, or the cells of a row, out of ascending
  order.

A part that is not XML at all (an image, a printer setting) is left alone: the
library does not parse it, or fails on it in its own way.
"""

import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
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
_FORMULA = f"{MAIN_NS}{_SEPARATOR}f"
_SHARED_STRINGS = f"{MAIN_NS}{_SEPARATOR}sst"
_STRING_ITEM = f"{MAIN_NS}{_SEPARATOR}si"
_TEXT = f"{MAIN_NS}{_SEPARATOR}t"

# The largest worksheet the file format describes.
SHEET_MAX_ROW = 1_048_576
SHEET_MAX_COLUMN = 16_384
# Elements outside the cells of a worksheet and outside the shared texts:
# formats, names, relationships, properties. A workbook with every one of the
# 65,490 cell formats a spreadsheet program allows stays below this.
MAX_STRUCTURE_ELEMENTS = 250_000
# Elements a cell is made of, on average, when the budget for cells is set:
# the cell, its value, and room for a formula or an inline text.
ELEMENTS_PER_CELL = 4
# A document written by a spreadsheet program is nested less than twenty deep.
MAX_DEPTH = 100
# Bytes between one ">" and the next: a tag with its attributes, or a text. The
# longest text a cell can hold is 32,767 characters, well below this.
MAX_RUN_BYTES = 1024 * 1024


def _too_much_content() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "A worksheet of the workbook, or its shared text, holds more cells than can be read. "
        "Copy the worksheet to import into a workbook of its own.",
    )


def _too_much_structure() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook holds more formatting and structure than can be read. "
        "Copy the data to import into a new workbook.",
    )


def _run_too_long() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook holds a single value or tag of more than a megabyte, which cannot be read. "
        "Copy the data to import into a new workbook.",
    )


def _misnumbered() -> SourceFileError:
    return SourceFileError(
        "MALFORMED_FILE",
        "The rows or cells of a worksheet are not numbered in ascending order within the "
        "size of a worksheet. Open the workbook in a spreadsheet program and save it again.",
    )


def _unreadable() -> SourceFileError:
    return SourceFileError("MALFORMED_FILE", "The workbook cannot be read. Save it again as .xlsx.")


def _too_many_rows() -> SourceFileError:
    return SourceFileError(
        "ROW_LIMIT_EXCEEDED",
        "The selected worksheet extends beyond the row scan limit. "
        "Remove trailing rows or split the file.",
    )


def _too_many_shared_strings() -> SourceFileError:
    return SourceFileError(
        "FILE_TOO_LARGE",
        "The workbook has too many shared strings or too much shared text to read safely. "
        "Copy the data into a new workbook.",
    )


@dataclass(frozen=True, slots=True)
class FormulaBitmap:
    """Compact formula-cell coordinates for the selected worksheet."""

    bits: bytes
    columns: int

    def contains(self, row: int, column: int) -> bool:
        if row < 1 or column < 1 or column > self.columns:
            return False
        offset = (row - 1) * self.columns + (column - 1)
        byte = offset >> 3
        return byte < len(self.bits) and bool(self.bits[byte] & (1 << (offset & 7)))


def content_budget(limits: ReaderLimits, scanned_rows: int) -> int:
    """How many elements the cells of one part may be made of.

    Enough for a worksheet that fills every row the reader scans and every
    column it accepts, and no more: what cannot be imported is not opened.
    """
    return ELEMENTS_PER_CELL * scanned_rows * (limits.max_columns + 1) + scanned_rows


def scan_parts(
    archive: zipfile.ZipFile,
    names: Iterable[str],
    *,
    cell_elements: int,
    max_rows: int,
    max_shared_string_items: int,
    max_shared_string_chars: int,
    formula_part: str | None = None,
    formula_columns: int = 0,
) -> FormulaBitmap | None:
    """Refuse selected XML parts that exceed parser budgets or misnumber cells."""
    formula_bitmap: FormulaBitmap | None = None
    for name in names:
        formula_bits = (
            bytearray((max_rows * formula_columns + 7) // 8)
            if name == formula_part and formula_columns > 0
            else None
        )
        scan = _PartScan(
            cell_elements,
            max_rows=max_rows,
            max_shared_string_items=max_shared_string_items,
            max_shared_string_chars=max_shared_string_chars,
            formula_bits=formula_bits,
            formula_columns=formula_columns,
        )
        parser = expat.ParserCreate(namespace_separator=_SEPARATOR)
        parser.StartElementHandler = scan.start
        parser.EndElementHandler = scan.end
        parser.CharacterDataHandler = scan.characters
        parser.StartDoctypeDeclHandler = scan.document_type
        parser.EntityDeclHandler = scan.document_type
        try:
            with archive.open(name) as part:
                parser.ParseFile(_BoundedRuns(part))
        except expat.ExpatError:
            # Only XML and relationship parts are passed to this scanner.
            # A broken part must not be treated as an unscanned safe part.
            raise _unreadable() from None
        except (SourceFileError, zipfile.BadZipFile):
            raise
        except Exception:
            # An encrypted or oddly compressed member, a row number that is
            # not a number, a cell reference that names no column.
            raise _unreadable() from None
        if formula_bits is not None:
            formula_bitmap = FormulaBitmap(bytes(formula_bits), formula_columns)
    return formula_bitmap


class _BoundedRuns:
    """Hands a part to the parser in pieces and refuses a run without a ``>``.

    The parser keeps a tag in memory until it is complete, attributes and
    all, and a text until its element ends. Neither can be counted before it
    has been read, so the bytes are watched on their way in: every tag ends
    with ``>``, in each encoding the parser accepts.
    """

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
    """What one XML part holds, counted while it streams past."""

    __slots__ = (
        "_cell_budget",
        "_cell_column",
        "_cell_depth",
        "_cell_row",
        "_column",
        "_container_depth",
        "_content",
        "_depth",
        "_formula_bits",
        "_formula_columns",
        "_max_rows",
        "_max_shared_string_chars",
        "_max_shared_string_items",
        "_root",
        "_row_depth",
        "_row_number",
        "_shared_string_chars",
        "_shared_string_items",
        "_structure",
        "_text_depth",
    )

    def __init__(
        self,
        cell_budget: int,
        *,
        max_rows: int,
        max_shared_string_items: int,
        max_shared_string_chars: int,
        formula_bits: bytearray | None = None,
        formula_columns: int = 0,
    ) -> None:
        self._cell_budget = cell_budget
        self._max_rows = max_rows
        self._max_shared_string_items = max_shared_string_items
        self._max_shared_string_chars = max_shared_string_chars
        self._shared_string_items = 0
        self._shared_string_chars = 0
        self._text_depth = 0
        self._formula_bits = formula_bits
        self._formula_columns = formula_columns
        self._cell_depth = 0
        self._cell_row = 0
        self._cell_column = 0
        self._depth = 0
        self._root = ""
        # Depth of the element whose descendants are cells or shared texts; 0 outside.
        self._container_depth = 0
        self._content = 0
        self._structure = 0
        # Depth of the row being read; 0 outside a row.
        self._row_depth = 0
        self._row_number = 0
        self._column = 0

    def document_type(self, *_: Any) -> None:
        raise _unreadable()

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self._depth += 1
        depth = self._depth
        if depth == 1:
            self._root = name
        elif depth > MAX_DEPTH:
            raise _unreadable()

        # The cells of a worksheet stand in its sheetData element; shared
        # strings are counted separately because openpyxl materializes the
        # entire table even when most entries are never referenced.
        at_top = depth == 2 and not self._container_depth
        if at_top and name == _STRING_ITEM and self._root == _SHARED_STRINGS:
            self._shared_string_items += 1
            if self._shared_string_items > self._max_shared_string_items:
                raise _too_many_shared_strings()
            self._container_depth = depth  # the entry itself is content
        if self._root == _SHARED_STRINGS and name == _TEXT:
            self._text_depth = depth
        if self._container_depth:
            self._content += 1
            if self._content > self._cell_budget:
                raise _too_much_content()
        else:
            self._structure += 1
            if self._structure > MAX_STRUCTURE_ELEMENTS:
                raise _too_much_structure()
            if at_top and name == _SHEET_DATA and self._root == _WORKSHEET:
                self._container_depth = depth  # what follows inside is content

        # Rows and cells are numbered the way the library numbers them,
        # wherever in a worksheet part they stand.
        if self._root == _WORKSHEET:
            if self._row_depth:
                if depth == self._row_depth + 1:
                    self._cell(name, attributes, depth)
                elif (
                    self._cell_depth
                    and depth == self._cell_depth + 1
                    and name.rsplit(_SEPARATOR, 1)[-1] == "f"
                    and self._formula_bits is not None
                ):
                    self._mark_formula()
                elif name == _ROW:
                    raise _misnumbered()  # a row inside a row
            elif name == _ROW:
                self._row(attributes, depth)

    def characters(self, value: str) -> None:
        """Count decoded text in shared-string entries before openpyxl builds them."""
        if self._text_depth:
            self._shared_string_chars += len(value)
            if self._shared_string_chars > self._max_shared_string_chars:
                raise _too_many_shared_strings()

    def end(self, name: str) -> None:
        depth = self._depth
        if depth == self._text_depth:
            self._text_depth = 0
        if depth == self._cell_depth:
            self._cell_depth = 0
            self._cell_row = 0
            self._cell_column = 0
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
        if number > self._max_rows:
            raise _too_many_rows()
        self._row_number = number
        self._row_depth = depth
        self._column = 0

    def _cell(self, name: str, attributes: dict[str, str], depth: int) -> None:
        if name != _CELL:
            # The library reads every child of a row as a cell and counts it
            # as a column, whatever it is called.
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
        self._cell_row = row
        self._cell_column = column

    def _mark_formula(self) -> None:
        """Set one bit; avoids loading a second openpyxl workbook for formula flags."""
        bits = self._formula_bits
        if bits is None or self._cell_column > self._formula_columns:
            return
        offset = (self._cell_row - 1) * self._formula_columns + (self._cell_column - 1)
        bits[offset >> 3] |= 1 << (offset & 7)
