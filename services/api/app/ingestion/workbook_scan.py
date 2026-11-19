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


def content_budget(limits: ReaderLimits, scanned_rows: int) -> int:
    """How many elements the cells of one part may be made of.

    Enough for a worksheet that fills every row the reader scans and every
    column it accepts, and no more: what cannot be imported is not opened.
    """
    return ELEMENTS_PER_CELL * scanned_rows * (limits.max_columns + 1) + scanned_rows


def scan_parts(archive: zipfile.ZipFile, names: Iterable[str], *, cell_elements: int) -> None:
    """Refuse the archive if one of its XML parts asks for too much or is misnumbered."""
    for name in names:
        scan = _PartScan(cell_elements)
        parser = expat.ParserCreate(namespace_separator=_SEPARATOR)
        parser.StartElementHandler = scan.start
        parser.EndElementHandler = scan.end
        parser.StartDoctypeDeclHandler = scan.document_type
        parser.EntityDeclHandler = scan.document_type
        try:
            with archive.open(name) as part:
                parser.ParseFile(_BoundedRuns(part))
        except expat.ExpatError:
            # Not XML, or XML that breaks off. What came before the break was
            # within every budget, and the library will fail on the rest.
            continue
        except (SourceFileError, zipfile.BadZipFile):
            raise
        except Exception:
            # An encrypted or oddly compressed member, a row number that is
            # not a number, a cell reference that names no column.
            raise _unreadable() from None


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
        "_column",
        "_container_depth",
        "_content",
        "_depth",
        "_root",
        "_row_depth",
        "_row_number",
        "_structure",
    )

    def __init__(self, cell_budget: int) -> None:
        self._cell_budget = cell_budget
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

        # The cells of a worksheet stand in its sheetData element; the shared
        # texts are the si elements of the text table. Nothing else is given
        # the budget for cells, whatever the part is called: the library reads
        # formats and names from any part that stands where it expects them.
        at_top = depth == 2 and not self._container_depth
        if at_top and name == _STRING_ITEM and self._root == _SHARED_STRINGS:
            self._container_depth = depth  # the entry itself is content
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
        # wherever in the part they stand: that is where it looks for them.
        if self._row_depth:
            if depth == self._row_depth + 1:
                self._cell(name, attributes)
            elif name == _ROW:
                raise _misnumbered()  # a row inside a row
        elif name == _ROW:
            self._row(attributes, depth)

    def end(self, name: str) -> None:
        depth = self._depth
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
        self._row_number = number
        self._row_depth = depth
        self._column = 0

    def _cell(self, name: str, attributes: dict[str, str]) -> None:
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
