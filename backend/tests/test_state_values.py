"""Tests for Typed State Values — Program J ADR-016 §3.

Covers:
- Provenance validation
- Typed value class behavior (unit, domain, validate)
- Arithmetic operators on NumericValue
- Factory function create_typed_value()
- TYPE_VALUE_MAP coverage
- StateVariable auto-wrapping
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.world.state_values import (
    Capacity,
    CustomerPriority,
    DemandRate,
    FinancialAmount,
    HealthScore,
    InventoryQuantity,
    LeadTime,
    Margin,
    NumericValue,
    Provenance,
    Revenue,
    SafetyStock,
    StateValue,
    TransitDelay,
    Utilization,
    WorkingCapital,
    create_typed_value,
)
from app.modules.world.world_models import StateVariable, StateVariableType


@pytest.fixture
def fixed_observed_at() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def provenance(fixed_observed_at: datetime) -> Provenance:
    return Provenance(
        observed_at=fixed_observed_at,
        source_event_id="evt_001",
        confidence=0.95,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provenance tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProvenance:
    def test_basic_construction(self, fixed_observed_at: datetime) -> None:
        p = Provenance(observed_at=fixed_observed_at)
        assert p.observed_at == fixed_observed_at
        assert p.source_event_id is None
        assert p.confidence == 1.0

    def test_confidence_bounds_valid(self, fixed_observed_at: datetime) -> None:
        for conf in (0.0, 0.5, 1.0):
            Provenance(observed_at=fixed_observed_at, confidence=conf)

    def test_confidence_below_zero_raises(self, fixed_observed_at: datetime) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Provenance(observed_at=fixed_observed_at, confidence=-0.1)

    def test_confidence_above_one_raises(self, fixed_observed_at: datetime) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Provenance(observed_at=fixed_observed_at, confidence=1.1)

    def test_from_event_factory(self, fixed_observed_at: datetime) -> None:
        p = Provenance.from_event(
            event_id="evt_42",
            occurred_at=fixed_observed_at,
            source_system="erp",
            confidence=0.8,
        )
        assert p.source_event_id == "evt_42"
        assert p.observed_at == fixed_observed_at
        assert p.source_system == "erp"
        assert p.confidence == 0.8

    def test_immutable(self, provenance: Provenance) -> None:
        with pytest.raises((AttributeError, Exception)):  # frozen dataclass
            provenance.confidence = 0.5  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Concrete typed value tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInventoryQuantity:
    def test_construction_and_default_unit(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=100, provenance=provenance)
        assert v.value == 100
        assert v.unit == "units"
        assert v.domain == "inventory"

    def test_validate_non_negative(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=10, provenance=provenance)
        assert v.validate() == []

        v_neg = InventoryQuantity(value=-5, provenance=provenance)
        assert any("negative" in e for e in v_neg.validate())


class TestCapacity:
    def test_default_unit(self, provenance: Provenance) -> None:
        v = Capacity(value=75.0, provenance=provenance)
        assert v.unit == "percent"
        assert v.domain == "capacity"

    def test_validate_negative(self, provenance: Provenance) -> None:
        v = Capacity(value=-10.0, provenance=provenance)
        assert any("negative" in e for e in v.validate())


class TestDemandRate:
    def test_default_unit(self, provenance: Provenance) -> None:
        v = DemandRate(value=50, provenance=provenance)
        assert v.unit == "units/day"
        assert v.domain == "demand"


class TestLeadTime:
    def test_default_unit(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        assert v.unit == "days"
        assert v.domain == "lead_time"

    def test_validate_non_negative(self, provenance: Provenance) -> None:
        v = LeadTime(value=-1, provenance=provenance)
        assert any("negative" in e for e in v.validate())


class TestTransitDelay:
    def test_default_unit(self, provenance: Provenance) -> None:
        v = TransitDelay(value=3, provenance=provenance)
        assert v.unit == "days"
        assert v.domain == "transit_delay"


class TestUtilization:
    def test_in_range(self, provenance: Provenance) -> None:
        for pct in (0, 50, 100):
            v = Utilization(value=pct, provenance=provenance)
            assert v.validate() == []

    def test_out_of_range(self, provenance: Provenance) -> None:
        for pct in (-1, 101):
            v = Utilization(value=pct, provenance=provenance)
            assert any("[0, 100]" in e for e in v.validate())


class TestHealthScore:
    def test_in_range(self, provenance: Provenance) -> None:
        for s in (0.0, 0.5, 1.0):
            v = HealthScore(value=s, provenance=provenance)
            assert v.validate() == []

    def test_out_of_range(self, provenance: Provenance) -> None:
        v = HealthScore(value=1.5, provenance=provenance)
        assert any("[0.0, 1.0]" in e for e in v.validate())


class TestCustomerPriority:
    def test_in_range(self, provenance: Provenance) -> None:
        for lvl in (1, 3, 5):
            v = CustomerPriority(value=lvl, provenance=provenance)
            assert v.validate() == []

    def test_out_of_range(self, provenance: Provenance) -> None:
        for lvl in (0, 6):
            v = CustomerPriority(value=lvl, provenance=provenance)
            assert any("[1, 5]" in e for e in v.validate())


class TestFinancialAmountFamily:
    def test_revenue(self, provenance: Provenance) -> None:
        v = Revenue(value=1000.0, provenance=provenance)
        assert v.domain == "revenue"

    def test_working_capital(self, provenance: Provenance) -> None:
        v = WorkingCapital(value=50000.0, provenance=provenance)
        assert v.domain == "working_capital"

    def test_financial_default_unit_usd(self, provenance: Provenance) -> None:
        v = FinancialAmount(value=100.0, provenance=provenance)
        assert v.unit == "USD"


class TestMargin:
    def test_in_range(self, provenance: Provenance) -> None:
        for m in (-100, 0, 50, 100):
            v = Margin(value=m, provenance=provenance)
            assert v.validate() == []

    def test_out_of_range(self, provenance: Provenance) -> None:
        v = Margin(value=150, provenance=provenance)
        assert any("[-100, 100]" in e for e in v.validate())


# ─────────────────────────────────────────────────────────────────────────────
# Arithmetic operator tests
# ─────────────────────────────────────────────────────────────────────────────


class TestArithmetic:
    def test_add_with_scalar(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=100, provenance=provenance)
        result = v + 50
        assert result.value == 150
        assert isinstance(result, InventoryQuantity)
        # provenance preserved through arithmetic
        assert result.provenance == provenance

    def test_add_with_numeric_value(self, provenance: Provenance) -> None:
        a = InventoryQuantity(value=100, provenance=provenance)
        b = InventoryQuantity(value=25, provenance=provenance)
        result = a + b
        assert result.value == 125

    def test_sub_with_scalar(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=100, provenance=provenance)
        result = v - 30
        assert result.value == 70

    def test_mul_with_scalar(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        result = v * 2
        assert result.value == 28

    def test_truediv_with_scalar(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        result = v / 2
        assert result.value == 7

    def test_truediv_by_zero_raises(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        with pytest.raises(ZeroDivisionError):
            _ = v / 0

    def test_comparison_operators(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        assert v < 20
        assert v <= 14
        assert v > 10
        assert v >= 14

    def test_float_conversion(self, provenance: Provenance) -> None:
        v = Capacity(value=75.5, provenance=provenance)
        assert float(v) == 75.5

    def test_int_conversion(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=100, provenance=provenance)
        assert int(v) == 100

    def test_arithmetic_preserves_unit(self, provenance: Provenance) -> None:
        v = LeadTime(value=14, provenance=provenance)
        result = v + 1
        assert result.unit == "days"


# ─────────────────────────────────────────────────────────────────────────────
# Factory + registry tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateTypedValue:
    @pytest.mark.parametrize(
        "var_type,cls",
        [
            (StateVariableType.INVENTORY, InventoryQuantity),
            (StateVariableType.SAFETY_STOCK, SafetyStock),
            (StateVariableType.DEMAND, DemandRate),
            (StateVariableType.LEAD_TIME, LeadTime),
            (StateVariableType.CAPACITY, Capacity),
            (StateVariableType.SUPPLIER_HEALTH, HealthScore),
            (StateVariableType.WAREHOUSE_UTILIZATION, Utilization),
            (StateVariableType.TRANSIT_DELAY, TransitDelay),
            (StateVariableType.CUSTOMER_PRIORITY, CustomerPriority),
            (StateVariableType.REVENUE, Revenue),
            (StateVariableType.MARGIN, Margin),
            (StateVariableType.WORKING_CAPITAL, WorkingCapital),
        ],
    )
    def test_factory_creates_correct_type(
        self, var_type: StateVariableType, cls: type[NumericValue], provenance: Provenance
    ) -> None:
        v = create_typed_value(variable_type=var_type, value=42, provenance=provenance)
        assert isinstance(v, cls)

    def test_factory_auto_unit(self, provenance: Provenance) -> None:
        v = create_typed_value(
            variable_type=StateVariableType.LEAD_TIME, value=14, provenance=provenance
        )
        assert v.unit == "days"

    def test_factory_custom_unit(self, provenance: Provenance) -> None:
        v = create_typed_value(
            variable_type=StateVariableType.LEAD_TIME,
            value=14,
            provenance=provenance,
            unit="weeks",
        )
        assert v.unit == "weeks"


# ─────────────────────────────────────────────────────────────────────────────
# StateVariable auto-wrap tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStateVariableAutoWrap:
    def test_raw_int_wraps_to_typed(self, fixed_observed_at: datetime) -> None:
        v = StateVariable(
            variable_id="inventory.wh_001.comp_042",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_042",
            entity_type="warehouse",
            value=100,
        )
        assert isinstance(v.value, InventoryQuantity)
        assert v.raw_value == 100

    def test_raw_float_wraps_to_typed(self) -> None:
        v = StateVariable(
            variable_id="capacity.factory.fac_001",
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_001",
            entity_type="factory",
            value=75.5,
        )
        assert isinstance(v.value, Capacity)
        assert v.raw_value == 75.5

    def test_unit_auto_populated_from_typed_value(self) -> None:
        v = StateVariable(
            variable_id="lead_time.supplier.sup_001",
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_001",
            entity_type="supplier",
            value=14,
        )
        assert v.unit == "days"

    def test_typed_value_passes_through(self, provenance: Provenance) -> None:
        typed = InventoryQuantity(value=50, provenance=provenance)
        v = StateVariable(
            variable_id="inventory.wh_001.comp_042",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_042",
            entity_type="warehouse",
            value=typed,
        )
        assert v.value is typed

    def test_to_dict_uses_raw_value(self) -> None:
        v = StateVariable(
            variable_id="inventory.wh_001.comp_042",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_042",
            entity_type="warehouse",
            value=100,
        )
        d = v.to_dict()
        assert d["value"] == 100
        assert d["unit"] == "units"


# ─────────────────────────────────────────────────────────────────────────────
# StateValue abstract base + to_dict tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStateValueABC:
    def test_abstract_cannot_instantiate(self, provenance: Provenance) -> None:
        with pytest.raises(TypeError):
            StateValue(value=1, provenance=provenance)  # type: ignore[abstract]

    def test_to_dict(self, provenance: Provenance) -> None:
        v = InventoryQuantity(value=42, provenance=provenance)
        d = v.to_dict()
        assert d["domain"] == "inventory"
        assert d["value"] == 42
        assert d["unit"] == "units"
        assert d["provenance"]["source_event_id"] == provenance.source_event_id
        assert d["provenance"]["confidence"] == 0.95
