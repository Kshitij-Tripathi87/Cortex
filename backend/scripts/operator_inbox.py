"""What is waiting for a person. Run it every working day.

Cortex sends no email and notifies nobody. Three things wait in the database
until someone looks:

  * requests sent through the site (demo requests, contact messages,
    security reports, privacy requests)   -> scripts/contact_requests.py
  * password resets asked for on the sign-in page -> scripts/admin_users.py
  * organizations whose trial has ended           -> scripts/admin_orgs.py

Usage (from backend/, with the same environment as the API; simplest is
inside a running API container):

    python scripts/operator_inbox.py            # print what is waiting
    python scripts/operator_inbox.py --check    # same, and exit with status 10
                                                # if a request or a reset waits

`--check` is for a scheduled job that should alert someone, for example
`python scripts/operator_inbox.py --check || <send yourself a message>`.
Paused organizations are shown for information and do not change the status:
they need no action unless the customer writes in.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.modules.access.models import Organization, User  # noqa: E402
from app.modules.billing.plans import subscription_is_active  # noqa: E402
from app.modules.contact.models import STATUS_NEW, ContactRequest  # noqa: E402

WAITING_STATUS = 10


@dataclass(frozen=True)
class Inbox:
    site_requests: int
    oldest_site_request: datetime | None
    reset_requests: int
    oldest_reset_request: datetime | None
    paused_organizations: int

    @property
    def needs_a_person(self) -> bool:
        return self.site_requests > 0 or self.reset_requests > 0


async def read_inbox(session: AsyncSession, *, now: datetime | None = None) -> Inbox:
    moment = now or datetime.now(UTC)
    site_count, site_oldest = (
        await session.execute(
            select(func.count(), func.min(ContactRequest.created_at)).where(
                ContactRequest.status == STATUS_NEW
            )
        )
    ).one()
    reset_count, reset_oldest = (
        await session.execute(
            select(func.count(), func.min(User.reset_requested_at)).where(
                User.reset_requested_at.is_not(None), User.is_active.is_(True)
            )
        )
    ).one()
    plans = (await session.execute(select(Organization.plan, Organization.trial_ends_at))).all()
    paused = sum(1 for plan, ends in plans if not subscription_is_active(plan, ends, now=moment))
    return Inbox(
        site_requests=int(site_count),
        oldest_site_request=site_oldest,
        reset_requests=int(reset_count),
        oldest_reset_request=reset_oldest,
        paused_organizations=paused,
    )


def _age(since: datetime | None, now: datetime) -> str:
    if since is None:
        return ""
    aware = since.replace(tzinfo=UTC) if since.tzinfo is None else since
    hours = int((now - aware).total_seconds() // 3600)
    if hours < 1:
        return ", oldest under an hour ago"
    if hours < 48:
        return f", oldest {hours} h ago"
    return f", oldest {hours // 24} days ago"


def format_inbox(inbox: Inbox, now: datetime) -> str:
    lines = [f"Waiting for a person ({now:%Y-%m-%d %H:%M} UTC)", ""]
    lines.append(
        f"Site requests unanswered : {inbox.site_requests}"
        f"{_age(inbox.oldest_site_request, now) if inbox.site_requests else ''}"
    )
    if inbox.site_requests:
        lines.append("    python scripts/contact_requests.py list")
    lines.append(
        f"Password resets waiting  : {inbox.reset_requests}"
        f"{_age(inbox.oldest_reset_request, now) if inbox.reset_requests else ''}"
    )
    if inbox.reset_requests:
        lines.append("    python scripts/admin_users.py reset-requests")
    lines.append(f"Paused organizations     : {inbox.paused_organizations} (for information)")
    if inbox.paused_organizations:
        lines.append("    python scripts/admin_orgs.py list --ended")
    if not inbox.needs_a_person:
        lines += ["", "Nothing needs an answer."]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.database import close_db, get_session, init_db

    await init_db(get_settings().db_dsn)
    try:
        async with get_session() as session:
            now = datetime.now(UTC)
            inbox = await read_inbox(session, now=now)
            print(format_inbox(inbox, now))
            return WAITING_STATUS if args.check and inbox.needs_a_person else 0
    finally:
        await close_db()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="What is waiting for a person")
    parser.add_argument(
        "--check",
        action="store_true",
        help=f"exit with status {WAITING_STATUS} when a request or a reset is waiting",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
