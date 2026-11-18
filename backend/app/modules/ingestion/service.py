"""Ingestion service — CSV upload orchestrator (file → S3 → validated rows in DB).

Flow:

1. Endpoint receives `UploadFile` and `dataset_type`.
2. `ingest_csv(...)` saves raw bytes to S3 via `ObjectStorageClient`
   (sync boto3 wrapped in a threadpool — no new dependency on aioboto3).
3. Creates an `audit.ingestion_log` row with status="received".
4. Parses CSV (StdLib `csv.DictReader`).
5. For each row:
   - Validate against the per-dataset Pydantic row schema.
   - If validation fails: increment rows_rejected, append to error_log,
     and if strict=True, abort the whole upload with status="failed".
   - If validation succeeds: insert via the appropriate
     `WorkspaceScopedRepository`. For rows that reference other entities
     by external identifier (SKU/code/name), look up the target UUID
     from an in-memory cache built once per run.
6. Finalize the `IngestionLog` row with counts and `status="completed"`
   (or "partial" if any rows rejected).
7. Caller (endpoint) commits the session.

The service itself does NOT commit; the endpoint owns the session and
may roll back if something goes wrong after the service returns.
"""

from __future__ import annotations

import csv
import hashlib
import io
import tempfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import MvpDatasetType
from app.config import get_settings
from app.infrastructure.storage_client import ObjectStorageClient
from app.modules.ingestion.models import IngestionLog
from app.modules.ingestion.repository import IngestionLogRepository
from app.modules.supply_chain.models import (
    BillOfMaterials,
    BOMLineRecord,
    BOMRevisionRecord,
    Component,
    Customer,
    Edge,
    Factory,
    Inventory,
    Order,
    Product,
    ProductionOrderRecord,
    PurchaseOrderLineRecord,
    Supplier,
    UOMConversionRecord,
    Warehouse,
)
from app.modules.supply_chain.repositories import (
    BomRepository,
    ComponentRepository,
    CustomerRepository,
    EdgeRepository,
    FactoryRepository,
    OrderRepository,
    ProductRepository,
    SupplierRepository,
    WarehouseRepository,
)
from app.modules.supply_chain.schemas import (
    BOMLineRow,
    BOMRevisionRow,
    BomRow,
    ComponentRow,
    CustomerRow,
    EdgeRow,
    FactoryRow,
    InventoryRow,
    OrderRow,
    ProductionOrderRow,
    ProductRow,
    PurchaseOrderLineRow,
    SupplierRow,
    UOMConversionRow,
    WarehouseRow,
)

# Map dataset_type -> ORM class + pydantic row schema.
_DATASET_TO_MODEL: dict[str, type] = {
    MvpDatasetType.SUPPLIERS: Supplier,
    MvpDatasetType.COMPONENTS: Component,
    MvpDatasetType.WAREHOUSES: Warehouse,
    MvpDatasetType.FACTORIES: Factory,
    MvpDatasetType.PRODUCTS: Product,
    MvpDatasetType.CUSTOMERS: Customer,
    MvpDatasetType.EDGES: Edge,
    MvpDatasetType.INVENTORY: Inventory,
    MvpDatasetType.BOM: BillOfMaterials,
    MvpDatasetType.ORDERS: Order,
    MvpDatasetType.BOM_REVISIONS: BOMRevisionRecord,
    MvpDatasetType.BOM_LINES: BOMLineRecord,
    MvpDatasetType.PRODUCTION_ORDERS: ProductionOrderRecord,
    MvpDatasetType.PURCHASE_ORDER_LINES: PurchaseOrderLineRecord,
    MvpDatasetType.UOM_CONVERSIONS: UOMConversionRecord,
}

_DATASET_TO_SCHEMA: dict[str, type] = {
    MvpDatasetType.SUPPLIERS: SupplierRow,
    MvpDatasetType.COMPONENTS: ComponentRow,
    MvpDatasetType.WAREHOUSES: WarehouseRow,
    MvpDatasetType.FACTORIES: FactoryRow,
    MvpDatasetType.PRODUCTS: ProductRow,
    MvpDatasetType.CUSTOMERS: CustomerRow,
    MvpDatasetType.EDGES: EdgeRow,
    MvpDatasetType.INVENTORY: InventoryRow,
    MvpDatasetType.BOM: BomRow,
    MvpDatasetType.ORDERS: OrderRow,
    MvpDatasetType.BOM_REVISIONS: BOMRevisionRow,
    MvpDatasetType.BOM_LINES: BOMLineRow,
    MvpDatasetType.PRODUCTION_ORDERS: ProductionOrderRow,
    MvpDatasetType.PURCHASE_ORDER_LINES: PurchaseOrderLineRow,
    MvpDatasetType.UOM_CONVERSIONS: UOMConversionRow,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ─────────────────────────────────────────────────────────────────────────────


async def ingest_csv(
    *,
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID | None,
    storage: ObjectStorageClient,
    dataset_type: MvpDatasetType,
    file_name: str,
    file_bytes: bytes,
    strict: bool = False,
) -> IngestionLog:
    """Persist the upload and apply validated rows within isolated savepoints."""
    if dataset_type not in _DATASET_TO_MODEL:
        raise ValueError(f"Unknown dataset_type: {dataset_type}")

    rows = await run_in_threadpool(_parse_csv_bytes, file_bytes)
    file_key = _build_key(workspace_id, uuid4(), file_name)
    await run_in_threadpool(storage.put_object, file_key, file_bytes, "text/csv")
    log = IngestionLog(
        workspace_id=workspace_id,
        user_id=user_id,
        dataset_type=dataset_type,
        file_name=file_name,
        file_key=file_key,
        file_size_bytes=len(file_bytes),
        file_sha256=hashlib.sha256(file_bytes).hexdigest(),
        status="received",
        started_at=datetime.now(UTC),
    )
    log_repo = IngestionLogRepository(session, workspace_id)
    log = await log_repo.create(log)
    await log_repo.mark_running(log.id)
    await session.flush()
    return await _apply_ingestion_rows(
        session=session,
        log_repo=log_repo,
        log=log,
        workspace_id=workspace_id,
        dataset_type=dataset_type,
        rows=rows,
        strict=strict,
    )


class CsvStructureError(ValueError):
    """Raised when a CSV file cannot be mapped to an unambiguous row shape."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _apply_ingestion_rows(
    *,
    session: AsyncSession,
    log_repo: IngestionLogRepository,
    log: IngestionLog,
    workspace_id: UUID,
    dataset_type: MvpDatasetType,
    rows: list[dict[str, str]],
    strict: bool,
) -> IngestionLog:
    """Isolate row failures and make strict imports all-or-nothing for entity rows."""
    schema_cls = _DATASET_TO_SCHEMA[dataset_type]
    accepted = 0
    rejected = 0
    errors: list[dict[str, Any]] = []
    # AsyncSession.begin_nested() only *builds* the transaction object; it has
    # to be awaited (or entered) before commit()/rollback() can be called on it.
    batch_savepoint = await session.begin_nested()
    resolver_cache: dict[str, dict[str, UUID]] = {}
    strict_failure_row: int | None = None

    for row_number, raw_row in enumerate(rows, start=1):
        try:
            row_obj = schema_cls(**raw_row)
        except Exception as exc:  # noqa: BLE001 - persist only sanitized details
            rejected += 1
            if len(errors) < 100:
                errors.append(
                    {
                        "row": row_number,
                        "phase": "validation",
                        "message": _safe_row_error(exc),
                    }
                )
            if strict:
                strict_failure_row = row_number
                break
            continue

        try:
            async with session.begin_nested():
                if hasattr(row_obj, "source_ref") and not row_obj.source_ref:
                    row_obj = row_obj.model_copy(
                        update={"source_ref": f"{log.file_key}#row={row_number}"}
                    )
                await _dispatch_insert(
                    dataset_type=dataset_type,
                    session=session,
                    workspace_id=workspace_id,
                    row=row_obj,
                    cache=resolver_cache,
                )
            accepted += 1
        except Exception as exc:  # noqa: BLE001 - isolate persistence failures per row
            rejected += 1
            if len(errors) < 100:
                errors.append(
                    {
                        "row": row_number,
                        "phase": "persistence",
                        "message": _safe_row_error(exc),
                    }
                )
            if strict:
                strict_failure_row = row_number
                break

    if strict_failure_row is not None:
        await batch_savepoint.rollback()
        accepted = 0
        status = "failed"
        message = (
            f"Strict import rejected row {strict_failure_row}; "
            "all entity rows from this file were rolled back."
        )
    else:
        await batch_savepoint.commit()
        status = "completed" if rejected == 0 else "partial"
        message = None if rejected == 0 else f"{rejected} rows rejected"

    await log_repo.finalize(
        log.id,
        status=status,
        rows_total=len(rows),
        rows_accepted=accepted,
        rows_rejected=rejected,
        finished_at=datetime.now(UTC),
        message=message,
        error_log=errors,
    )
    await session.flush()
    result = await log_repo.get(log.id)
    if result is None:
        raise RuntimeError(f"Ingestion log {log.id} disappeared during finalization")
    return result


def _safe_row_error(exc: Exception) -> str:
    """Return validation information without storing raw uploaded values."""
    if isinstance(exc, ValidationError):
        messages = []
        for detail in exc.errors(include_input=False, include_context=False, include_url=False)[:4]:
            location = ".".join(str(part) for part in detail.get("loc", ()))
            message = str(detail.get("msg", "invalid value"))
            messages.append(f"{location}: {message}" if location else message)
        return "; ".join(messages) or "row validation failed"
    if isinstance(exc, CsvStructureError):
        return exc.message
    return f"row persistence failed ({type(exc).__name__})"


# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────────────────────────────────────


def _parse_csv_bytes(data: bytes) -> list[dict[str, str]]:
    """Parse UTF-8 CSV after rejecting ambiguous headers and malformed row widths."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvStructureError(
            "INVALID_ENCODING", "CSV must be encoded as UTF-8 or UTF-8 with BOM"
        ) from exc
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if reader.fieldnames is None:
            return []
        headers = [header.strip() for header in reader.fieldnames]
        if any(not header for header in headers):
            raise CsvStructureError("BLANK_HEADER", "CSV contains a blank column header")
        normalized = [header.casefold() for header in headers]
        if len(normalized) != len(set(normalized)):
            raise CsvStructureError(
                "DUPLICATE_HEADER",
                "CSV contains duplicate column headers after whitespace normalization",
            )
        reader.fieldnames = headers
        rows: list[dict[str, str]] = []
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise CsvStructureError(
                    "EXTRA_COLUMNS", f"CSV row {row_number} contains more values than the header"
                )
            if any(value is None for value in raw_row.values()):
                raise CsvStructureError(
                    "MISSING_COLUMNS",
                    f"CSV row {row_number} contains fewer values than the header",
                )
            rows.append(
                {
                    key: value.strip()
                    for key, value in raw_row.items()
                    if key is not None and isinstance(value, str)
                }
            )
        return rows
    except csv.Error as exc:
        raise CsvStructureError("CSV_PARSE_ERROR", "CSV syntax is invalid") from exc


async def _parse_csv_streaming(file: UploadFile) -> list[dict[str, str]]:
    """Parse upload bytes with the shared strict structural validator."""
    file.file.seek(0)
    data = await run_in_threadpool(file.file.read)
    return await run_in_threadpool(_parse_csv_bytes, data)


async def ingest_csv_streaming(
    *,
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID | None,
    storage: ObjectStorageClient,
    dataset_type: MvpDatasetType,
    file: UploadFile,
    file_name: str,
    strict: bool = False,
) -> IngestionLog:
    """Stage a bounded upload, hash it, and apply rows transactionally."""
    if dataset_type not in _DATASET_TO_MODEL:
        raise ValueError(f"Unknown dataset_type: {dataset_type}")

    file_key = _build_key(workspace_id, uuid4(), file_name)
    log = IngestionLog(
        workspace_id=workspace_id,
        user_id=user_id,
        dataset_type=dataset_type,
        file_name=file_name,
        file_key=file_key,
        file_size_bytes=file.size or 0,
        file_sha256=None,
        status="received",
        started_at=datetime.now(UTC),
    )
    log_repo = IngestionLogRepository(session, workspace_id)
    log = await log_repo.create(log)
    await log_repo.mark_running(log.id)
    await session.flush()

    settings = get_settings()
    digest = hashlib.sha256()
    file_size = 0
    # Read and write: the staged copy is read back below. Opened write-only,
    # every upload ended in a server error at that point.
    with tempfile.NamedTemporaryFile(mode="w+b", delete=True) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > settings.upload_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (limit {settings.upload_max_bytes} bytes)",
                )
            digest.update(chunk)
            tmp.write(chunk)
        tmp.flush()
        tmp.seek(0)
        file_bytes = tmp.read()

    rows = await run_in_threadpool(_parse_csv_bytes, file_bytes)
    await run_in_threadpool(storage.put_object, file_key, file_bytes, "text/csv")
    log.file_size_bytes = file_size
    log.file_sha256 = digest.hexdigest()
    await session.flush()
    return await _apply_ingestion_rows(
        session=session,
        log_repo=log_repo,
        log=log,
        workspace_id=workspace_id,
        dataset_type=dataset_type,
        rows=rows,
        strict=strict,
    )


def _parse_csv_from_tempfile(path: str) -> list[dict[str, str]]:
    """Read the staged upload and apply the same structural CSV validation."""
    with open(path, "rb") as file_handle:
        return _parse_csv_bytes(file_handle.read())


def _build_key(workspace_id: UUID, run_id: UUID, file_name: str) -> str:
    """Deterministic S3 key layout for an ingestion upload."""
    safe_name = file_name.replace("\\", "/").split("/")[-1]
    return f"cortex/ingestion/{workspace_id}/{run_id}/{safe_name}"


# ─────────────────────────────────────────────────────────────────────────────
# Per-dataset insert dispatch
# ─────────────────────────────────────────────────────────────────────────────


async def _dispatch_insert(
    *,
    dataset_type: str,
    session: AsyncSession,
    workspace_id: UUID,
    row: Any,
    cache: dict[str, dict[str, UUID]],
) -> None:
    if dataset_type == MvpDatasetType.SUPPLIERS:
        repo = SupplierRepository(session, workspace_id)
        await repo.add(
            Supplier(
                name=row.name,
                country=row.country,
                tier=row.tier.value if hasattr(row.tier, "value") else row.tier,
                lead_time_days=row.lead_time_days,
                status=row.status.value if hasattr(row.status, "value") else row.status,
                risk_score=row.risk_score,
            )
        )
        return

    if dataset_type == MvpDatasetType.COMPONENTS:
        repo = ComponentRepository(session, workspace_id)
        await repo.add(
            Component(
                sku=row.sku,
                name=row.name,
                category=row.category,
                unit_of_measure=row.unit_of_measure,
            )
        )
        return

    if dataset_type == MvpDatasetType.WAREHOUSES:
        repo = WarehouseRepository(session, workspace_id)
        await repo.add(
            Warehouse(
                code=row.code,
                name=row.name,
                location=row.location,
                capacity_units=row.capacity_units,
            )
        )
        return

    if dataset_type == MvpDatasetType.FACTORIES:
        repo = FactoryRepository(session, workspace_id)
        await repo.add(
            Factory(
                code=row.code,
                name=row.name,
                location=row.location,
                throughput_per_day=row.throughput_per_day,
            )
        )
        return

    if dataset_type == MvpDatasetType.CUSTOMERS:
        repo = CustomerRepository(session, workspace_id)
        await repo.add(
            Customer(
                name=row.name,
                country=row.country,
                tier=row.tier,
                contract_value_annual=row.contract_value_annual,
            )
        )
        return

    if dataset_type == MvpDatasetType.PRODUCTS:
        await _insert_product(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.EDGES:
        await _insert_edge(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.INVENTORY:
        await _insert_inventory(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.BOM:
        await _insert_bom(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.ORDERS:
        await _insert_order(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.BOM_REVISIONS:
        await _insert_bom_revision(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.BOM_LINES:
        await _insert_bom_line(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.PRODUCTION_ORDERS:
        await _insert_production_order(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.PURCHASE_ORDER_LINES:
        await _insert_purchase_order_line(session, workspace_id, row, cache)
        return

    if dataset_type == MvpDatasetType.UOM_CONVERSIONS:
        await _insert_uom_conversion(session, workspace_id, row)
        return

    raise ValueError(f"No insert handler for dataset_type={dataset_type}")


async def _insert_product(
    session: AsyncSession, workspace_id: UUID, row: ProductRow, cache: dict
) -> None:
    factory_id: UUID | None = None
    if row.factory_code:
        factory_id = await _resolve_node(session, workspace_id, cache, "factory", row.factory_code)
    repo = ProductRepository(session, workspace_id)
    await repo.add(
        Product(
            sku=row.sku,
            name=row.name,
            factory_id=factory_id,
            unit_price=row.unit_price,
            lead_time_days=row.lead_time_days,
        )
    )


async def _insert_edge(
    session: AsyncSession, workspace_id: UUID, row: EdgeRow, cache: dict
) -> None:
    from_id = await _resolve_node(session, workspace_id, cache, row.from_type, row.from_ref)
    to_id = await _resolve_node(session, workspace_id, cache, row.to_type, row.to_ref)
    repo = EdgeRepository(session, workspace_id)
    await repo.add(
        Edge(
            from_type=row.from_type,
            from_id=from_id,
            to_type=row.to_type,
            to_id=to_id,
            edge_type=row.edge_type,
            weight=row.weight,
        )
    )


_NODE_LOADERS: dict[str, tuple[type, str]] = {
    # node_type → (RepositoryClass, attribute on the model used as the ref)
    "supplier": (SupplierRepository, "name"),
    "component": (ComponentRepository, "sku"),
    "warehouse": (WarehouseRepository, "code"),
    "factory": (FactoryRepository, "code"),
    "product": (ProductRepository, "sku"),
    "customer": (CustomerRepository, "name"),
}


async def _resolve_node(
    session: AsyncSession,
    workspace_id: UUID,
    cache: dict,
    node_type: str,
    ref: str,
) -> UUID:
    """Resolve a polymorphic node ref (sku/code/name) to a UUID.

    Caches "all rows of node_type" keyed by the relevant attribute once
    per ingestion run. Lookups raise KeyError if the ref doesn't exist —
    the caller's try/except translates that into an error_log row.
    """
    if node_type not in _NODE_LOADERS:
        raise ValueError(f"Unknown node_type for edge resolution: {node_type}")
    repo_cls, key_field = _NODE_LOADERS[node_type]
    cache_key = f"{node_type}s_by_{key_field}"
    if cache.get(cache_key) is None:
        repo = repo_cls(session, workspace_id)
        all_rows = await repo.list(limit=10000)
        cache[cache_key] = {getattr(r, key_field): r.id for r in all_rows}
    return cache[cache_key][ref]


async def _insert_inventory(
    session: AsyncSession, workspace_id: UUID, row: InventoryRow, cache: dict
) -> None:
    warehouse_id = await _resolve_node(
        session, workspace_id, cache, "warehouse", row.warehouse_code
    )
    component_id = await _resolve_node(session, workspace_id, cache, "component", row.component_sku)
    stmt = (
        select(Inventory)
        .where(Inventory.workspace_id == workspace_id)
        .where(Inventory.warehouse_id == warehouse_id)
        .where(Inventory.component_id == component_id)
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        record = Inventory(
            workspace_id=workspace_id,
            warehouse_id=warehouse_id,
            component_id=component_id,
            quantity=row.quantity,
            safety_stock=row.safety_stock,
        )
        session.add(record)
    record.quantity = row.quantity
    record.safety_stock = row.safety_stock
    record.reserved_quantity = row.reserved_quantity
    record.blocked_quantity = row.blocked_quantity
    record.quantity_basis = row.quantity_basis
    record.basis_excludes_reserved = row.basis_excludes_reserved
    record.basis_excludes_blocked = row.basis_excludes_blocked
    record.source_ref = row.source_ref
    record.last_updated_at = datetime.now(UTC)
    await session.flush()


async def _insert_bom(session: AsyncSession, workspace_id: UUID, row: BomRow, cache: dict) -> None:
    product_id = await _resolve_node(session, workspace_id, cache, "product", row.product_sku)
    component_id = await _resolve_node(session, workspace_id, cache, "component", row.component_sku)
    repo = BomRepository(session, workspace_id)
    await repo.add(
        BillOfMaterials(
            product_id=product_id,
            component_id=component_id,
            quantity_per_unit=row.quantity_per_unit,
        )
    )


async def _insert_order(
    session: AsyncSession, workspace_id: UUID, row: OrderRow, cache: dict
) -> None:
    customer_id = await _resolve_node(session, workspace_id, cache, "customer", row.customer_name)
    product_id = await _resolve_node(session, workspace_id, cache, "product", row.product_sku)
    repo = OrderRepository(session, workspace_id)
    await repo.add(
        Order(
            customer_id=customer_id,
            product_id=product_id,
            quantity=row.quantity,
            status=row.status,
            order_date=row.order_date,
            requested_delivery_date=row.requested_delivery_date,
            actual_delivery_date=row.actual_delivery_date,
        )
    )


async def _resolve_revision(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    parent_item_type: str,
    parent_item_id: UUID,
    revision_code: str,
    facility_id: UUID | None,
) -> BOMRevisionRecord:
    stmt = (
        select(BOMRevisionRecord)
        .where(BOMRevisionRecord.workspace_id == workspace_id)
        .where(BOMRevisionRecord.parent_item_type == parent_item_type)
        .where(BOMRevisionRecord.parent_item_id == parent_item_id)
        .where(BOMRevisionRecord.revision_code == revision_code)
    )
    if facility_id is None:
        stmt = stmt.where(BOMRevisionRecord.facility_id.is_(None))
    else:
        stmt = stmt.where(BOMRevisionRecord.facility_id == facility_id)
    result = await session.execute(stmt)
    revision = result.scalar_one_or_none()
    if revision is None:
        raise ValueError(
            f"BOM_REVISION_NOT_FOUND:{parent_item_type}:{parent_item_id}:{revision_code}"
        )
    return revision


async def _insert_bom_revision(
    session: AsyncSession, workspace_id: UUID, row: BOMRevisionRow, cache: dict
) -> None:
    parent_id = await _resolve_node(
        session, workspace_id, cache, row.parent_item_type, row.parent_item_ref
    )
    facility_id = (
        await _resolve_node(session, workspace_id, cache, "factory", row.factory_code)
        if row.factory_code
        else None
    )
    stmt = (
        select(BOMRevisionRecord)
        .where(BOMRevisionRecord.workspace_id == workspace_id)
        .where(BOMRevisionRecord.parent_item_type == row.parent_item_type)
        .where(BOMRevisionRecord.parent_item_id == parent_id)
        .where(BOMRevisionRecord.revision_code == row.revision_code)
    )
    stmt = stmt.where(
        BOMRevisionRecord.facility_id.is_(None)
        if facility_id is None
        else BOMRevisionRecord.facility_id == facility_id
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        record = BOMRevisionRecord(
            workspace_id=workspace_id,
            parent_item_type=row.parent_item_type,
            parent_item_id=parent_id,
            revision_code=row.revision_code,
            facility_id=facility_id,
        )
        session.add(record)
    record.valid_from = row.valid_from
    record.valid_to = row.valid_to
    record.active = row.active
    record.source_ref = row.source_ref
    await session.flush()


async def _insert_bom_line(
    session: AsyncSession, workspace_id: UUID, row: BOMLineRow, cache: dict
) -> None:
    parent_id = await _resolve_node(
        session, workspace_id, cache, row.parent_item_type, row.parent_item_ref
    )
    facility_id = (
        await _resolve_node(session, workspace_id, cache, "factory", row.factory_code)
        if row.factory_code
        else None
    )
    revision = await _resolve_revision(
        session,
        workspace_id,
        parent_item_type=row.parent_item_type,
        parent_item_id=parent_id,
        revision_code=row.revision_code,
        facility_id=facility_id,
    )
    child_id = await _resolve_node(
        session, workspace_id, cache, row.child_item_type, row.child_item_ref
    )
    stmt = (
        select(BOMLineRecord)
        .where(BOMLineRecord.workspace_id == workspace_id)
        .where(BOMLineRecord.revision_id == revision.id)
        .where(BOMLineRecord.line_code == row.line_code)
    )
    result = await session.execute(stmt)
    line = result.scalar_one_or_none()
    if line is None:
        line = BOMLineRecord(
            workspace_id=workspace_id,
            revision_id=revision.id,
            line_code=row.line_code,
            child_item_type=row.child_item_type,
            child_item_id=child_id,
            usage_quantity=row.usage_quantity,
            usage_uom=row.usage_uom,
            child_base_uom=row.child_base_uom,
        )
        session.add(line)
    line.child_item_type = row.child_item_type
    line.child_item_id = child_id
    line.usage_quantity = row.usage_quantity
    line.usage_uom = row.usage_uom
    line.child_base_uom = row.child_base_uom
    line.child_is_assembly = row.child_is_assembly
    line.scrap_factor = row.scrap_factor
    line.valid_from = row.valid_from
    line.valid_to = row.valid_to
    line.source_ref = row.source_ref
    await session.flush()


async def _insert_production_order(
    session: AsyncSession, workspace_id: UUID, row: ProductionOrderRow, cache: dict
) -> None:
    factory_id = await _resolve_node(session, workspace_id, cache, "factory", row.factory_code)
    warehouse_id = await _resolve_node(
        session, workspace_id, cache, "warehouse", row.warehouse_code
    )
    item_id = await _resolve_node(session, workspace_id, cache, row.item_type, row.item_ref)
    revision_id = None
    if row.bom_revision_code:
        revision = await _resolve_revision(
            session,
            workspace_id,
            parent_item_type=row.item_type,
            parent_item_id=item_id,
            revision_code=row.bom_revision_code,
            facility_id=factory_id,
        )
        revision_id = revision.id

    stmt = (
        select(ProductionOrderRecord)
        .where(ProductionOrderRecord.workspace_id == workspace_id)
        .where(ProductionOrderRecord.order_number == row.order_number)
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        record = ProductionOrderRecord(
            workspace_id=workspace_id,
            order_number=row.order_number,
            factory_id=factory_id,
            warehouse_id=warehouse_id,
            item_type=row.item_type,
            item_id=item_id,
            quantity=row.quantity,
            order_uom=row.order_uom,
            item_base_uom=row.item_base_uom,
            material_need_at=row.material_need_at,
            status=row.status,
        )
        session.add(record)
    record.factory_id = factory_id
    record.warehouse_id = warehouse_id
    record.item_type = row.item_type
    record.item_id = item_id
    record.quantity = row.quantity
    record.order_uom = row.order_uom
    record.item_base_uom = row.item_base_uom
    record.material_need_at = row.material_need_at
    record.status = row.status
    record.bom_revision_id = revision_id
    record.source_ref = row.source_ref
    await session.flush()


async def _insert_purchase_order_line(
    session: AsyncSession, workspace_id: UUID, row: PurchaseOrderLineRow, cache: dict
) -> None:
    supplier_id = await _resolve_node(session, workspace_id, cache, "supplier", row.supplier_name)
    warehouse_id = await _resolve_node(
        session, workspace_id, cache, "warehouse", row.warehouse_code
    )
    component_id = await _resolve_node(session, workspace_id, cache, "component", row.component_sku)
    stmt = (
        select(PurchaseOrderLineRecord)
        .where(PurchaseOrderLineRecord.workspace_id == workspace_id)
        .where(PurchaseOrderLineRecord.po_number == row.po_number)
        .where(PurchaseOrderLineRecord.line_number == row.line_number)
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        record = PurchaseOrderLineRecord(
            workspace_id=workspace_id,
            po_number=row.po_number,
            line_number=row.line_number,
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            component_id=component_id,
            ordered_quantity=row.ordered_quantity,
            received_quantity=row.received_quantity,
            status=row.status,
            uom=row.uom,
        )
        session.add(record)
    record.supplier_id = supplier_id
    record.warehouse_id = warehouse_id
    record.component_id = component_id
    record.ordered_quantity = row.ordered_quantity
    record.received_quantity = row.received_quantity
    record.open_quantity = row.open_quantity
    record.expected_date = row.expected_date
    record.status = row.status
    record.confirmed = row.confirmed
    record.uom = row.uom
    record.source_ref = row.source_ref
    await session.flush()


async def _insert_uom_conversion(
    session: AsyncSession, workspace_id: UUID, row: UOMConversionRow
) -> None:
    from_uom = row.from_uom.strip().upper()
    to_uom = row.to_uom.strip().upper()
    if from_uom == to_uom:
        raise ValueError("UOM_CONVERSION_SOURCE_AND_TARGET_MUST_DIFFER")
    stmt = (
        select(UOMConversionRecord)
        .where(UOMConversionRecord.workspace_id == workspace_id)
        .where(UOMConversionRecord.from_uom == from_uom)
        .where(UOMConversionRecord.to_uom == to_uom)
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        record = UOMConversionRecord(
            workspace_id=workspace_id,
            from_uom=from_uom,
            to_uom=to_uom,
            factor=row.factor,
        )
        session.add(record)
    record.factor = row.factor
    record.source_ref = row.source_ref
    await session.flush()


__all__ = ["ingest_csv"]
