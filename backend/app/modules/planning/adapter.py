"""Workspace-scoped PostgreSQL adapter for snapshot-bound material planning.

The adapter deliberately performs no business arithmetic. It reads one
workspace's canonical rows, fingerprints the captured input, and maps those
rows into the ORM-free deterministic planning contracts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.planning.models import (
    BOMLine,
    BOMRevision,
    InventoryBalanceInput,
    ItemType,
    MaterialReceipt,
    ProductionOrder,
    QuantityBasis,
    UOMConverter,
)
from app.modules.planning.service import PlanningSnapshot
from app.modules.supply_chain.models import (
    BOMLineRecord,
    BOMRevisionRecord,
    Component,
    Inventory,
    Order,
    ProductionOrderRecord,
    PurchaseOrderLineRecord,
    UOMConversionRecord,
)


@dataclass(frozen=True, slots=True)
class LoadedPlanningSnapshot:
    snapshot: PlanningSnapshot
    input_payload: dict[str, Any]
    customer_orders: tuple[Order, ...]


def _json_value(value: Any) -> Any:
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return value.value
    return value


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        column.name: _json_value(getattr(row, column.name))
        for column in row.__table__.columns
    }


def _sorted_payload(rows: list[Any]) -> list[dict[str, Any]]:
    return sorted(
        (_row_payload(row) for row in rows),
        key=lambda item: str(item.get("id", "")),
    )


async def load_material_planning_snapshot(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    as_of: date,
) -> LoadedPlanningSnapshot:
    """Capture all P1/P2 input records for one workspace.

    Inventory is intentionally keyed by warehouse, not pooled at factory level.
    A production order must identify the warehouse from which material is issued.
    """
    inventory_result = await session.execute(
        select(Inventory).where(Inventory.workspace_id == workspace_id)
    )
    inventory_rows = list(inventory_result.scalars().all())

    production_result = await session.execute(
        select(ProductionOrderRecord).where(
            ProductionOrderRecord.workspace_id == workspace_id
        )
    )
    production_rows = list(production_result.scalars().all())

    revision_result = await session.execute(
        select(BOMRevisionRecord).where(
            BOMRevisionRecord.workspace_id == workspace_id
        )
    )
    revision_rows = list(revision_result.scalars().all())

    line_result = await session.execute(
        select(BOMLineRecord).where(BOMLineRecord.workspace_id == workspace_id)
    )
    line_rows = list(line_result.scalars().all())

    receipt_result = await session.execute(
        select(PurchaseOrderLineRecord).where(
            PurchaseOrderLineRecord.workspace_id == workspace_id
        )
    )
    receipt_rows = list(receipt_result.scalars().all())

    uom_result = await session.execute(
        select(UOMConversionRecord).where(
            UOMConversionRecord.workspace_id == workspace_id
        )
    )
    uom_rows = list(uom_result.scalars().all())

    customer_result = await session.execute(
        select(Order).where(Order.workspace_id == workspace_id)
    )
    customer_orders = tuple(customer_result.scalars().all())

    component_ids = {row.component_id for row in inventory_rows}
    component_ids.update(
        row.child_item_id
        for row in line_rows
        if row.child_item_type == ItemType.COMPONENT.value
    )
    component_result = await session.execute(
        select(Component)
        .where(Component.workspace_id == workspace_id)
        .where(Component.id.in_(component_ids))
    ) if component_ids else None
    components = (
        {row.id: row for row in component_result.scalars().all()}
        if component_result is not None else {}
    )

    all_payload = {
        "as_of": as_of.isoformat(),
        "inventory": _sorted_payload(inventory_rows),
        "production_orders": _sorted_payload(production_rows),
        "bom_revisions": _sorted_payload(revision_rows),
        "bom_lines": _sorted_payload(line_rows),
        "purchase_order_lines": _sorted_payload(receipt_rows),
        "uom_conversions": _sorted_payload(uom_rows),
        "customer_orders": _sorted_payload(list(customer_orders)),
    }
    snapshot_id = hashlib.sha256(
        json.dumps(all_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    lines_by_revision: dict[UUID, list[BOMLine]] = {}
    for row in line_rows:
        lines_by_revision.setdefault(row.revision_id, []).append(
            BOMLine(
                line_id=str(row.id),
                child_item_id=str(row.child_item_id),
                child_item_type=ItemType(row.child_item_type),
                usage_quantity=Decimal(row.usage_quantity),
                usage_uom=row.usage_uom,
                child_base_uom=row.child_base_uom,
                child_is_assembly=row.child_is_assembly,
                scrap_factor=(
                    Decimal(row.scrap_factor) if row.scrap_factor is not None else None
                ),
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
        )

    revisions = tuple(
        BOMRevision(
            revision_id=str(row.id),
            parent_item_id=str(row.parent_item_id),
            parent_item_type=ItemType(row.parent_item_type),
            revision_code=row.revision_code,
            lines=tuple(sorted(lines_by_revision.get(row.id, []), key=lambda line: line.line_id)),
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            facility_id=str(row.facility_id) if row.facility_id else None,
            active=row.active,
        )
        for row in revision_rows
    )

    production_orders = tuple(
        ProductionOrder(
            order_id=str(row.id),
            facility_id=str(row.warehouse_id),
            item_id=str(row.item_id),
            item_type=ItemType(row.item_type),
            quantity=Decimal(row.quantity),
            order_uom=row.order_uom,
            item_base_uom=row.item_base_uom,
            material_need_at=row.material_need_at,
            status=row.status,
            bom_facility_id=str(row.factory_id),
            bom_revision_id=str(row.bom_revision_id) if row.bom_revision_id else None,
            source_ref=row.source_ref or f"production-order:{row.id}",
        )
        for row in production_rows
    )

    balances: list[InventoryBalanceInput] = []
    for row in inventory_rows:
        component = components.get(row.component_id)
        if component is None:
            # The FK should prevent this; fail closed if the workspace data is inconsistent.
            continue
        balances.append(
            InventoryBalanceInput(
                workspace_id=str(workspace_id),
                snapshot_id=snapshot_id,
                facility_id=str(row.warehouse_id),
                material_id=str(row.component_id),
                as_of=as_of,
                quantity=Decimal(row.quantity),
                quantity_basis=QuantityBasis(row.quantity_basis),
                safety_stock_quantity=Decimal(row.safety_stock),
                reserved_quantity=Decimal(row.reserved_quantity),
                blocked_quantity=Decimal(row.blocked_quantity),
                basis_excludes_reserved=row.basis_excludes_reserved,
                basis_excludes_blocked=row.basis_excludes_blocked,
                uom=component.unit_of_measure,
                source_refs=(f"inventory:{row.id}",),
            )
        )

    receipts = tuple(
        MaterialReceipt(
            receipt_id=str(row.id),
            facility_id=str(row.warehouse_id),
            material_id=str(row.component_id),
            ordered_quantity=Decimal(row.ordered_quantity),
            received_quantity=Decimal(row.received_quantity),
            expected_date=row.expected_date,
            status=row.status,
            confirmed=row.confirmed,
            uom=row.uom,
            open_quantity=(
                Decimal(row.open_quantity) if row.open_quantity is not None else None
            ),
            supplier_id=str(row.supplier_id),
            source_ref=row.source_ref or f"purchase-order-line:{row.id}",
        )
        for row in receipt_rows
    )

    factors = {
        (row.from_uom.strip().upper(), row.to_uom.strip().upper()): Decimal(row.factor)
        for row in uom_rows
    }

    snapshot = PlanningSnapshot(
        workspace_id=str(workspace_id),
        snapshot_id=snapshot_id,
        as_of=as_of,
        bom_revisions=revisions,
        production_orders=production_orders,
        inventory_balances=tuple(balances),
        receipts=receipts,
        uom_converter=UOMConverter(factors),
    )
    return LoadedPlanningSnapshot(
        snapshot=snapshot,
        input_payload=all_payload,
        customer_orders=customer_orders,
    )


__all__ = ["LoadedPlanningSnapshot", "load_material_planning_snapshot"]
