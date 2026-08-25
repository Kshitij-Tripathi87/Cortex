"""Repository for analytics.impact_reports (engines come in Week 2)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.disruption.models import ImpactReport


class ImpactReportRepository:
    """Workspace-scoped repository for `analytics.impact_reports`.

    In the MVP wedge this repository is INSERT-only; the propagation+impact
    engine uses it to persist computation results. Reads come from
    `GET /api/v1/mvp/ingest/{ingestion_id}` and the Week 3 Morning Brief
    endpoint.
    """

    def __init__(self, session: AsyncSession, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def append(self, report: ImpactReport) -> ImpactReport:
        report.workspace_id = self._workspace_id
        self._session.add(report)
        await self._session.flush()
        return report

    async def get(self, report_id: UUID) -> ImpactReport | None:
        stmt = select(ImpactReport).where(
            ImpactReport.id == report_id,
            ImpactReport.workspace_id == self._workspace_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def latest_for_event(self, disruption_event_id: UUID) -> ImpactReport | None:
        stmt = (
            select(ImpactReport)
            .where(
                ImpactReport.workspace_id == self._workspace_id,
                ImpactReport.disruption_event_id == disruption_event_id,
            )
            .order_by(ImpactReport.computed_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


__all__ = ["ImpactReportRepository"]
