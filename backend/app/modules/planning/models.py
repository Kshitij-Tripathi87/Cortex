"""Typed, ORM-free contracts for deterministic material planning.

All quantities use Decimal. Dates are plant-local business dates; callers must
convert timestamps into the facility calendar before constructing inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Mapping


class ItemType(StrEnum):
    PRODUCT = "product"
    COMPONENT = "component"


class ProjectionStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    NOT_CALCULABLE = "not_calculable"


class QuantityBasis(StrEnum):
    PHYSICAL_ON_HAND = "physical_on_hand"
    AVAILABLE_TO_USE = "available_to_use"
    FREE_STOCK = "free_stock"


def as_decimal(value: Decimal | int | str) -> Decimal:
    """Convert external numeric values without introducing binary float error."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("float quantities are not accepted; use Decimal or str")
    return Decimal(value)


@dataclass(frozen=True, slots=True)
class UOMConverter:
    """Explicit one-way or two-way UOM factors; no inferred cross-dimension math."""

    factors: Mapping[tuple[str, str], Decimal] = field(default_factory=dict)

    def convert(self, quantity: Decimal, from_uom: str, to_uom: str) -> Decimal:
        source = from_uom.strip().upper()
        target = to_uom.strip().upper()
        if not source or not target:
            raise ValueError("UOM_MISSING")
        if source == target:
            return quantity
        factor = self.factors.get((source, target))
        if factor is None:
            reverse = self.factors.get((target, source))
            if reverse is not None and reverse != 0:
                factor = Decimal(1) / reverse
        if factor is None or factor <= 0:
            raise ValueError(f"UOM_CONVERSION_MISSING:{source}:{target}")
        return quantity * factor


@dataclass(frozen=True, slots=True)
class BOMLine:
    line_id: str
    child_item_id: str
    child_item_type: ItemType
    usage_quantity: Decimal
    usage_uom: str
    child_base_uom: str
    child_is_assembly: bool = False
    # None means the source supplied no scrap factor; no additional scrap is applied.
    scrap_factor: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None

    def is_effective_at(self, effective_at: date) -> bool:
        return (self.valid_from is None or self.valid_from <= effective_at) and (
            self.valid_to is None or effective_at <= self.valid_to
        )


@dataclass(frozen=True, slots=True)
class BOMRevision:
    revision_id: str
    parent_item_id: str
    parent_item_type: ItemType
    revision_code: str
    lines: tuple[BOMLine, ...]
    valid_from: date | None = None
    valid_to: date | None = None
    facility_id: str | None = None
    active: bool = True

    def is_effective_at(self, effective_at: date, facility_id: str) -> bool:
        if not self.active:
            return False
        if self.facility_id is not None and self.facility_id != facility_id:
            return False
        return (self.valid_from is None or self.valid_from <= effective_at) and (
            self.valid_to is None or effective_at <= self.valid_to
        )


@dataclass(frozen=True, slots=True)
class ExplicitMaterialRequirement:
    requirement_id: str
    material_id: str
    quantity: Decimal
    uom: str
    need_at: date
    reserved_quantity: Decimal = Decimal("0")
    reservation_linked: bool = False
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ProductionOrder:
    order_id: str
    facility_id: str
    item_id: str
    item_type: ItemType
    quantity: Decimal
    order_uom: str
    item_base_uom: str
    material_need_at: date
    status: str
    bom_revision_id: str | None = None
    explicit_requirements: tuple[ExplicitMaterialRequirement, ...] = ()
    explicit_requirements_authoritative: bool = False
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DemandContribution:
    contribution_id: str
    production_order_id: str
    facility_id: str
    material_id: str
    gross_quantity: Decimal
    reserved_quantity: Decimal
    reservation_linked: bool
    uncovered_quantity: Decimal
    uom: str
    need_at: date
    bom_line_path: tuple[str, ...] = ()
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class OrderRequirementsResult:
    production_order_id: str
    status: ProjectionStatus
    contributions: tuple[DemandContribution, ...]
    warnings: tuple[str, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryBalanceInput:
    workspace_id: str
    snapshot_id: str
    facility_id: str
    material_id: str
    as_of: date
    quantity: Decimal
    quantity_basis: QuantityBasis
    safety_stock_quantity: Decimal
    reserved_quantity: Decimal | None = None
    blocked_quantity: Decimal | None = None
    # For AVAILABLE_TO_USE/FREE_STOCK, these flags document source semantics.
    basis_excludes_reserved: bool | None = None
    basis_excludes_blocked: bool | None = None
    uom: str = "EA"
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialReceipt:
    receipt_id: str
    facility_id: str
    material_id: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    expected_date: date | None
    status: str
    confirmed: bool
    uom: str
    open_quantity: Decimal | None = None
    supplier_id: str | None = None
    source_ref: str | None = None

    def remaining_open_quantity(self) -> Decimal:
        remaining = (
            self.open_quantity
            if self.open_quantity is not None
            else self.ordered_quantity - self.received_quantity
        )
        if remaining < 0:
            raise ValueError(f"RECEIPT_OPEN_QUANTITY_NEGATIVE:{self.receipt_id}")
        return remaining


@dataclass(frozen=True, slots=True)
class DailyInventoryBucket:
    bucket_date: date
    opening_quantity: Decimal
    confirmed_receipts: Decimal
    uncertain_receipts: Decimal
    uncovered_demand: Decimal
    closing_quantity: Decimal
    safety_stock_quantity: Decimal
    status: str
    demand_refs: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryProjection:
    workspace_id: str
    snapshot_id: str
    facility_id: str
    material_id: str
    status: ProjectionStatus
    quantity_basis: QuantityBasis
    uom: str
    start_date: date
    end_date: date
    opening_usable_quantity: Decimal
    first_safety_stock_breach: date | None
    first_negative_balance: date | None
    daily_buckets: tuple[DailyInventoryBucket, ...]
    uncertain_receipts_excluded: Decimal
    uncovered_requirement_quantity: Decimal
    warnings: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
