"""Authenticated material-planning API.

POST /planning/material-plan creates a reproducible, workspace-scoped planning
run from persisted manufacturing records. GET /planning/runs/{run_id} reads
back the stored input and result hashes/payloads.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.workspace_scope import reset_workspace_scope, set_workspace_scope
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.planning.adapter import load_material_planning_snapshot
from app.modules.planning.service import run_material_plan
from app.modules.supply_chain.models import MaterialPlanningRunRecord

router = APIRouter()


class MaterialPlanRequest(BaseModel):
    workspace_id: UUID
    as_of: date
    horizon_days: int = Field(default=90, ge=1, le=366)


def _plan_payload(result: Any) -> dict[str, Any]:
    return {
        "workspace_id": result.workspace_id,
        "snapshot_id": result.snapshot_id,
        "algorithm_version": result.algorithm_version,
        "status": result.status.value,
        "engine_result_sha256": result.result_sha256,
        "warnings": list(result.warnings),
        "production_orders": [
            {
                "production_order_id": order.production_order_id,
                "status": order.status.value,
                "error_code": order.error_code,
                "warnings": list(order.warnings),
                "material_requirements": [
                    {
                        "contribution_id": item.contribution_id,
                        "material_id": item.material_id,
                        "facility_id": item.facility_id,
                        "gross_quantity": format(item.gross_quantity, "f"),
                        "reserved_quantity": format(item.reserved_quantity, "f"),
                        "uncovered_quantity": format(item.uncovered_quantity, "f"),
                        "uom": item.uom,
                        "need_at": item.need_at.isoformat(),
                        "bom_line_path": list(item.bom_line_path),
                        "source_ref": item.source_ref,
                    }
                    for item in order.contributions
                ],
            }
            for order in result.order_results
        ],
        "material_projections": [
            {
                "facility_id": projection.facility_id,
                "material_id": projection.material_id,
                "status": projection.status.value,
                "quantity_basis": projection.quantity_basis.value,
                "uom": projection.uom,
                "start_date": projection.start_date.isoformat(),
                "end_date": projection.end_date.isoformat(),
                "opening_usable_quantity": format(
                    projection.opening_usable_quantity, "f"
                ),
                "first_safety_stock_breach": (
                    projection.first_safety_stock_breach.isoformat()
                    if projection.first_safety_stock_breach else None
                ),
                "first_negative_balance": (
                    projection.first_negative_balance.isoformat()
                    if projection.first_negative_balance else None
                ),
                "uncertain_receipts_excluded": format(
                    projection.uncertain_receipts_excluded, "f"
                ),
                "uncovered_requirement_quantity": format(
                    projection.uncovered_requirement_quantity, "f"
                ),
                "warnings": list(projection.warnings),
                "source_refs": list(projection.source_refs),
                "daily_buckets": [
                    {
                        "date": bucket.bucket_date.isoformat(),
                        "opening_quantity": format(bucket.opening_quantity, "f"),
                        "confirmed_receipts": format(bucket.confirmed_receipts, "f"),
                        "uncertain_receipts": format(bucket.uncertain_receipts, "f"),
                        "uncovered_demand": format(bucket.uncovered_demand, "f"),
                        "closing_quantity": format(bucket.closing_quantity, "f"),
                        "safety_stock_quantity": format(
                            bucket.safety_stock_quantity, "f"
                        ),
                        "status": bucket.status,
                        "demand_refs": list(bucket.demand_refs),
                        "receipt_refs": list(bucket.receipt_refs),
                    }
                    for bucket in projection.daily_buckets
                ],
            }
            for projection in result.inventory_projections
        ],
    }


@router.post("/material-plan", summary="Calculate a snapshot-bound manufacturing material plan")
async def create_material_plan(
    request: MaterialPlanRequest,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Calculate material requirements and shortage timelines for one workspace."""
    require_workspace_access(request.workspace_id, auth)
    end_date = request.as_of + timedelta(days=request.horizon_days - 1)
    token = set_workspace_scope(request.workspace_id)
    try:
        loaded = await load_material_planning_snapshot(
            session, request.workspace_id, as_of=request.as_of
        )
        result = run_material_plan(
            loaded.snapshot,
            start_date=request.as_of,
            end_date=end_date,
        )
        payload = _plan_payload(result)

        risk_by_material: list[dict[str, Any]] = []
        affected_production_order_ids: set[str] = set()
        production_orders = {
            order.order_id: order for order in loaded.snapshot.production_orders
        }
        for projection in result.inventory_projections:
            risky_buckets = [
                bucket for bucket in projection.daily_buckets
                if bucket.status in {"at_risk", "shortage"}
            ]
            order_ids = {
                reference.split(":", 1)[0]
                for bucket in risky_buckets
                for reference in bucket.demand_refs
            }
            affected_production_order_ids.update(order_ids)
            if risky_buckets:
                risk_by_material.append(
                    {
                        "facility_id": projection.facility_id,
                        "material_id": projection.material_id,
                        "first_safety_stock_breach": (
                            projection.first_safety_stock_breach.isoformat()
                            if projection.first_safety_stock_breach else None
                        ),
                        "first_negative_balance": (
                            projection.first_negative_balance.isoformat()
                            if projection.first_negative_balance else None
                        ),
                        "affected_production_order_ids": sorted(order_ids),
                    }
                )

        affected_product_ids = {
            UUID(order.item_id)
            for order_id, order in production_orders.items()
            if order_id in affected_production_order_ids
            and order.item_type.value == "product"
        }
        potentially_exposed_customer_orders = [
            {
                "customer_order_id": str(order.id),
                "product_id": str(order.product_id),
                "quantity": str(order.quantity),
                "status": getattr(order.status, "value", str(order.status)),
                "requested_delivery_date": order.requested_delivery_date.isoformat(),
                "allocation_status": "not_pegged_to_production_order",
                "exposure_assessment": "potential",
            }
            for order in loaded.customer_orders
            if order.product_id in affected_product_ids
            and getattr(order.status, "value", str(order.status)).lower()
            not in {"cancelled", "canceled", "completed", "delivered", "shipped"}
        ]
        payload["material_impacts"] = risk_by_material
        payload["potentially_exposed_customer_orders"] = potentially_exposed_customer_orders
        if potentially_exposed_customer_orders:
            payload["warnings"] = sorted(
                set(payload["warnings"])
                | {"CUSTOMER_ORDER_EXPOSURE_IS_PRODUCT_LEVEL_ONLY"}
            )

        persisted_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        run = MaterialPlanningRunRecord(
            workspace_id=request.workspace_id,
            snapshot_id=loaded.snapshot.snapshot_id,
            algorithm_version=result.algorithm_version,
            as_of=request.as_of,
            end_date=end_date,
            status=result.status.value,
            warnings=payload["warnings"],
            result_sha256=persisted_hash,
            input_snapshot=loaded.input_payload,
            result_payload=payload,
        )
        session.add(run)
        await session.commit()
        return {
            "run_id": str(run.id),
            "snapshot_id": run.snapshot_id,
            "algorithm_version": run.algorithm_version,
            "status": run.status,
            "result_sha256": run.result_sha256,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            **payload,
        }
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        reset_workspace_scope(token)


@router.get("/runs/{run_id}", summary="Retrieve a persisted material-planning run")
async def get_material_plan_run(
    run_id: UUID,
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a previously persisted planning run without exposing other tenants."""
    require_workspace_access(workspace_id, auth)
    stmt = (
        select(MaterialPlanningRunRecord)
        .where(MaterialPlanningRunRecord.id == run_id)
        .where(MaterialPlanningRunRecord.workspace_id == workspace_id)
    )
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Planning run not found")
    return {
        "run_id": str(run.id),
        "workspace_id": str(run.workspace_id),
        "snapshot_id": run.snapshot_id,
        "algorithm_version": run.algorithm_version,
        "as_of": run.as_of.isoformat(),
        "end_date": run.end_date.isoformat(),
        "status": run.status,
        "warnings": run.warnings,
        "result_sha256": run.result_sha256,
        "input_snapshot": run.input_snapshot,
        "result": run.result_payload,
        "created_at": run.created_at.isoformat(),
    }


__all__ = ["router"]
