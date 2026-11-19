"""Read real workbooks with the service's reader and compare with an independent reading.

Usage (from services/api):
    uv run python ../../scripts/compare_workbooks.py <directory with .xlsx files>

The tests read workbooks written by openpyxl or by hand. This script is for
workbooks written by other programs: a spreadsheet program, an ERP export, a
supplier portal. For every worksheet of every file it compares

* what the service's reader returns (streaming, bounded, what an import sees)
* with what openpyxl returns in its ordinary in-memory mode, which does not
  depend on the range a worksheet claims and never leaves a row out.

A worksheet counts as identical when the header row, the row numbers and
every value under a header are the same. A worksheet the reader refuses
(no header over a column with values, a duplicate header, no data) is
reported with the reason; it is a problem only when the reason is not one of
those. Nothing is imported and no database is needed. Exit code 1 when a
worksheet differs or is refused for an unexpected reason.
"""

import io
import re
import sys
import warnings
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.ingestion import readers
from app.ingestion.contracts import ReaderLimits, SourceFileError
from app.ingestion.normalization import is_blank

LIMITS = ReaderLimits(
    max_rows=10_000,
    max_columns=100,
    max_cell_chars=2_000,
    max_uncompressed_bytes=200 * 1024 * 1024,
)
# Reasons for which the reader rightly refuses a worksheet that is not a plain table.
TABLE_RULES = {"EMPTY_FILE", "MISSING_HEADER", "DUPLICATE_HEADER"}


def written_by(data: bytes) -> str:
    """The program named in the workbook's properties, when it names one."""
    try:
        properties = zipfile.ZipFile(io.BytesIO(data)).read("docProps/app.xml").decode("utf-8")
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile):
        return "unknown program"
    name = re.search(r"<Application>(.*?)</Application>", properties)
    version = re.search(r"<AppVersion>(.*?)</AppVersion>", properties)
    return " ".join(part.group(1) for part in (name, version) if part)[:40] or "unknown program"


def reference_rows(sheet: Any) -> list[tuple[int, tuple[Any, ...]]]:
    """Rows that hold anything, as the in-memory reader sees them: (row number, values)."""
    rows = []
    for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        values = tuple(readers._json_cell(value) for value in row)
        if any(not is_blank(value) for value in values):
            rows.append((number, values))
    return rows


def compare(
    data: bytes, title: str, expected: list[tuple[int, tuple[Any, ...]]]
) -> tuple[bool, str]:
    """Whether the reader agrees with the reference for one worksheet, and a note."""
    try:
        parsed = readers.read_xlsx(data, title, LIMITS)
    except SourceFileError as exc:
        return exc.code in TABLE_RULES, f"refused, {exc.code}"
    if not expected:
        return False, "the reader found rows where the reference found none"
    header_number, header = expected[0]
    kept = [index for index, value in enumerate(header) if not is_blank(value)]
    wanted = []
    for number, values in expected[1:]:
        picked = tuple(values[index] if index < len(values) else None for index in kept)
        if any(not is_blank(value) for value in picked):
            wanted.append((number, picked))
    found = [(row.row_number, tuple(row.raw_data.values())) for row in parsed.rows]
    if parsed.header_row_number == header_number and found == wanted:
        return True, f"identical, {len(found)} data row(s)"
    return False, f"DIFFERENT: reader {len(found)} row(s), reference {len(wanted)} row(s)"


def main(directory: str) -> int:
    files = sorted(Path(directory).glob("*.xlsx"))
    problems = 0
    identical = 0
    for path in files:
        data = path.read_bytes()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # openpyxl warns about features it does not keep
            reference = load_workbook(io.BytesIO(data), data_only=True)
            notes = []
            for sheet in reference.worksheets:
                agrees, note = compare(data, sheet.title, reference_rows(sheet))
                problems += 0 if agrees else 1
                identical += 1 if note.startswith("identical") else 0
                notes.append(f"{sheet.title!r}: {note}")
        print(f"{path.name:<36} {written_by(data):<42} " + "; ".join(notes))
    print()
    print(
        f"{len(files)} workbook(s); {identical} worksheet(s) identical cell by cell; "
        f"{problems} problem(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
