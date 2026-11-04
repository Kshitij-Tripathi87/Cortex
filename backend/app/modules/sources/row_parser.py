"""Bounded row-level parser for source evidence compilation.

The parser is deliberately separate from profiling: profiling may inspect a
sample, while claims and row provenance must be extracted from every row.
"""

from __future__ import annotations

import csv
import io
from pathlib import PurePath
from typing import Any

MAX_SOURCE_ROWS = 100_000
MAX_SOURCE_COLUMNS = 256


class SourceRowParseError(ValueError):
    """Stable, user-safe source parsing error."""


def parse_source_rows(
    data: bytes,
    filename: str,
    *,
    max_rows: int = MAX_SOURCE_ROWS,
    max_columns: int = MAX_SOURCE_COLUMNS,
) -> list[dict[str, Any]]:
    """Parse every data row from an uploaded CSV/XLSX artifact.

    Values are returned as strings (or XLSX scalar values) without guessing
    canonical business meaning. Header whitespace is normalized; row values
    are preserved for source evidence.
    """
    if not data:
        raise SourceRowParseError("SOURCE_FILE_EMPTY")
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".csv":
        return _parse_csv(data, max_rows=max_rows, max_columns=max_columns)
    if suffix == ".xlsx":
        return _parse_xlsx(data, max_rows=max_rows, max_columns=max_columns)
    raise SourceRowParseError("SOURCE_FILE_TYPE_UNSUPPORTED")


def _validate_headers(headers: list[Any], max_columns: int) -> list[str]:
    if not headers:
        raise SourceRowParseError("SOURCE_HEADERS_MISSING")
    if len(headers) > max_columns:
        raise SourceRowParseError("SOURCE_COLUMN_LIMIT_EXCEEDED")
    normalized = [str(value).strip() if value is not None else "" for value in headers]
    if any(not name for name in normalized):
        raise SourceRowParseError("SOURCE_HEADER_EMPTY")
    if len(set(normalized)) != len(normalized):
        raise SourceRowParseError("SOURCE_HEADER_DUPLICATE")
    return normalized


def _parse_csv(
    data: bytes, *, max_rows: int, max_columns: int
) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceRowParseError("SOURCE_ENCODING_UNSUPPORTED") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        headers = _validate_headers(next(reader), max_columns)
    except StopIteration as exc:
        raise SourceRowParseError("SOURCE_HEADERS_MISSING") from exc

    rows: list[dict[str, Any]] = []
    for line_number, values in enumerate(reader, start=2):
        if len(rows) >= max_rows:
            raise SourceRowParseError("SOURCE_ROW_LIMIT_EXCEEDED")
        if not values or (len(values) == 1 and values[0] == ""):
            continue
        if len(values) != len(headers):
            raise SourceRowParseError(f"SOURCE_ROW_WIDTH_MISMATCH:{line_number}")
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _parse_xlsx(
    data: bytes, *, max_rows: int, max_columns: int
) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise SourceRowParseError("XLSX_PARSER_UNAVAILABLE") from exc

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=False, keep_links=False
        )
    except Exception as exc:  # noqa: BLE001 - normalize parser failures
        raise SourceRowParseError("XLSX_INVALID_OR_CORRUPT") from exc

    try:
        worksheet = workbook.active
        iterator = worksheet.iter_rows(values_only=True)
        try:
            headers = _validate_headers(list(next(iterator)), max_columns)
        except StopIteration as exc:
            raise SourceRowParseError("SOURCE_HEADERS_MISSING") from exc

        rows: list[dict[str, Any]] = []
        for row_number, values in enumerate(iterator, start=2):
            if len(rows) >= max_rows:
                raise SourceRowParseError("SOURCE_ROW_LIMIT_EXCEEDED")
            values_list = list(values)
            if not values_list or all(value is None for value in values_list):
                continue
            if len(values_list) > len(headers):
                if any(value is not None for value in values_list[len(headers):]):
                    raise SourceRowParseError(f"SOURCE_ROW_WIDTH_MISMATCH:{row_number}")
            values_list = values_list[:len(headers)]
            if len(values_list) < len(headers):
                values_list.extend([None] * (len(headers) - len(values_list)))
            rows.append(dict(zip(headers, values_list, strict=True)))
        return rows
    finally:
        workbook.close()


__all__ = ["MAX_SOURCE_COLUMNS", "MAX_SOURCE_ROWS", "SourceRowParseError", "parse_source_rows"]
