"""Read the requests sent through the public site (demo requests, contact form).

The site has no mailbox behind it: a visitor's request is saved in the
database and this is how the team reads it. Nothing notifies you when one
arrives, so check regularly (for example `list` once a working day).

Usage (from backend/, with the same environment as the API: at least
CORTEX_ENV and CORTEX_DB_DSN; simplest is to run it inside a running API
container, e.g. `docker compose exec <api service> python scripts/contact_requests.py list`):

    python scripts/contact_requests.py list                  # unanswered, newest first
    python scripts/contact_requests.py list --status all --topic security --limit 50
    python scripts/contact_requests.py show REQ-7K3F9Q2M     # the whole request
    python scripts/contact_requests.py handle REQ-7K3F9Q2M --note "replied 18 Nov"

Requests contain personal data (name, email, the message). Run this only from
a trusted operator machine, and do not paste its output into shared channels.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.modules.contact.models import (  # noqa: E402
    STATUS_HANDLED,
    STATUS_NEW,
    TOPICS,
    ContactRequest,
)


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


async def list_requests(
    session: AsyncSession, *, status: str = STATUS_NEW, topic: str | None = None, limit: int = 20
) -> list[ContactRequest]:
    stmt = select(ContactRequest).order_by(ContactRequest.created_at.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(ContactRequest.status == status)
    if topic:
        stmt = stmt.where(ContactRequest.topic == topic)
    return list((await session.execute(stmt)).scalars().all())


async def find_request(session: AsyncSession, reference: str) -> ContactRequest | None:
    stmt = select(ContactRequest).where(ContactRequest.reference == reference.strip().upper())
    return (await session.execute(stmt)).scalar_one_or_none()


async def mark_handled(
    session: AsyncSession, reference: str, note: str | None = None
) -> ContactRequest | None:
    record = await find_request(session, reference)
    if record is None:
        return None
    record.status = STATUS_HANDLED
    record.handled_at = datetime.now(UTC)
    record.handled_note = (note or "").strip()[:500] or None
    await session.commit()
    return record


def format_row(record: ContactRequest) -> str:
    company = f" ({record.company})" if record.company else ""
    return (
        f"{record.reference}  {_when(record.created_at)}  {record.status:<7}  "
        f"{record.topic:<11}  {record.full_name}{company} <{record.email}>"
    )


def format_request(record: ContactRequest) -> str:
    lines = [
        f"Reference : {record.reference}",
        f"Received  : {_when(record.created_at)} UTC",
        f"Topic     : {record.topic}",
        f"From      : {record.full_name} <{record.email}>",
        f"Company   : {record.company or '-'}",
        f"Status    : {record.status}"
        + (f" on {_when(record.handled_at)} UTC" if record.handled_at else ""),
    ]
    if record.handled_note:
        lines.append(f"Note      : {record.handled_note}")
    for key, value in sorted((record.details or {}).items()):
        shown = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        if shown:
            lines.append(f"{key.replace('_', ' ').capitalize():<10}: {shown}")
    lines += ["", "Message:", record.message]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.database import close_db, get_session, init_db

    await init_db(get_settings().db_dsn)
    try:
        async with get_session() as session:
            if args.command == "list":
                records = await list_requests(
                    session, status=args.status, topic=args.topic, limit=args.limit
                )
                for listed in records:
                    print(format_row(listed))
                kind = "" if args.status == "all" else f"{args.status} "
                noun = "request" if len(records) == 1 else "requests"
                print(f"{len(records)} {kind}{noun} shown")
                return 0
            if args.command == "show":
                record = await find_request(session, args.reference)
                if record is None:
                    print(f"error: no request with reference {args.reference}", file=sys.stderr)
                    return 1
                print(format_request(record))
                return 0
            record = await mark_handled(session, args.reference, args.note)
            if record is None:
                print(f"error: no request with reference {args.reference}", file=sys.stderr)
                return 1
            print(f"{record.reference} marked as handled")
            return 0
    finally:
        await close_db()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read requests sent through the public site")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="list requests, newest first")
    listing.add_argument(
        "--status", choices=[STATUS_NEW, STATUS_HANDLED, "all"], default=STATUS_NEW
    )
    listing.add_argument("--topic", choices=list(TOPICS), default=None)
    listing.add_argument("--limit", type=int, default=20)

    show = commands.add_parser("show", help="print one request in full")
    show.add_argument("reference")

    handle = commands.add_parser("handle", help="mark a request as answered")
    handle.add_argument("reference")
    handle.add_argument("--note", default=None, help="what was done (max 500 characters)")
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
