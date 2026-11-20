"""Workbooks no spreadsheet program writes, and what the reader does with them.

Each workbook here is built by hand. The reader has to answer every one with
a file error after a bounded amount of work: no entity that the workbook
declares is expanded, no worksheet is walked across sixteen thousand empty
columns, and no error message grows with what the workbook contains.
"""

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.ingestion import readers, workbook_scan
from app.ingestion.contracts import ReaderLimits, SourceFileError
from app.ingestion.readers import read_xlsx
from app.models.limits import SHEET_NAME_MAX
from tests.factories import xlsx_bytes
from tests.workbooks import (
    MAIN_NS,
    XML_DECLARATION,
    Raw,
    Shared,
    entity_declaration,
    handmade_workbook,
    shared_strings_part,
    sheet_part,
)

LIMITS = ReaderLimits(
    max_rows=100, max_columns=10, max_cell_chars=50, max_uncompressed_bytes=5_000_000
)
SERVICE_ROOT = Path(__file__).resolve().parents[2]
PROJECTS = sheet_part([["Project Code", "Project Name"], ["DC-1", "One"]])


def refused(code: str) -> pytest.RaisesExc[SourceFileError]:
    return pytest.raises(SourceFileError, check=lambda exc: exc.code == code)


# --- the helper itself ------------------------------------------------------------------


def test_a_handmade_workbook_is_read_like_any_other() -> None:
    """The control: what the tests below refuse is refused for its content, not its making."""
    inline = handmade_workbook([("Projects", PROJECTS)])
    shared = handmade_workbook(
        [("Projects", sheet_part([[Shared(0), Shared(1)], [Shared(2), Shared(3)]]))],
        shared_strings=shared_strings_part(["Project Code", "Project Name", "DC-1", "One"]),
    )

    for workbook in (inline, shared):
        sheet = read_xlsx(workbook, None, LIMITS)

        assert (sheet.sheet_name, sheet.headers_original) == (
            "Projects",
            ("Project Code", "Project Name"),
        )
        assert [dict(row.raw_data) for row in sheet.rows] == [
            {"Project Code": "DC-1", "Project Name": "One"}
        ]


# --- entities ---------------------------------------------------------------------------


def test_workbook_xml_is_parsed_by_the_hardened_parser() -> None:
    """openpyxl uses defusedxml only when it can import it; here it must."""
    assert openpyxl.DEFUSEDXML is True


def _entity_in_the_worksheet() -> bytes:
    declared = sheet_part(
        [["Project Code", "Project Name"], ["DC-1", Raw("&v;")]],
        prolog=entity_declaration("v", "EXPANDED"),
    )
    return handmade_workbook([("Projects", declared)])


def _entity_in_the_shared_strings() -> bytes:
    return handmade_workbook(
        [("Projects", sheet_part([[Shared(0), Shared(1)], [Shared(2), Shared(3)]]))],
        shared_strings=shared_strings_part(
            ["Project Code", "Project Name", "DC-1", Raw("&v;")],
            prolog=entity_declaration("v", "EXPANDED", root="sst"),
        ),
    )


def _entity_in_the_workbook_part() -> bytes:
    return handmade_workbook(
        [("Projects", PROJECTS)],
        workbook_prolog=entity_declaration("v", "EXPANDED", root="workbook"),
    )


@pytest.mark.parametrize(
    "workbook",
    [_entity_in_the_worksheet, _entity_in_the_shared_strings, _entity_in_the_workbook_part],
    ids=["worksheet", "shared strings", "workbook part"],
)
def test_a_workbook_that_declares_an_entity_is_refused(workbook: object) -> None:
    """Never read with the entity filled in: that would be the text "EXPANDED" in a cell."""
    assert callable(workbook)

    with refused("MALFORMED_FILE"):
        read_xlsx(workbook(), None, LIMITS)


def test_entities_cannot_multiply_the_size_of_a_workbook() -> None:
    """Fifty thousand references to a hundred characters: five megabytes from one cell.

    Refused for the declaration. CELL_TOO_LONG would mean the text had been
    built first, and with a larger workbook that is gigabytes.
    """
    multiplied = sheet_part(
        [["Project Code", "Project Name"], ["DC-1", Raw("&a;" * 50_000)]],
        prolog=entity_declaration("a", "A" * 100),
    )
    workbook = handmade_workbook([("Projects", multiplied)])

    assert len(workbook) < 10_000  # what travels is small
    with refused("MALFORMED_FILE"):
        read_xlsx(workbook, None, LIMITS)


def test_the_parser_refuses_entities_by_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two guards stand in front of an entity. This is the second, with the first removed."""
    monkeypatch.setattr(readers, "scan_parts", lambda *args, **kwargs: None)

    for workbook in (_entity_in_the_worksheet(), _entity_in_the_shared_strings()):
        with refused("MALFORMED_FILE"):
            read_xlsx(workbook, None, LIMITS)


def test_a_document_type_is_refused_even_without_an_entity() -> None:
    """No part of a workbook has one. It could also give attributes a default value."""
    declared = sheet_part(
        [["Project Code", "Project Name"], ["DC-1", "One"]],
        prolog='<!DOCTYPE worksheet [<!ATTLIST row r CDATA "7">]>',
    )

    with refused("MALFORMED_FILE"):
        read_xlsx(handmade_workbook([("Projects", declared)]), None, LIMITS)


def test_an_entity_that_names_a_file_is_not_read(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    external = sheet_part(
        [["Project Code", "Project Name"], ["DC-1", Raw("&x;")]],
        prolog=f'<!DOCTYPE worksheet [<!ENTITY x SYSTEM "{secret.as_uri()}">]>',
    )

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(handmade_workbook([("Projects", external)]), None, LIMITS)

    assert failure.value.code == "MALFORMED_FILE"
    assert "TOP-SECRET" not in failure.value.message


def test_the_reader_does_not_load_without_the_hardened_parser() -> None:
    """With the protection switched off, the module refuses to be imported at all."""
    result = subprocess.run(
        [sys.executable, "-c", "import app.ingestion.readers"],
        cwd=SERVICE_ROOT,
        env={**os.environ, "OPENPYXL_DEFUSEDXML": "False"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "defusedxml" in result.stderr


# --- the width of a worksheet -----------------------------------------------------------


def test_an_explicitly_selected_sheet_is_read_without_probing_other_sheets() -> None:
    """Selecting a sheet never probes all of its neighbours to guess the user's intent."""
    far_away = sheet_part({1: {5_000: "something"}})
    workbook = handmade_workbook([("Far", far_away), ("Projects", PROJECTS)])

    assert read_xlsx(workbook, "Projects", LIMITS).sheet_name == "Projects"


def test_blank_cells_far_to_the_right_are_not_walked() -> None:
    """Fifty rows, each with one blank cell in the last column a worksheet can have."""
    blank_far_right = sheet_part({row: {16_384: " "} for row in range(1, 51)})
    workbook = handmade_workbook(
        [*[(f"Blank {number}", blank_far_right) for number in range(20)], ("Projects", PROJECTS)]
    )
    visited = 0
    real_is_blank = sys.modules["app.ingestion.readers"].is_blank

    def counting(value: object) -> bool:
        nonlocal visited
        visited += 1
        return bool(real_is_blank(value))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.ingestion.readers.is_blank", counting)
        sheet = read_xlsx(workbook, None, LIMITS)

    assert sheet.sheet_name == "Projects"
    # Twenty worksheets of fifty rows, eleven columns each at most; not 16,384.
    assert visited < 20 * 50 * (LIMITS.max_columns + 1) + 1_000


# --- worksheet names --------------------------------------------------------------------


def test_the_name_of_the_imported_worksheet_must_fit_the_ledger() -> None:
    longest = "N" * SHEET_NAME_MAX

    assert read_xlsx(handmade_workbook([(longest, PROJECTS)]), None, LIMITS).sheet_name == longest

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(handmade_workbook([(longest + "N", PROJECTS)]), None, LIMITS)

    assert failure.value.code == "MALFORMED_FILE"
    assert str(SHEET_NAME_MAX) in failure.value.message
    assert "NNNNN" not in failure.value.message


def test_a_long_name_of_a_worksheet_that_is_not_imported_does_not_matter() -> None:
    workbook = handmade_workbook([("X" * 5_000, sheet_part([])), ("Projects", PROJECTS)])

    assert read_xlsx(workbook, "Projects", LIMITS).sheet_name == "Projects"


@pytest.mark.parametrize(
    ("requested", "code"), [(None, "AMBIGUOUS_WORKSHEET"), ("Nope", "WORKSHEET_NOT_FOUND")]
)
def test_an_error_lists_a_bounded_number_of_shortened_names(
    requested: str | None, code: str
) -> None:
    names = [f"{number:02d}-" + "x" * 2_000 for number in range(40)]
    workbook = handmade_workbook([(name, PROJECTS) for name in names])

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, requested, LIMITS)

    assert failure.value.code == code
    message = failure.value.message
    assert len(message) < 800
    assert "00-xxx" in message
    assert "09-xxx" in message
    assert "10-xxx" not in message
    assert "and 30 more" in message


def test_names_in_an_error_carry_no_control_characters() -> None:
    workbook = handmade_workbook(
        [("Line\nbreak", PROJECTS), ("Tab\there", PROJECTS), ("Right\u202eto left", PROJECTS)]
    )

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, None, LIMITS)

    assert failure.value.code == "AMBIGUOUS_WORKSHEET"
    message = failure.value.message
    assert all(character.isprintable() for character in message)
    assert "Linebreak" in message
    assert "Tabhere" in message


def test_two_worksheets_with_one_name_are_refused() -> None:
    """A name would no longer say which worksheet is meant."""
    other = sheet_part([["Project Code", "Project Name"], ["DC-2", "Two"]])
    workbook = handmade_workbook([("Projects", PROJECTS), ("Projects", other)])

    for requested in (None, "Projects"):
        with pytest.raises(SourceFileError) as failure:
            read_xlsx(workbook, requested, LIMITS)

        assert failure.value.code == "MALFORMED_FILE"
        assert "same name" in failure.value.message


def test_a_request_finds_the_one_worksheet_that_differs_only_by_spaces_around_its_name() -> None:
    other = sheet_part([["Supplier Code"], ["S-1"]])
    workbook = handmade_workbook([(" Projects ", PROJECTS), ("Suppliers", other)])

    assert read_xlsx(workbook, "Projects", LIMITS).sheet_name == " Projects "
    assert read_xlsx(workbook, " Suppliers ", LIMITS).sheet_name == "Suppliers"


def test_an_exact_name_wins_over_one_that_matches_after_trimming() -> None:
    padded = sheet_part([["Project Code", "Project Name"], ["DC-9", "Padded"]])
    workbook = handmade_workbook([("Projects ", padded), ("Projects", PROJECTS)])

    sheet = read_xlsx(workbook, "Projects", LIMITS)

    assert sheet.sheet_name == "Projects"
    assert sheet.rows[0].raw_data["Project Code"] == "DC-1"


def test_a_request_that_fits_two_worksheets_after_trimming_finds_none() -> None:
    workbook = handmade_workbook([(" Projects", PROJECTS), ("Projects ", PROJECTS)])

    with refused("WORKSHEET_NOT_FOUND"):
        read_xlsx(workbook, "Projects", LIMITS)


# --- what a worksheet says about itself ---------------------------------------------------

THREE_PROJECTS = [
    ["Project Code", "Project Name"],
    ["DC-1", "One"],
    ["DC-2", "Two"],
    ["DC-3", "Three"],
]


@pytest.mark.parametrize(
    "claimed", [None, "A1:B4", "A1", "A1:A1", "A1:B2", "B2:B3", "A1:XFD1048576"]
)
def test_a_worksheet_is_read_to_its_end_whatever_range_it_claims(claimed: str | None) -> None:
    """Some programs export a worksheet that states its used range as ``A1``.

    The range is a hint for whoever opens the file. Believing it would import
    the first rows and leave the rest out without a word.
    """
    workbook = handmade_workbook([("Projects", sheet_part(THREE_PROJECTS, dimension=claimed))])

    sheet = read_xlsx(workbook, None, LIMITS)

    assert sheet.headers_original == ("Project Code", "Project Name")
    assert [(row.row_number, row.raw_data["Project Code"]) for row in sheet.rows] == [
        (2, "DC-1"),
        (3, "DC-2"),
        (4, "DC-3"),
    ]

def test_selected_sheet_row_numbers_are_bounded_before_iteration() -> None:
    """A million-row worksheet is refused at the first row outside the scan window."""
    oversized = sheet_part({1: {1: "Project Code", 2: "Project Name"}, 1_102: {1: "DC-1"}})
    workbook = handmade_workbook([("Projects", oversized)])

    with refused("ROW_LIMIT_EXCEEDED"):
        read_xlsx(workbook, "Projects", LIMITS)


def test_unselected_worksheet_content_does_not_refuse_the_selected_sheet() -> None:
    """Bad or huge data on another sheet is not parsed by this import."""
    oversized_other_sheet = sheet_part({1_048_576: {1: "unused"}})
    workbook = handmade_workbook([("Projects", PROJECTS), ("Archive", oversized_other_sheet)])

    sheet = read_xlsx(workbook, "Projects", LIMITS)

    assert sheet.sheet_name == "Projects"
    assert [row.raw_data["Project Code"] for row in sheet.rows] == ["DC-1"]


def test_hidden_unselected_worksheet_does_not_extend_reader_work() -> None:
    hidden = sheet_part({1_048_576: {1: "unused"}})
    workbook = handmade_workbook([("Projects", PROJECTS), ("Archive", hidden)], hidden=("Archive",))

    assert read_xlsx(workbook, None, LIMITS).sheet_name == "Projects"


def test_multiple_visible_sheets_require_an_explicit_selection() -> None:
    workbook = handmade_workbook([("Empty", sheet_part([])), ("Projects", PROJECTS)])

    with refused("AMBIGUOUS_WORKSHEET"):
        read_xlsx(workbook, None, LIMITS)

    assert read_xlsx(workbook, "Projects", LIMITS).sheet_name == "Projects"


def test_a_formula_below_the_claimed_range_is_still_reported() -> None:
    rows = [["Project Code", "Budget"], ["DC-1", "10"], ["DC-2", "20"]]
    part = sheet_part(rows, dimension="A1:B2").replace(
        b'<c r="B3" t="inlineStr"><is><t xml:space="preserve">20</t></is></c>',
        b'<c r="B3"><f>B2*2</f></c>',  # a formula without a stored result
    )
    assert b"<f>B2*2</f>" in part

    sheet = read_xlsx(handmade_workbook([("Projects", part)]), None, LIMITS)

    assert [row.row_number for row in sheet.rows] == [2, 3]
    assert sheet.rows[1].formula_cells == ("Budget",)
    assert sheet.rows[1].raw_data["Budget"] is None


def test_cached_formula_values_are_preserved_without_a_second_workbook_load() -> None:
    part = sheet_part([["Project Code", "Budget"], ["DC-1", "10"]]).replace(
        b'<c r="B2" t="inlineStr"><is><t xml:space="preserve">10</t></is></c>',
        b'<c r="B2"><f>6*7</f><v>42</v></c>',
    )
    sheet = read_xlsx(handmade_workbook([("Projects", part)]), None, LIMITS)

    assert sheet.rows[0].raw_data["Budget"] == 42
    assert sheet.rows[0].formula_cells == ("Budget",)
    assert any(issue.code == "FORMULA_CACHED_VALUE_USED" for issue in sheet.warnings)


def test_openpyxl_loads_the_workbook_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Formula locations come from the bounded XML scan, not a second workbook."""
    original = readers.load_workbook
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(readers, "load_workbook", counted)

    read_xlsx(handmade_workbook([("Projects", PROJECTS)]), None, LIMITS)

    assert calls == 1


def _numbered(rows: list[tuple[int | None, list[tuple[str | None, str]]]]) -> bytes:
    """A worksheet part with exactly the row numbers and cell references given."""
    body = ""
    for number, cells in rows:
        body += "<row>" if number is None else f'<row r="{number}">'
        for reference, text in cells:
            attribute = "" if reference is None else f' r="{reference}"'
            body += f'<c{attribute} t="inlineStr"><is><t>{text}</t></is></c>'
        body += "</row>"
    return (
        f'{XML_DECLARATION}<worksheet xmlns="{MAIN_NS}"><sheetData>{body}</sheetData></worksheet>'
    ).encode()


HEADER = (1, [("A1", "Project Code"), ("B1", "Project Name")])


@pytest.mark.parametrize(
    "rows",
    [
        # A row number used twice: the second row of the two would be left out.
        [HEADER, (2, [("A2", "DC-1")]), (2, [("A2", "DC-2")]), (3, [("A3", "DC-3")])],
        # Rows out of order: the one that comes late would be left out.
        [HEADER, (3, [("A3", "DC-2")]), (2, [("A2", "DC-1")]), (4, [("A4", "DC-3")])],
        # Every row claims to be the first.
        [HEADER, (1, [("A1", "DC-1")]), (1, [("A1", "DC-2")])],
        # A row before the first: the header would be left out and a data row taken for it.
        [(0, [("A0", "Project Code")]), (1, [("A1", "DC-1")]), (2, [("A2", "DC-2")])],
        # A cell reference used twice: the earlier value would be overwritten.
        [HEADER, (2, [("A2", "DC-1"), ("A2", "DC-1 again"), ("B2", "One")])],
        # Cells out of order.
        [HEADER, (2, [("B2", "One"), ("A2", "DC-1")])],
        # A cell that says it belongs to another row.
        [HEADER, (2, [("A9", "DC-1"), ("B2", "One")]), (3, [("A3", "DC-2")])],
    ],
    ids=[
        "row number twice",
        "rows out of order",
        "all rows numbered 1",
        "row 0",
        "cell reference twice",
        "cells out of order",
        "cell of another row",
    ],
)
def test_a_worksheet_whose_rows_or_cells_are_misnumbered_is_refused(
    rows: list[tuple[int | None, list[tuple[str | None, str]]]],
) -> None:
    """The library places rows and cells by their numbers and drops what does not fit.

    Reading such a worksheet would import part of it. No spreadsheet program
    writes one; the file is refused and the message says why.
    """
    with pytest.raises(SourceFileError) as failure:
        read_xlsx(handmade_workbook([("Projects", _numbered(rows))]), None, LIMITS)

    assert failure.value.code == "MALFORMED_FILE"
    assert "ascending order" in failure.value.message


def test_rows_and_cells_without_numbers_are_taken_in_the_order_written() -> None:
    """Numbers are optional in the format; some programs leave them out."""
    rows = [
        (None, [(None, "Project Code"), (None, "Project Name")]),
        (None, [(None, "DC-1"), (None, "One")]),
        (None, [(None, "DC-2"), (None, "Two")]),
    ]

    sheet = read_xlsx(handmade_workbook([("Projects", _numbered(rows))]), None, LIMITS)

    assert [(row.row_number, dict(row.raw_data)) for row in sheet.rows] == [
        (2, {"Project Code": "DC-1", "Project Name": "One"}),
        (3, {"Project Code": "DC-2", "Project Name": "Two"}),
    ]


def test_numbered_and_unnumbered_cells_may_be_mixed() -> None:
    rows = [
        HEADER,
        (None, [(None, "DC-1"), ("B2", "One")]),
        (5, [("A5", "DC-2"), (None, "Two")]),
    ]

    sheet = read_xlsx(handmade_workbook([("Projects", _numbered(rows))]), None, LIMITS)

    assert [(row.row_number, dict(row.raw_data)) for row in sheet.rows] == [
        (2, {"Project Code": "DC-1", "Project Name": "One"}),
        (5, {"Project Code": "DC-2", "Project Name": "Two"}),
    ]


@pytest.mark.parametrize(
    "rows",
    [
        '<row r="1"><c r="A1"><v>1</v></c><row r="2"><c r="A2"><v>2</v></c></row></row>',
        '<row r="1"><extLst/><c><v>1</v></c></row>',
        '<row r="1048577"><c><v>1</v></c></row>',
        '<row r="1"><c r="XFE1"><v>1</v></c></row>',
        '<row r="one"><c><v>1</v></c></row>',
        '<row r="1"><c r="1A"><v>1</v></c></row>',
    ],
    ids=[
        "a row inside a row",
        "a row child that is not a cell",
        "a row beyond the last row of a worksheet",
        "a cell beyond the last column of a worksheet",
        "a row number that is not a number",
        "a cell reference that names no column",
    ],
)
def test_rows_and_cells_the_format_does_not_allow_are_refused(rows: str) -> None:
    part = (
        f'{XML_DECLARATION}<worksheet xmlns="{MAIN_NS}"><sheetData>{rows}</sheetData></worksheet>'
    ).encode()

    with refused("MALFORMED_FILE"):
        read_xlsx(handmade_workbook([("Projects", PROJECTS), ("Odd", part)]), "Projects", LIMITS)


# --- more objects than bytes ------------------------------------------------------------


def _replace_part(workbook: bytes, name: str, content: bytes) -> bytes:
    """The archive with one part replaced, or added when it is not there yet."""
    source = zipfile.ZipFile(io.BytesIO(workbook))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            if entry.filename != name:
                target.writestr(entry, source.read(entry.filename))
        target.writestr(name, content)
    return buffer.getvalue()


def _document(root: str, body: str) -> bytes:
    return f'{XML_DECLARATION}<{root} xmlns="{MAIN_NS}">{body}</{root}>'.encode()


CELL_BUDGET = workbook_scan.content_budget(
    LIMITS, LIMITS.max_rows + readers.BLANK_ROW_ALLOWANCE + 1
)
OVER_STRUCTURE = workbook_scan.MAX_STRUCTURE_ELEMENTS + 1


def test_a_megabyte_of_empty_cell_formats_is_refused_before_it_becomes_objects() -> None:
    """Five bytes each on the wire; a style object each once the workbook is opened."""
    styles = _document("styleSheet", "<cellXfs>" + "<xf/>" * OVER_STRUCTURE + "</cellXfs>")
    workbook = _replace_part(
        xlsx_bytes({"Projects": [["Project Code"], ["DC-1"]]}), "xl/styles.xml", styles
    )

    assert len(workbook) < 20_000
    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, None, LIMITS)

    assert failure.value.code == "FILE_TOO_LARGE"
    assert "formatting and structure" in failure.value.message


def test_a_workbook_part_stuffed_with_elements_is_refused() -> None:
    plain = handmade_workbook([("Projects", PROJECTS)])
    part = zipfile.ZipFile(io.BytesIO(plain)).read("xl/workbook.xml")
    stuffed = part.replace(
        b"</workbook>", b"<extLst>" + b"<a/>" * OVER_STRUCTURE + b"</extLst></workbook>"
    )

    with refused("FILE_TOO_LARGE"):
        read_xlsx(_replace_part(plain, "xl/workbook.xml", stuffed), None, LIMITS)


def test_formats_hidden_in_a_part_that_calls_itself_a_worksheet_are_counted_as_formats() -> None:
    """Only what stands among the cells of a worksheet is given the budget for cells."""
    disguised = _document(
        "worksheet", "<sheetData/><cellXfs>" + "<xf/>" * OVER_STRUCTURE + "</cellXfs>"
    )
    workbook = _replace_part(
        handmade_workbook([("Projects", PROJECTS)]), "xl/styles.xml", disguised
    )

    with refused("FILE_TOO_LARGE"):
        read_xlsx(workbook, None, LIMITS)


def test_selected_worksheet_with_more_cells_than_can_be_read_is_refused() -> None:
    cells = CELL_BUDGET // 2 + 1  # a cell and its value: two elements
    rows = "".join(
        f'<row r="{number}">' + "<c><v>1</v></c>" * 1_000 + "</row>"
        for number in range(1, cells // 1_000 + 2)
    )
    crowded = _document("worksheet", f"<sheetData>{rows}</sheetData>")
    workbook = handmade_workbook([("Projects", PROJECTS), ("Crowded", crowded)], hidden=["Crowded"])

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, "Crowded", LIMITS)

    assert failure.value.code == "FILE_TOO_LARGE"
    assert "worksheet of its own" in failure.value.message


def test_a_larger_worksheet_beside_the_imported_one_is_tolerated_within_the_budget() -> None:
    """Five times the rows that could be imported, and still far below the budget for cells."""
    sibling = sheet_part([["Code"], *[[f"X{index}"] for index in range(LIMITS.max_rows * 5)]])
    workbook = handmade_workbook([("Projects", PROJECTS), ("Sibling", sibling)])

    assert read_xlsx(workbook, "Projects", LIMITS).sheet_name == "Projects"


def test_shared_text_with_more_entries_than_can_be_read_is_refused() -> None:
    entries = CELL_BUDGET // 2 + 1  # an entry and its text: two elements
    shared = _document("sst", "<si><t>a</t></si>" * entries)
    workbook = handmade_workbook(
        [("Projects", sheet_part([[Shared(0)], [Shared(1)]]))], shared_strings=shared
    )

    with refused("FILE_TOO_LARGE"):
        read_xlsx(workbook, None, LIMITS)


def test_shared_string_entry_count_has_a_separate_tight_budget() -> None:
    shared = shared_strings_part(["Project Code", "Project Name", "P1", "Unused"])
    workbook = handmade_workbook(
        [("Projects", sheet_part([[Shared(0), Shared(1)], [Shared(2), Shared(2)]]))],
        shared_strings=shared,
    )
    limits = ReaderLimits(
        max_rows=100,
        max_columns=10,
        max_cell_chars=50,
        max_uncompressed_bytes=5_000_000,
        max_shared_string_items=3,
    )

    with refused("FILE_TOO_LARGE"):
        read_xlsx(workbook, "Projects", limits)


def test_shared_string_total_text_has_a_separate_budget() -> None:
    values = ["Project Code", "Project Name", "P1", "twenty characters...."]
    shared = shared_strings_part(values)
    workbook = handmade_workbook(
        [("Projects", sheet_part([[Shared(0), Shared(1)], [Shared(2), Shared(2)]]))],
        shared_strings=shared,
    )
    limits = ReaderLimits(
        max_rows=100,
        max_columns=10,
        max_cell_chars=50,
        max_uncompressed_bytes=5_000_000,
        max_shared_string_items=20,
        max_shared_string_chars=40,
    )

    with refused("FILE_TOO_LARGE"):
        read_xlsx(workbook, "Projects", limits)


def test_a_part_nested_deeper_than_any_program_writes_is_refused() -> None:
    depth = workbook_scan.MAX_DEPTH + 1
    nested = _document("styleSheet", "<a>" * depth + "</a>" * depth)
    workbook = _replace_part(handmade_workbook([("Projects", PROJECTS)]), "xl/styles.xml", nested)

    with refused("MALFORMED_FILE"):
        read_xlsx(workbook, None, LIMITS)


def test_parts_that_are_not_xml_do_not_matter() -> None:
    """A picture, a printer setting: the scan leaves them alone and so does the reader."""
    workbook = handmade_workbook(
        [("Projects", PROJECTS)],
        extra_parts={
            "xl/media/image1.png": b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4,
            "xl/printerSettings/printerSettings1.bin": b"\x00\x01\x02" * 100,
            "docProps/thumbnail.jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 64,
            "xl/notes.txt": b"plain text, not XML",
        },
    )

    assert len(read_xlsx(workbook, None, LIMITS).rows) == 1


def test_a_workbook_at_the_limits_is_within_every_budget() -> None:
    """The largest worksheet that can be imported, written by the spreadsheet library."""
    header = [f"Column {index}" for index in range(LIMITS.max_columns)]
    rows = [
        [f"r{row}c{column}" for column in range(LIMITS.max_columns)]
        for row in range(LIMITS.max_rows)
    ]

    sheet = read_xlsx(xlsx_bytes({"Full": [header, *rows]}), None, LIMITS)

    assert (len(sheet.rows), len(sheet.headers_original)) == (LIMITS.max_rows, LIMITS.max_columns)


@pytest.mark.parametrize(
    "part",
    [
        # A million attributes on one element; the parser holds them all at once.
        lambda: _document(
            "worksheet",
            "<sheetData><row "
            + " ".join(f'a{number:x}=""' for number in range(150_000))
            + "/></sheetData>",
        ),
        # One attribute, one megabyte and a little.
        lambda: _document("worksheet", f'<sheetData><row spans="{"1" * 1_100_000}"/></sheetData>'),
        # One text of that length.
        lambda: _document(
            "worksheet",
            '<sheetData><row><c t="inlineStr"><is><t>' + "x" * 1_100_000 + "</t></is></c></row>"
            "</sheetData>",
        ),
        # An element name of that length.
        lambda: _document("worksheet", "<sheetData/><" + "n" * 1_100_000 + "/>"),
    ],
    ids=["attributes", "attribute value", "text", "element name"],
)
def test_a_single_tag_or_text_of_more_than_a_megabyte_is_refused(part: object) -> None:
    assert callable(part)
    workbook = handmade_workbook([("Projects", PROJECTS), ("Long", part())], hidden=["Long"])

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, "Projects", LIMITS)

    assert failure.value.code == "FILE_TOO_LARGE"
    assert "more than a megabyte" in failure.value.message


def test_a_long_text_below_that_length_is_judged_as_a_cell() -> None:
    """Thirty thousand characters fit a spreadsheet cell; the reader applies its own limit."""
    long_cell = sheet_part([["Project Code", "Project Name"], ["DC-1", "x" * 30_000]])

    with refused("CELL_TOO_LONG"):
        read_xlsx(handmade_workbook([("Projects", long_cell)]), None, LIMITS)
