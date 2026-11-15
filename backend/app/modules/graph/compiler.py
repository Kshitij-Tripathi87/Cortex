"""Evidence → Graph Compiler — deterministic, provenance-bearing graph construction.

Given a batch of approved evidence claims, the compiler:
1. Re-parses source files to row-level data (needed because Phase 2
   claims are column-level; the compiler does entity resolution per row).
2. Detects the primary entity type of each file from its primary-key column.
3. For each row: extracts entity_id, builds attribute dict, emits an
   upsert_node GraphWriteEvent.
4. For each foreign-key column: emits an upsert_edge GraphWriteEvent, with
   a stub target node created if the referenced entity hasn't been compiled yet.
5. Seeds ProvenanceLink rows linking every node/edge to the source claims.
6. Seals an immutable hash-chained snapshot (see snapshots.py).

Determinism contract: the same approved evidence + the same source bytes
always produce the same graph (identical nodes, edges, write events, and
snapshot hash). Compilation order is fixed by sorting files by original_name.

Production path: reads raw bytes from S3-compatible storage via ObjectStorageClient.
Test path: uses profiler sample_values when storage unavailable.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.common.ids import uuid7
from app.config import get_settings
from app.infrastructure.storage_client import ObjectStorageClient, get_storage
from app.modules.compiler.models import EvidenceClaim
from app.modules.graph.entity_keys import (
    ENTITY_FOREIGN_KEYS,
    ENTITY_PRIMARY_KEYS,
    FACILITY_ENTITY_TYPES,
    canonical_column_name,
    infer_entity_type,
)
from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphWriteEvent,
    ProvenanceLink,
)
from app.modules.graph.versioning import get_next_version
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile


@dataclass(frozen=True)
class CompilationResult:
    snapshot_id: str
    version: int
    snapshot_hash: str
    node_count: int
    edge_count: int
    write_event_count: int
    provenance_link_count: int
    integrity_passed: bool


@dataclass
class _PendingWrite:
    operation: str
    element_type: str
    element_id: str
    payload: dict[str, Any]
    provenance_claim_ids: list[str]


def _entity_pk_field(entity_type: str) -> str | None:
    return ENTITY_PRIMARY_KEYS.get(entity_type)


def _normalize_facility_type(entity_type: str) -> str:
    return FACILITY_ENTITY_TYPES.get(entity_type, entity_type.lower())


def _parse_csv_rows(data: bytes, encoding: str | None = None) -> list[dict[str, str]]:
    """Parse CSV bytes into a list of row dicts keyed by column name."""
    enc = encoding or "utf-8"
    text = data.decode(enc, errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _detect_entity_type(headers: list[str]) -> str | None:
    """Infer the row entity without mistaking foreign keys for row primary keys."""
    return infer_entity_type(headers)


def _mapped_source_field(
    source_column: str,
    entity_type: str,
    field_mappings: dict[str, str] | None = None,
) -> str:
    """Use an accepted human mapping before falling back to deterministic aliases."""
    explicit = (field_mappings or {}).get(source_column)
    return explicit or canonical_column_name(source_column, entity_type)


def _detect_pk_column(
    headers: list[str],
    entity_type: str,
    field_mappings: dict[str, str] | None = None,
) -> str | None:
    """Return the source header that maps to this file entity's canonical primary key."""
    pk_field = _entity_pk_field(entity_type)
    if not pk_field:
        return None
    for header in headers:
        if _mapped_source_field(header, entity_type, field_mappings) == pk_field:
            return header
    return None


def _resolve_fk_columns(
    headers: list[str],
    entity_type: str,
    field_mappings: dict[str, str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Return canonical FK fields and their relationship definitions."""
    result = []
    for header in headers:
        canonical_field = _mapped_source_field(header, entity_type, field_mappings)
        key = (entity_type, canonical_field)
        if key in ENTITY_FOREIGN_KEYS:
            target_type, relationship = ENTITY_FOREIGN_KEYS[key]
            result.append((canonical_field, target_type, relationship, canonical_field))
    return result


def _canonicalize_source_row(
    row: dict[str, Any],
    entity_type: str | None = None,
    field_mappings: dict[str, str] | None = None,
) -> dict[str, str]:
    """Normalize row keys; reject ambiguous duplicate aliases instead of losing data."""
    canonical: dict[str, str] = {}
    for source_column, raw_value in row.items():
        field = (field_mappings or {}).get(str(source_column)) or canonical_column_name(
            str(source_column), entity_type
        )
        value = "" if raw_value is None else str(raw_value)
        current = canonical.get(field)
        if (
            current is not None
            and current.strip()
            and value.strip()
            and current.strip() != value.strip()
        ):
            raise ValueError(f"Source file contains conflicting columns that both map to '{field}'")
        if current is None or not current.strip():
            canonical[field] = value
    return canonical


def _parse_xlsx_rows(data: bytes) -> list[dict[str, str]]:
    """Read the first worksheet as normalized string-valued source rows."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        iterator = worksheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            return []
        headers = [
            str(value).strip() if value is not None else f"column_{index + 1}"
            for index, value in enumerate(header_row)
        ]
        rows: list[dict[str, str]] = []
        for values in iterator:
            row: dict[str, str] = {}
            for index, header in enumerate(headers):
                value = values[index] if index < len(values) else None
                if value is None:
                    row[header] = ""
                elif hasattr(value, "isoformat"):
                    row[header] = value.isoformat()
                else:
                    row[header] = str(value)
            if any(value.strip() for value in row.values()):
                rows.append(row)
        return rows
    finally:
        workbook.close()


def _canonical_payload(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization for hashing — sorted keys, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


async def compile_evidence_to_graph(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
    storage: ObjectStorageClient | None = None,
) -> CompilationResult:
    """Compile approved evidence claims into operational graph elements.

    Pure function over the batch's source data — the same source bytes +
    claims always produce the same graph. Returns the sealed snapshot.

    Args:
        db: Database session
        workspace_id: Workspace identifier
        batch_id: Source batch identifier
        storage: Optional S3-compatible storage client. If provided, reads
            raw file bytes from S3 for production parsing. If None, falls
            back to profiler sample_values (test/dev mode).
    """
    from app.modules.graph.snapshots import get_latest_snapshot, seal_snapshot

    # Production and pilot must compile the exact immutable bytes held in object
    # storage. Profile samples are a local test/dev fallback only.
    if storage is None and get_settings().env.lower() in {"staging", "pilot", "prod", "production"}:
        storage = get_storage()

    # Lock the batch row so two concurrent publish requests for the same batch
    # serialize before checking for an already-published snapshot.
    batch_stmt = (
        select(SourceBatch)
        .where(SourceBatch.batch_id == batch_id)
        .where(SourceBatch.workspace_id == workspace_id)
        .with_for_update()
    )
    batch_result = await db.execute(batch_stmt)
    batch = batch_result.scalar_one_or_none()
    if batch is None:
        raise ValueError(f"Batch {batch_id} not found")

    # A batch is published at most once. Retried requests return the sealed
    # snapshot instead of adding duplicate graph nodes and edges.
    existing_stmt = (
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .where(GraphSnapshot.source_batch_id == batch_id)
        .limit(1)
    )
    existing_result = await db.execute(existing_stmt)
    existing_snapshot = existing_result.scalar_one_or_none()
    if existing_snapshot is not None:
        event_count_result = await db.execute(
            select(func.count(GraphWriteEvent.event_id)).where(
                GraphWriteEvent.snapshot_id == existing_snapshot.snapshot_id
            )
        )
        link_count_result = await db.execute(
            select(func.count(ProvenanceLink.link_id)).where(
                ProvenanceLink.graph_element_id.in_(
                    select(GraphWriteEvent.element_id).where(
                        GraphWriteEvent.snapshot_id == existing_snapshot.snapshot_id
                    )
                )
            )
        )
        from app.modules.graph.integrity import run_integrity_checks

        integrity = await run_integrity_checks(db, workspace_id, existing_snapshot.snapshot_id)
        return CompilationResult(
            snapshot_id=existing_snapshot.snapshot_id,
            version=existing_snapshot.version,
            snapshot_hash=existing_snapshot.snapshot_hash,
            node_count=existing_snapshot.node_count,
            edge_count=existing_snapshot.edge_count,
            write_event_count=int(event_count_result.scalar_one()),
            provenance_link_count=int(link_count_result.scalar_one()),
            integrity_passed=integrity,
        )

    file_stmt = (
        select(SourceFile)
        .where(SourceFile.batch_id == batch_id)
        .where(SourceFile.workspace_id == workspace_id)
        .where(SourceFile.profiled.is_(True))
        .order_by(SourceFile.original_name)
    )
    file_result = await db.execute(file_stmt)
    files = list(file_result.scalars().all())

    # Only accepted claims in this workspace can support graph publication.
    claim_stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.claim_state == ClaimState.ACCEPTED.value)
    )
    claim_result = await db.execute(claim_stmt)
    claims = list(claim_result.scalars().all())
    if not claims:
        raise ValueError("No accepted evidence claims are available for this batch")
    claims_by_file: dict[str, list[EvidenceClaim]] = {}
    for claim in claims:
        claims_by_file.setdefault(claim.source_file_id, []).append(claim)

    # 3. Build pending write events from source data
    writes: list[_PendingWrite] = []
    node_keys: set[tuple[str, str]] = set()
    edge_keys: set[tuple[str, str, str, str]] = set()
    node_provenance: dict[tuple[str, str], set[str]] = {}
    edge_provenance: dict[tuple[str, str, str], set[str]] = {}

    for file in files:
        # Fetch stored data — production reads from S3, test uses sample_values
        file_claims = claims_by_file.get(file.file_id, [])
        if not file_claims:
            # An accepted claim from another file cannot confer provenance on
            # this file's rows.
            continue
        file_claim_ids = [claim.claim_id for claim in file_claims]
        field_mappings: dict[str, str] = {}
        for claim in file_claims:
            if not claim.canonical_field:
                continue
            previous = field_mappings.get(claim.source_column)
            if previous is not None and previous != claim.canonical_field:
                raise ValueError(
                    f"Conflicting accepted mappings exist for source column '{claim.source_column}'"
                )
            field_mappings[claim.source_column] = claim.canonical_field

        profiles_stmt = (
            select(SourceColumnProfile)
            .where(SourceColumnProfile.file_id == file.file_id)
            .where(SourceColumnProfile.workspace_id == workspace_id)
            .order_by(SourceColumnProfile.column_index)
        )
        profiles_result = await db.execute(profiles_stmt)
        profiles = list(profiles_result.scalars().all())

        if not profiles:
            continue

        source_headers = [profile.column_name for profile in profiles]
        entity_type = _detect_entity_type(source_headers)

        # A reviewed mapping may resolve an otherwise unknown primary-key
        # column. A mapping to another entity's primary key is treated as a
        # foreign key unless it matches the file's detected row type.
        mapped_primary_entities = {
            claim.canonical_entity
            for claim in file_claims
            if claim.canonical_entity in ENTITY_PRIMARY_KEYS
            and claim.canonical_field == ENTITY_PRIMARY_KEYS[claim.canonical_entity]
        }
        if entity_type is None and len(mapped_primary_entities) == 1:
            entity_type = next(iter(mapped_primary_entities))
        elif entity_type is None and len(mapped_primary_entities) > 1:
            raise ValueError("Accepted mappings identify multiple possible row entity types")

        if entity_type is None:
            continue

        headers = [
            _mapped_source_field(header, entity_type, field_mappings) for header in source_headers
        ]
        pk_source_column = _detect_pk_column(source_headers, entity_type, field_mappings)
        if pk_source_column is None:
            continue
        pk_column = _mapped_source_field(pk_source_column, entity_type, field_mappings)

        fk_columns = _resolve_fk_columns(source_headers, entity_type, field_mappings)

        # Read the same immutable bytes that were uploaded. In prod/pilot,
        # storage errors fail closed; sample-value reconstruction is only for
        # unit/integration tests and explicitly local development.
        if storage is not None:
            raw_bytes = storage.get_object(file.storage_key)
            if file.original_name.lower().endswith(".xlsx"):
                sample_rows = _parse_xlsx_rows(raw_bytes)
            else:
                sample_rows = _parse_csv_rows(raw_bytes, file.encoding)
        elif get_settings().env.lower() in {"dev", "test"}:
            sample_rows = _reconstruct_rows_from_profiles(profiles)
        else:
            raise RuntimeError(
                "Object storage is required to publish source data in this environment"
            )

        for _row_idx, raw_row in enumerate(sample_rows):
            row = _canonicalize_source_row(raw_row, entity_type, field_mappings)
            entity_id = row.get(pk_column, "").strip()
            if not entity_id:
                continue

            # Build attributes from all non-empty columns
            attributes: dict[str, Any] = {}
            for h in headers:
                val = row.get(h, "").strip()
                if val:
                    attributes[h] = val

            # Resolve entity type to Facility for facility-like entities
            resolved_type = entity_type
            if entity_type in FACILITY_ENTITY_TYPES:
                resolved_type = "Facility"
                attributes["_facility_type"] = _normalize_facility_type(entity_type)

            key = (resolved_type, entity_id)
            node_provenance.setdefault(key, set()).update(file_claim_ids)
            if key not in node_keys:
                node_keys.add(key)
                writes.append(
                    _PendingWrite(
                        operation="upsert_node",
                        element_type="node",
                        element_id=uuid7(),
                        payload={
                            "entity_type": resolved_type,
                            "entity_id": entity_id,
                            "attributes": attributes,
                        },
                        provenance_claim_ids=file_claim_ids[:],
                    )
                )

            # Emit edges for FK columns
            for col_name, target_type, rel, _fk_field in fk_columns:
                target_id = row.get(col_name, "").strip()
                if not target_id:
                    continue
                target_resolved = target_type
                if target_type in FACILITY_ENTITY_TYPES:
                    target_resolved = "Facility"

                # Create stub node for target if not seen
                target_key = (target_resolved, target_id)
                node_provenance.setdefault(target_key, set()).update(file_claim_ids)
                if target_key not in node_keys:
                    node_keys.add(target_key)
                    stub_attrs: dict[str, Any] = {}
                    if target_type in FACILITY_ENTITY_TYPES:
                        stub_attrs["_facility_type"] = _normalize_facility_type(target_type)
                    writes.append(
                        _PendingWrite(
                            operation="upsert_node",
                            element_type="node",
                            element_id=uuid7(),
                            payload={
                                "entity_type": target_resolved,
                                "entity_id": target_id,
                                "attributes": stub_attrs,
                                "_stub": True,
                            },
                            provenance_claim_ids=file_claim_ids[:],
                        )
                    )

                # Edge key: (source_entity_type, source_entity_id, target_entity_id, rel)
                source_node_key = f"{resolved_type}:{entity_id}"
                target_node_key = f"{target_resolved}:{target_id}"
                edge_key = (source_node_key, target_node_key, rel, col_name)
                edge_provenance.setdefault((source_node_key, target_node_key, rel), set()).update(
                    file_claim_ids
                )
                if edge_key in edge_keys:
                    continue
                edge_keys.add(edge_key)

                writes.append(
                    _PendingWrite(
                        operation="upsert_edge",
                        element_type="edge",
                        element_id=uuid7(),
                        payload={
                            "source_entity_type": resolved_type,
                            "source_entity_id": entity_id,
                            "target_entity_type": target_resolved,
                            "target_entity_id": target_id,
                            "relationship_type": rel,
                            "attributes": {"source_column": col_name},
                        },
                        provenance_claim_ids=file_claim_ids[:],
                    )
                )

    if not writes:
        raise ValueError(
            "No graph entities could be resolved from this batch; verify that it contains "
            "supported canonical primary-key columns and accepted claims"
        )

    # 4. Get latest snapshot for hash chain + version
    latest = await get_latest_snapshot(db, workspace_id)
    prev_hash = latest.snapshot_hash if latest else None
    prev_id = latest.snapshot_id if latest else None

    # Use DB-backed monotonic versioning
    next_version = await get_next_version(db, workspace_id, "graph")

    # 5. Upsert canonical nodes, reusing stable workspace/entity IDs.
    # This mirrors the unique key enforced by migration 003 and prevents later
    # batches from creating duplicate suppliers, products, facilities, etc.
    node_id_map: dict[tuple[str, str], str] = {}
    edge_id_map: dict[tuple[str, str, str], str] = {}

    node_keys_to_upsert = {
        (str(w.payload["entity_type"]), str(w.payload["entity_id"]))
        for w in writes
        if w.operation == "upsert_node"
    }
    entity_types = {entity_type for entity_type, _entity_id in node_keys_to_upsert}
    entity_ids = {entity_id for _entity_type, entity_id in node_keys_to_upsert}
    existing_nodes: dict[tuple[str, str], GraphNode] = {}
    if node_keys_to_upsert:
        existing_node_stmt = (
            select(GraphNode)
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.entity_type.in_(entity_types))
            .where(GraphNode.entity_id.in_(entity_ids))
        )
        existing_node_result = await db.execute(existing_node_stmt)
        existing_nodes = {
            (node.entity_type, node.entity_id): node
            for node in existing_node_result.scalars().all()
            if (node.entity_type, node.entity_id) in node_keys_to_upsert
        }

    for w in writes:
        if w.operation != "upsert_node":
            continue
        entity_type = str(w.payload["entity_type"])
        entity_id = str(w.payload["entity_id"])
        node_key = (entity_type, entity_id)
        if node_key in node_id_map:
            continue

        attributes = dict(w.payload["attributes"])
        existing_node = existing_nodes.get(node_key)
        if existing_node is not None:
            # Preserve prior known attributes while letting the latest
            # accepted source values refresh fields they actually provide.
            existing_node.attributes = {**(existing_node.attributes or {}), **attributes}
            existing_node.valid_to = None
            existing_node.last_modified_version = next_version
            node_id_map[node_key] = existing_node.node_id
        else:
            node_id = w.element_id
            node_id_map[node_key] = node_id
            db.add(
                GraphNode(
                    node_id=node_id,
                    workspace_id=workspace_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    attributes=attributes,
                    first_seen_version=next_version,
                    last_modified_version=next_version,
                )
            )

    # Resolve all edge endpoints after every node (including FK stubs) has a
    # stable database ID, then upsert using the canonical relationship key.
    edge_candidates: dict[tuple[str, str, str], tuple[str, str]] = {}
    for w in writes:
        if w.operation != "upsert_edge":
            continue
        source_key = (
            str(w.payload["source_entity_type"]),
            str(w.payload["source_entity_id"]),
        )
        target_key = (
            str(w.payload["target_entity_type"]),
            str(w.payload["target_entity_id"]),
        )
        source_node_id = node_id_map.get(source_key)
        target_node_id = node_id_map.get(target_key)
        if not source_node_id or not target_node_id:
            continue
        entity_edge_key = (
            f"{source_key[0]}:{source_key[1]}",
            f"{target_key[0]}:{target_key[1]}",
            str(w.payload["relationship_type"]),
        )
        edge_candidates[entity_edge_key] = (source_node_id, target_node_id)

    existing_edges: dict[tuple[str, str, str], GraphEdge] = {}
    if edge_candidates:
        source_ids = {source_id for source_id, _target_id in edge_candidates.values()}
        target_ids = {target_id for _source_id, target_id in edge_candidates.values()}
        edge_stmt = (
            select(GraphEdge)
            .where(GraphEdge.workspace_id == workspace_id)
            .where(GraphEdge.source_node_id.in_(source_ids))
            .where(GraphEdge.target_node_id.in_(target_ids))
        )
        edge_result = await db.execute(edge_stmt)
        edge_keys_by_node_ids = {
            (source_node_id, target_node_id, entity_key[2]): entity_key
            for entity_key, (source_node_id, target_node_id) in edge_candidates.items()
        }
        for edge in edge_result.scalars().all():
            edge_key = edge_keys_by_node_ids.get(
                (edge.source_node_id, edge.target_node_id, edge.relationship_type)
            )
            if edge_key is not None:
                existing_edges[edge_key] = edge

    for w in writes:
        if w.operation != "upsert_edge":
            continue
        source_key = (
            str(w.payload["source_entity_type"]),
            str(w.payload["source_entity_id"]),
        )
        target_key = (
            str(w.payload["target_entity_type"]),
            str(w.payload["target_entity_id"]),
        )
        source_node_id = node_id_map.get(source_key)
        target_node_id = node_id_map.get(target_key)
        if not source_node_id or not target_node_id:
            continue

        entity_edge_key = (
            f"{source_key[0]}:{source_key[1]}",
            f"{target_key[0]}:{target_key[1]}",
            str(w.payload["relationship_type"]),
        )
        if entity_edge_key in edge_id_map:
            continue

        attributes = dict(w.payload["attributes"])
        existing_edge = existing_edges.get(entity_edge_key)
        if existing_edge is not None:
            existing_edge.attributes = {**(existing_edge.attributes or {}), **attributes}
            existing_edge.valid_to = None
            existing_edge.last_modified_version = next_version
            edge_id_map[entity_edge_key] = existing_edge.edge_id
        else:
            edge_id = w.element_id
            edge_id_map[entity_edge_key] = edge_id
            db.add(
                GraphEdge(
                    edge_id=edge_id,
                    workspace_id=workspace_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    relationship_type=str(w.payload["relationship_type"]),
                    attributes=attributes,
                    first_seen_version=next_version,
                    last_modified_version=next_version,
                )
            )

    await db.flush()
    actual_node_count = len(node_id_map)
    actual_edge_count = len(edge_id_map)

    # 6. Persist write events (sorted for deterministic hashing)
    sorted_writes = sorted(
        writes,
        key=lambda w: (
            w.element_type,
            w.payload.get("entity_type", ""),
            w.payload.get("entity_id", ""),
            w.payload.get("relationship_type", ""),
        ),
    )

    snapshot_id = uuid7()
    for w in sorted_writes:
        actual_element_id = w.element_id
        if w.operation == "upsert_node":
            node_key = (w.payload["entity_type"], w.payload["entity_id"])
            actual_element_id = node_id_map.get(node_key, w.element_id)
            event_claim_ids = sorted(node_provenance.get(node_key, set()))
        else:
            src = f"{w.payload['source_entity_type']}:{w.payload['source_entity_id']}"
            tgt = f"{w.payload['target_entity_type']}:{w.payload['target_entity_id']}"
            actual_element_id = edge_id_map.get(
                (src, tgt, w.payload["relationship_type"]), w.element_id
            )
            event_claim_ids = sorted(
                edge_provenance.get((src, tgt, w.payload["relationship_type"]), set())
            )
        db.add(
            GraphWriteEvent(
                event_id=uuid7(),
                workspace_id=workspace_id,
                snapshot_id=snapshot_id,
                operation=w.operation,
                element_type=w.element_type,
                element_id=actual_element_id,
                payload=w.payload,
                provenance_claim_ids=event_claim_ids,
            )
        )

    # 7. Create provenance links for each graph element, using the accepted
    # claims that actually contributed the relevant source row(s).
    link_count = 0
    for node_key, node_id in node_id_map.items():
        for claim_id in sorted(node_provenance.get(node_key, set())):
            db.add(
                ProvenanceLink(
                    link_id=uuid7(),
                    workspace_id=workspace_id,
                    graph_element_type="node",
                    graph_element_id=node_id,
                    claim_id=claim_id,
                )
            )
            link_count += 1
    for edge_key, edge_id in edge_id_map.items():
        for claim_id in sorted(edge_provenance.get(edge_key, set())):
            db.add(
                ProvenanceLink(
                    link_id=uuid7(),
                    workspace_id=workspace_id,
                    graph_element_type="edge",
                    graph_element_id=edge_id,
                    claim_id=claim_id,
                )
            )
            link_count += 1

    await db.flush()

    # 8. Seal snapshot (hash-chained)
    snapshot_hash = await seal_snapshot(
        db=db,
        snapshot_id=snapshot_id,
        workspace_id=workspace_id,
        version=next_version,
        prev_snapshot_id=prev_id,
        prev_snapshot_hash=prev_hash,
        write_events=sorted_writes,
        node_count=actual_node_count,
        edge_count=actual_edge_count,
        source_batch_id=batch_id,
    )

    # 9. Integrity check
    from app.modules.graph.integrity import run_integrity_checks

    integrity = await run_integrity_checks(db, workspace_id, snapshot_id)

    return CompilationResult(
        snapshot_id=snapshot_id,
        version=next_version,
        snapshot_hash=snapshot_hash,
        node_count=actual_node_count,
        edge_count=actual_edge_count,
        write_event_count=len(sorted_writes),
        provenance_link_count=link_count,
        integrity_passed=integrity,
    )


def _reconstruct_rows_from_profiles(
    profiles: list[SourceColumnProfile],
) -> list[dict[str, str]]:
    """Reconstruct row-level data from column profiles using sample_values.

    Phase 3 v1 limitation: the profiler stores only sample values (up to 5).
    A full implementation reads the raw file from S3 and parses it directly.
    This helper creates deterministic pseudo-rows from the sample values,
    which is sufficient for initial graph compilation testing.

    When raw bytes are available (Phase 3 v2), replace this with:
        raw_bytes = storage.get(file.storage_key)
        return _parse_csv_rows(raw_bytes, file.encoding)
    """
    if not profiles:
        return []
    max_rows = max(len(p.sample_values) for p in profiles) if profiles else 0
    rows: list[dict[str, str]] = []
    for row_idx in range(max_rows):
        row = {}
        for p in profiles:
            if row_idx < len(p.sample_values):
                row[p.column_name] = p.sample_values[row_idx]
            else:
                row[p.column_name] = ""
        rows.append(row)
    return rows if max_rows > 0 else []
