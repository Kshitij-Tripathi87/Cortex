from pathlib import Path

import pytest

from app.modules.sources.row_parser import SourceRowParseError, parse_source_rows


def test_csv_parser_preserves_row_values_and_normalizes_headers():
    rows = parse_source_rows(
        b" SKU , Description , Quantity\nC-01,  Bolt  ,12\nC-02,Nut,8\n",
        "materials.csv",
    )
    assert rows == [
        {"SKU": "C-01", "Description": "  Bolt  ", "Quantity": "12"},
        {"SKU": "C-02", "Description": "Nut", "Quantity": "8"},
    ]


def test_csv_parser_rejects_duplicate_headers():
    with pytest.raises(SourceRowParseError, match="SOURCE_HEADER_DUPLICATE"):
        parse_source_rows(b"sku,sku\nA,B\n", "materials.csv")


def test_csv_parser_rejects_row_width_mismatch():
    with pytest.raises(SourceRowParseError, match="SOURCE_ROW_WIDTH_MISMATCH:2"):
        parse_source_rows(b"sku,name\nA\n", "materials.csv")


def test_csv_parser_rejects_row_limit():
    with pytest.raises(SourceRowParseError, match="SOURCE_ROW_LIMIT_EXCEEDED"):
        parse_source_rows(b"sku\nA\nB\n", "materials.csv", max_rows=1)


def test_csv_parser_rejects_unsupported_extension():
    with pytest.raises(SourceRowParseError, match="SOURCE_FILE_TYPE_UNSUPPORTED"):
        parse_source_rows(b"sku\nA\n", "materials.pdf")


def test_csv_parser_rejects_unsupported_encoding():
    with pytest.raises(SourceRowParseError, match="SOURCE_ENCODING_UNSUPPORTED"):
        parse_source_rows(b"sku\n\xff", "materials.csv")
