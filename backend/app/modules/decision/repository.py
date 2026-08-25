"""Repositories for decision_log and decision_memory."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.decision.models import DecisionLog


class DecisionLogRepository:
    """Workspace-scoped repository for `decision.decision_log`.

    Records are INSERT-only by convention (ADR-0010); this repository is
    strictly additive. Mutation methods are deliberately absent.
    """

    def __init__(self, session: AsyncSession, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def append(self, record: DecisionLog) -> DecisionLog:
        record.workspace_id = self._workspace_id
        self._session.add(record)
        await self._session.flush()
        return record

    async def get(self, decision_id: UUID) -> DecisionLog | None:
        stmt = select(DecisionLog).where(
            DecisionLog.id == decision_id,
            DecisionLog.workspace_id == self._workspace_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_event(
        self,
        disruption_event_id: UUID,
        *,
        limit: int = 100,
    ) -> list[DecisionLog]:
        stmt = (
            select(DecisionLog)
            .where(
                DecisionLog.workspace_id == self._workspace_id,
                DecisionLog.disruption_event_id == disruption_event_id,
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())


__all__ = ["DecisionLogRepository"]
