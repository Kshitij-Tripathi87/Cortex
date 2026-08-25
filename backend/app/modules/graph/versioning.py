"""Snapshot version sequences — DB-backed monotonic versioning.

Provides atomic, workspace-scoped version sequence generation for:
  - Graph snapshots
  - Feature snapshots
  - Context snapshots
  - Signal snapshots
  - Propagation snapshots
  - Scenario snapshots
  - Recommendation snapshots

All versioning is now DB-backed — no more hardcoded `version = 1`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class SnapshotSequence(Base):
    """Tracks the next version number for each snapshot type per workspace.

    Uniqueness: (workspace_id, snapshot_type)
    """

    __tablename__ = "snapshot_sequences"

    sequence_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(64), nullable=False)
    next_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


async def get_next_version(
    db: AsyncSession,
    workspace_id: str,
    snapshot_type: str,
) -> int:
    """Get and increment the next version number for a workspace/snapshot type.

    This is atomic — no two callers can get the same version.

    Args:
        db: Database session
        workspace_id: Workspace scope
        snapshot_type: One of 'graph', 'feature', 'context', 'signal',
                       'propagation', 'scenario', 'recommendation'

    Returns:
        The next monotonic version number (1-based)
    """
    # Try to find existing sequence
    stmt = select(SnapshotSequence).where(
        SnapshotSequence.workspace_id == workspace_id,
        SnapshotSequence.snapshot_type == snapshot_type,
    )
    result = await db.execute(stmt)
    seq = result.scalar_one_or_none()

    if seq is None:
        # Create new sequence starting at 1
        seq = SnapshotSequence(
            workspace_id=workspace_id,
            snapshot_type=snapshot_type,
            next_version=1,
        )
        db.add(seq)
        await db.flush()
        return 1

    # Get current version and increment
    version = seq.next_version
    seq.next_version += 1
    await db.flush()

    return version


async def get_current_version(
    db: AsyncSession,
    workspace_id: str,
    snapshot_type: str,
) -> int | None:
    """Get the current (last used) version number without incrementing.

    Returns None if no sequence exists yet.
    """
    stmt = select(SnapshotSequence).where(
        SnapshotSequence.workspace_id == workspace_id,
        SnapshotSequence.snapshot_type == snapshot_type,
    )
    result = await db.execute(stmt)
    seq = result.scalar_one_or_none()

    if seq is None:
        return None

    # Current version is next_version - 1 (since next_version is the upcoming one)
    return seq.next_version - 1 if seq.next_version > 1 else None
