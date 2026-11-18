"""What the published records of a workspace show, for the Command Center.

The cockpit used to draw its figures from the risk register alone. Nothing
writes that register except a direct API call, so a workspace with late
purchase orders showed "0 open disruptions" beside an Ask box that listed
them. This module answers the cockpit from the same facts as the Ask box:
``workspace_evidence`` loads the records and ``workspace_facts`` judges them,
and the sentences come from ``answer_rendering``. The two can therefore not
disagree about what is late, short or flagged.

Read-only. Nothing here is estimated: an order is late because of the dates
and status in its own record, and each item says which.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.p0_migration import workspace_evidence
from app.modules.nexus_spine.p0_migration.answer_rendering import (
    attention_sentences,
    flagged_sentence,
    kind_noun,
    late_flow_parts,
    late_flow_sentence,
    stock_parts,
    stock_sentence,
)
from app.modules.nexus_spine.p0_migration.workspace_evidence import (
    _attention_view,
    _entity_counts,
    _load_records,
    _relationship_counts,
    _snapshots,
    utc_iso,
)
from app.modules.nexus_spine.p0_migration.workspace_facts import (
    WorkspaceIndex,
    attention_summary,
    flagged_records,
    late_flows,
    stock_positions,
)

# Items listed per group. The matching "count" always carries the full number.
MAX_OVERVIEW_ITEMS = 10

# Kinds whose own status field can mark a problem (same list as the Ask box).
_FLAGGED_KINDS: tuple[str, ...] = ("Supplier", "Carrier", "Customer")


def _late_item(flow: Mapping[str, Any]) -> dict[str, Any]:
    subject, reasons = late_flow_parts(flow)
    return {
        "entity_type": flow["entity_type"],
        "entity_id": flow["entity_id"],
        "noun": kind_noun(str(flow["entity_type"]), 1),
        "days_late": flow["days_late"],
        "status": flow["status"],
        "promised_date": flow["promised_date"],
        "expected_date": flow["expected_date"],
        # What it carries and why it counts as late, then both as one sentence.
        "subject": subject,
        "reasons": reasons,
        "text": late_flow_sentence(flow),
    }


def _stock_item(position: Mapping[str, Any]) -> dict[str, Any]:
    where, detail = stock_parts(position)
    return {
        "entity_type": position["entity_type"],
        "entity_id": position["entity_id"],
        "product": position["product"],
        "facility": position["facility"],
        "on_hand": position["on_hand"],
        "threshold": position["threshold"],
        "threshold_field": position["threshold_field"],
        "out_of_stock": position["out_of_stock"],
        # Which stock, the figures it is judged on, then both as one sentence.
        "where": where,
        "detail": detail,
        "text": f"{stock_sentence(position)}.",
    }


def _flagged_item(flag: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": flag["entity_type"],
        "entity_id": flag["entity_id"],
        "name": flag["name"],
        "noun": kind_noun(str(flag["entity_type"]), 1),
        "status": flag["status"],
        "text": flagged_sentence(flag),
    }


async def build_workspace_overview(
    session: AsyncSession,
    workspace_id: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Counts of the published records and what stands out in them.

    ``published`` is ``None`` until a first upload has been published; the
    counts are then zero and the three groups are empty.
    """
    # One clock for the cockpit and the Ask box: the date an answer states.
    as_of = today or workspace_evidence._today()
    counts = await _entity_counts(session, workspace_id)
    relationship_counts = await _relationship_counts(session, workspace_id)
    snapshots = await _snapshots(session, workspace_id)
    # Loaded exactly as for a question that names no kind of record, so the
    # figures match the answer to "What needs attention?".
    records, coverage = await _load_records(session, workspace_id, counts, ())
    index = WorkspaceIndex(records)

    late = late_flows(index, as_of)
    stock = stock_positions(index)
    flagged = flagged_records(index, _FLAGGED_KINDS)
    checked_flows = sum(int(number) for number in late["assessed"].values())

    latest = snapshots[0] if snapshots else None
    by_type = [
        {"entity_type": entity_type, "noun": kind_noun(entity_type, count), "count": count}
        for entity_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "as_of": as_of.isoformat(),
        "published": (
            {
                "version": latest["version"],
                "published_at": utc_iso(latest["sealed_at"]),
                # Files of this publish; earlier versions came from other files.
                "files": latest["files"],
            }
            if latest
            else None
        ),
        "records": {"total": sum(counts.values()), "by_type": by_type},
        "relationships": {"total": sum(relationship_counts.values())},
        "reading": {
            "complete": bool(coverage["complete"]),
            "records_read": int(coverage["records_loaded"]),
            "records_total": int(coverage["records_total"]),
        },
        # The sentences the Ask box gives for "What needs attention?".
        "summary": (
            attention_sentences(_attention_view(attention_summary(index, as_of))) if counts else []
        ),
        "late": {
            "count": late["late_count"],
            "checked": checked_flows,
            "items": [_late_item(flow) for flow in late["late"][:MAX_OVERVIEW_ITEMS]],
        },
        "stock": {
            "count": stock["short_count"],
            "checked": stock["assessed"],
            "items": [_stock_item(position) for position in stock["short"][:MAX_OVERVIEW_ITEMS]],
        },
        "flagged": {
            "count": len(flagged),
            "items": [_flagged_item(flag) for flag in flagged[:MAX_OVERVIEW_ITEMS]],
        },
        "attention_count": late["late_count"] + stock["short_count"] + len(flagged),
    }


__all__ = ["MAX_OVERVIEW_ITEMS", "build_workspace_overview"]
