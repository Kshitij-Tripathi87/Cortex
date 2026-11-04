"""Deterministic material planning primitives for Cortex Priority 2.

This module deliberately has no database, HTTP, graph, or LLM dependencies.
It is the calculation core that repository-backed services can call with a
workspace-scoped, immutable input snapshot.

Semantics:
* BOM revision effectivity uses [valid_from, valid_to) dates.
* Recursive BOM explosion uses an ancestry stack, not a global visited set;
  shared components reached through separate branches are counted separately.
* An explicit, authoritative, complete material-requirements list takes
  precedence over BOM explosion. Partial/ambiguous lists fail closed.
* Inventory quantity basis is explicit. PHYSICAL_ON_HAND subtracts reserved
  and blocked quantities; AVAILABLE_TO_USE does not subtract them again.
* Only firm, dated receipts enter the base projection. Other receipts are
  surfaced as excluded uncertainty.
* Receipts expected on a date are available before that date's demand.
* All arithmetic uses Decimal; no inferred financial values are produced.
"""

from __future__ import annotations

import collections
import collections.abc
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_MAX_BOM_DEPTH = 32
DEFAULT_MAX_BOM_LINES = 20_000
DEFAULT_MAX_PROJECTION_DAYS = 366
DEFAULT_FIRM_RECEIPT_STATUSES = frozenset({"approved", "confirmed", "released"})
MATERIAL_PLANNING_VERSION = "1.0.0"


class PlanningInputError(ValueError):
    """A deterministic planning failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CalculationStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"


class QuantityBasis(StrEnum):
    PHYSICAL_ON_HAND = "physical_on_hand"
    AVAILABLE_TO_USE = "available_to_use"


def _decimal(value: Decimal | int | str | float, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PlanningInputError("INVALID_QUANTITY", f"{field_name} is not a valid decimal") from exc
    if not result.is_finite():
        raise PlanningInputError("INVALID_QUANTITY", f"{field_name} must be finite")
    return result


def _positive(value: Decimal, field_name: str, *, allow_zero: bool = False) -> None:
    if value < ZERO or (not allow_zero and value == ZERO):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise PlanningInputError("INVALID_QUANTITY", f"{field_name} must be {qualifier}")


def _uom(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise PlanningInputError("UOM_REQUIRED", "Unit of measure cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class UnitConversion:
    """An explicitly configured conversion: target_qty = source_qty * factor."""

    from_uom: str
    to_uom: str
    factor: Decimal
    conversion_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_uom", _uom(self.from_uom))
        object.__setattr__(self, "to_uom", _uom(self.to_uom))
        factor = _decimal(self.factor, "conversion factor")
        _positive(factor, "conversion factor")
        object.__setattr__(self, "factor", factor)
        if self.from_uom == self.to_uom and factor != ONE:
            raise PlanningInputError(
                "INVALID_UOM_CONVERSION", "A same-unit conversion must have factor 1"
            )


class UnitConverter:
    """Converts only units connected by an explicit configured conversion."""

    def __init__(self, conversions: collections.abc.Iterable[UnitConversion] = ()) -> None:
        self._factors: dict[tuple[str, str], Decimal] = {}
        for conversion in conversions:
            self.add(conversion)

    def add(self, conversion: UnitConversion) -> None:
        direct = (conversion.from_uom, conversion.to_uom)
        inverse = (conversion.to_uom, conversion.from_uom)
        existing = self._factors.get(direct)
        if existing is not None and existing != conversion.factor:
            raise PlanningInputError(
                "AMBIGUOUS_UOM_CONVERSION",
                f"Conflicting conversions configured for {direct[0]} to {direct[1]}",
            )
        inverse_existing = self._factors.get(inverse)
        if inverse_existing is not None and inverse_existing != ONE / conversion.factor:
            raise PlanningInputError(
                "AMBIGUOUS_UOM_CONVERSION",
                f"Conflicting conversions configured for {inverse[0]} to {inverse[1]}",
            )
        self._factors[direct] = conversion.factor
        self._factors[inverse] = ONE / conversion.factor

    def convert(self, quantity: Decimal | int | str, from_uom: str, to_uom: str) -> Decimal:
        amount = _decimal(quantity, "quantity")
        source = _uom(from_uom)
        target = _uom(to_uom)
        if source == target:
            return amount
        factor = self._factors.get((source, target))
        if factor is None:
            raise PlanningInputError(
                "UOM_CONVERSION_MISSING",
                f"No configured conversion exists from {source} to {target}",
            )
        return amount * factor


@dataclass(frozen=True, slots=True)
class BomLine:
    line_id: str
    child_item_id: str
    quantity_per_parent: Decimal
    usage_uom: str
    child_base_uom: str
    scrap_multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.line_id.strip() or not self.child_item_id.strip():
            raise PlanningInputError("INVALID_BOM_LINE", "BOM line and child item IDs are required")
        quantity = _decimal(self.quantity_per_parent, "quantity_per_parent")
        _positive(quantity, "quantity_per_parent")
        object.__setattr__(self, "quantity_per_parent", quantity)
        object.__setattr__(self, "usage_uom", _uom(self.usage_uom))
        object.__setattr__(self, "child_base_uom", _uom(self.child_base_uom))
        if self.scrap_multiplier is not None:
            scrap = _decimal(self.scrap_multiplier, "scrap_multiplier")
            _positive(scrap, "scrap_multiplier")
            object.__setattr__(self, "scrap_multiplier", scrap)


@dataclass(frozen=True, slots=True)
class BomRevision:
    revision_id: str
    parent_item_id: str
    revision_code: str
    parent_base_uom: str
    valid_from: date
    valid_to: date | None
    lines: tuple[BomLine, ...]
    facility_id: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.revision_id or not self.parent_item_id or not self.revision_code:
            raise PlanningInputError("INVALID_BOM_REVISION", "BOM revision identifiers are required")
        object.__setattr__(self, "parent_base_uom", _uom(self.parent_base_uom))
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise PlanningInputError(
                "INVALID_BOM_EFFECTIVITY",
                f"BOM revision {self.revision_id} has an empty or reversed validity interval",
            )
        line_ids = [line.line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise PlanningInputError(
                "DUPLICATE_BOM_LINE", f"BOM revision {self.revision_id} has duplicate line IDs"
            )

    def effective_on(self, on_date: date) -> bool:
        return (
            self.active
            and self.valid_from <= on_date
            and (self.valid_to is None or on_date < self.valid_to)
        )


@dataclass(frozen=True, slots=True)
class ExplicitMaterialRequirement:
    requirement_id: str
    material_id: str
    quantity: Decimal
    uom: str
    material_base_uom: str
    need_at: date | None = None

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.material_id:
            raise PlanningInputError(
                "INVALID_MATERIAL_REQUIREMENT", "Requirement and material IDs are required"
            )
        quantity = _decimal(self.quantity, "material requirement quantity")
        _positive(quantity, "material requirement quantity")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "uom", _uom(self.uom))
        object.__setattr__(self, "material_base_uom", _uom(self.material_base_uom))


@dataclass(frozen=True, slots=True)
class ProductionOrder:
    production_order_id: str
    item_id: str
    facility_id: str
    quantity: Decimal
    quantity_uom: str
    scheduled_date: date
    explicit_requirements: tuple[ExplicitMaterialRequirement, ...] | None = None
    explicit_requirements_complete: bool = False
    explicit_requirements_authoritative: bool = False
    root_bom_revision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.production_order_id or not self.item_id or not self.facility_id:
            raise PlanningInputError(
                "INVALID_PRODUCTION_ORDER", "Production order, item, and facility IDs are required"
            )
        quantity = _decimal(self.quantity, "production order quantity")
        _positive(quantity, "production order quantity")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "quantity_uom", _uom(self.quantity_uom))


@dataclass(frozen=True, slots=True)
class DemandContribution:
    requirement_id: str
    production_order_id: str
    material_id: str
    facility_id: str
    quantity: Decimal
    base_uom: str
    need_at: date
    source_kind: str
    bom_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExplodedRequirements:
    production_order_id: str
    snapshot_id: str
    contributions: tuple[DemandContribution, ...]
    revision_ids: tuple[str, ...]
    calculation_version: str = MATERIAL_PLANNING_VERSION
    status: CalculationStatus = CalculationStatus.COMPLETED
    warnings: tuple[str, ...] = ()


def resolve_bom_revision(
    revisions: collections.abc.Sequence[BomRevision],
    *,
    parent_item_id: str,
    facility_id: str,
    effective_date: date,
    explicit_revision_id: str | None = None,
) -> BomRevision:
    """Resolve one and only one effective BOM revision for a facility/date."""
    if explicit_revision_id is not None:
        matches = [
            revision
            for revision in revisions
            if revision.revision_id == explicit_revision_id
            and revision.parent_item_id == parent_item_id
        ]
        if len(matches) != 1:
            raise PlanningInputError(
                "BOM_REVISION_NOT_FOUND",
                f"Explicit BOM revision {explicit_revision_id} was not found for {parent_item_id}",
            )
        revision = matches[0]
        if not revision.effective_on(effective_date) or (
            revision.facility_id is not None and revision.facility_id != facility_id
        ):
            raise PlanningInputError(
                "BOM_REVISION_NOT_EFFECTIVE",
                f"Explicit BOM revision {explicit_revision_id} is not effective for this order",
            )
        return revision

    candidates = [
        revision
        for revision in revisions
        if revision.parent_item_id == parent_item_id
        and revision.effective_on(effective_date)
        and revision.facility_id in (None, facility_id)
    ]
    facility_specific = [item for item in candidates if item.facility_id == facility_id]
    selected_scope = facility_specific if facility_specific else [
        item for item in candidates if item.facility_id is None
    ]
    if not selected_scope:
        raise PlanningInputError(
            "BOM_REVISION_MISSING",
            f"No effective BOM revision exists for item {parent_item_id} at {facility_id}",
        )
    if len(selected_scope) != 1:
        raise PlanningInputError(
            "BOM_REVISION_AMBIGUOUS",
            f"Multiple effective BOM revisions exist for item {parent_item_id} at {facility_id}",
        )
    return selected_scope[0]


def explode_production_order(
    order: ProductionOrder,
    revisions: collections.abc.Sequence[BomRevision],
    *,
    snapshot_id: str,
    manufactured_item_ids: set[str] | frozenset[str],
    converter: UnitConverter,
    max_depth: int = DEFAULT_MAX_BOM_DEPTH,
    max_lines: int = DEFAULT_MAX_BOM_LINES,
) -> ExplodedRequirements:
    """Explode a production order into leaf material requirements.

    A repeated material in separate BOM branches is intentionally emitted as
    separate contributions. Callers may aggregate by material/date after
    preserving the contributing order and BOM paths for evidence.
    """
    if not snapshot_id.strip():
        raise PlanningInputError("SNAPSHOT_REQUIRED", "BOM explosion requires an immutable snapshot ID")
    if max_depth < 1 or max_lines < 1:
        raise PlanningInputError("INVALID_PLANNING_LIMIT", "BOM limits must be positive")
    if order.explicit_requirements is not None:
        if not (
            order.explicit_requirements_complete
            and order.explicit_requirements_authoritative
        ):
            raise PlanningInputError(
                "EXPLICIT_REQUIREMENTS_INCOMPLETE",
                "Explicit material requirements are present but not marked both complete and authoritative",
            )
        direct: list[DemandContribution] = []
        for requirement in order.explicit_requirements:
            quantity = converter.convert(
                requirement.quantity, requirement.uom, requirement.material_base_uom
            )
            direct.append(
                DemandContribution(
                    requirement_id=requirement.requirement_id,
                    production_order_id=order.production_order_id,
                    material_id=requirement.material_id,
                    facility_id=order.facility_id,
                    quantity=quantity,
                    base_uom=requirement.material_base_uom,
                    need_at=requirement.need_at or order.scheduled_date,
                    source_kind="explicit_requirement",
                )
            )
        return ExplodedRequirements(
            production_order_id=order.production_order_id,
            snapshot_id=snapshot_id,
            contributions=tuple(
                sorted(direct, key=lambda item: (item.material_id, item.need_at, item.requirement_id))
            ),
            revision_ids=(),
        )

    revisions_used: set[str] = set()
    contributions: list[DemandContribution] = []
    visited_line_count = 0
    assemblies = set(manufactured_item_ids)

    def walk(
        item_id: str,
        quantity: Decimal,
        item_uom: str,
        ancestry: tuple[str, ...],
        path: tuple[str, ...],
        explicit_revision_id: str | None = None,
    ) -> None:
        nonlocal visited_line_count
        if item_id in ancestry:
            cycle = " -> ".join((*ancestry, item_id))
            raise PlanningInputError("BOM_CYCLE", f"Cycle detected in BOM: {cycle}")
        if len(ancestry) >= max_depth:
            raise PlanningInputError(
                "BOM_DEPTH_EXCEEDED",
                f"BOM explosion exceeded the configured depth limit ({max_depth})",
            )
        revision = resolve_bom_revision(
            revisions,
            parent_item_id=item_id,
            facility_id=order.facility_id,
            effective_date=order.scheduled_date,
            explicit_revision_id=explicit_revision_id,
        )
        revisions_used.add(revision.revision_id)
        parent_quantity = converter.convert(quantity, item_uom, revision.parent_base_uom)
        if not revision.lines:
            raise PlanningInputError(
                "BOM_HAS_NO_LINES", f"BOM revision {revision.revision_id} contains no component lines"
            )
        for line in sorted(revision.lines, key=lambda item: item.line_id):
            visited_line_count += 1
            if visited_line_count > max_lines:
                raise PlanningInputError(
                    "BOM_LINE_LIMIT_EXCEEDED",
                    f"BOM explosion exceeded the configured line limit ({max_lines})",
                )
            required = parent_quantity * line.quantity_per_parent
            if line.scrap_multiplier is not None:
                required *= line.scrap_multiplier
            child_quantity = converter.convert(
                required, line.usage_uom, line.child_base_uom
            )
            next_path = (*path, f"{revision.revision_id}:{line.line_id}")
            if line.child_item_id in assemblies:
                walk(
                    line.child_item_id,
                    child_quantity,
                    line.child_base_uom,
                    (*ancestry, item_id),
                    next_path,
                )
            else:
                contributions.append(
                    DemandContribution(
                        requirement_id=f"{order.production_order_id}:{'/'.join(next_path)}",
                        production_order_id=order.production_order_id,
                        material_id=line.child_item_id,
                        facility_id=order.facility_id,
                        quantity=child_quantity,
                        base_uom=line.child_base_uom,
                        need_at=order.scheduled_date,
                        source_kind="bom_explosion",
                        bom_path=next_path,
                    )
                )

    if order.item_id not in assemblies:
        raise PlanningInputError(
            "ROOT_ITEM_NOT_MANUFACTURED",
            f"Production order item {order.item_id} is not registered as a manufactured item",
        )
    walk(
        order.item_id,
        order.quantity,
        order.quantity_uom,
        (),
        (),
        order.root_bom_revision_id,
    )
    contributions.sort(
        key=lambda item: (
            item.material_id,
            item.need_at,
            item.production_order_id,
            item.bom_path,
        )
    )
    return ExplodedRequirements(
        production_order_id=order.production_order_id,
        snapshot_id=snapshot_id,
        contributions=tuple(contributions),
        revision_ids=tuple(sorted(revisions_used)),
    )


@dataclass(frozen=True, slots=True)
class InventoryBalance:
    facility_id: str
    material_id: str
    as_of: date
    quantity_basis: QuantityBasis
    quantity: Decimal
    uom: str
    reserved_quantity: Decimal = ZERO
    blocked_quantity: Decimal = ZERO
    safety_stock: Decimal = ZERO
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.facility_id or not self.material_id:
            raise PlanningInputError("INVALID_INVENTORY", "Facility and material IDs are required")
        for name in ("quantity", "reserved_quantity", "blocked_quantity", "safety_stock"):
            amount = _decimal(getattr(self, name), name)
            _positive(amount, name, allow_zero=True)
            object.__setattr__(self, name, amount)
        object.__setattr__(self, "uom", _uom(self.uom))
        if (
            self.quantity_basis == QuantityBasis.PHYSICAL_ON_HAND
            and self.reserved_quantity + self.blocked_quantity > self.quantity
        ):
            raise PlanningInputError(
                "INVENTORY_COMPONENTS_EXCEED_ON_HAND",
                "Reserved plus blocked inventory exceeds physical on-hand quantity",
            )


@dataclass(frozen=True, slots=True)
class ReservationAllocation:
    reservation_id: str
    production_order_id: str
    facility_id: str
    material_id: str
    quantity: Decimal
    uom: str
    need_at: date

    def __post_init__(self) -> None:
        if not all(
            (self.reservation_id, self.production_order_id, self.facility_id, self.material_id)
        ):
            raise PlanningInputError("INVALID_RESERVATION", "Reservation identifiers are required")
        quantity = _decimal(self.quantity, "reservation quantity")
        _positive(quantity, "reservation quantity")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "uom", _uom(self.uom))


@dataclass(frozen=True, slots=True)
class SupplyReceipt:
    receipt_id: str
    facility_id: str
    material_id: str
    quantity: Decimal
    uom: str
    expected_date: date | None
    status: str

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.facility_id or not self.material_id:
            raise PlanningInputError("INVALID_RECEIPT", "Receipt identifiers are required")
        quantity = _decimal(self.quantity, "receipt quantity")
        _positive(quantity, "receipt quantity", allow_zero=True)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "uom", _uom(self.uom))
        object.__setattr__(self, "status", self.status.strip().casefold())


@dataclass(frozen=True, slots=True)
class DailyInventoryBucket:
    day: date
    opening_quantity: Decimal
    firm_receipts: Decimal
    gross_demand: Decimal
    reserved_demand: Decimal
    net_demand: Decimal
    closing_quantity: Decimal
    safety_stock: Decimal
    safety_stock_gap: Decimal
    unmet_demand: Decimal


@dataclass(frozen=True, slots=True)
class InventoryProjection:
    facility_id: str
    material_id: str
    base_uom: str
    snapshot_id: str
    calculation_version: str
    status: CalculationStatus
    opening_usable_quantity: Decimal
    daily_buckets: tuple[DailyInventoryBucket, ...]
    first_safety_stock_breach: date | None
    first_stockout: date | None
    total_unmet_demand: Decimal
    excluded_receipt_quantity: Decimal
    unlinked_reserved_quantity: Decimal
    warnings: tuple[str, ...]
    input_source_refs: tuple[str, ...] = ()


def project_inventory(
    inventory: InventoryBalance,
    demands: collections.abc.Sequence[DemandContribution],
    *,
    snapshot_id: str,
    receipts: collections.abc.Sequence[SupplyReceipt] = (),
    reservations: collections.abc.Sequence[ReservationAllocation] = (),
    start_date: date,
    end_date: date,
    converter: UnitConverter,
    firm_receipt_statuses: frozenset[str] = DEFAULT_FIRM_RECEIPT_STATUSES,
    max_projection_days: int = DEFAULT_MAX_PROJECTION_DAYS,
) -> InventoryProjection:
    """Build a deterministic, date-bucketed inventory projection for one material/facility.

    The opening balance is the usable quantity after applying the declared
    quantity-basis semantics. Linked reservations reduce gross demand once;
    the reserved stock itself is already excluded from a physical on-hand
    opening balance.
    """
    if not snapshot_id.strip():
        raise PlanningInputError("SNAPSHOT_REQUIRED", "Inventory projection requires an immutable snapshot ID")
    if end_date < start_date:
        raise PlanningInputError("INVALID_HORIZON", "Projection end date precedes start date")
    day_count = (end_date - start_date).days + 1
    if day_count > max_projection_days:
        raise PlanningInputError(
            "PROJECTION_HORIZON_EXCEEDED",
            f"Projection horizon exceeds {max_projection_days} days",
        )
    if inventory.as_of != start_date:
        raise PlanningInputError(
            "INVENTORY_SNAPSHOT_DATE_MISMATCH",
            "Inventory snapshot date must equal the projection opening date",
        )

    def matches(facility_id: str, material_id: str) -> bool:
        return (
            facility_id == inventory.facility_id
            and material_id == inventory.material_id
        )

    demand_by_order_day: dict[tuple[str, date], Decimal] = collections.defaultdict(lambda: ZERO)
    gross_by_day: dict[date, Decimal] = collections.defaultdict(lambda: ZERO)
    warnings: set[str] = set()
    evidence_refs: set[str] = set(inventory.source_refs)
    for demand in demands:
        if not matches(demand.facility_id, demand.material_id):
            continue
        evidence_refs.add(demand.requirement_id)
        quantity = converter.convert(demand.quantity, demand.base_uom, inventory.uom)
        _positive(quantity, "demand quantity")
        demand_by_order_day[(demand.production_order_id, demand.need_at)] += quantity
        if start_date <= demand.need_at <= end_date:
            gross_by_day[demand.need_at] += quantity
        else:
            warnings.add("DEMAND_OUTSIDE_PROJECTION_HORIZON")

    reserved_by_order_day: dict[tuple[str, date], Decimal] = collections.defaultdict(lambda: ZERO)
    total_linked_reservations = ZERO
    for reservation in reservations:
        if not matches(reservation.facility_id, reservation.material_id):
            continue
        evidence_refs.add(reservation.reservation_id)
        quantity = converter.convert(reservation.quantity, reservation.uom, inventory.uom)
        _positive(quantity, "reservation quantity")
        key = (reservation.production_order_id, reservation.need_at)
        if key not in demand_by_order_day:
            warnings.add("RESERVATION_WITHOUT_MATCHING_DEMAND")
            continue
        reserved_by_order_day[key] += quantity
        total_linked_reservations += quantity

    for key, reserved in reserved_by_order_day.items():
        if reserved > demand_by_order_day[key]:
            raise PlanningInputError(
                "RESERVATION_EXCEEDS_DEMAND",
                f"Linked reservation exceeds demand for production order {key[0]} on {key[1]}",
            )

    if total_linked_reservations > inventory.reserved_quantity:
        raise PlanningInputError(
            "ALLOCATIONS_EXCEED_RESERVED_STOCK",
            "Linked reservation allocations exceed the inventory reserved quantity",
        )
    unlinked_reserved = inventory.reserved_quantity - total_linked_reservations
    if unlinked_reserved > ZERO:
        warnings.add("UNLINKED_RESERVED_STOCK")

    reserved_by_day: dict[date, Decimal] = collections.defaultdict(lambda: ZERO)
    for (_order_id, need_at), quantity in reserved_by_order_day.items():
        if start_date <= need_at <= end_date:
            reserved_by_day[need_at] += quantity

    receipts_by_day: dict[date, Decimal] = collections.defaultdict(lambda: ZERO)
    excluded_receipts = ZERO
    eligible_statuses = frozenset(status.casefold() for status in firm_receipt_statuses)
    for receipt in receipts:
        if not matches(receipt.facility_id, receipt.material_id):
            continue
        evidence_refs.add(receipt.receipt_id)
        quantity = converter.convert(receipt.quantity, receipt.uom, inventory.uom)
        if receipt.status in {"cancelled", "canceled", "closed", "received", "rejected"}:
            continue
        if receipt.status not in eligible_statuses or receipt.expected_date is None:
            excluded_receipts += quantity
            warnings.add(
                "UNCONFIRMED_RECEIPT_EXCLUDED"
                if receipt.expected_date is not None
                else "UNDATED_RECEIPT_EXCLUDED"
            )
            continue
        if start_date <= receipt.expected_date <= end_date:
            receipts_by_day[receipt.expected_date] += quantity
        else:
            warnings.add("FIRM_RECEIPT_OUTSIDE_PROJECTION_HORIZON")

    if inventory.quantity_basis == QuantityBasis.PHYSICAL_ON_HAND:
        opening = inventory.quantity - inventory.reserved_quantity - inventory.blocked_quantity
    elif inventory.quantity_basis == QuantityBasis.AVAILABLE_TO_USE:
        opening = inventory.quantity
    else:
        raise PlanningInputError("UNKNOWN_QUANTITY_BASIS", "Inventory quantity basis is unsupported")
    if opening < ZERO:
        raise PlanningInputError("NEGATIVE_OPENING_STOCK", "Usable opening stock cannot be negative")

    buckets: list[DailyInventoryBucket] = []
    balance = opening
    first_safety_breach: date | None = None
    first_stockout: date | None = None
    total_unmet = ZERO
    current_day = start_date
    while current_day <= end_date:
        firm_receipts = receipts_by_day[current_day]
        gross_demand = gross_by_day[current_day]
        reserved_demand = reserved_by_day[current_day]
        net_demand = gross_demand - reserved_demand
        opening_quantity = balance
        available_before_demand = opening_quantity + firm_receipts
        closing = available_before_demand - net_demand
        unmet = max(ZERO, -closing) - max(ZERO, -available_before_demand)
        total_unmet += unmet
        gap = max(ZERO, inventory.safety_stock - closing)
        if first_safety_breach is None and closing < inventory.safety_stock:
            first_safety_breach = current_day
        if first_stockout is None and closing < ZERO:
            first_stockout = current_day
        buckets.append(
            DailyInventoryBucket(
                day=current_day,
                opening_quantity=opening_quantity,
                firm_receipts=firm_receipts,
                gross_demand=gross_demand,
                reserved_demand=reserved_demand,
                net_demand=net_demand,
                closing_quantity=closing,
                safety_stock=inventory.safety_stock,
                safety_stock_gap=gap,
                unmet_demand=unmet,
            )
        )
        balance = closing
        current_day += timedelta(days=1)

    return InventoryProjection(
        facility_id=inventory.facility_id,
        material_id=inventory.material_id,
        base_uom=inventory.uom,
        snapshot_id=snapshot_id,
        calculation_version=MATERIAL_PLANNING_VERSION,
        status=CalculationStatus.DEGRADED if warnings else CalculationStatus.COMPLETED,
        opening_usable_quantity=opening,
        daily_buckets=tuple(buckets),
        first_safety_stock_breach=first_safety_breach,
        first_stockout=first_stockout,
        total_unmet_demand=total_unmet,
        excluded_receipt_quantity=excluded_receipts,
        unlinked_reserved_quantity=unlinked_reserved,
        warnings=tuple(sorted(warnings)),
        input_source_refs=tuple(sorted(evidence_refs)),
    )


__all__ = [
    "BomLine",
    "BomRevision",
    "CalculationStatus",
    "DailyInventoryBucket",
    "DemandContribution",
    "ExplicitMaterialRequirement",
    "ExplodedRequirements",
    "InventoryBalance",
    "InventoryProjection",
    "MATERIAL_PLANNING_VERSION",
    "PlanningInputError",
    "ProductionOrder",
    "QuantityBasis",
    "ReservationAllocation",
    "SupplyReceipt",
    "UnitConversion",
    "UnitConverter",
    "explode_production_order",
    "project_inventory",
    "resolve_bom_revision",
]
