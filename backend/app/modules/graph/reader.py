"""EvidenceReader — decouples the compiler from the source of row data.

Today the compiler reads reconstructed rows from the profiler's sample_values.
Tomorrow it will read raw bytes from S3 (Phase 3 v2). The compiler should
not know or care — it talks to an EvidenceReader.

    EvidenceReader (Protocol)
        ├── ProfilerEvidenceReader  (Phase 3 v1: uses column profiles)
        └── ObjectStorageEvidenceReader  (Phase 3 v2: reads raw bytes from S3)

This abstraction lets us swap data sources without touching the compiler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.sources.models import SourceColumnProfile


@dataclass(frozen=True)
class EvidenceRow:
    """A single row of source data with its column profiles attached."""

    row_index: int
    values: dict[str, str]
    profiles: list[SourceColumnProfile]


class EvidenceReader(Protocol):
    """Reads row-level evidence from a source file.

    The compiler receives one of these and calls read_rows() to get back
    deterministic, ordered rows. Each implementation is responsible for
    its own caching and encoding handling.
    """

    async def read_rows(self, file_id: str, workspace_id: str) -> list[EvidenceRow]:
        """Return all rows for the given file, in deterministic order."""
        ...


class ProfilerEvidenceReader:
    """Phase 3 v1 reader — reconstructs rows from column profile sample_values.

    This is the bridge that lets Program A's compiler keep working without
    raw file access. Sample values are limited to MAX_SAMPLE_VALUES per
    column, so the reconstructed graph is partial. The compiler contract
    still holds: same inputs → same outputs.

    When ObjectStorageEvidenceReader lands in Phase 3 v2, swap it in here
    and the compiler code path is unchanged.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def read_rows(self, file_id: str, workspace_id: str) -> list[EvidenceRow]:
        from sqlalchemy import select

        stmt = (
            select(SourceColumnProfile)
            .where(SourceColumnProfile.file_id == file_id)
            .order_by(SourceColumnProfile.column_index)
        )
        result = await self._db.execute(stmt)
        profiles = list(result.scalars().all())

        if not profiles:
            return []

        max_rows = max((len(p.sample_values) for p in profiles), default=0)
        rows: list[EvidenceRow] = []
        for row_idx in range(max_rows):
            values: dict[str, str] = {}
            for p in profiles:
                values[p.column_name] = (
                    p.sample_values[row_idx] if row_idx < len(p.sample_values) else ""
                )
            rows.append(EvidenceRow(row_index=row_idx, values=values, profiles=profiles))
        return rows


class ObjectStorageEvidenceReader:
    """Phase 3 v2 reader — reads raw bytes from object storage and parses them.

    Stub. Will be activated when we wire raw file retrieval through the
    SourceStorage client. The compiler change is one line:
        reader = ObjectStorageEvidenceReader(storage_client)
    replacing:
        reader = ProfilerEvidenceReader(db)
    """

    def __init__(self, storage_client: Any) -> None:
        self._storage = storage_client

    async def read_rows(self, file_id: str, workspace_id: str) -> list[EvidenceRow]:
        raise NotImplementedError(
            "ObjectStorageEvidenceReader is a Phase 3 v2 stub. Use ProfilerEvidenceReader for now."
        )
