"""Ingestion log repository — read/update audit.ingestion_log."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingestion.models import IngestionLog


class IngestionLogRepository:
    """Workspace-scoped repository for `audit.ingestion_log`.

    The service creates a row at upload time and updates it as the ingest
    job progresses. Reads come from the `GET /api/v1/mvp/ingest/{id}`
    status endpoint.
    """

    def __init__(self, session: AsyncSession, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def create(self, log: IngestionLog) -> IngestionLog:
        log.workspace_id = self._workspace_id
        self._session.add(log)
        await self._session.flush()
        return log

    async def get(self, ingestion_id: UUID) -> IngestionLog | None:
        stmt = select(IngestionLog).where(
            IngestionLog.id == ingestion_id,
            IngestionLog.workspace_id == self._workspace_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_running(self, ingestion_id: UUID) -> None:
        stmt = (
            update(IngestionLog)
            .where(
                IngestionLog.id == ingestion_id,
                IngestionLog.workspace_id == self._workspace_id,
            )
            .values(status="running")
        )
        await self._session.execute(stmt)

    async def finalize(
        self,
        ingestion_id: UUID,
        *,
        status: str,
        rows_total: int,
        rows_accepted: int,
        rows_rejected: int,
        finished_at,
        message: str | None = None,
        error_log: list | None = None,
    ) -> None:
        values = {
            "status": status,
            "rows_total": rows_total,
            "rows_accepted": rows_accepted,
            "rows_rejected": rows_rejected,
            "finished_at": finished_at,
        }
        if message is not None:
            values["message"] = message
        if error_log is not None:
            values["error_log"] = error_log
        stmt = (
            update(IngestionLog)
            .where(
                IngestionLog.id == ingestion_id,
                IngestionLog.workspace_id == self._workspace_id,
            )
            .values(**values)
        )
        await self._session.execute(stmt)


__all__ = ["IngestionLogRepository"]
