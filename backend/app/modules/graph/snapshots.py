"""Graph snapshot sealing — immutable, hash-chained, deterministic.

Each snapshot seals a set of GraphWriteEvents into a tamper-evident chain.
The snapshot hash is SHA256(prev_hash || canonical_sort(write_event_payloads)).
The same inputs always produce the same hash (determinism contract).

Snapshot chain integrity can be verified later by replaying:
    verify_snapshot(snapshot_id) → recompute hash → compare with stored hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import GraphSnapshot, GraphWriteEvent


def _canonical_write_hash(payload: dict[str, Any]) -> str:
    """Hash a single write event's payload deterministically."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_snapshot_hash(
    prev_hash: str | None,
    write_payloads: list[dict[str, Any]],
) -> str:
    """Compute the deterministic hash of a snapshot.

    Hash = SHA256(prev_hash || SHA256(concat(canonical_sort(write_hashes))))
    """
    payload_hashes = sorted(_canonical_write_hash(p) for p in write_payloads)
    chain_input = (prev_hash or "") + "".join(payload_hashes)
    return hashlib.sha256(chain_input.encode("utf-8")).hexdigest()


async def seal_snapshot(
    db: AsyncSession,
    snapshot_id: str,
    workspace_id: str,
    version: int,
    prev_snapshot_id: str | None,
    prev_snapshot_hash: str | None,
    write_events: list[Any],
    node_count: int,
    edge_count: int,
    source_batch_id: str | None,
) -> str:
    """Persist a sealed GraphSnapshot with its hash-chained hash.

    Returns the computed snapshot_hash so callers can surface it.
    """
    write_payloads = [w.payload for w in write_events]
    snapshot_hash = compute_snapshot_hash(prev_snapshot_hash, write_payloads)

    snapshot = GraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id=workspace_id,
        version=version,
        prev_snapshot_id=prev_snapshot_id,
        prev_snapshot_hash=prev_snapshot_hash,
        snapshot_hash=snapshot_hash,
        node_count=node_count,
        edge_count=edge_count,
        source_batch_id=source_batch_id,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot_hash


async def get_latest_snapshot(
    db: AsyncSession,
    workspace_id: str,
) -> GraphSnapshot | None:
    """Return the most recent sealed snapshot for a workspace."""
    stmt = (
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .order_by(GraphSnapshot.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> GraphSnapshot | None:
    """Return a specific snapshot by ID."""
    return await db.get(GraphSnapshot, snapshot_id)


async def list_snapshots(
    db: AsyncSession,
    workspace_id: str,
    limit: int = 50,
) -> list[GraphSnapshot]:
    """List snapshots for a workspace, newest first."""
    stmt = (
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .order_by(GraphSnapshot.version.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def verify_snapshot_chain(
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Re-verify the entire snapshot hash chain for a workspace.

    Recomputes each snapshot's hash from its write events and compares
    it to the stored hash. Returns True if the entire chain is intact.
    """
    stmt = (
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .order_by(GraphSnapshot.version.asc())
    )
    result = await db.execute(stmt)
    snapshots = list(result.scalars().all())

    prev_hash: str | None = None
    for snap in snapshots:
        # Fetch write events for this snapshot
        event_stmt = (
            select(GraphWriteEvent)
            .where(GraphWriteEvent.snapshot_id == snap.snapshot_id)
            .order_by(GraphWriteEvent.occurred_at)
        )
        event_result = await db.execute(event_stmt)
        events = list(event_result.scalars().all())
        payloads = [e.payload for e in events]
        recomputed = compute_snapshot_hash(prev_hash, payloads)
        if recomputed != snap.snapshot_hash:
            return False
        prev_hash = snap.snapshot_hash
    return True
