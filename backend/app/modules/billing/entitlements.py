"""Billing gate — server-side subscription/entitlement enforcement.

The enforcement point for the Nexus durable task runtime. Every check is
server-side and DB-backed; the React layer never manufactures entitlement.

Enforced before expensive/consequential operations:

    active subscription        → ALLOW
    expired subscription       → DENY  (402)
    quota exhausted            → DENY  (429)
    unentitled capability      → DENY  (403)
    unprovisioned workspace    → DENY  (403)
    concurrent creation race   → deterministic

Determinism: the concurrent-task quota is enforced while holding the
organization row (``SELECT ... FOR UPDATE``) across the whole creation —
the durable task commits before the slot is released, so a simultaneous
creation always observes every prior task in the count. Two creations can
never both pass the same quota boundary.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.access.models import Organization, Workspace
from app.modules.orchestration.task_lifecycle import TERMINAL_STATUSES
from app.modules.orchestration.task_runtime_models import TaskDB


class EntitlementDenied(Exception):
    """Server-side billing denial; the API maps ``http_status`` directly."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# Plans whose subscription never expires. "trial" is time-boxed by
# trial_ends_at; unknown plan values fall back to the free tier.
_PAID_PLANS = frozenset({"free", "pro", "enterprise"})

# Concurrent (non-terminal) task limit per plan. Product policy lives here,
# not in the runtime or the routes.
PLAN_CONCURRENT_TASK_LIMITS: dict[str, int] = {
    "free": 5,
    "trial": 25,
    "pro": 100,
    "enterprise": 1000,
}
_DEFAULT_CONCURRENT_TASK_LIMIT = PLAN_CONCURRENT_TASK_LIMITS["free"]

# Capability entitlements per plan: None = the full workspace-provisioned
# slice; a set = the only capability ids the plan may require.
PLAN_CAPABILITY_ENTITLEMENTS: dict[str, frozenset[str] | None] = {
    "free": frozenset({"world.inventory.read", "world.supplier.read", "world.risk.analyze"}),
    "trial": None,
    "pro": None,
    "enterprise": None,
}
_DEFAULT_CAPABILITY_ENTITLEMENTS: frozenset[str] | None = PLAN_CAPABILITY_ENTITLEMENTS["free"]


@dataclass(frozen=True)
class EntitlementSnapshot:
    """Resolved subscription state for one workspace's organization."""

    organization_id: UUID
    plan: str
    trial_ends_at: datetime | None
    active: bool
    concurrent_task_limit: int


class EntitlementService:
    """Server-side subscription/entitlement enforcement (billing gate)."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ── Resolution ───────────────────────────────────────────────────────────

    async def _resolve_org(self, session: AsyncSession, workspace_id: UUID) -> Organization | None:
        """Resolve the organization for a workspace via Workspace.organization_id."""
        row = await session.execute(
            select(Organization)
            .join(Workspace, Workspace.organization_id == Organization.id)
            .where(Workspace.id == workspace_id)
        )
        return row.scalars().first()

    @staticmethod
    def _subscription_active(org: Organization) -> bool:
        """Paid plans are active; a trial is active until trial_ends_at.

        SQLite reads back naive datetimes even for timezone=True columns;
        normalize to UTC before comparing (same convention as the relay
        health check).
        """
        if org.plan in _PAID_PLANS:
            return True
        if org.plan == "trial":
            trial_ends = org.trial_ends_at
            if trial_ends is not None and trial_ends.tzinfo is None:
                trial_ends = trial_ends.replace(tzinfo=UTC)
            return trial_ends is None or trial_ends >= datetime.now(UTC)
        return False

    async def snapshot(self, *, workspace_id: UUID) -> EntitlementSnapshot | None:
        """Read-only subscription state for a workspace (billing introspection)."""
        async with self._session_factory() as session:
            org = await self._resolve_org(session, workspace_id)
        if org is None:
            return None
        return EntitlementSnapshot(
            organization_id=org.id,
            plan=org.plan,
            trial_ends_at=org.trial_ends_at,
            active=self._subscription_active(org),
            concurrent_task_limit=PLAN_CONCURRENT_TASK_LIMITS.get(
                org.plan, _DEFAULT_CONCURRENT_TASK_LIMIT
            ),
        )

    # ── Checks ───────────────────────────────────────────────────────────────

    async def check_subscription(self, *, workspace_id: UUID) -> None:
        """Subscription gate for expensive/consequential operations.

        Active subscription → ALLOW. Expired trial → DENY (402).
        Unprovisioned workspace/org → DENY (403).
        """
        async with self._session_factory() as session:
            org = await self._resolve_org(session, workspace_id)
        if org is None:
            raise EntitlementDenied(
                "workspace_unprovisioned",
                f"No organization is provisioned for workspace {workspace_id}.",
                403,
            )
        if not self._subscription_active(org):
            raise EntitlementDenied(
                "subscription_expired",
                f"Subscription for organization '{org.name}' (plan '{org.plan}') "
                f"expired at {org.trial_ends_at.isoformat() if org.trial_ends_at else 'unknown'}.",
                402,
            )

    @asynccontextmanager
    async def creation_slot(
        self, *, workspace_id: UUID, required_capabilities: tuple[str, ...] = ()
    ) -> AsyncGenerator[None]:
        """Full task-creation gate, serialized on the organization row.

        The org row lock (FOR UPDATE) is held from acquisition until the
        caller finishes the durable creation, so the quota count at
        acquisition reflects every committed prior task of the organization
        and the race between simultaneous creations is deterministic.

        Order: subscription (402) → capability entitlement (403) →
        concurrent quota (429).
        """
        async with self._session_factory() as session:
            org = (
                (
                    await session.execute(
                        select(Organization)
                        .join(Workspace, Workspace.organization_id == Organization.id)
                        .where(Workspace.id == workspace_id)
                        .with_for_update(of=Organization)
                    )
                )
                .scalars()
                .first()
            )
            if org is None:
                raise EntitlementDenied(
                    "workspace_unprovisioned",
                    f"No organization is provisioned for workspace {workspace_id}.",
                    403,
                )
            if not self._subscription_active(org):
                raise EntitlementDenied(
                    "subscription_expired",
                    f"Subscription for organization '{org.name}' (plan '{org.plan}') "
                    f"expired at {org.trial_ends_at.isoformat() if org.trial_ends_at else 'unknown'}.",
                    402,
                )

            allowed = PLAN_CAPABILITY_ENTITLEMENTS.get(org.plan, _DEFAULT_CAPABILITY_ENTITLEMENTS)
            if allowed is not None:
                unentitled = tuple(
                    capability for capability in required_capabilities if capability not in allowed
                )
                if unentitled:
                    raise EntitlementDenied(
                        "capability_not_entitled",
                        f"Plan '{org.plan}' does not include capabilities: "
                        + ", ".join(unentitled),
                        403,
                    )

            limit = PLAN_CONCURRENT_TASK_LIMITS.get(org.plan, _DEFAULT_CONCURRENT_TASK_LIMIT)
            active = await self._count_active_tasks(session, org.id)
            if active >= limit:
                raise EntitlementDenied(
                    "quota_exhausted",
                    f"Plan '{org.plan}' concurrent task limit ({limit}) reached "
                    f"({active} active tasks).",
                    429,
                )
            # The caller performs the durable creation while the slot is
            # held; the task commits before the lock is released.
            yield

    async def _count_active_tasks(self, session: AsyncSession, org_id: UUID) -> int:
        """Count non-terminal tasks across the organization's workspaces."""
        workspace_ids = (
            (await session.execute(select(Workspace.id).where(Workspace.organization_id == org_id)))
            .scalars()
            .all()
        )
        if not workspace_ids:
            return 0
        row = await session.execute(
            select(func.count())
            .select_from(TaskDB)
            .where(
                TaskDB.workspace_id.in_([str(workspace_id) for workspace_id in workspace_ids]),
                TaskDB.status.not_in(sorted(TERMINAL_STATUSES)),
            )
        )
        return row.scalar() or 0
