"""CSV and XLSX readers: what they accept, what they refuse, and what they never do."""

import io
import zipfile
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from app.ingestion.contracts import ParsedSheet, ReaderLimits, SourceFileError
from app.ingestion.readers import detect_file_format, read_csv, read_xlsx
from app.models.enums import SourceFormat
from tests.factories import csv_bytes, xlsx_bytes

LIMITS = ReaderLimits(
    max_rows=100, max_columns=10, max_cell_chars=50, max_uncompressed_bytes=5_000_000
)


def refused(code: str) -> pytest.RaisesExc[SourceFileError]:
    return pytest.raises(SourceFileError, check=lambda exc: exc.code == code)


def rows_of(sheet: ParsedSheet) -> list[tuple[int, dict[str, object]]]:
    return [(row.row_number, dict(row.raw_data)) for row in sheet.rows]


# --- file type ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("projects.csv", "text/csv", SourceFormat.CSV),
        ("PROJECTS.CSV", None, SourceFormat.CSV),
        ("projects.csv", "application/vnd.ms-excel", SourceFormat.CSV),
        ("projects.csv", "application/octet-stream", SourceFormat.CSV),
        ("projects.csv", "text/csv; charset=utf-8", SourceFormat.CSV),
        (
            "book.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            SourceFormat.XLSX,
        ),
        ("book.xlsx", "", SourceFormat.XLSX),
        # The name is only read for its extension; it is never a path.
        ("../../etc/passwd.csv", "text/csv", SourceFormat.CSV),
        ("C:\\Users\\x\\book.xlsx", None, SourceFormat.XLSX),
    ],
)
def test_supported_file_types(filename: str, content_type: str | None, expected: object) -> None:
    assert detect_file_format(filename, content_type) is expected


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("book.xls", "application/vnd.ms-excel"),
        ("book.xlsm", None),
        ("book.xlsb", None),
        ("data.json", "application/json"),
        ("archive.zip", "application/zip"),
        ("noextension", None),
        ("projects.csv", "image/png"),
        ("book.xlsx", "text/csv"),
        ("projects.csv.exe", None),
    ],
)
def test_unsupported_file_types(filename: str, content_type: str | None) -> None:
    with refused("UNSUPPORTED_FILE"):
        detect_file_format(filename, content_type)


# --- CSV ------------------------------------------------------------------------------


def test_csv_with_utf8_bom() -> None:
    sheet = read_csv(
        csv_bytes(["Project Code", "Project Name"], [["P1", "Näme"]], bom=True), LIMITS
    )

    assert sheet.source_format is SourceFormat.CSV
    assert sheet.headers_original == ("Project Code", "Project Name")
    assert sheet.headers_normalized == ("project code", "project name")
    assert rows_of(sheet) == [(2, {"Project Code": "P1", "Project Name": "Näme"})]


@pytest.mark.parametrize("content", [b"", b"   \n\n  \n", b"\xef\xbb\xbf"])
def test_empty_csv(content: bytes) -> None:
    with refused("EMPTY_FILE"):
        read_csv(content, LIMITS)


def test_csv_with_a_header_and_no_rows() -> None:
    with refused("EMPTY_FILE"):
        read_csv(b"Project Code,Project Name\n", LIMITS)


def test_csv_whose_header_names_nothing() -> None:
    with refused("MISSING_HEADER"):
        read_csv(b"###,---\n1,2\n", LIMITS)


def test_csv_column_with_values_and_no_header() -> None:
    with refused("MISSING_HEADER"):
        read_csv(b"Project Code,,Project Name\nP1,orphan,Name\n", LIMITS)


def test_an_empty_column_without_header_is_ignored() -> None:
    sheet = read_csv(b"Project Code,Project Name,\nP1,Name,\n", LIMITS)

    assert sheet.headers_original == ("Project Code", "Project Name")


@pytest.mark.parametrize(
    "header",
    ["PO Number,PO Number", "PO Number, po number ", "PO Number,po_number", "PO-Number,PO  NUMBER"],
)
def test_duplicate_headers_are_refused_also_after_normalization(header: str) -> None:
    with refused("DUPLICATE_HEADER"):
        read_csv(f"{header}\n1,2\n".encode(), LIMITS)


def test_blank_rows_are_skipped_and_row_numbers_stay_physical() -> None:
    content = b"\nProject Code,Project Name\nP1,One\n\n , \nP2,Two\n\n"

    sheet = read_csv(content, LIMITS)

    assert sheet.header_row_number == 2
    assert [row.row_number for row in sheet.rows] == [3, 6]
    assert [(issue.code, issue.severity.value) for issue in sheet.warnings] == [
        ("BLANK_ROWS_SKIPPED", "WARNING")
    ]
    assert "2 blank row" in sheet.warnings[0].message


def test_a_quoted_cell_spanning_lines_counts_by_its_first_line() -> None:
    content = b'Project Code,Project Name\nP1,"line one\nline two"\nP2,Two\n'

    sheet = read_csv(content, LIMITS)

    assert [row.row_number for row in sheet.rows] == [2, 4]
    assert sheet.rows[0].raw_data["Project Name"] == "line one\nline two"


@pytest.mark.parametrize("content", ["Projekt,Näme\n1,2\n".encode("latin-1"), b"a,b\n\xff\xfe,1\n"])
def test_malformed_encoding(content: bytes) -> None:
    with refused("INVALID_ENCODING"):
        read_csv(content, LIMITS)


def test_malformed_csv_quoting() -> None:
    with refused("MALFORMED_FILE"):
        read_csv(b'a,b\n"unterminated,1\n', LIMITS)


def test_binary_content_is_not_a_csv() -> None:
    with refused("UNSUPPORTED_FILE"):
        read_csv(b"a,b\n1,\x00\x01\n", LIMITS)
    with refused("UNSUPPORTED_FILE"):
        read_csv(xlsx_bytes({"S": [["a"], [1]]}), LIMITS)


def test_excessive_row_count() -> None:
    rows = [[f"P{index}", "x"] for index in range(LIMITS.max_rows + 1)]

    with refused("ROW_LIMIT_EXCEEDED"):
        read_csv(csv_bytes(["Project Code", "Project Name"], rows), LIMITS)

    read_csv(csv_bytes(["Project Code", "Project Name"], rows[:-1]), LIMITS)


def test_excessive_column_count() -> None:
    headers = [f"Column {index}" for index in range(LIMITS.max_columns + 1)]

    with refused("COLUMN_LIMIT_EXCEEDED"):
        read_csv(csv_bytes(headers, [["x"] * len(headers)]), LIMITS)


def test_excessive_cell_length() -> None:
    with refused("CELL_TOO_LONG"):
        read_csv(csv_bytes(["Project Code"], [["x" * (LIMITS.max_cell_chars + 1)]]), LIMITS)


def test_cells_beyond_the_header_are_reported_not_dropped() -> None:
    sheet = read_csv(b"Project Code,Project Name\nP1,One,surplus,\nP2\n", LIMITS)

    assert sheet.rows[0].extra_cells == ("surplus",)
    # A short row is fine: the missing cell is simply absent.
    assert dict(sheet.rows[1].raw_data) == {"Project Code": "P2", "Project Name": None}
    assert sheet.rows[1].extra_cells == ()


def test_cell_text_is_never_interpreted() -> None:
    """A formula-looking or script-looking cell in a CSV is plain text."""
    sheet = read_csv(b"Project Code,Project Name\n=1+1,\"=cmd|' /C calc'!A0\"\n", LIMITS)

    assert dict(sheet.rows[0].raw_data) == {
        "Project Code": "=1+1",
        "Project Name": "=cmd|' /C calc'!A0",
    }


# --- XLSX -----------------------------------------------------------------------------


def test_xlsx_single_sheet_with_typed_cells() -> None:
    workbook = xlsx_bytes(
        {
            "Orders": [
                ["PO Number", "Issue Date", "Total Value", "Quantity", "Confirmed"],
                ["PO-1", date(2026, 6, 1), 1234.56, 2, True],
                ["PO-2", datetime(2026, 6, 2, 14, 30), None, 3.5, False],
            ]
        }
    )

    sheet = read_xlsx(workbook, None, LIMITS)

    assert (sheet.source_format, sheet.sheet_name, sheet.header_row_number) == (
        SourceFormat.XLSX,
        "Orders",
        1,
    )
    assert rows_of(sheet) == [
        (
            2,
            {
                "PO Number": "PO-1",
                "Issue Date": "2026-06-01",
                "Total Value": 1234.56,
                "Quantity": 2,
                "Confirmed": True,
            },
        ),
        (
            3,
            {
                "PO Number": "PO-2",
                "Issue Date": "2026-06-02T14:30:00",
                "Total Value": None,
                "Quantity": 3.5,
                "Confirmed": False,
            },
        ),
    ]


def test_xlsx_sheet_selection() -> None:
    workbook = xlsx_bytes(
        {"Projects": [["Project Code"], ["P1"]], "Suppliers": [["Supplier Code"], ["S1"], ["S2"]]}
    )

    assert read_xlsx(workbook, "Suppliers", LIMITS).sheet_name == "Suppliers"
    assert len(read_xlsx(workbook, "Suppliers", LIMITS).rows) == 2
    assert read_xlsx(workbook, " Projects ", LIMITS).headers_original == ("Project Code",)


def test_xlsx_with_several_data_sheets_needs_a_choice() -> None:
    workbook = xlsx_bytes({"Projects": [["Project Code"], ["P1"]], "Notes": [["remember this"]]})

    with pytest.raises(SourceFileError) as failure:
        read_xlsx(workbook, None, LIMITS)

    assert failure.value.code == "AMBIGUOUS_WORKSHEET"
    assert "Projects" in failure.value.message
    assert "Notes" in failure.value.message


def test_xlsx_with_one_data_sheet_among_empty_ones_is_unambiguous() -> None:
    workbook = xlsx_bytes({"Empty": [], "Projects": [["Project Code"], ["P1"]], "Blank": [[None]]})

    assert read_xlsx(workbook, None, LIMITS).sheet_name == "Projects"


def test_xlsx_unknown_sheet_and_empty_workbook() -> None:
    with refused("WORKSHEET_NOT_FOUND"):
        read_xlsx(xlsx_bytes({"Projects": [["Project Code"], ["P1"]]}), "Suppliers", LIMITS)
    with refused("EMPTY_FILE"):
        read_xlsx(xlsx_bytes({"Empty": []}), None, LIMITS)


def test_hidden_sheets_are_not_picked_automatically() -> None:
    workbook = Workbook()
    visible = workbook.active
    assert visible is not None
    visible.title = "Visible"
    visible.append(["Project Code"])
    visible.append(["P1"])
    hidden = workbook.create_sheet("Hidden")
    hidden.append(["Project Code"])
    hidden.append(["P9"])
    hidden.sheet_state = "hidden"
    buffer = io.BytesIO()
    workbook.save(buffer)

    assert read_xlsx(buffer.getvalue(), None, LIMITS).sheet_name == "Visible"


@pytest.mark.parametrize(
    "content",
    [
        b"Project Code,Project Name\nP1,One\n",  # a text file named .xlsx
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,  # legacy binary .xls signature
        b"",
    ],
)
def test_non_workbook_content_is_unsupported(content: bytes) -> None:
    with refused("UNSUPPORTED_FILE"):
        read_xlsx(content, None, LIMITS)


def test_an_arbitrary_zip_is_not_a_workbook() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a workbook")

    with refused("UNSUPPORTED_FILE"):
        read_xlsx(buffer.getvalue(), None, LIMITS)


def test_a_truncated_workbook_is_malformed() -> None:
    workbook = xlsx_bytes({"Projects": [["Project Code"], ["P1"]]})

    with refused("MALFORMED_FILE"):
        read_xlsx(workbook[: len(workbook) // 2], None, LIMITS)


def _rewrite(
    workbook: bytes, *, add: dict[str, str] | None = None, replace: dict[str, bytes] | None = None
) -> bytes:
    """Copy a workbook archive, adding or replacing parts."""
    source = zipfile.ZipFile(io.BytesIO(workbook))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            data = (replace or {}).get(entry.filename, source.read(entry.filename))
            target.writestr(entry, data)
        for name, text in (add or {}).items():
            target.writestr(name, text)
    return buffer.getvalue()


def test_macro_enabled_workbooks_are_refused_even_when_named_xlsx() -> None:
    workbook = xlsx_bytes({"Projects": [["Project Code"], ["P1"]]})

    with refused("UNSUPPORTED_FILE"):
        read_xlsx(_rewrite(workbook, add={"xl/vbaProject.bin": "macro"}), None, LIMITS)

    content_types = zipfile.ZipFile(io.BytesIO(workbook)).read("[Content_Types].xml")
    as_xlsm = content_types.replace(
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    )
    with refused("UNSUPPORTED_FILE"):
        read_xlsx(_rewrite(workbook, replace={"[Content_Types].xml": as_xlsm}), None, LIMITS)


def test_a_workbook_that_is_too_large_uncompressed_is_refused_before_parsing() -> None:
    workbook = xlsx_bytes({"Projects": [["Project Code"], ["P1"]]})
    padded = _rewrite(workbook, add={"xl/media/padding.bin": "0" * 200_000})
    tight = ReaderLimits(
        max_rows=100, max_columns=10, max_cell_chars=50, max_uncompressed_bytes=100_000
    )

    assert len(padded) < 100_000  # small on the wire, large once inflated
    with refused("FILE_TOO_LARGE"):
        read_xlsx(padded, None, tight)


def test_xlsx_row_and_column_limits() -> None:
    tall = xlsx_bytes({"S": [["Project Code"], *[[f"P{i}"] for i in range(LIMITS.max_rows + 1)]]})
    wide = xlsx_bytes({"S": [[f"H{i}" for i in range(LIMITS.max_columns + 1)], ["x"] * 11]})

    with refused("ROW_LIMIT_EXCEEDED"):
        read_xlsx(tall, None, LIMITS)
    with refused("COLUMN_LIMIT_EXCEEDED"):
        read_xlsx(wide, None, LIMITS)


def _workbook_with_formulas() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Items"
    sheet.append(["PO Number", "Quantity", "Unit Price"])
    sheet.append(["PO-1", "=1+1", 10])
    sheet.append(["PO-2", 3, 20])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_a_formula_without_a_stored_result_is_reported_and_not_evaluated() -> None:
    """openpyxl writes the formula text and no cached value, as an unsaved export would."""
    sheet = read_xlsx(_workbook_with_formulas(), None, LIMITS)

    first, second = sheet.rows
    assert first.formula_cells == ("Quantity",)
    # Not 2: the formula was not computed, and its text is not passed on as a value.
    assert first.raw_data["Quantity"] is None
    assert second.formula_cells == ()
    assert second.raw_data["Quantity"] == 3


def test_a_formula_with_a_stored_result_uses_that_result_and_says_so() -> None:
    workbook = _workbook_with_formulas()
    sheet_xml = zipfile.ZipFile(io.BytesIO(workbook)).read("xl/worksheets/sheet1.xml")
    assert b"<f>1+1</f><v></v>" in sheet_xml or b"<f>1+1</f>" in sheet_xml
    with_cache = sheet_xml.replace(b"<f>1+1</f><v></v>", b"<f>1+1</f><v>2</v>").replace(
        b"<f>1+1</f><v />", b"<f>1+1</f><v>2</v>"
    )
    if with_cache == sheet_xml:
        with_cache = sheet_xml.replace(b"<f>1+1</f>", b"<f>1+1</f><v>2</v>")

    sheet = read_xlsx(
        _rewrite(workbook, replace={"xl/worksheets/sheet1.xml": with_cache}), None, LIMITS
    )

    assert sheet.rows[0].raw_data["Quantity"] == 2
    assert sheet.rows[0].formula_cells == ()
    assert [issue.code for issue in sheet.warnings] == ["FORMULA_CACHED_VALUE_USED"]
