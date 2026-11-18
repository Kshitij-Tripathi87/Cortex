"""Operator commands for organizations: see plans, extend a trial, set a plan.

Every sign-up starts a 7-day trial. When it ends, creating, running and
approving tasks is refused (HTTP 402) and the site tells the user to write
in. Cortex has no billing system: this script is how a plan is changed.

Usage (from backend/, with the same environment as the API: at least
CORTEX_ENV and CORTEX_DB_DSN; simplest is to run it inside a running API
container, e.g. `docker compose exec <api service> python scripts/admin_orgs.py list`):

    python scripts/admin_orgs.py list                    # every organization and its plan
    python scripts/admin_orgs.py list --ended            # only the ones that are paused
    python scripts/admin_orgs.py show --email user@example.com
    python scripts/admin_orgs.py extend-trial --email user@example.com --days 14
    python scripts/admin_orgs.py set-plan --org meridian-pumps --plan pro
    python scripts/admin_orgs.py set-plan --org meridian-pumps --plan trial --days 30

An organization is named either by its slug (--org, as printed by `list`) or
by the email of one of its users (--email). Add --note "why" to record the
reason; every change is written to the organization's audit trail.

Plans: trial (ends on a date), free, pro, enterprise (do not end). The
limits of each plan are in app/modules/billing/entitlements.py.

Security: run only from a trusted operator machine with database access.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.modules.access.models import Organization, User, Workspace  # noqa: E402
from app.modules.audit.service import emit as emit_audit  # noqa: E402
from app.modules.billing.plans import (  # noqa: E402
    KNOWN_PLANS,
    PAUSED_ACTIONS,
    TRIAL_PLAN,
    as_utc,
    subscription_is_active,
)

MAX_TRIAL_DAYS = 365


class OperatorError(Exception):
    """A command could not be carried out; the message is for the operator."""


@dataclass(frozen=True)
class PlanChange:
    organization: str
    before: str
    after: str


def _day(value: datetime | None) -> str:
    return as_utc(value).strftime("%Y-%m-%d %H:%M UTC") if value else "no end date"


def describe_plan(plan: str, trial_ends_at: datetime | None, *, now: datetime | None = None) -> str:
    """One phrase for the state of a plan, e.g. 'trial, ended 2026-11-10 05:00 UTC'."""
    if plan != TRIAL_PLAN:
        if subscription_is_active(plan, trial_ends_at, now=now):
            return plan
        return f"{plan} (not a known plan: paused)"
    if trial_ends_at is None:
        return "trial, no end date"
    if subscription_is_active(plan, trial_ends_at, now=now):
        return f"trial, ends {_day(trial_ends_at)}"
    return f"trial, ended {_day(trial_ends_at)}"


def _check_days(days: int | None) -> int:
    if days is None:
        raise OperatorError("--days is required")
    if not 1 <= days <= MAX_TRIAL_DAYS:
        raise OperatorError(f"--days must be between 1 and {MAX_TRIAL_DAYS}")
    return days


# ── Lookups ───────────────────────────────────────────────────────────


async def find_organization(
    session: AsyncSession, *, slug: str | None = None, email: str | None = None
) -> Organization:
    if bool(slug) == bool(email):
        raise OperatorError("name the organization with exactly one of --org or --email")
    if slug:
        wanted = slug.strip().lower()
        org = (
            await session.execute(select(Organization).where(Organization.slug == wanted))
        ).scalar_one_or_none()
        if org is None:
            raise OperatorError(f"no organization with the slug {wanted}")
        return org
    address = (email or "").strip().lower()
    orgs = (
        (
            await session.execute(
                select(Organization)
                .join(Workspace, Workspace.organization_id == Organization.id)
                .join(User, User.workspace_id == Workspace.id)
                .where(User.email == address)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not orgs:
        raise OperatorError(f"no organization has a user with the email {address}")
    if len(orgs) > 1:
        slugs = ", ".join(sorted(o.slug for o in orgs))
        raise OperatorError(f"{address} belongs to several organizations ({slugs}); use --org")
    return orgs[0]


async def list_organizations(
    session: AsyncSession,
    *,
    only_ended: bool = False,
    limit: int = 50,
    now: datetime | None = None,
) -> list[Organization]:
    """Newest first. ``only_ended`` keeps the organizations whose plan is paused."""
    orgs = (
        (await session.execute(select(Organization).order_by(Organization.created_at.desc())))
        .scalars()
        .all()
    )
    if only_ended:
        orgs = [o for o in orgs if not subscription_is_active(o.plan, o.trial_ends_at, now=now)]
    return list(orgs[:limit])


async def count_users(session: AsyncSession, organization: Organization) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .join(Workspace, Workspace.id == User.workspace_id)
        .where(Workspace.organization_id == organization.id)
    )
    return int((await session.execute(stmt)).scalar_one())


# ── Changes ───────────────────────────────────────────────────────────


async def _record(
    session: AsyncSession,
    organization: Organization,
    *,
    event_type: str,
    message: str,
    before: str,
    after: str,
    note: str | None,
) -> None:
    workspace_id = (
        await session.execute(
            select(Workspace.id)
            .where(Workspace.organization_id == organization.id)
            .order_by(Workspace.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    payload = {"organization_id": str(organization.id), "before": before, "after": after}
    if note and note.strip():
        payload["note"] = note.strip()[:500]
    await emit_audit(
        session,
        event_type=event_type,
        workspace_id=str(workspace_id) if workspace_id is not None else None,
        tenant_id=str(organization.id),
        actor_type="operator",
        subject_type="organization",
        subject_id=str(organization.id),
        payload=payload,
        message=message,
    )


async def extend_trial(
    session: AsyncSession,
    organization: Organization,
    days: int | None,
    *,
    note: str | None = None,
    now: datetime | None = None,
) -> PlanChange:
    """Add days to a trial: from its end date if it is still running, else from now."""
    days = _check_days(days)
    if organization.plan != TRIAL_PLAN:
        raise OperatorError(
            f"{organization.slug} is on the plan '{organization.plan}', not a trial; "
            "use `set-plan --plan trial --days N` to start one"
        )
    if organization.trial_ends_at is None:
        raise OperatorError(f"the trial of {organization.slug} has no end date: nothing to extend")
    moment = now or datetime.now(UTC)
    before = describe_plan(organization.plan, organization.trial_ends_at, now=moment)
    start = max(as_utc(organization.trial_ends_at), moment)
    organization.trial_ends_at = start + timedelta(days=days)
    organization.updated_at = moment
    after = describe_plan(organization.plan, organization.trial_ends_at, now=moment)
    await _record(
        session,
        organization,
        event_type="billing.trial_extended",
        message=f"Trial extended by {days} days by an operator",
        before=before,
        after=after,
        note=note,
    )
    await session.commit()
    return PlanChange(organization=organization.slug, before=before, after=after)


async def set_plan(
    session: AsyncSession,
    organization: Organization,
    plan: str,
    *,
    days: int | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> PlanChange:
    """Put the organization on a plan. A trial needs ``days``; other plans do not end."""
    if plan not in KNOWN_PLANS:
        raise OperatorError(f"unknown plan '{plan}'; choose one of: {', '.join(KNOWN_PLANS)}")
    moment = now or datetime.now(UTC)
    before = describe_plan(organization.plan, organization.trial_ends_at, now=moment)
    if plan == TRIAL_PLAN:
        organization.trial_ends_at = moment + timedelta(days=_check_days(days))
    elif days is not None:
        raise OperatorError(f"--days only applies to a trial; the plan '{plan}' does not end")
    organization.plan = plan
    organization.updated_at = moment
    after = describe_plan(organization.plan, organization.trial_ends_at, now=moment)
    await _record(
        session,
        organization,
        event_type="billing.plan_changed",
        message=f"Plan set to '{plan}' by an operator",
        before=before,
        after=after,
        note=note,
    )
    await session.commit()
    return PlanChange(organization=organization.slug, before=before, after=after)


# ── Output ────────────────────────────────────────────────────────────


def format_row(organization: Organization, *, now: datetime | None = None) -> str:
    state = describe_plan(organization.plan, organization.trial_ends_at, now=now)
    return f"{organization.slug:<28}  {state:<38}  {organization.name}"


def format_organization(
    organization: Organization, users: int, *, now: datetime | None = None
) -> str:
    active = subscription_is_active(organization.plan, organization.trial_ends_at, now=now)
    lines = [
        f"Organization : {organization.name}",
        f"Slug         : {organization.slug}",
        f"Plan         : {describe_plan(organization.plan, organization.trial_ends_at, now=now)}",
        f"Users        : {users}",
        f"Created      : {_day(organization.created_at)}",
        f"State        : {'active' if active else 'paused'}",
    ]
    if not active:
        lines.append(f"               {PAUSED_ACTIONS}")
    return "\n".join(lines)


def format_change(change: PlanChange) -> str:
    return f"{change.organization}: {change.before}  ->  {change.after}"


# ── Command line ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator commands for organizations and plans")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="every organization and its plan, newest first")
    listing.add_argument("--ended", action="store_true", help="only paused organizations")
    listing.add_argument("--limit", type=int, default=50)

    def _named(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--org", default=None, help="slug of the organization")
        sub.add_argument("--email", default=None, help="email of one of its users")
        return sub

    _named("show", "one organization in full")

    extend = _named("extend-trial", "add days to a trial")
    extend.add_argument("--days", type=int, required=True)
    extend.add_argument("--note", default=None, help="why (kept in the audit trail)")

    plan = _named("set-plan", "put the organization on a plan")
    plan.add_argument("--plan", choices=list(KNOWN_PLANS), required=True)
    plan.add_argument("--days", type=int, default=None, help="length of a trial")
    plan.add_argument("--note", default=None, help="why (kept in the audit trail)")
    return parser


async def _dispatch(args: argparse.Namespace, session: AsyncSession) -> int:
    now = datetime.now(UTC)
    if args.command == "list":
        orgs = await list_organizations(session, only_ended=args.ended, limit=args.limit, now=now)
        for org in orgs:
            print(format_row(org, now=now))
        noun = "organization" if len(orgs) == 1 else "organizations"
        print(f"{len(orgs)} {'paused ' if args.ended else ''}{noun} shown")
        return 0

    org = await find_organization(session, slug=args.org, email=args.email)
    if args.command == "show":
        print(format_organization(org, await count_users(session, org), now=now))
        return 0
    if args.command == "extend-trial":
        change = await extend_trial(session, org, args.days, note=args.note, now=now)
    else:
        change = await set_plan(session, org, args.plan, days=args.days, note=args.note, now=now)
    print(format_change(change))
    return 0


async def _run(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.database import close_db, get_session, init_db

    await init_db(get_settings().db_dsn)
    try:
        async with get_session() as session:
            try:
                return await _dispatch(args, session)
            except OperatorError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
    finally:
        await close_db()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
