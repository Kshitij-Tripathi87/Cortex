"""Workbook archives written by hand, part by part.

A spreadsheet library only writes what a spreadsheet program would write. The
reader also has to refuse what such a program never writes: XML that declares
entities, worksheet names of any length, two worksheets with one name, cells
far beyond the last real column. These helpers build exactly that, as the
bytes a client could upload.
"""

import io
import zipfile
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape, quoteattr

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

WORKBOOK_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
WORKSHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
SHARED_STRINGS_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
)


class Raw(str):
    """Cell text that is already XML: written as it is, not escaped."""

    __slots__ = ()


class Shared(int):
    """A cell that refers to an entry of the shared-strings part by its index."""

    __slots__ = ()


def column_letters(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, 16384 -> XFD."""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _cell(reference: str, value: object) -> str:
    if isinstance(value, Shared):
        return f'<c r="{reference}" t="s"><v>{int(value)}</v></c>'
    text = value if isinstance(value, Raw) else escape(str(value))
    return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def sheet_part(
    rows: Sequence[Sequence[object]] | Mapping[int, Mapping[int, object]],
    *,
    prolog: str = "",
    dimension: str | None = None,
) -> bytes:
    """A worksheet part.

    ``rows`` is a list of rows of cell values (``None`` leaves a cell out), or
    a mapping of row number to a mapping of column number to value, for cells
    that sit far apart. ``prolog`` goes between the XML declaration and the
    root element, which is where a document type declaration belongs.
    ``dimension`` is the used range the worksheet claims, such as ``A1:C9``;
    a spreadsheet program states it, and a reader that finds it does not have
    to read the whole part to open the worksheet.
    """
    if isinstance(rows, Mapping):
        numbered = {number: dict(cells) for number, cells in rows.items()}
    else:
        numbered = {
            number: dict(enumerate(cells, start=1)) for number, cells in enumerate(rows, start=1)
        }
    body = "".join(
        f'<row r="{number}">'
        + "".join(
            _cell(f"{column_letters(column)}{number}", value)
            for column, value in sorted(cells.items())
            if value is not None
        )
        + "</row>"
        for number, cells in sorted(numbered.items())
    )
    claimed = f'<dimension ref="{dimension}"/>' if dimension else ""
    return (
        f'{XML_DECLARATION}{prolog}<worksheet xmlns="{MAIN_NS}">{claimed}'
        f"<sheetData>{body}</sheetData></worksheet>"
    ).encode()


def shared_strings_part(strings: Sequence[object], *, prolog: str = "") -> bytes:
    """A shared-strings part holding the given texts in order."""
    entries = "".join(
        f"<si><t>{text if isinstance(text, Raw) else escape(str(text))}</t></si>"
        for text in strings
    )
    return (
        f'{XML_DECLARATION}{prolog}<sst xmlns="{MAIN_NS}" count="{len(strings)}" '
        f'uniqueCount="{len(strings)}">{entries}</sst>'
    ).encode()


def handmade_workbook(
    sheets: Sequence[tuple[str, bytes]],
    *,
    shared_strings: bytes | None = None,
    workbook_prolog: str = "",
    hidden: Sequence[str] = (),
    extra_parts: Mapping[str, bytes] | None = None,
) -> bytes:
    """An .xlsx archive with the given ``(worksheet name, worksheet part)`` pairs."""
    numbers = range(1, len(sheets) + 1)
    sheet_elements = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{number}"'
        + (' state="hidden"' if name in hidden else "")
        + f' r:id="rId{number}"/>'
        for number, (name, _) in zip(numbers, sheets, strict=True)
    )
    workbook_part = (
        f'{XML_DECLARATION}{workbook_prolog}<workbook xmlns="{MAIN_NS}" '
        f'xmlns:r="{RELATIONSHIPS_NS}"><sheets>{sheet_elements}</sheets></workbook>'
    )
    relationships = "".join(
        f'<Relationship Id="rId{number}" Type="{RELATIONSHIPS_NS}/worksheet" '
        f'Target="worksheets/sheet{number}.xml"/>'
        for number in numbers
    )
    overrides = f'<Override PartName="/xl/workbook.xml" ContentType="{WORKBOOK_TYPE}"/>' + "".join(
        f'<Override PartName="/xl/worksheets/sheet{number}.xml" ContentType="{WORKSHEET_TYPE}"/>'
        for number in numbers
    )
    if shared_strings is not None:
        relationships += (
            f'<Relationship Id="rId{len(sheets) + 1}" Type="{RELATIONSHIPS_NS}/sharedStrings" '
            'Target="sharedStrings.xml"/>'
        )
        overrides += (
            f'<Override PartName="/xl/sharedStrings.xml" ContentType="{SHARED_STRINGS_TYPE}"/>'
        )
    content_types = (
        f'{XML_DECLARATION}<Types xmlns="{CONTENT_TYPES_NS}">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{overrides}</Types>"
    )
    package_relationships = (
        f'{XML_DECLARATION}<Relationships xmlns="{PACKAGE_NS}">'
        f'<Relationship Id="rId1" Type="{RELATIONSHIPS_NS}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_relationships)
        archive.writestr("xl/workbook.xml", workbook_part)
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'{XML_DECLARATION}<Relationships xmlns="{PACKAGE_NS}">{relationships}</Relationships>',
        )
        for number, (_, part) in zip(numbers, sheets, strict=True):
            archive.writestr(f"xl/worksheets/sheet{number}.xml", part)
        if shared_strings is not None:
            archive.writestr("xl/sharedStrings.xml", shared_strings)
        for name, content in (extra_parts or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def entity_declaration(name: str, value: str, *, root: str = "worksheet") -> str:
    """A document type declaration that defines one internal entity."""
    return f'<!DOCTYPE {root} [<!ENTITY {name} "{value}">]>'
