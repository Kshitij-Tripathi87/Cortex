"""The brief adapter hands whole-unit integers to the disruption engines.

Migration 020 widened ``inventory.quantity`` and ``inventory.safety_stock`` to
NUMERIC(18, 4), so the ORM now yields ``Decimal``. The disruption engines mix
these values with float arithmetic, where a ``Decimal`` operand raises
``TypeError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.api.v1.briefs import _to_inventory_data
from app.modules.disruption.engines.impact import DEFAULT_UNIT_COST
from app.modules.supply_chain.models import Inventory


def test_inventory_adapter_converts_numeric_columns_to_whole_units() -> None:
    row = Inventory(
        warehouse_id=uuid4(),
        component_id=uuid4(),
        quantity=Decimal("120.0000"),
        safety_stock=Decimal("40.7500"),
        last_updated_at=datetime(2026, 11, 1, tzinfo=UTC),
    )

    data = _to_inventory_data(row)

    assert type(data.quantity) is int
    assert type(data.safety_stock) is int
    assert data.quantity == 120
    assert data.safety_stock == 40
    # The arithmetic the impact and timeline engines apply to these values.
    assert data.quantity * DEFAULT_UNIT_COST == 3000.0
    assert data.safety_stock * 1.2 == 48.0
