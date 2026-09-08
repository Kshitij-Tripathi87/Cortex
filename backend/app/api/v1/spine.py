"""Spine API — POST /api/v1/spine/run.

Accepts uploaded CSV files and runs the full Real Data Spine end-to-end:
ingestion → entity resolution → operational graph → world state → signals
→ blast radius → agent selection → proposals → twin counterfactual →
policy gate → execution → outcome → evidence DAG.

Returns a ``SpineResult`` with all stages, metrics, and evidence.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.infrastructure.database import get_session
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalTable,
    EntityType,
    OlistAdapter,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_service import WorldStateService

logger = logging.getLogger(__name__)

router = APIRouter()


class SpineRunRequest(BaseModel):
    """Request body for spine run (non-file fields)."""

    workspace_id: str = Field(default="", description="Workspace ID")
    organization_id: str = Field(default="", description="Organization ID")


class SpineRunResponse(BaseModel):
    """Response body for spine run."""

    spine_result: dict[str, Any]


def _detect_entity_type_from_filename(filename: str) -> EntityType | None:
    """Best-effort entity type detection from filename."""
    name = os.path.splitext(os.path.basename(filename))[0].lower()
    if "supplier" in name or "seller" in name or "vendor" in name:
        return EntityType.SUPPLIER
    if "customer" in name or "client" in name:
        return EntityType.CUSTOMER
    if "order_item" in name or "item" in name:
        return EntityType.ORDER_ITEM
    if "order" in name:
        return EntityType.ORDER
    if "product" in name:
        return EntityType.PRODUCT
    if "shipment" in name:
        return EntityType.SHIPMENT
    if "carrier" in name:
        return EntityType.CARRIER
    if "warehouse" in name:
        return EntityType.WAREHOUSE
    if "inventory" in name:
        return EntityType.INVENTORY
    if "route" in name:
        return EntityType.ROUTE
    return None


def _detect_id_field(rows: list[dict[str, Any]], entity_type: EntityType) -> str | None:
    """Detect the primary ID column for a table."""
    if not rows:
        return None
    sample = rows[0]
    preferred = f"{entity_type.value.lower()}_id"
    if preferred in sample:
        return preferred
    for col in sample:
        if col.endswith("_id") and not col.startswith("_"):
            return col
    return None


async def _parse_csv_upload(file: UploadFile) -> list[dict[str, Any]]:
    """Parse a CSV upload into a list of row dicts."""
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(reader):
        row["_source_file"] = file.filename or "upload.csv"
        row["_source_row"] = idx + 1
        rows.append(row)
    return rows


@router.post("/run", response_model=SpineRunResponse)
async def run_spine(
    workspace_id: str = Form(default=""),
    organization_id: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    use_olist_adapter: bool = Form(default=False),
    olist_data_dir: str = Form(default=""),
    auth: AuthContext = Depends(get_current_user),
) -> SpineRunResponse:
    """Run the full Real Data Spine on uploaded CSV files.

    Accepts either:
    - Multiple CSV files uploaded directly (generic path)
    - A path to an Olist data directory (adapter path, for testing)

    Returns the full SpineResult with graph, signals, blast radius,
    agent proposals, twin comparison, decision card, execution result,
    and evidence DAG.
    """
    require_workspace_access(workspace_id or "default", auth)
    dataset = CanonicalDataset(
        workspace_id=workspace_id or f"ws_{workspace_id or 'default'}",
        organization_id=organization_id or f"org_{organization_id or 'default'}",
    )

    if use_olist_adapter and olist_data_dir:
        adapter = OlistAdapter()
        dataset = adapter.from_data_dir(
            olist_data_dir,
            workspace_id=workspace_id,
            organization_id=organization_id,
        )
    else:
        for file in files:
            entity_type = _detect_entity_type_from_filename(file.filename or "")
            if entity_type is None:
                continue  # skip unrecognized files

            rows = await _parse_csv_upload(file)
            if not rows:
                continue

            # Detect column types from first row
            column_types: dict[str, str] = {}
            for col, val in rows[0].items():
                if col.startswith("_"):
                    continue
                try:
                    float(val)
                    column_types[col] = "float"
                except (ValueError, TypeError):
                    column_types[col] = "str"

            dataset.tables[entity_type] = CanonicalTable(
                entity_type=entity_type,
                rows=rows,
                column_types=column_types,
                source_file=file.filename,
            )

    if not dataset.tables:
        return SpineRunResponse(
            spine_result={
                "status": "FAILED",
                "error": "No recognizable entity types found in uploaded files",
            }
        )

    spine = RealDataSpine()

    # Production path: fail closed when World State is unavailable.
    # The in-memory fallback is test-only (call spine.run() without world_service).
    async with get_session() as session:
        repo = StateRepository(session)
        world_service = WorldStateService(repository=repo, snapshot_interval=100)
        try:
            result = await spine.run(
                dataset,
                organization_id=dataset.organization_id,
                workspace_id=dataset.workspace_id,
                world_service=world_service,
            )
        except Exception as exc:
            logger.error(
                "Spine run failed: %s",
                exc,
                extra={"workspace_id": dataset.workspace_id},
            )
            return SpineRunResponse(
                spine_result={
                    "status": "FAILED",
                    "error": "World State service unavailable or spine execution failed",
                }
            )

    return SpineRunResponse(spine_result=result.to_dict())
