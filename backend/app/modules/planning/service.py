"""Snapshot-bound orchestration for deterministic material planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.planning.bom import explode_production_order
from app.modules.planning.inventory import project_inventory
from app.modules.planning.models import (
    BOMRevision,
    InventoryBalanceInput,
    InventoryProjection,
    MaterialReceipt,
    ProductionOrder,
    ProjectionStatus,
    UOMConverter,
    OrderRequirementsResult,
)


ALGORITHM_VERSION = "cortex-material-plan-v1"


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    workspace_id: str
    snapshot_id: str
    as_of: date
    bom_revisions: tuple[BOMRevision, ...]
    production_orders: tuple[ProductionOrder, ...]
    inventory_balances: tuple[InventoryBalanceInput, ...]
    receipts: tuple[MaterialReceipt, ...] = ()
    uom_converter: UOMConverter = UOMConverter()


@dataclass(frozen=True, slots=True)
class MaterialPlanResult:
    workspace_id: str
    snapshot_id: str
    algorithm_version: str
    status: ProjectionStatus
    order_results: tuple[OrderRequirementsResult, ...]
    inventory_projections: tuple[InventoryProjection, ...]
    warnings: tuple[str, ...]
    result_sha256: str


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _projection_payload(projection: InventoryProjection) -> dict[str, Any]:
    return {
        "facility_id": projection.facility_id,
        "material_id": projection.material_id,
        "status": projection.status.value,
        "quantity_basis": projection.quantity_basis.value,
        "uom": projection.uom,
        "start_date": projection.start_date.isoformat(),
        "end_date": projection.end_date.isoformat(),
        "opening_usable_quantity": _decimal(projection.opening_usable_quantity),
        "first_safety_stock_breach": (
            projection.first_safety_stock_breach.isoformat()
            if projection.first_safety_stock_breach else None
        ),
        "first_negative_balance": (
            projection.first_negative_balance.isoformat()
            if projection.first_negative_balance else None
        ),
        "uncovered_requirement_quantity": _decimal(
            projection.uncovered_requirement_quantity
        ),
        "uncertain_receipts_excluded": _decimal(
            projection.uncertain_receipts_excluded
        ),
        "warnings": list(projection.warnings),
        "daily_buckets": [
            {
                "date": bucket.bucket_date.isoformat(),
                "opening": _decimal(bucket.opening_quantity),
                "confirmed_receipts": _decimal(bucket.confirmed_receipts),
                "uncertain_receipts": _decimal(bucket.uncertain_receipts),
                "demand": _decimal(bucket.uncovered_demand),
                "closing": _decimal(bucket.closing_quantity),
                "safety_stock": _decimal(bucket.safety_stock_quantity),
                "status": bucket.status,
                "demand_refs": list(bucket.demand_refs),
                "receipt_refs": list(bucket.receipt_refs),
            }
            for bucket in projection.daily_buckets
        ],
        "source_refs": list(projection.source_refs),
    }


def run_material_plan(
    snapshot: PlanningSnapshot,
    *,
    start_date: date,
    end_date: date,
) -> MaterialPlanResult:
    """Explode eligible orders and project each material/facility independently.

    The caller is responsible for assembling all inputs from one immutable
    canonical snapshot. Cross-snapshot inventory rows are rejected before any
    calculation is returned.
    """
    if not snapshot.workspace_id or not snapshot.snapshot_id:
        raise ValueError("SNAPSHOT_IDENTITY_REQUIRED")
    if not snapshot.inventory_balances:
        return MaterialPlanResult(
            snapshot.workspace_id,
            snapshot.snapshot_id,
            ALGORITHM_VERSION,
            ProjectionStatus.NOT_CALCULABLE,
            (),
            (),
            ("INVENTORY_SNAPSHOT_MISSING",),
            hashlib.sha256(b"").hexdigest(),
        )
    if any(
        balance.workspace_id != snapshot.workspace_id
        or balance.snapshot_id != snapshot.snapshot_id
        or balance.as_of != snapshot.as_of
        for balance in snapshot.inventory_balances
    ):
        raise ValueError("SNAPSHOT_BOUNDARY_MISMATCH")

    balances_by_key: dict[tuple[str, str], InventoryBalanceInput] = {}
    for balance in snapshot.inventory_balances:
        key = (balance.facility_id, balance.material_id)
        if key in balances_by_key:
            raise ValueError(f"DUPLICATE_INVENTORY_BALANCE:{key[0]}:{key[1]}")
        balances_by_key[key] = balance

    order_results = tuple(
        explode_production_order(
            order, snapshot.bom_revisions, snapshot.uom_converter
        )
        for order in sorted(snapshot.production_orders, key=lambda item: item.order_id)
    )
    demand_by_key: dict[tuple[str, str], list] = {}
    warnings: list[str] = []
    for order_result in order_results:
        if order_result.status == ProjectionStatus.NOT_CALCULABLE:
            warnings.append(
                f"ORDER_NOT_CALCULABLE:{order_result.production_order_id}:"
                f"{order_result.error_code or 'UNKNOWN'}"
            )
            continue
        warnings.extend(
            f"ORDER_WARNING:{order_result.production_order_id}:{warning}"
            for warning in order_result.warnings
        )
        for contribution in order_result.contributions:
            key = (contribution.facility_id, contribution.material_id)
            demand_by_key.setdefault(key, []).append(contribution)

    projections: list[InventoryProjection] = []
    for key in sorted(demand_by_key):
        balance = balances_by_key.get(key)
        if balance is None:
            warnings.append(f"INVENTORY_BALANCE_MISSING:{key[0]}:{key[1]}")
            continue
        projected = project_inventory(
            balance,
            snapshot.receipts,
            tuple(demand_by_key[key]),
            start_date=start_date,
            end_date=end_date,
            uom_converter=snapshot.uom_converter,
        )
        projections.append(projected)
        warnings.extend(
            f"PROJECTION_WARNING:{key[0]}:{key[1]}:{warning}"
            for warning in projected.warnings
        )

    if not projections:
        status = ProjectionStatus.NOT_CALCULABLE
    elif any(p.status == ProjectionStatus.NOT_CALCULABLE for p in projections):
        status = ProjectionStatus.DEGRADED
    elif warnings or any(p.status == ProjectionStatus.DEGRADED for p in projections):
        status = ProjectionStatus.DEGRADED
    else:
        status = ProjectionStatus.COMPLETED

    payload = {
        "workspace_id": snapshot.workspace_id,
        "snapshot_id": snapshot.snapshot_id,
        "algorithm_version": ALGORITHM_VERSION,
        "status": status.value,
        "order_results": [
            {
                "order_id": result.production_order_id,
                "status": result.status.value,
                "error_code": result.error_code,
                "contributions": [
                    {
                        "id": item.contribution_id,
                        "material_id": item.material_id,
                        "facility_id": item.facility_id,
                        "gross": _decimal(item.gross_quantity),
                        "reserved": _decimal(item.reserved_quantity),
                        "uncovered": _decimal(item.uncovered_quantity),
                        "uom": item.uom,
                        "need_at": item.need_at.isoformat(),
                        "path": list(item.bom_line_path),
                        "source_ref": item.source_ref,
                    }
                    for item in result.contributions
                ],
            }
            for result in order_results
        ],
        "projections": [_projection_payload(item) for item in projections],
        "warnings": sorted(set(warnings)),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return MaterialPlanResult(
        workspace_id=snapshot.workspace_id,
        snapshot_id=snapshot.snapshot_id,
        algorithm_version=ALGORITHM_VERSION,
        status=status,
        order_results=order_results,
        inventory_projections=tuple(projections),
        warnings=tuple(sorted(set(warnings))),
        result_sha256=digest,
    )


__all__ = [
    "ALGORITHM_VERSION",
    "MaterialPlanResult",
    "PlanningSnapshot",
    "run_material_plan",
]
