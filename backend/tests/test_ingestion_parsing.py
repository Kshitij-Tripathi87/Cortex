"""Ingestion service — pure-function tests for CSV parsing and row validation.

Does not touch the DB or S3: exercises `_parse_csv_bytes` and the
Pydantic row schemas.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.ingestion.service import _build_key, _parse_csv_bytes
from app.modules.supply_chain.schemas import (
    ComponentRow,
    EdgeRow,
    InventoryRow,
    OrderRow,
    SupplierRow,
    WarehouseRow,
)


def test_parse_csv_bytes_strips_whitespace_and_headers() -> None:
    data = b"name, tier, lead_time_days\n ACME , tier_1 , 14"
    rows = _parse_csv_bytes(data)
    assert rows == [{"name": "ACME", "tier": "tier_1", "lead_time_days": "14"}]


def test_parse_csv_bytes_tolerates_bom() -> None:
    data = b"\xef\xbb\xbfsku,name\nCOMP-0001,Widget"
    rows = _parse_csv_bytes(data)
    assert rows == [{"sku": "COMP-0001", "name": "Widget"}]


def test_parse_csv_bytes_empty_input_returns_empty_list() -> None:
    assert _parse_csv_bytes(b"name\n") == []


def test_build_key_uses_workspace_and_run_and_filename() -> None:
    ws = UUID("12345678-1234-5678-1234-567812345678")
    run = UUID("00000000-0000-0000-0000-000000000001")
    key = _build_key(ws, run, "suppliers.csv")
    assert key == f"cortex/ingestion/{ws}/{run}/suppliers.csv"


def test_build_key_strips_path_components_from_filename() -> None:
    ws = UUID("00000000-0000-0000-0000-000000000000")
    run = UUID("00000000-0000-0000-0000-000000000001")
    key = _build_key(ws, run, r"C:\uploads\sub\suppliers.csv")
    assert key.endswith("/suppliers.csv")


def test_supplier_row_validates_minimal_fields() -> None:
    row = SupplierRow(name="ACME", country="US", tier="tier_1", lead_time_days=14)
    assert row.tier.value == "tier_1"
    assert row.status.value == "active"
    assert row.risk_score is None


def test_supplier_row_rejects_bad_country_length() -> None:
    with pytest.raises(ValidationError):
        SupplierRow(name="ACME", country="USA", tier="tier_1", lead_time_days=14)


def test_supplier_row_rejects_negative_lead_time() -> None:
    with pytest.raises(ValidationError):
        SupplierRow(name="ACME", country="US", tier="tier_1", lead_time_days=-1)


def test_component_row_defaults_unit_of_measure() -> None:
    row = ComponentRow(sku="C-1", name="Widget")
    assert row.unit_of_measure == "EA"


def test_warehouse_row_requires_code_and_name() -> None:
    row = WarehouseRow(code="WH-001", name="Main", location="US/East")
    assert row.code == "WH-001"
    with pytest.raises(ValidationError):
        WarehouseRow(code="", name="Main")


def test_edge_row_coerces_enum_to_lowercase() -> None:
    row = EdgeRow(
        from_type="SUPPLIER",
        from_ref="ACME",
        to_type="component",
        to_ref="C-1",
        edge_type="SUPPLIES",
    )
    assert row.from_type.value == "supplier"
    assert row.to_type.value == "component"
    assert row.edge_type.value == "supplies"


def test_inventory_row_validates_quantity_bounds() -> None:
    row = InventoryRow(warehouse_code="WH-001", component_sku="C-1", quantity=0, safety_stock=0)
    assert row.quantity == 0

    with pytest.raises(ValidationError):
        InventoryRow(warehouse_code="WH-001", component_sku="C-1", quantity=-1)


def test_order_row_parses_dates() -> None:
    row = OrderRow(
        customer_name="ACME",
        product_sku="P-1",
        quantity=100,
        status="pending",
        order_date="2026-01-01",
        requested_delivery_date="2026-01-15",
    )
    from datetime import date

    assert row.order_date == date(2026, 1, 1)
    assert row.requested_delivery_date == date(2026, 1, 15)
    assert row.actual_delivery_date is None
