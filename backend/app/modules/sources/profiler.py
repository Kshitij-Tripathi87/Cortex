"""Source profiler — column-level profiling of validated source files.

Profiles are deterministic: same file → same profile. Profiles feed schema mapping.
The profiler never mutates source data and never infers business meaning beyond
column-level statistics.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from app.common.enums import ColumnInferredType
from app.modules.sources.validation import _detect_encoding

MAX_SAMPLE_VALUES = 5
MAX_PROFILED_ROWS = 10_000


@dataclass(frozen=True)
class ColumnProfileResult:
    """Per-column profiling output."""

    column_name: str
    column_index: int
    inferred_type: str
    null_ratio: float
    distinct_count: int
    sample_values: list[str]


@dataclass(frozen=True)
class FileProfileResult:
    """Full file profiling output."""

    file_kind: str
    row_count: int
    column_count: int
    columns: list[ColumnProfileResult]
    encoding: str | None


def profile_csv(data: bytes, encoding: str | None = None) -> FileProfileResult:
    """Profile a CSV file. Deterministic and read-only."""
    enc = encoding or _detect_encoding(data) or "utf-8"
    text = data.decode(enc, errors="replace")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return FileProfileResult(
            file_kind="csv", row_count=0, column_count=0, columns=[], encoding=enc
        )

    headers = rows[0]
    data_rows = rows[1:][:MAX_PROFILED_ROWS]
    total_rows = len(rows) - 1

    columns = []
    for col_idx, header in enumerate(headers):
        col_values = [r[col_idx] if col_idx < len(r) else "" for r in data_rows]
        profile = _profile_column(header, col_idx, col_values)
        columns.append(profile)

    return FileProfileResult(
        file_kind="csv",
        row_count=total_rows,
        column_count=len(headers),
        columns=columns,
        encoding=enc,
    )


def profile_xlsx(data: bytes) -> FileProfileResult:
    """Profile an XLSX file. Deterministic and read-only."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = list(next(rows_iter))
    except StopIteration:
        wb.close()
        return FileProfileResult(
            file_kind="xlsx", row_count=0, column_count=0, columns=[], encoding=None
        )

    data_rows: list[list[Any]] = []
    for i, row in enumerate(rows_iter):
        if i >= MAX_PROFILED_ROWS:
            break
        data_rows.append(list(row))

    # Count total rows
    total_rows = ws.max_row - 1 if ws.max_row else len(data_rows)

    columns = []
    for col_idx, header in enumerate(headers):
        col_values: list[str] = []
        for row in data_rows:
            val = row[col_idx] if col_idx < len(row) else None
            col_values.append("" if val is None else str(val))
        profile = _profile_column(
            str(header) if header is not None else f"column_{col_idx}", col_idx, col_values
        )
        columns.append(profile)

    wb.close()
    return FileProfileResult(
        file_kind="xlsx",
        row_count=total_rows,
        column_count=len(headers),
        columns=columns,
        encoding=None,
    )


def _profile_column(name: str, index: int, values: list[str]) -> ColumnProfileResult:
    """Profile a single column from its raw string values."""
    total = len(values)
    if total == 0:
        return ColumnProfileResult(
            column_name=name,
            column_index=index,
            inferred_type=ColumnInferredType.EMPTY.value,
            null_ratio=1.0,
            distinct_count=0,
            sample_values=[],
        )

    non_null = [v for v in values if v.strip() != ""]
    null_count = total - len(non_null)
    null_ratio = null_count / total

    distinct = set(non_null)
    distinct_count = len(distinct)

    inferred_type = _infer_type(non_null)

    sample_values = list(distinct)[:MAX_SAMPLE_VALUES]

    return ColumnProfileResult(
        column_name=name,
        column_index=index,
        inferred_type=inferred_type,
        null_ratio=round(null_ratio, 4),
        distinct_count=distinct_count,
        sample_values=sample_values,
    )


def _infer_type(values: list[str]) -> str:
    """Infer the dominant type of non-null string values."""
    if not values:
        return ColumnInferredType.EMPTY.value

    integer_count = 0
    decimal_count = 0
    date_count = 0
    bool_count = 0

    for v in values:
        v_stripped = v.strip()
        if _is_integer(v_stripped):
            integer_count += 1
        elif _is_decimal(v_stripped):
            decimal_count += 1
        elif _is_boolean(v_stripped):
            bool_count += 1
        elif _is_date(v_stripped):
            date_count += 1

    n = len(values)
    if integer_count / n >= 0.9:
        return ColumnInferredType.INTEGER.value
    if (integer_count + decimal_count) / n >= 0.9:
        return ColumnInferredType.DECIMAL.value
    if bool_count / n >= 0.9:
        return ColumnInferredType.BOOLEAN.value
    if date_count / n >= 0.9:
        return ColumnInferredType.DATE.value
    if integer_count > 0 and (integer_count + decimal_count + date_count + bool_count) / n > 0.3:
        return ColumnInferredType.MIXED.value
    return ColumnInferredType.STRING.value


def _is_integer(val: str) -> bool:
    try:
        int(val)
        return True
    except ValueError:
        return False


def _is_decimal(val: str) -> bool:
    try:
        float(val)
        return "." in val  # distinguish from ints
    except ValueError:
        return False


def _is_boolean(val: str) -> bool:
    return val.lower() in {"true", "false", "yes", "no", "y", "n", "1", "0", "t", "f"}


_DATE_PATTERNS = [
    r"^\d{4}-\d{2}-\d{2}$",
    r"^\d{2}/\d{2}/\d{4}$",
    r"^\d{2}\.\d{2}\.\d{4}$",
    r"^\d{4}/\d{2}/\d{2}$",
]


def _is_date(val: str) -> bool:
    import re

    return any(re.match(pattern, val) for pattern in _DATE_PATTERNS)
