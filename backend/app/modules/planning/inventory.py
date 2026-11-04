"""Deterministic daily inventory projection with explicit quantity semantics."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.modules.planning.models import (
    DemandContribution,
    DailyInventoryBucket,
    InventoryBalanceInput,
    InventoryProjection,
    MaterialReceipt,
    ProjectionStatus,
    QuantityBasis,
)

_FIRM_RECEIPT_STATUSES = {"open", "confirmed", "partially_received", "partial" }
_EXCLUDED_RECEIPT_STATUSES = {"cancelled", "canceled", "closed", "received", "complete", "completed"}


class InventoryProjectionError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def _opening_usable(balance: InventoryBalanceInput) -> Decimal:
    quantity = balance.quantity
    if quantity < 0 or balance.safety_stock_quantity < 0:
        raise InventoryProjectionError("INVENTORY_QUANTITY_NEGATIVE")
    reserved = balance.reserved_quantity
    blocked = balance.blocked_quantity

    if balance.quantity_basis == QuantityBasis.PHYSICAL_ON_HAND:
        if reserved is None or blocked is None:
            raise InventoryProjectionError("INVENTORY_BUCKETS_REQUIRED_FOR_PHYSICAL_ON_HAND")
        if reserved < 0 or blocked < 0 or reserved + blocked > quantity:
            raise InventoryProjectionError("INVENTORY_BUCKETS_EXCEED_ON_HAND")
        return quantity - reserved - blocked

    if balance.basis_excludes_reserved is None or balance.basis_excludes_blocked is None:
        raise InventoryProjectionError("INVENTORY_BASIS_SEMANTICS_UNKNOWN")
    usable = quantity
    if not balance.basis_excludes_reserved:
        if reserved is None:
            raise InventoryProjectionError("RESERVED_QUANTITY_REQUIRED")
        usable -= reserved
    if not balance.basis_excludes_blocked:
        if blocked is None:
            raise InventoryProjectionError("BLOCKED_QUANTITY_REQUIRED")
        usable -= blocked
    if usable < 0:
        raise InventoryProjectionError("INVENTORY_BUCKETS_EXCEED_QUANTITY")
    return usable


def _uncovered_demand(item: DemandContribution) -> Decimal:
    if item.gross_quantity < 0 or item.reserved_quantity < 0:
        raise InventoryProjectionError("DEMAND_QUANTITY_NEGATIVE", item.contribution_id)
    if item.reservation_linked:
        if item.reserved_quantity > item.gross_quantity:
            raise InventoryProjectionError("RESERVATION_EXCEEDS_DEMAND", item.contribution_id)
        return item.gross_quantity - item.reserved_quantity
    if item.reserved_quantity > 0:
        raise InventoryProjectionError("UNLINKED_RESERVATION", item.contribution_id)
    return item.gross_quantity


def project_inventory(
    balance: InventoryBalanceInput,
    receipts: tuple[MaterialReceipt, ...],
    demand: tuple[DemandContribution, ...],
    *,
    start_date,
    end_date,
    max_horizon_days: int = 366,
) -> InventoryProjection:
    """Project one facility/material pair. Facilities are never implicitly pooled.

    Daily closing balance = previous closing + confirmed receipts - uncovered
    demand. Unconfirmed and undated receipts are reported but excluded from
    the guaranteed/base supply curve.
    """
    if end_date < start_date:
        raise InventoryProjectionError("PROJECTION_HORIZON_INVALID")
    if start_date < balance.as_of:
        raise InventoryProjectionError("PROJECTION_START_PRECEDES_INVENTORY_AS_OF")
    horizon = (end_date - start_date).days + 1
    if horizon > max_horizon_days:
        raise InventoryProjectionError("PROJECTION_HORIZON_EXCEEDED", str(max_horizon_days))

    try:
        opening = _opening_usable(balance)
    except InventoryProjectionError as exc:
        return InventoryProjection(
            balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
            ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
            start_date, end_date, balance.quantity, None, None, (), Decimal("0"),
            Decimal("0"), (str(exc),), balance.source_refs,
        )

    seen_receipts: set[str] = set()
    firm_by_date: dict = defaultdict(Decimal)
    uncertain_total = Decimal("0")
    warnings: list[str] = []
    receipt_refs: set[str] = set()
    for receipt in receipts:
        if receipt.facility_id != balance.facility_id or receipt.material_id != balance.material_id:
            continue
        if receipt.receipt_id in seen_receipts:
            return InventoryProjection(
                balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
                ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
                start_date, end_date, opening, None, None, (), Decimal("0"), Decimal("0"),
                (f"DUPLICATE_RECEIPT_ID:{receipt.receipt_id}",), balance.source_refs,
            )
        seen_receipts.add(receipt.receipt_id)
        status = receipt.status.strip().lower()
        if status in _EXCLUDED_RECEIPT_STATUSES:
            continue
        if status not in _FIRM_RECEIPT_STATUSES:
            warnings.append(f"RECEIPT_STATUS_NOT_RECOGNIZED:{receipt.receipt_id}:{status}")
            continue
        remaining = receipt.remaining_open_quantity()
        if remaining == 0:
            continue
        if receipt.uom.strip().upper() != balance.uom.strip().upper():
            return InventoryProjection(
                balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
                ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
                start_date, end_date, opening, None, None, (), Decimal("0"), Decimal("0"),
                (f"RECEIPT_UOM_MISMATCH:{receipt.receipt_id}",), balance.source_refs,
            )
        if receipt.expected_date is None:
            warnings.append(f"RECEIPT_DATE_MISSING:{receipt.receipt_id}")
            continue
        if receipt.expected_date < balance.as_of:
            warnings.append(f"RECEIPT_DATE_PRECEDES_SNAPSHOT:{receipt.receipt_id}")
            continue
        if not receipt.confirmed:
            uncertain_total += remaining
            warnings.append(f"UNCONFIRMED_RECEIPT_EXCLUDED:{receipt.receipt_id}")
            continue
        if start_date <= receipt.expected_date <= end_date:
            firm_by_date[receipt.expected_date] += remaining
            if receipt.source_ref:
                receipt_refs.add(receipt.source_ref)

    demand_by_date: dict = defaultdict(Decimal)
    demand_refs_by_date: dict = defaultdict(set)
    total_uncovered = Decimal("0")
    for item in demand:
        if item.facility_id != balance.facility_id or item.material_id != balance.material_id:
            continue
        try:
            uncovered = _uncovered_demand(item)
        except InventoryProjectionError as exc:
            return InventoryProjection(
                balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
                ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
                start_date, end_date, opening, None, None, (), uncertain_total, total_uncovered,
                (str(exc),), balance.source_refs,
            )
        if item.uom.strip().upper() != balance.uom.strip().upper():
            return InventoryProjection(
                balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
                ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
                start_date, end_date, opening, None, None, (), uncertain_total, total_uncovered,
                (f"DEMAND_UOM_MISMATCH:{item.contribution_id}",), balance.source_refs,
            )
        if item.need_at < balance.as_of:
            warnings.append(f"DEMAND_DATE_PRECEDES_SNAPSHOT:{item.contribution_id}")
            return InventoryProjection(
                balance.workspace_id, balance.snapshot_id, balance.facility_id, balance.material_id,
                ProjectionStatus.NOT_CALCULABLE, balance.quantity_basis, balance.uom,
                start_date, end_date, opening, None, None, (), uncertain_total, total_uncovered,
                tuple(warnings), balance.source_refs,
            )
        if start_date <= item.need_at <= end_date:
            demand_by_date[item.need_at] += uncovered
            total_uncovered += uncovered
            demand_refs_by_date[item.need_at].add(item.contribution_id)

    buckets: list[DailyInventoryBucket] = []
    first_safety: object | None = None
    first_negative: object | None = None
    closing = opening
    current = start_date
    while current <= end_date:
        day_opening = closing
        receipts_today = firm_by_date[current]
        demand_today = demand_by_date[current]
        closing = day_opening + receipts_today - demand_today
        if first_safety is None and closing < balance.safety_stock_quantity:
            first_safety = current
        if first_negative is None and closing < 0:
            first_negative = current
        status = "shortage" if closing < 0 else (
            "at_risk" if closing < balance.safety_stock_quantity else "healthy"
        )
        buckets.append(
            DailyInventoryBucket(
                bucket_date=current,
                opening_quantity=day_opening,
                confirmed_receipts=receipts_today,
                uncertain_receipts=Decimal("0"),
                uncovered_demand=demand_today,
                closing_quantity=closing,
                safety_stock_quantity=balance.safety_stock_quantity,
                status=status,
                demand_refs=tuple(sorted(demand_refs_by_date[current])),
                receipt_refs=(),
            )
        )
        current += timedelta(days=1)

    if warnings:
        result_status = ProjectionStatus.DEGRADED
    else:
        result_status = ProjectionStatus.COMPLETED
    return InventoryProjection(
        workspace_id=balance.workspace_id,
        snapshot_id=balance.snapshot_id,
        facility_id=balance.facility_id,
        material_id=balance.material_id,
        status=result_status,
        quantity_basis=balance.quantity_basis,
        uom=balance.uom,
        start_date=start_date,
        end_date=end_date,
        opening_usable_quantity=opening,
        first_safety_stock_breach=first_safety,
        first_negative_balance=first_negative,
        daily_buckets=tuple(buckets),
        uncertain_receipts_excluded=uncertain_total,
        uncovered_requirement_quantity=total_uncovered,
        warnings=tuple(sorted(set(warnings))),
        source_refs=tuple(sorted(set(balance.source_refs) | receipt_refs)),
    )


__all__ = ["InventoryProjectionError", "project_inventory"]
