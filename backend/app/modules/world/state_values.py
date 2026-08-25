"""Typed State Values — Domain-Specific Value Types for World State.

Program J (World State & Digital Twin) — ADR-016 §3.

Replaces the generic `float | int | str` value typing with typed
per-domain wrapper classes. This gives Cortex:

- Strong typing for arithmetic operations (no more `float | int | str + int` mypy errors)
- Domain semantics: Capacity is always a percentage, LeadTime is always in days
- Provenance + freshness separated from the value itself
- Safe surface for simulation arithmetic, feature extraction, GNN input construction,
  RL state vectors, validation, unit conversion, and financial calculations

Architecture:
    StateValue (abstract base)
    ├── NumericValue (base for all numeric domains)
    │   ├── InventoryQuantity      (int, units, ≥ 0)
    │   ├── Capacity               (float [0..100], percent)
    │   ├── DemandRate             (int, units/day)
    │   ├── LeadTime               (int, days, ≥ 0)
    │   ├── TransitDelay           (int, days, ≥ 0)
    │   ├── Utilization            (float [0..100], percent)
    │   ├── HealthScore            (float [0..1], ratio)
    │   ├── FinancialAmount        (float, currency)
    │   ├── Margin                 (float [-100..100], percent)
    │   └── WorkingCapital         (float, USD)
    └── Provenance (separate from value)
        ├── observed_at    (when the source event occurred)
        ├── effective_at   (when the value takes effect)
        ├── expires_at     (for forecasts; None for facts)
        ├── source_event_id
        ├── source_system
        └── confidence     (0..1, separate from value)

Key design principles:
- Value is the actual numeric/string quantity
- Provenance/freshness are SEPARATE fields, never mixed into the value
- `inventory = 500 ± confidence` is FORBIDDEN; instead:
    InventoryQuantity(value=500, confidence=0.95, ...)
- This separation matters enormously for ML (Programs L/M/N) where
  "is this number a fact or a forecast?" must be unambiguous
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.world.world_models import StateVariableType

# Deferred runtime import to avoid circular dependency with world_models
from app.modules.world.world_models import StateVariableType  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Provenance — separated from value per ADR-016 §3
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Provenance:
    """Provenance and freshness metadata for a StateValue.

    Separated from the value itself per ADR-016 §3. Programs L/M/N
    (RL, Multi-Agent, Execution Plane) need this separation to
    disambiguate "is this number a fact or a forecast?" without
    encoding confidence into the value (e.g., `value ± confidence`).
    """

    observed_at: datetime  # When the source event occurred
    source_event_id: str | None = None  # Event that produced this value
    source_system: str | None = None  # System that recorded the event
    effective_at: datetime | None = None  # When the value takes effect (may be future)
    expires_at: datetime | None = None  # For forecasts; None for facts
    confidence: float = 1.0  # 0..1; separate from value
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    @classmethod
    def from_event(
        cls,
        event_id: str,
        occurred_at: datetime,
        source_system: str | None = None,
        confidence: float = 1.0,
    ) -> Provenance:
        """Factory: create Provenance from an event's identity."""
        return cls(
            observed_at=occurred_at,
            source_event_id=event_id,
            source_system=source_system,
            confidence=confidence,
        )


# ─────────────────────────────────────────────────────────────────────────────
# StateValue — abstract base for all typed values
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateValue(ABC):
    """Abstract base for all typed World State values.

    Every concrete value type carries:
    - A domain-specific numeric/string `value`
    - `Provenance` with observed_at, source_event_id, confidence, etc.
    - `unit` (e.g., "units", "days", "percent")

    Subclasses MUST:
    - Override `domain` property
    - Implement `validate()` for domain-specific range checks
    - Implement arithmetic operators if applicable

    Provenance is ALWAYS separate from the value.
    """

    value: float | int | str
    provenance: Provenance
    unit: str | None = None

    @property
    @abstractmethod
    def domain(self) -> str:
        """The domain this value belongs to (e.g., 'inventory', 'capacity')."""

    def validate(self) -> list[str]:
        """Return list of validation error messages (empty if valid)."""
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "value": self.value,
            "unit": self.unit,
            "provenance": {
                "observed_at": self.provenance.observed_at.isoformat(),
                "source_event_id": self.provenance.source_event_id,
                "source_system": self.provenance.source_system,
                "effective_at": self.provenance.effective_at.isoformat()
                if self.provenance.effective_at
                else None,
                "expires_at": self.provenance.expires_at.isoformat()
                if self.provenance.expires_at
                else None,
                "confidence": self.provenance.confidence,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# NumericValue — base for all numeric domain values
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NumericValue(StateValue):
    """Base for numeric StateValues with arithmetic support."""

    value: float | int  # type: ignore[assignment]

    def __add__(self, other: NumericValue | float | int) -> NumericValue:
        if isinstance(other, NumericValue):
            new_value = self.value + other.value
        else:
            new_value = self.value + other
        return self._with_new_value(new_value)

    def __sub__(self, other: NumericValue | float | int) -> NumericValue:
        if isinstance(other, NumericValue):
            new_value = self.value - other.value
        else:
            new_value = self.value - other
        return self._with_new_value(new_value)

    def __mul__(self, other: NumericValue | float | int) -> NumericValue:
        if isinstance(other, NumericValue):
            new_value = self.value * other.value
        else:
            new_value = self.value * other
        return self._with_new_value(new_value)

    def __truediv__(self, other: NumericValue | float | int) -> NumericValue:
        divisor = other.value if isinstance(other, NumericValue) else other
        if divisor == 0:
            raise ZeroDivisionError(f"division by zero in {self.domain}")
        new_value = self.value / divisor
        return self._with_new_value(new_value)

    def __lt__(self, other: NumericValue | float | int) -> bool:
        if isinstance(other, NumericValue):
            return self.value < other.value
        return self.value < other

    def __le__(self, other: NumericValue | float | int) -> bool:
        if isinstance(other, NumericValue):
            return self.value <= other.value
        return self.value <= other

    def __gt__(self, other: NumericValue | float | int) -> bool:
        if isinstance(other, NumericValue):
            return self.value > other.value
        return self.value > other

    def __ge__(self, other: NumericValue | float | int) -> bool:
        if isinstance(other, NumericValue):
            return self.value >= other.value
        return self.value >= other

    def __float__(self) -> float:
        return float(self.value)

    def __int__(self) -> int:
        return int(self.value)

    def _with_new_value(self, new_value: float | int) -> NumericValue:
        """Create a new instance with the same provenance but updated value."""
        # Use object.__setattr__ to bypass frozen (we're creating a new instance)
        new_instance = self.__class__.__new__(self.__class__)
        object.__setattr__(new_instance, "value", new_value)
        object.__setattr__(new_instance, "provenance", self.provenance)
        object.__setattr__(new_instance, "unit", self.unit)
        return new_instance


# ─────────────────────────────────────────────────────────────────────────────
# Concrete Domain Value Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InventoryQuantity(NumericValue):
    """Inventory quantity in units (always ≥ 0).

    Domain: inventory
    Unit: "units" (default)
    Range: ≥ 0
    """

    unit: str | None = "units"

    @property
    def domain(self) -> str:
        return "inventory"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0:
            errors.append(f"InventoryQuantity cannot be negative: {self.value}")
        return errors


@dataclass(frozen=True)
class SafetyStock(NumericValue):
    """Safety stock level in units (always ≥ 0).

    Domain: safety_stock
    Unit: "units" (default)
    Range: ≥ 0
    """

    unit: str | None = "units"

    @property
    def domain(self) -> str:
        return "safety_stock"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0:
            errors.append(f"SafetyStock cannot be negative: {self.value}")
        return errors


@dataclass(frozen=True)
class Capacity(NumericValue):
    """Factory capacity utilization as percentage (0..100).

    Domain: capacity
    Unit: "percent"
    Range: [0, 100] (values > 100 are warnings, not errors)
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "percent"

    @property
    def domain(self) -> str:
        return "capacity"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0:
            errors.append(f"Capacity cannot be negative: {self.value}")
        return errors


@dataclass(frozen=True)
class DemandRate(NumericValue):
    """Demand rate in units/day.

    Domain: demand
    Unit: "units/day" (default)
    Range: unrestricted (can be negative for demand decrease)
    """

    unit: str | None = "units/day"

    @property
    def domain(self) -> str:
        return "demand"


@dataclass(frozen=True)
class LeadTime(NumericValue):
    """Lead time in days (always ≥ 0).

    Domain: lead_time
    Unit: "days" (default)
    Range: ≥ 0
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "days"

    @property
    def domain(self) -> str:
        return "lead_time"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0:
            errors.append(f"LeadTime cannot be negative: {self.value}")
        return errors


@dataclass(frozen=True)
class TransitDelay(NumericValue):
    """Transit delay in days (always ≥ 0).

    Domain: transit_delay
    Unit: "days" (default)
    Range: ≥ 0
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "days"

    @property
    def domain(self) -> str:
        return "transit_delay"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0:
            errors.append(f"TransitDelay cannot be negative: {self.value}")
        return errors


@dataclass(frozen=True)
class Utilization(NumericValue):
    """Warehouse utilization as percentage (0..100).

    Domain: warehouse_utilization
    Unit: "percent"
    Range: [0, 100]
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "percent"

    @property
    def domain(self) -> str:
        return "warehouse_utilization"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0 or self.value > 100:
            errors.append(f"Utilization must be in [0, 100]: {self.value}")
        return errors


@dataclass(frozen=True)
class HealthScore(NumericValue):
    """Supplier health score as ratio (0.0..1.0).

    Domain: supplier_health
    Unit: "ratio"
    Range: [0.0, 1.0]
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "ratio"

    @property
    def domain(self) -> str:
        return "supplier_health"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 0.0 or self.value > 1.0:
            errors.append(f"HealthScore must be in [0.0, 1.0]: {self.value}")
        return errors


@dataclass(frozen=True)
class CustomerPriority(NumericValue):
    """Customer priority score (1..5, where 5 is highest).

    Domain: customer_priority
    Unit: "level" (default)
    Range: [1, 5]
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "level"

    @property
    def domain(self) -> str:
        return "customer_priority"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < 1 or self.value > 5:
            errors.append(f"CustomerPriority must be in [1, 5]: {self.value}")
        return errors


@dataclass(frozen=True)
class FinancialAmount(NumericValue):
    """Financial amount in a specific currency.

    Domain: revenue, working_capital, etc.
    Unit: currency code (e.g., "USD", "EUR")
    Range: unrestricted (can be negative for losses)
    """

    unit: str | None = "USD"

    @property
    def domain(self) -> str:
        return "financial"


@dataclass(frozen=True)
class Revenue(FinancialAmount):
    """Revenue in currency units.

    Domain: revenue
    """

    @property
    def domain(self) -> str:
        return "revenue"


@dataclass(frozen=True)
class Margin(NumericValue):
    """Margin as percentage (-100..100).

    Domain: margin
    Unit: "percent"
    Range: [-100, 100]
    """

    value: float | int  # type: ignore[assignment]
    unit: str | None = "percent"

    @property
    def domain(self) -> str:
        return "margin"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.value < -100 or self.value > 100:
            errors.append(f"Margin must be in [-100, 100]: {self.value}")
        return errors


@dataclass(frozen=True)
class WorkingCapital(FinancialAmount):
    """Working capital in currency units.

    Domain: working_capital
    """

    @property
    def domain(self) -> str:
        return "working_capital"


# ─────────────────────────────────────────────────────────────────────────────
# Type Registry — maps StateVariableType to typed value class
# ─────────────────────────────────────────────────────────────────────────────


TYPE_VALUE_MAP: dict[StateVariableType, type[NumericValue]] = {
    StateVariableType.INVENTORY: InventoryQuantity,
    StateVariableType.SAFETY_STOCK: SafetyStock,
    StateVariableType.DEMAND: DemandRate,
    StateVariableType.LEAD_TIME: LeadTime,
    StateVariableType.CAPACITY: Capacity,
    StateVariableType.SUPPLIER_HEALTH: HealthScore,
    StateVariableType.WAREHOUSE_UTILIZATION: Utilization,
    StateVariableType.TRANSIT_DELAY: TransitDelay,
    StateVariableType.CUSTOMER_PRIORITY: CustomerPriority,
    StateVariableType.REVENUE: Revenue,
    StateVariableType.MARGIN: Margin,
    StateVariableType.WORKING_CAPITAL: WorkingCapital,
}


def create_typed_value(
    variable_type: StateVariableType,
    value: float | int | str,
    provenance: Provenance,
    unit: str | None = None,
) -> NumericValue:
    """Factory: create the appropriate typed value for a StateVariableType.

    This is the canonical way to create typed values. Direct construction
    of concrete value classes is also supported but this factory ensures
    the right type is used for each variable_type.
    """
    value_class = TYPE_VALUE_MAP.get(variable_type)
    if value_class is None:
        raise ValueError(f"No typed value class registered for {variable_type}")

    # Use default unit if not specified
    if unit is None:
        # Create a default instance to get the default unit
        default_instance = value_class(value=0, provenance=provenance)
        unit = default_instance.unit

    return value_class(value=value, provenance=provenance, unit=unit)
