"""Question-aware, read-only evidence about the records published in a workspace.

The reasoning tools call ``build_workspace_evidence`` with the user's question.
It reads the published graph, links the question to real records (by identifier
and by name), derives the facts the question is about (late orders, short
stock, exposure, what changed, intake status) and returns them as plain data.
The same data feeds the built-in answer renderer and a configured model, so
both answer from identical evidence. Nothing here writes to the database.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot, GraphWriteEvent
from app.modules.nexus_spine.p0_migration.country_names import (
    countries_mentioned,
    country_code,
    country_name,
    is_country_field,
)
from app.modules.nexus_spine.p0_migration.question_focus import (
    TOPIC_CHANGES,
    TOPIC_DELAYS,
    TOPIC_ENTITIES,
    TOPIC_EXPOSURE,
    TOPIC_INTAKE,
    TOPIC_OVERVIEW,
    TOPIC_SHORTAGES,
    QuestionFocus,
    content_words,
    fold_word,
    normalize_text,
    parse_question,
)
from app.modules.nexus_spine.p0_migration.workspace_facts import (
    FLOW_TYPES,
    INVENTORY_TYPES,
    NodeRecord,
    WorkspaceIndex,
    aggregate_records,
    apply_value_filters,
    attention_summary,
    build_exposure,
    counterparties,
    diff_attributes,
    flagged_status,
    late_flows,
    link_names,
    link_single_words,
    match_value_filters,
    numeric_fields,
    open_flows,
    related_records,
    resolve_numeric_field,
    stock_positions,
    supplier_rollup,
)
from app.modules.sources.models import SourceBatch, SourceFile

# Reading limits. When a limit is reached the evidence says so, and the answer
# repeats it, so a partial reading is never presented as the whole workspace.
MAX_NODES_PER_TYPE = 2000
MAX_NODES_TOTAL = 12000
MAX_LISTED_RECORDS = 50
MAX_DETAILED_ENTITIES = 3
MAX_COMPARED_ENTITIES = 4
# The record that says where an order or a stock position is: a purchase order
# has no country of its own, the supplier it names has one.
_PARTNER_OF: dict[str, str] = {
    "PurchaseOrder": "Supplier",
    "Shipment": "Supplier",
    "SalesOrder": "Customer",
    "InventoryItem": "Facility",
    "InventoryLot": "Facility",
}
MAX_ALSO_MATCHED = 20
# Lists inside one answer. The matching "*_count" always carries the full number.
MAX_LISTED_FLOWS = 15
MAX_LISTED_STOCK = 15
MAX_LISTED_PARTS = 10
MAX_NESTED_ITEMS = 8
MAX_PART_ITEMS = 4
MAX_LISTED_ATTRIBUTES = 40
# Upper bound on the evidence handed to the answer step (characters of JSON).
# Lists are shortened further until it fits; counts keep the full numbers.
MAX_EVIDENCE_CHARS = 18000
MAX_RELATIONSHIP_EXAMPLES = 8
MAX_SNAPSHOT_HISTORY = 8
MAX_CHANGE_EVENTS = 2000
MAX_CHANGED_RECORDS = 200
MAX_LISTED_CHANGES = 25
MAX_BATCHES = 25

# Kinds of record loaded first when a workspace is larger than the total limit.
_PRIORITY_TYPES: tuple[str, ...] = (
    *FLOW_TYPES,
    *INVENTORY_TYPES,
    "Supplier",
    "Product",
    "Facility",
    "BOM",
    "Customer",
    "Carrier",
)
# Identifier fields a configured model may extract from the question.
_HINT_FIELDS: tuple[str, ...] = ("entity_id", "supplier_id", "sku", "target_entity_id")


def _today() -> date:
    """The date lateness is judged against (UTC). Answers state it."""
    return datetime.now(UTC).date()


def _record(node: GraphNode) -> NodeRecord:
    return NodeRecord(
        node_id=node.node_id,
        entity_type=node.entity_type,
        entity_id=node.entity_id,
        attributes=dict(node.attributes or {}),
        first_seen_version=int(node.first_seen_version or 0),
        last_modified_version=int(node.last_modified_version or 0),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _entity_counts(session: AsyncSession, workspace_id: str) -> dict[str, int]:
    rows = await session.execute(
        select(GraphNode.entity_type, func.count(GraphNode.node_id))
        .where(GraphNode.workspace_id == workspace_id, GraphNode.valid_to.is_(None))
        .group_by(GraphNode.entity_type)
    )
    return {str(entity_type): int(count) for entity_type, count in rows.all()}


async def _relationship_counts(session: AsyncSession, workspace_id: str) -> dict[str, int]:
    rows = await session.execute(
        select(GraphEdge.relationship_type, func.count(GraphEdge.edge_id))
        .where(GraphEdge.workspace_id == workspace_id, GraphEdge.valid_to.is_(None))
        .group_by(GraphEdge.relationship_type)
    )
    return {str(relationship): int(count) for relationship, count in rows.all()}


async def _load_records(
    session: AsyncSession,
    workspace_id: str,
    counts: Mapping[str, int],
    wanted_types: Sequence[str],
) -> tuple[list[NodeRecord], dict[str, Any]]:
    """Load published records, at most MAX_NODES_PER_TYPE per kind and MAX_NODES_TOTAL overall."""
    ordered = [entity_type for entity_type in wanted_types if entity_type in counts]
    ordered += [t for t in _PRIORITY_TYPES if t in counts and t not in ordered]
    ordered += [t for t in sorted(counts) if t not in ordered]

    records: list[NodeRecord] = []
    limited: dict[str, dict[str, int]] = {}
    for entity_type in ordered:
        room = MAX_NODES_TOTAL - len(records)
        quota = max(0, min(MAX_NODES_PER_TYPE, room))
        loaded = 0
        if quota:
            rows = await session.execute(
                select(GraphNode)
                .where(
                    GraphNode.workspace_id == workspace_id,
                    GraphNode.valid_to.is_(None),
                    GraphNode.entity_type == entity_type,
                )
                .order_by(GraphNode.entity_id)
                .limit(quota)
            )
            for node in rows.scalars().all():
                records.append(_record(node))
                loaded += 1
        if loaded < counts[entity_type]:
            limited[entity_type] = {"loaded": loaded, "total": counts[entity_type]}
    total = sum(counts.values())
    return records, {
        "complete": not limited,
        "records_loaded": len(records),
        "records_total": total,
        "limited_types": limited,
    }


async def _lookup_identifiers(
    session: AsyncSession, workspace_id: str, candidates: Sequence[str]
) -> list[NodeRecord]:
    """Published records whose identifier is one of the candidate tokens (any letter case)."""
    variants: list[str] = []
    for candidate in candidates:
        for variant in (candidate, candidate.upper(), candidate.lower()):
            if variant and variant not in variants:
                variants.append(variant)
    if not variants:
        return []
    rows = await session.execute(
        select(GraphNode)
        .where(
            GraphNode.workspace_id == workspace_id,
            GraphNode.valid_to.is_(None),
            GraphNode.entity_id.in_(variants),
        )
        .order_by(GraphNode.entity_type, GraphNode.entity_id)
        .limit(50)
    )
    return [_record(node) for node in rows.scalars().all()]


async def _snapshots(session: AsyncSession, workspace_id: str) -> list[dict[str, Any]]:
    """Latest published versions, newest first, each with the file names it came from."""
    rows = await session.execute(
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .order_by(GraphSnapshot.version.desc())
        .limit(MAX_SNAPSHOT_HISTORY)
    )
    snapshots = list(rows.scalars().all())
    batch_ids = [snapshot.source_batch_id for snapshot in snapshots if snapshot.source_batch_id]
    files: dict[str, list[str]] = {}
    if batch_ids:
        file_rows = await session.execute(
            select(SourceFile.batch_id, SourceFile.original_name)
            .where(SourceFile.workspace_id == workspace_id, SourceFile.batch_id.in_(batch_ids))
            .order_by(SourceFile.original_name)
        )
        for batch_id, name in file_rows.all():
            files.setdefault(str(batch_id), []).append(str(name))
    return [
        {
            "version": int(snapshot.version),
            "snapshot_id": snapshot.snapshot_id,
            "sealed_at": _iso(snapshot.sealed_at),
            "source_batch_id": snapshot.source_batch_id,
            "files": files.get(str(snapshot.source_batch_id), []),
            "records_written": int(snapshot.node_count or 0),
            "relationships_written": int(snapshot.edge_count or 0),
        }
        for snapshot in snapshots
    ]


async def _version_files(
    session: AsyncSession,
    workspace_id: str,
    versions: set[int],
    known: Sequence[Mapping[str, Any]],
) -> dict[int, list[str]]:
    """File names behind the given published versions."""
    result = {int(item["version"]): list(item["files"]) for item in known}
    missing = sorted(version for version in versions if version and version not in result)
    if not missing:
        return result
    rows = await session.execute(
        select(GraphSnapshot.version, SourceFile.original_name)
        .join(SourceFile, SourceFile.batch_id == GraphSnapshot.source_batch_id)
        .where(
            GraphSnapshot.workspace_id == workspace_id,
            SourceFile.workspace_id == workspace_id,
            GraphSnapshot.version.in_(missing),
        )
        .order_by(SourceFile.original_name)
    )
    for version, name in rows.all():
        result.setdefault(int(version), []).append(str(name))
    return result


async def _relationships(
    session: AsyncSession,
    workspace_id: str,
    record: NodeRecord,
    by_node_id: dict[str, NodeRecord],
) -> list[dict[str, Any]]:
    """Relationships of one record: exact counts per type and direction, with a few examples."""
    result: list[dict[str, Any]] = []
    for direction, own, other in (
        ("outgoing", GraphEdge.source_node_id, GraphEdge.target_node_id),
        ("incoming", GraphEdge.target_node_id, GraphEdge.source_node_id),
    ):
        scope = (
            GraphEdge.workspace_id == workspace_id,
            GraphEdge.valid_to.is_(None),
            own == record.node_id,
        )
        counts = await session.execute(
            select(GraphEdge.relationship_type, func.count(GraphEdge.edge_id))
            .where(*scope)
            .group_by(GraphEdge.relationship_type)
            .order_by(GraphEdge.relationship_type)
        )
        for relationship, count in counts.all():
            example_rows = await session.execute(
                select(other)
                .where(*scope, GraphEdge.relationship_type == relationship)
                .order_by(other)
                .limit(MAX_RELATIONSHIP_EXAMPLES)
            )
            node_ids = [str(node_id) for (node_id,) in example_rows.all()]
            missing = [node_id for node_id in node_ids if node_id not in by_node_id]
            if missing:
                extra = await session.execute(
                    select(GraphNode).where(
                        GraphNode.workspace_id == workspace_id, GraphNode.node_id.in_(missing)
                    )
                )
                for node in extra.scalars().all():
                    by_node_id[node.node_id] = _record(node)
            examples = sorted(
                (by_node_id[node_id].ref() for node_id in node_ids if node_id in by_node_id),
                key=lambda ref: (str(ref["entity_type"]), str(ref["entity_id"])),
            )
            result.append(
                {
                    "relationship": str(relationship),
                    "direction": direction,
                    "count": int(count),
                    "examples": examples,
                }
            )
    return result


async def _changes(
    session: AsyncSession,
    workspace_id: str,
    snapshots: Sequence[Mapping[str, Any]],
    by_node_id: dict[str, NodeRecord],
) -> dict[str, Any]:
    """What the latest published version added and changed, from the graph write log."""
    if not snapshots:
        return {"latest": None, "history": []}
    latest = snapshots[0]
    version = int(latest["version"])

    added_rows = await session.execute(
        select(GraphNode.entity_type, func.count(GraphNode.node_id))
        .where(GraphNode.workspace_id == workspace_id, GraphNode.first_seen_version == version)
        .group_by(GraphNode.entity_type)
    )
    added_counts = {str(entity_type): int(count) for entity_type, count in added_rows.all()}
    edge_rows = await session.execute(
        select(GraphEdge.relationship_type, func.count(GraphEdge.edge_id))
        .where(GraphEdge.workspace_id == workspace_id, GraphEdge.first_seen_version == version)
        .group_by(GraphEdge.relationship_type)
    )
    relationships_added = {str(name): int(count) for name, count in edge_rows.all()}

    event_rows = await session.execute(
        select(GraphWriteEvent)
        .where(
            GraphWriteEvent.workspace_id == workspace_id,
            GraphWriteEvent.snapshot_id == latest["snapshot_id"],
            GraphWriteEvent.element_type == "node",
        )
        .order_by(GraphWriteEvent.event_id)
        .limit(MAX_CHANGE_EVENTS + 1)
    )
    events = list(event_rows.scalars().all())
    truncated = len(events) > MAX_CHANGE_EVENTS
    events = events[:MAX_CHANGE_EVENTS]

    missing = [event.element_id for event in events if event.element_id not in by_node_id]
    for start in range(0, len(missing), 500):
        rows = await session.execute(
            select(GraphNode).where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.node_id.in_(missing[start : start + 500]),
            )
        )
        for node in rows.scalars().all():
            by_node_id[node.node_id] = _record(node)

    added_examples: dict[str, list[str]] = {}
    placeholders: list[dict[str, Any]] = []
    rewritten: list[tuple[NodeRecord, Mapping[str, Any]]] = []
    for event in events:
        record = by_node_id.get(event.element_id)
        if record is None:
            continue
        payload = event.payload or {}
        is_placeholder = bool(payload.get("_stub"))
        if record.first_seen_version == version:
            if is_placeholder and not record.items():
                # Named by another record's reference column, with no row of its own.
                placeholders.append(record.ref())
            else:
                added_examples.setdefault(record.entity_type, []).append(record.entity_id)
        elif not is_placeholder:
            rewritten.append((record, payload.get("attributes") or {}))

    # Rebuild each rewritten record as it stood before this version: the
    # compiler merges every accepted row into the stored record, in order.
    considered = rewritten[:MAX_CHANGED_RECORDS]
    before: dict[str, dict[str, Any]] = {record.node_id: {} for record, _ in considered}
    if considered:
        prior_rows = await session.execute(
            select(GraphWriteEvent)
            .where(
                GraphWriteEvent.workspace_id == workspace_id,
                GraphWriteEvent.element_type == "node",
                GraphWriteEvent.element_id.in_(list(before)),
                GraphWriteEvent.snapshot_id != latest["snapshot_id"],
            )
            .order_by(GraphWriteEvent.occurred_at, GraphWriteEvent.event_id)
        )
        for event in prior_rows.scalars().all():
            before[event.element_id].update((event.payload or {}).get("attributes") or {})

    updated: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    unchanged = 0
    for record, attributes in considered:
        earlier = {key: value for key, value in before[record.node_id].items() if key[:1] != "_"}
        field_changes = diff_attributes(earlier, attributes)
        if not field_changes:
            unchanged += 1
        elif not earlier:
            # Until now the record was only a reference from another file.
            completed.append(record.ref())
        else:
            updated.append({**record.ref(), "changes": field_changes})
    updated.sort(key=lambda item: (str(item["entity_type"]), str(item["entity_id"])))
    completed.sort(key=lambda item: (str(item["entity_type"]), str(item["entity_id"])))

    return {
        "latest": {
            "version": version,
            "sealed_at": latest["sealed_at"],
            "files": latest["files"],
            "added": {
                entity_type: {
                    "count": count,
                    "examples": sorted(added_examples.get(entity_type, []))[
                        :MAX_RELATIONSHIP_EXAMPLES
                    ],
                }
                for entity_type, count in sorted(added_counts.items())
            },
            "added_count": sum(added_counts.values()),
            "placeholders": placeholders[:MAX_LISTED_CHANGES],
            "placeholder_count": len(placeholders),
            "updated": updated[:MAX_LISTED_CHANGES],
            "updated_count": len(updated),
            "completed": completed[:MAX_LISTED_CHANGES],
            "completed_count": len(completed),
            "resubmitted_unchanged_count": unchanged,
            "relationships_added": relationships_added,
            "relationships_added_count": sum(relationships_added.values()),
            "truncated": truncated or len(rewritten) > MAX_CHANGED_RECORDS,
        },
        "history": [
            {
                "version": item["version"],
                "sealed_at": item["sealed_at"],
                "files": item["files"],
                "records_written": item["records_written"],
                "relationships_written": item["relationships_written"],
            }
            for item in snapshots[1:]
        ],
    }


_FLOW_KEYS: tuple[str, ...] = (
    "entity_type",
    "entity_id",
    "status",
    "days_late",
    "reasons",
    "promised_date",
    "expected_date",
    "actual_date",
    "quantity",
    "supplier",
    "customer",
    "product",
    "facility",
    "unreadable_date_fields",
)
_STOCK_KEYS: tuple[str, ...] = (
    "entity_type",
    "entity_id",
    "product",
    "facility",
    "on_hand",
    "threshold",
    "threshold_field",
    "shortfall",
)


def _present(item: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """The named keys of an item that carry a value."""
    return {key: item[key] for key in keys if item.get(key) not in (None, "", [], {})}


def _flow_view(flow: Mapping[str, Any]) -> dict[str, Any]:
    return _present(flow, _FLOW_KEYS)


def _stock_view(position: Mapping[str, Any]) -> dict[str, Any]:
    view = _present(position, _STOCK_KEYS)
    view["below_threshold"] = bool(position.get("below_threshold"))
    if position.get("out_of_stock"):
        view["out_of_stock"] = True
    return view


def _late_view(result: Mapping[str, Any], limit: int = MAX_LISTED_FLOWS) -> dict[str, Any]:
    return {
        "as_of": result["as_of"],
        "assessed": result["assessed"],
        "late_count": result["late_count"],
        "late": [_flow_view(flow) for flow in result["late"][:limit]],
        "delivered_late_count": result["delivered_late_count"],
        "delivered_late": [
            _flow_view(flow) for flow in result["delivered_late"][:MAX_NESTED_ITEMS]
        ],
        "unreadable_date_count": result["unreadable_date_count"],
    }


def _stock_result_view(
    result: Mapping[str, Any], limit: int = MAX_LISTED_STOCK, *, include_positions: bool = False
) -> dict[str, Any]:
    view = _stock_counts_view(result, limit)
    if include_positions:
        view["positions"] = [_stock_view(position) for position in result["positions"][:limit]]
    return view


def _stock_counts_view(result: Mapping[str, Any], limit: int) -> dict[str, Any]:
    return {
        "assessed": result["assessed"],
        "short_count": result["short_count"],
        "short": [_stock_view(position) for position in result["short"][:limit]],
        "without_quantity": result["without_quantity"],
        "without_threshold": result["without_threshold"],
    }


def _exposure_view(
    result: Mapping[str, Any], *, include_late_supply: bool = True
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for part in result["parts_at_risk"][:MAX_LISTED_PARTS]:
        parts.append(
            {
                "product": part["product"],
                "late_order_count": len(part["late_orders"]),
                "late_orders": part["late_orders"][:MAX_NESTED_ITEMS],
                "late_quantity": part["late_quantity"] if part["late_quantity_complete"] else None,
                "suppliers": part["suppliers"][:MAX_NESTED_ITEMS],
                "stock_state": part["stock_state"],
                "stock": [_stock_view(position) for position in part["stock"][:MAX_PART_ITEMS]],
                "stock_position_count": len(part["stock"]),
                "on_time_supply_count": len(part["on_time_supply"]),
                "on_time_supply": part["on_time_supply"][:MAX_PART_ITEMS],
                "other_supplier_count": len(part["other_suppliers"]),
                "other_suppliers": part["other_suppliers"][:MAX_PART_ITEMS],
                "goes_into": part["goes_into"][:MAX_NESTED_ITEMS],
                "customer_order_count": len(part["customer_orders"]),
            }
        )
    return {
        "as_of": result["as_of"],
        "late_supply_count": result["late_supply_count"],
        "late_supply": [_flow_view(flow) for flow in result["late_supply"][:MAX_LISTED_FLOWS]]
        if include_late_supply
        else [],
        "parts_at_risk_count": len(result["parts_at_risk"]),
        "parts_at_risk": parts,
        "late_supply_without_product": result["late_supply_without_product"][:MAX_NESTED_ITEMS],
        "customer_order_count": result["customer_order_count"],
        "customer_orders": [
            _present(order, tuple(order)) for order in result["customer_orders"][:MAX_LISTED_FLOWS]
        ],
        "late_customer_flow_count": len(result["late_customer_flows"]),
        "late_customer_flows": [
            _flow_view(flow) for flow in result["late_customer_flows"][:MAX_LISTED_FLOWS]
        ],
        "gaps": result["gaps"],
    }


def _attention_view(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "as_of": result["as_of"],
        "late_count": result["late_count"],
        "late_by_type": {
            entity_type: {"count": len(ids), "examples": ids[:MAX_NESTED_ITEMS]}
            for entity_type, ids in result["late_by_type"].items()
        },
        "flows_assessed": result["flows_assessed"],
        "stock_short_count": result["stock_short_count"],
        "stock_short": [
            _present(position, tuple(position))
            for position in result["stock_short"][:MAX_NESTED_ITEMS]
        ],
        "stock_assessed": result["stock_assessed"],
        "flagged_count": result["flagged_count"],
        "flagged": result["flagged"][:MAX_NESTED_ITEMS],
    }


def _supplier_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**row, "late_orders": list(row["late_orders"])[:MAX_NESTED_ITEMS]}
        for row in rows[:MAX_LISTED_FLOWS]
    ]


def batch_state(
    *,
    published_version: int | None,
    accepted: int,
    pending: int,
    open_conflicts: int,
    blocking_conflicts: int,
    claims: int,
) -> str:
    """Where an upload stands. Mirrors the publish gate and ``compute_readiness``."""
    if published_version is not None:
        return "published"
    if claims == 0:
        return "not_prepared"
    if blocking_conflicts > 0:
        return "blocked"
    if pending > 0 or open_conflicts > 0:
        return "review_required"
    if accepted == 0:
        return "nothing_accepted"
    return "ready_to_publish"


async def _intake(session: AsyncSession, workspace_id: str) -> dict[str, Any]:
    """Uploads of the workspace and where each stands between upload and publication."""
    total = int(
        await session.scalar(
            select(func.count(SourceBatch.batch_id)).where(SourceBatch.workspace_id == workspace_id)
        )
        or 0
    )
    batch_rows = await session.execute(
        select(SourceBatch)
        .where(SourceBatch.workspace_id == workspace_id)
        .order_by(SourceBatch.created_at.desc(), SourceBatch.batch_id)
        .limit(MAX_BATCHES)
    )
    batches = list(batch_rows.scalars().all())
    batch_ids = [batch.batch_id for batch in batches]
    files: dict[str, list[dict[str, Any]]] = {}
    claims: dict[str, dict[str, int]] = {}
    conflicts: dict[str, dict[str, int]] = {}
    published: dict[str, int] = {}
    if batch_ids:
        file_rows = await session.execute(
            select(SourceFile)
            .where(SourceFile.workspace_id == workspace_id, SourceFile.batch_id.in_(batch_ids))
            .order_by(SourceFile.original_name)
        )
        for source_file in file_rows.scalars().all():
            files.setdefault(source_file.batch_id, []).append(
                {"name": source_file.original_name, "rows": source_file.row_count}
            )
        claim_rows = await session.execute(
            select(
                EvidenceClaim.batch_id,
                EvidenceClaim.claim_state,
                func.count(EvidenceClaim.claim_id),
            )
            .where(
                EvidenceClaim.workspace_id == workspace_id, EvidenceClaim.batch_id.in_(batch_ids)
            )
            .group_by(EvidenceClaim.batch_id, EvidenceClaim.claim_state)
        )
        for batch_id, state, count in claim_rows.all():
            claims.setdefault(str(batch_id), {})[str(state)] = int(count)
        conflict_rows = await session.execute(
            select(
                EvidenceConflict.batch_id,
                EvidenceConflict.blocking,
                func.count(EvidenceConflict.conflict_id),
            )
            .where(
                EvidenceConflict.workspace_id == workspace_id,
                EvidenceConflict.batch_id.in_(batch_ids),
                EvidenceConflict.status.in_(["open", "escalated"]),
            )
            .group_by(EvidenceConflict.batch_id, EvidenceConflict.blocking)
        )
        for batch_id, blocking, count in conflict_rows.all():
            entry = conflicts.setdefault(str(batch_id), {"open": 0, "blocking": 0})
            entry["open"] += int(count)
            if blocking:
                entry["blocking"] += int(count)
        snapshot_rows = await session.execute(
            select(GraphSnapshot.source_batch_id, GraphSnapshot.version).where(
                GraphSnapshot.workspace_id == workspace_id,
                GraphSnapshot.source_batch_id.in_(batch_ids),
            )
        )
        for source_batch_id, version in snapshot_rows.all():
            published[str(source_batch_id)] = int(version)

    items: list[dict[str, Any]] = []
    by_state: dict[str, int] = {}
    for batch in batches:
        states = claims.get(batch.batch_id, {})
        accepted = states.get(ClaimState.ACCEPTED.value, 0)
        pending = states.get(ClaimState.PENDING_REVIEW.value, 0)
        conflict = conflicts.get(batch.batch_id, {"open": 0, "blocking": 0})
        state = batch_state(
            published_version=published.get(batch.batch_id),
            accepted=accepted,
            pending=pending,
            open_conflicts=conflict["open"],
            blocking_conflicts=conflict["blocking"],
            claims=sum(states.values()),
        )
        by_state[state] = by_state.get(state, 0) + 1
        items.append(
            {
                "batch_id": batch.batch_id,
                "files": files.get(batch.batch_id, []),
                "uploaded_at": _iso(batch.created_at),
                "state": state,
                "published_version": published.get(batch.batch_id),
                "claims_accepted": accepted,
                "claims_pending_review": pending,
                "claims_rejected": states.get(ClaimState.REJECTED.value, 0),
                "open_conflicts": conflict["open"],
                "blocking_conflicts": conflict["blocking"],
            }
        )
    return {
        "batch_count": total,
        "batches": items,
        "batches_listed": len(items),
        "by_state": by_state,
    }


def utc_iso(value: str | None) -> str | None:
    """An ISO timestamp with its UTC offset.

    PostgreSQL returns timezone-aware values; SQLite returns naive ones for the
    same columns. A browser reads a timestamp without an offset as local time,
    so a value that leaves the API always carries one.
    """
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


async def list_uploads(session: AsyncSession, workspace_id: str) -> dict[str, Any]:
    """Uploads of a workspace, newest first, and where each stands.

    The same reading as the answer to "Is my data ready?": at most
    ``MAX_BATCHES`` uploads are listed and ``batch_count`` carries the full
    number.
    """
    intake = await _intake(session, workspace_id)
    return {
        "batch_count": intake["batch_count"],
        "batches": [
            {**batch, "uploaded_at": utc_iso(batch["uploaded_at"])} for batch in intake["batches"]
        ],
    }


def _matched_view(match: Mapping[str, Any]) -> dict[str, Any]:
    record: NodeRecord = match["record"]
    return {**record.ref(), "matched_on": match["matched_on"], "text": match["text"]}


def _link(
    focus: QuestionFocus, index: WorkspaceIndex, identifier_hits: Sequence[NodeRecord]
) -> list[dict[str, Any]]:
    """Records the question names, by identifier first and then by name."""
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    hits = list(identifier_hits)
    # "supplier S-101" names the supplier even if another kind of record shares the identifier.
    if focus.entity_types and any(hit.entity_type in focus.entity_types for hit in hits):
        hits = [hit for hit in hits if hit.entity_type in focus.entity_types]
    for hit in hits:
        record = index.get(hit.entity_type, hit.entity_id) or hit
        key = (record.entity_type, record.entity_id)
        if key not in seen:
            seen.add(key)
            matches.append({"record": record, "matched_on": "identifier", "text": record.entity_id})
    for match in link_names(focus.normalized, index):
        record = match["record"]
        key = (record.entity_type, record.entity_id)
        if key not in seen:
            seen.add(key)
            matches.append(match)
    return matches


def _source_of(record: NodeRecord, files: Mapping[int, list[str]]) -> dict[str, Any]:
    return {
        "first_published_version": record.first_seen_version,
        "first_published_from": files.get(record.first_seen_version, []),
        "last_touched_version": record.last_modified_version,
        "last_touched_from": files.get(record.last_modified_version, []),
    }


def _explained_words(
    filters: Sequence[Mapping[str, Any]], records: Sequence[NodeRecord]
) -> set[str]:
    """Words of a question that a value filter or a field name already accounts for."""
    words: set[str] = set()
    for item in filters:
        for text in (item.get("value"), item.get("asked_as"), item.get("field")):
            words.update(fold_word(word) for word in normalize_text(str(text or "")).split())
    for record in records:
        for key, _text in record.items():
            words.update(fold_word(word) for word in normalize_text(key).split())
    return words


# Words a question may put in front of "of <record>" that every record answers.
_ALWAYS_ANSWERABLE: frozenset[str] = frozenset(
    {
        "name", "identifier", "kind", "type", "field", "attribute", "value", "everything",
        "anything", "rest", "picture", "state", "situation", "story", "background", "profile",
        "case", "matter", "subject", "topic", "update", "risk", "history", "version",
        "relationship", "link", "connection", "dependency", "performance", "reliability",
        "track", "origin", "source", "meaning", "definition",
    }
)  # fmt: skip
# Not "from": "orders from S-101" and "what comes from S-101" ask for linked
# records, not for an attribute of the supplier.
_BEFORE_A_RECORD = ("in", "of", "for", "at", "on", "about", "regarding")
_SKIPPED_BEFORE_A_RECORD = ("the", "my", "our", "this", "that")


def _unanswered_attributes(
    focus: QuestionFocus, matches: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Things a question asks about a named record that the record has no field for.

    "Weather in Pune" names the Pune warehouse, and nothing published says
    anything about weather. Answering with the warehouse record alone would
    look like an answer. The words in front of "in/of/for/at <record>" and
    after "<record>'s" are taken as what is asked for; a word counts as
    unanswered when it is none of the record's field names and not a word the
    question reader already understood (topics and record kinds are removed
    from the residual before this runs).
    """
    padded = f" {focus.normalized} "
    understood = set(content_words(focus.residual))
    found: list[dict[str, Any]] = []
    for match in matches:
        record: NodeRecord = match["record"]
        needle = normalize_text(str(match["text"]))
        position = padded.find(f" {needle} ") if needle else -1
        if position < 0:
            continue
        before = padded[:position].split()
        after = padded[position + len(needle) + 2 :].split()
        asked: list[str] = []
        while before and before[-1] in _SKIPPED_BEFORE_A_RECORD:
            before.pop()
        if before and before[-1] in _BEFORE_A_RECORD:
            for word in reversed(before[:-1][-3:]):
                if word not in understood:
                    break
                asked.insert(0, word)
        if after[:1] == ["s"]:
            for word in after[1:3]:
                if word not in understood:
                    break
                asked.append(word)
        if not asked:
            continue
        own_words = {
            fold_word(word) for key, _text in record.items() for word in normalize_text(key).split()
        }
        name_words = {fold_word(word) for word in normalize_text(record.name or "").split()}
        unknown = [
            word
            for word in asked
            if fold_word(word) not in own_words
            and fold_word(word) not in name_words
            and fold_word(word) not in _ALWAYS_ANSWERABLE
        ]
        if unknown:
            found.append(
                {
                    "words": unknown,
                    "about": record.ref(),
                    "fields": [key for key, _text in record.items()][:MAX_LISTED_ATTRIBUTES],
                }
            )
    return found


def _comparison_entry(index: WorkspaceIndex, as_of: date, record: NodeRecord) -> dict[str, Any]:
    """One record of a comparison: its fields, and what the orders and stock linked to it show."""
    late = late_flows(index, as_of, focus=[record])
    stock = stock_positions(index, focus=[record])
    return {
        "record": record.summary(max_attributes=MAX_LISTED_ATTRIBUTES),
        "flag": flagged_status(record),
        "orders": {
            "assessed": late["assessed"],
            "late_count": late["late_count"],
            "late": [flow["entity_id"] for flow in late["late"]][:MAX_NESTED_ITEMS],
        },
        "counterparties": {
            role: [
                {key: row[key] for key in ("entity_type", "entity_id", "name")}
                for row in rows[:MAX_NESTED_ITEMS]
            ]
            for role, rows in counterparties(index, as_of, record).items()
        },
        "stock": {
            "assessed": stock["assessed"],
            "short_count": stock["short_count"],
        },
    }


def _aggregate_view(
    index: WorkspaceIndex,
    records: Sequence[NodeRecord],
    entity_type: str,
    counts: Mapping[str, int],
    focus: QuestionFocus,
    explained: set[str],
) -> dict[str, Any]:
    """The figure a question asks for over records of one kind, or why it cannot be given.

    ``explained`` holds the words of the question that a name, an identifier
    or a value filter already accounts for. A word that is left over and is
    not part of a field name asks for something the records may not have
    ("total value"): the usual quantity is then not offered in its place.
    """
    words = [*focus.residual.split(), *focus.aggregate_words]
    field_words = {
        fold_word(word)
        for record in records
        for key, _text in record.items()
        for word in normalize_text(key).split()
    }
    unexplained = [
        word
        for word in content_words(focus.residual)
        if fold_word(word) not in explained and fold_word(word) not in field_words
    ]
    field_name = resolve_numeric_field(words, records, allow_usual=not unexplained)
    view: dict[str, Any] = {
        "entity_type": entity_type,
        "published_total": int(counts.get(entity_type, 0)),
        "considered": len(records),
        "operation": focus.aggregate,
        "field": field_name,
        "numeric_fields": numeric_fields(records)[:MAX_LISTED_ATTRIBUTES],
        # Words the question used that no field of these records is named by.
        "not_a_field": unexplained[:5],
    }
    if field_name is not None and focus.aggregate is not None:
        view.update(aggregate_records(index, records, field_name, focus.aggregate))
    return view


def _asked_figures(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The figures a question asks for, when it lists more than one kind of record.

    "Total quantity on order from tier 1 suppliers" lists orders and
    suppliers, and the quantity is a field of the orders: the suppliers are
    there to say which orders. A kind whose records have no field the
    question names is left out, unless that is true of every kind.
    """
    resolved = [view for view in views if view.get("field")]
    return resolved or views


async def build_workspace_evidence(
    session: AsyncSession,
    workspace_id: str,
    question: str,
    *,
    hints: Mapping[str, Any] | None = None,
    default_topic: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Evidence about the published records that the question is about.

    ``hints`` are identifiers a model extracted from the question; they are
    looked up exactly like identifiers found in its text. ``default_topic`` is
    used when the question itself names no topic, kind of record or record
    (the overview tool asks for an overview, the risk tool for exposure).
    """
    as_of = today or _today()
    focus = parse_question(question)
    counts = await _entity_counts(session, workspace_id)
    relationship_counts = await _relationship_counts(session, workspace_id)
    snapshots = await _snapshots(session, workspace_id)
    records, coverage = await _load_records(session, workspace_id, counts, focus.entity_types)

    candidates = [*focus.identifier_candidates, *focus.capital_words, *focus.quoted_phrases]
    for name in _HINT_FIELDS:
        value = (hints or {}).get(name)
        if isinstance(value, str) and value.strip() and value.strip() not in candidates:
            candidates.append(value.strip())
    identifier_hits = await _lookup_identifiers(session, workspace_id, candidates)
    loaded = {(record.entity_type, record.entity_id) for record in records}
    records.extend(hit for hit in identifier_hits if (hit.entity_type, hit.entity_id) not in loaded)

    index = WorkspaceIndex(records)
    by_node_id = {record.node_id: record for record in index.records}
    matches = _link(focus, index, identifier_hits)
    matched = [match["record"] for match in matches]
    if not matched and focus.entity_types and focus.topic == TOPIC_ENTITIES:
        # The question lists a kind of record and names nothing by any other
        # rule. A word nothing else explains may be one word of a name:
        # "who supplies bearings?" -> "Ball Bearing 6205".
        asked_of = index.of_types([t for t in focus.entity_types if t in counts]) or index.records
        provisional = match_value_filters(
            focus.residual, asked_of, short_codes=focus.short_codes, question=question
        )
        explained = _explained_words(provisional, asked_of)
        leftover = [
            word for word in content_words(focus.residual) if fold_word(word) not in explained
        ]
        matches = link_single_words(leftover, index, avoid_types=focus.entity_types)
        matched = [match["record"] for match in matches]
    matched_types = {record.entity_type for record in matched}
    found_ids = {record.entity_id.lower() for record in matched}

    topic = focus.topic
    # "Summarise S-101" and "any issues with PO-5001?" ask about that record,
    # not for an overview of the whole workspace.
    if topic == TOPIC_OVERVIEW and matched:
        topic = TOPIC_ENTITIES
    elif topic == TOPIC_ENTITIES and not focus.entity_types and not matched and default_topic:
        topic = default_topic

    # Kinds the question names that are not the kind of a matched record:
    # "purchase orders from S-101" lists purchase orders that point at S-101.
    listed_types = [
        entity_type
        for entity_type in focus.entity_types
        if entity_type in counts and (not matched or entity_type not in matched_types)
    ]
    filter_scope = index.of_types(listed_types) if listed_types else []
    if not filter_scope and not matched and topic == TOPIC_ENTITIES:
        filter_scope = index.records
    already_named = [
        *(str(match["text"]) for match in matches),
        *(r.entity_id for r in matched),
        *(r.name for r in matched if r.name),
    ]
    filters = (
        match_value_filters(
            focus.residual,
            filter_scope,
            exclude=already_named,
            short_codes=focus.short_codes,
            question=question,
        )
        if filter_scope
        else []
    )
    unanswered = _unanswered_attributes(focus, matches) if topic == TOPIC_ENTITIES else []
    # Countries the question names, other than as part of a matched name. A
    # two-letter code in capitals ("DE") counts when the workspace stores that
    # country somewhere; "QA" and "IT" are otherwise not countries.
    matched_names = [f" {normalize_text(r.name or '')} " for r in matched]
    countries_in_question = {
        code: words
        for code, words in countries_mentioned(question).items()
        if not any(f" {normalize_text(words)} " in name for name in matched_names)
    }
    if focus.short_codes:
        stored_countries = {
            country_code(text)
            for record in index.records
            for key, text in record.items()
            if is_country_field(key)
        }
        for code in focus.short_codes:
            if code in stored_countries:
                countries_in_question.setdefault(code, code)
    countries_applied: set[str] = set()

    def narrowed(
        entity_type: str, candidates: Sequence[NodeRecord]
    ) -> tuple[list[NodeRecord], list[dict[str, Any]], dict[str, Any] | None]:
        """Records of one listed kind after the filters that apply to it.

        Returns (records, the filters on its own fields, a filter on the
        record it names). A filter applies to a kind of record only when that
        kind has the field: "orders from Indian suppliers" must not drop every
        order because orders have no country. A country the kind has no field
        for is looked for on the record it names: the supplier of a purchase
        order, the customer of a sales order, the facility of a stock position.
        """
        own_fields = {
            key.lower()
            for record in index.by_type.get(entity_type, [])
            for key, _text in record.items()
        }
        own = [item for item in filters if str(item["field"]).lower() in own_fields]
        kept = apply_value_filters(candidates, own)
        if focus.open_only:
            kept = open_flows(index, as_of, kept)
        own_countries = {
            country_code(str(item["value"])) for item in own if is_country_field(str(item["field"]))
        }
        countries_applied.update(code for code in own_countries if code)
        wanted = {code for code in countries_in_question if code not in own_countries}
        partner_type = _PARTNER_OF.get(entity_type)
        partners = index.by_type.get(partner_type, []) if partner_type else []
        if not partner_type or not partners:
            return kept, own, None
        partner_filters: list[dict[str, Any]] = []
        if wanted:
            partner_filters = [
                item
                for item in match_value_filters(
                    focus.residual,
                    partners,
                    exclude=already_named,
                    short_codes=focus.short_codes,
                    question=question,
                )
                if is_country_field(str(item["field"]))
                and country_code(str(item["value"])) in wanted
            ]
        if partner_type in listed_types:
            # "Orders from tier 1 suppliers": the question lists the suppliers
            # too, and a filter on a field only they have narrows the orders
            # that name them.
            partner_fields = {key.lower() for record in partners for key, _text in record.items()}
            partner_filters += [
                item
                for item in filters
                if str(item["field"]).lower() in partner_fields
                and str(item["field"]).lower() not in own_fields
                and item not in partner_filters
            ]
        if not partner_filters:
            return kept, own, None
        allowed = {id(record) for record in apply_value_filters(partners, partner_filters)}
        kept = [
            record
            for record in kept
            if (named_partner := index.reference(record, partner_type)) is not None
            and id(named_partner) in allowed
        ]
        countries_applied.update(
            code for item in partner_filters if (code := country_code(str(item["value"])))
        )
        return kept, own, {"through": partner_type, "filters": partner_filters}

    # Words of the question that a name, an identifier or a filter accounts for.
    explained_words = _explained_words(filters, [])
    for words in countries_in_question.values():
        explained_words.update(fold_word(word) for word in normalize_text(words).split())
    for match in matches:
        explained_words.update(
            fold_word(word) for word in normalize_text(str(match["text"])).split()
        )
    for record in matched:
        explained_words.update(
            fold_word(word) for word in normalize_text(record.name or "").split()
        )
    if focus.wants_comparison and len(matched) >= 2:
        # Side by side in the order the question names them.
        padded_question = f" {focus.normalized} "

        def asked_at(record: NodeRecord) -> int:
            positions = [
                padded_question.find(f" {normalize_text(str(match['text']))} ")
                for match in matches
                if match["record"] is record
            ]
            found_at = [position for position in positions if position >= 0]
            return min(found_at) if found_at else len(padded_question)

        matched = sorted(matched, key=asked_at)
        matches = sorted(matches, key=lambda match: asked_at(match["record"]))
    used_values = {normalize_text(str(item["value"])) for item in filters}
    unmatched = [
        candidate
        for candidate in focus.identifier_candidates
        if candidate.lower() not in found_ids and normalize_text(candidate) not in used_values
    ]

    version_files = await _version_files(
        session,
        workspace_id,
        {record.first_seen_version for record in matched}
        | {record.last_modified_version for record in matched},
        snapshots,
    )

    result: dict[str, Any]
    if not counts:
        result = {"kind": "empty_workspace", "intake": await _intake(session, workspace_id)}
    elif topic == TOPIC_CHANGES:
        result = {
            "kind": "changes",
            **(await _changes(session, workspace_id, snapshots, by_node_id)),
        }
    elif topic == TOPIC_INTAKE:
        result = {"kind": "intake", **(await _intake(session, workspace_id))}
    elif topic == TOPIC_DELAYS:
        result = {
            "kind": "late",
            **_late_view(late_flows(index, as_of, entity_types=focus.entity_types, focus=matched)),
            # Late supply traced to the parts it carries and their stock, so a
            # "what should I do" question is answered from the same facts.
            "exposure": _exposure_view(
                build_exposure(index, as_of, focus=matched), include_late_supply=False
            ),
        }
        if "Supplier" in focus.entity_types or "Supplier" in matched_types:
            wanted = {record.entity_id for record in matched if record.entity_type == "Supplier"}
            result["suppliers"] = _supplier_rows(
                [
                    row
                    for row in supplier_rollup(index, as_of)
                    if (row["late_order_count"] or row["flag"])
                    and (not wanted or row["entity_id"] in wanted)
                ]
            )
    elif topic == TOPIC_SHORTAGES:
        result = {"kind": "stock", **_stock_result_view(stock_positions(index, focus=matched))}
    elif topic == TOPIC_EXPOSURE:
        result = {"kind": "exposure", **_exposure_view(build_exposure(index, as_of, focus=matched))}
        if "Supplier" in focus.entity_types and not matched:
            result["suppliers"] = _supplier_rows(
                [
                    row
                    for row in supplier_rollup(index, as_of)
                    if row["late_order_count"] or row["flag"]
                ]
            )
    elif topic == TOPIC_OVERVIEW:
        result = {"kind": "overview", "intake": await _intake(session, workspace_id)}
    elif focus.wants_comparison and len(matched) >= 2:
        result = {
            "kind": "comparison",
            "as_of": as_of.isoformat(),
            "entities": [
                _comparison_entry(index, as_of, record)
                for record in matched[:MAX_COMPARED_ENTITIES]
            ],
            "matched_count": len(matched),
            "also_matched": [
                record.ref()
                for record in matched[
                    MAX_COMPARED_ENTITIES : MAX_COMPARED_ENTITIES + MAX_ALSO_MATCHED
                ]
            ],
        }
    elif matched and listed_types:
        # Records of the listed kinds that are linked to the named records:
        # directly, the other way round, or through orders that name both.
        groups: list[dict[str, Any]] = []
        aggregates: list[dict[str, Any]] = []
        for entity_type in listed_types:
            link = related_records(index, as_of, entity_type, matched)
            related, own_filters, partner = narrowed(entity_type, link["records"])
            group = _groups(related, [entity_type], counts)[0]
            group["via"] = link["via"]
            group["filters"] = own_filters
            group["partner_filter"] = partner
            if link["via"] == "orders":
                for item in group["records"]:
                    item["orders"] = link["orders"].get(str(item["entity_id"]))
            groups.append(group)
            if focus.aggregate:
                aggregates.append(
                    _aggregate_view(index, related, entity_type, counts, focus, explained_words)
                )
        result = {
            "kind": "aggregate" if focus.aggregate else "entity_list",
            "related_to": [record.ref() for record in matched[:MAX_ALSO_MATCHED]],
            "groups": groups,
            "open_only": focus.open_only,
        }
        if focus.aggregate:
            result["aggregates"] = _asked_figures(aggregates)
    elif matched:
        detailed: list[dict[str, Any]] = []
        for record in matched[:MAX_DETAILED_ENTITIES]:
            detailed.append(
                {
                    "record": record.summary(max_attributes=MAX_LISTED_ATTRIBUTES),
                    "source": _source_of(record, version_files),
                    "relationships": await _relationships(
                        session, workspace_id, record, by_node_id
                    ),
                    "counterparties": {
                        role: rows[:MAX_NESTED_ITEMS]
                        for role, rows in counterparties(index, as_of, record).items()
                    },
                    "late": _late_view(late_flows(index, as_of, focus=[record]), MAX_NESTED_ITEMS),
                    "stock": _stock_result_view(
                        stock_positions(index, focus=[record]),
                        MAX_NESTED_ITEMS,
                        include_positions=True,
                    ),
                    "exposure": _exposure_view(
                        build_exposure(index, as_of, focus=[record]), include_late_supply=False
                    )
                    if record.entity_type in {"Supplier", "Product", *FLOW_TYPES}
                    else None,
                }
            )
        result = {
            "kind": "entity_detail",
            "entities": detailed,
            "also_matched": [
                record.ref()
                for record in matched[
                    MAX_DETAILED_ENTITIES : MAX_DETAILED_ENTITIES + MAX_ALSO_MATCHED
                ]
            ],
            "matched_count": len(matched),
        }
    elif listed_types:
        groups = []
        aggregates = []
        for entity_type in listed_types:
            selected, own_filters, partner = narrowed(entity_type, index.of_types([entity_type]))
            group = _groups(selected, [entity_type], counts)[0]
            group["filters"] = own_filters
            group["partner_filter"] = partner
            groups.append(group)
            if focus.aggregate:
                aggregates.append(
                    _aggregate_view(index, selected, entity_type, counts, focus, explained_words)
                )
        result = {
            "kind": "aggregate" if focus.aggregate else "entity_list",
            "related_to": None,
            "groups": groups,
            "open_only": focus.open_only,
        }
        if focus.aggregate:
            result["aggregates"] = _asked_figures(aggregates)
    elif filters:
        selected = apply_value_filters(index.records, filters)
        result = {
            "kind": "entity_list",
            "related_to": None,
            "groups": _groups(selected, sorted({r.entity_type for r in selected}), counts),
        }
    elif focus.aggregate and (
        named_field := resolve_numeric_field(
            [*focus.residual.split(), *focus.aggregate_words], index.records, allow_usual=False
        )
    ):
        # "Highest unit price": no kind of record is named, but the field is.
        # The figure is given for each kind of record that has the field.
        holders = sorted(
            {record.entity_type for record in index.records if record.value(named_field.lower())}
        )
        result = {
            "kind": "aggregate",
            "related_to": None,
            "groups": [],
            "open_only": False,
            "aggregates": [
                _aggregate_view(
                    index,
                    index.of_types([entity_type]),
                    entity_type,
                    counts,
                    focus,
                    explained_words,
                )
                for entity_type in holders
            ],
        }
    else:
        missing_types = [t for t in focus.entity_types if t not in counts]
        result = {"kind": "no_match", "kinds_not_published": missing_types}

    return _fit(
        {
            "question_focus": {
                "topic": topic,
                "entity_types": list(focus.entity_types),
                "matched": [_matched_view(match) for match in matches[:MAX_ALSO_MATCHED]],
                "filters": filters,
                "unmatched_identifiers": unmatched,
                "wants_count": focus.wants_count,
                "asks_why": focus.asks_why,
                # What the question asks about a named record that the record
                # has no field for ("weather in Pune").
                "unanswered": unanswered,
                # Countries the question names that narrowed nothing: neither
                # the records listed nor the ones they name have a country.
                "countries_not_applied": [
                    country_name(code) or words
                    for code, words in countries_in_question.items()
                    if code not in countries_applied
                ]
                if result.get("kind") in {"entity_list", "aggregate"} and result.get("groups")
                else [],
            },
            "workspace": {
                "world_state_version": snapshots[0]["version"] if snapshots else 0,
                "entity_counts": dict(sorted(counts.items())),
                "relationship_counts": dict(sorted(relationship_counts.items())),
                "coverage": coverage,
                # A couple of real identifiers per kind, for "try asking" hints.
                "examples": {
                    entity_type: [record.entity_id for record in records_of_type[:2]]
                    for entity_type, records_of_type in sorted(index.by_type.items())[:8]
                },
                "sources": [
                    {
                        "version": item["version"],
                        "files": item["files"],
                        "sealed_at": item["sealed_at"],
                    }
                    for item in snapshots
                ],
            },
            "attention": _attention_view(attention_summary(index, as_of)) if counts else None,
            "result": result,
        }
    )


def _shrink(value: Any, max_items: int) -> Any:
    """Copy of a JSON-like value with every list cut to ``max_items`` entries."""
    if isinstance(value, dict):
        return {key: _shrink(item, max_items) for key, item in value.items()}
    if isinstance(value, list):
        return [_shrink(item, max_items) for item in value[:max_items]]
    return value


def _fit(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep the evidence within MAX_EVIDENCE_CHARS by shortening its lists.

    Totals live in separate "*_count" fields, so a shortened list never
    changes a number; ``lists_shortened_to`` records that it happened.
    """
    candidate = evidence
    for max_items in (None, 10, 6, 4, 2, 1):
        if max_items is not None:
            candidate = {**_shrink(evidence, max_items), "lists_shortened_to": max_items}
        size = len(json.dumps(candidate, default=str, separators=(",", ":")))
        if size <= MAX_EVIDENCE_CHARS:
            break
    return candidate


def _groups(
    records: Sequence[NodeRecord], entity_types: Sequence[str], counts: Mapping[str, int]
) -> list[dict[str, Any]]:
    """Records grouped by kind, each group listing at most MAX_LISTED_RECORDS."""
    groups: list[dict[str, Any]] = []
    for entity_type in entity_types:
        selected = [record for record in records if record.entity_type == entity_type]
        groups.append(
            {
                "entity_type": entity_type,
                "published_total": int(counts.get(entity_type, 0)),
                "matched": len(selected),
                "records": [
                    record.summary(max_attributes=MAX_LISTED_ATTRIBUTES)
                    for record in selected[:MAX_LISTED_RECORDS]
                ],
            }
        )
    return groups
