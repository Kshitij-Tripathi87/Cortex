"""Operator commands for user accounts: password resets, activation, listing.

Cortex sends no email. When a user asks for a password reset on the sign-in
page, the request is recorded and waits here until a person deals with it.
Nothing notifies you when one arrives, so check regularly (for example
`reset-requests` once a working day).

Usage (from backend/, with the same environment as the API: at least
CORTEX_ENV and CORTEX_DB_DSN; simplest is to run it inside a running API
container, e.g. `docker compose exec <api service> python scripts/admin_users.py ...`):

    python scripts/admin_users.py reset-requests                  # who is waiting for a link
    python scripts/admin_users.py issue-reset --email user@example.com
    python scripts/admin_users.py issue-reset --email user@example.com --valid-hours 4
    python scripts/admin_users.py dismiss-reset --email user@example.com
    python scripts/admin_users.py set-password --email user@example.com
    python scripts/admin_users.py deactivate --email user@example.com
    python scripts/admin_users.py activate --email user@example.com
    python scripts/admin_users.py list --limit 20

`issue-reset` prints a single-use link (valid 24 hours unless --valid-hours
says otherwise). Send it to the address on the account and to nobody else:
whoever holds the link can set the password. A request that reaches you some
other way ("please send my link to this other address") is how accounts get
stolen.

Security: run only from a trusted operator machine with database access, and
do not paste the output into shared channels.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.common.ids import uuid7_uuid  # noqa: E402
from app.modules.access.models import PasswordResetToken, User, Workspace  # noqa: E402
from app.modules.audit.service import emit as emit_audit  # noqa: E402
from app.modules.identity.jwt_auth import hash_password  # noqa: E402

# How long a link issued by an operator stays valid. The link travels by a
# person's mail, so the 30 minutes of the dev/test in-band token would have
# passed before most users read it.
DEFAULT_VALID_HOURS = 24
MAX_VALID_HOURS = 72

RESET_PAGE = "/auth/reset-password"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OperatorError(Exception):
    """A command could not be carried out; the message is for the operator."""


@dataclass(frozen=True)
class IssuedReset:
    email: str
    token: str
    expires_at: datetime


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _waited(since: datetime, now: datetime) -> str:
    hours = int((now - _aware(since)).total_seconds() // 3600)
    if hours < 1:
        return "under an hour"
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} days"


# ── Lookups ───────────────────────────────────────────────────────────


async def find_user(session: AsyncSession, email: str, workspace_id: str | None = None) -> User:
    stmt = select(User).where(User.email == email.strip().lower())
    if workspace_id:
        stmt = stmt.where(User.workspace_id == workspace_id)
    users = (await session.execute(stmt)).scalars().all()
    if not users:
        raise OperatorError(f"no account with the email {email.strip().lower()}")
    if len(users) > 1:
        raise OperatorError(
            f"{len(users)} accounts share the email {email.strip().lower()}; "
            "add --workspace-id to choose one"
        )
    return users[0]


async def waiting_reset_requests(session: AsyncSession, *, limit: int = 50) -> list[User]:
    """Active accounts with a reset request nobody has dealt with, oldest first."""
    stmt = (
        select(User)
        .where(User.reset_requested_at.is_not(None), User.is_active.is_(True))
        .order_by(User.reset_requested_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# ── Password resets ───────────────────────────────────────────────────


async def issue_reset(
    session: AsyncSession,
    user: User,
    *,
    valid_hours: int = DEFAULT_VALID_HOURS,
    now: datetime | None = None,
) -> IssuedReset:
    """Create the user's single-use reset token and close their waiting request."""
    if not 1 <= valid_hours <= MAX_VALID_HOURS:
        raise OperatorError(f"--valid-hours must be between 1 and {MAX_VALID_HOURS}")
    if not user.is_active:
        raise OperatorError(
            f"{user.email} is deactivated, so a reset link would not work; "
            "run `activate` first if the account should be usable"
        )
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(hours=valid_hours)
    # One live token per user: a link sent earlier stops working.
    await session.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    raw_token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            id=uuid7_uuid(),
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=expires_at,
            created_at=issued_at,
        )
    )
    user.reset_requested_at = None
    await emit_audit(
        session,
        event_type="auth.reset_issued",
        workspace_id=str(user.workspace_id),
        actor_type="operator",
        subject_type="user",
        subject_id=str(user.id),
        payload={"valid_hours": valid_hours},
        message="Password reset link issued by an operator",
    )
    await session.commit()
    return IssuedReset(email=user.email, token=raw_token, expires_at=expires_at)


async def dismiss_reset(session: AsyncSession, user: User) -> bool:
    """Close a waiting request without issuing a link. False if none was waiting."""
    if user.reset_requested_at is None:
        return False
    user.reset_requested_at = None
    await emit_audit(
        session,
        event_type="auth.reset_dismissed",
        workspace_id=str(user.workspace_id),
        actor_type="operator",
        subject_type="user",
        subject_id=str(user.id),
        message="Password reset request closed by an operator without a link",
    )
    await session.commit()
    return True


async def set_password(session: AsyncSession, user: User, password: str) -> None:
    if (
        len(password) < 10
        or not any(c.isalpha() for c in password)
        or not any(c.isdigit() for c in password)
    ):
        raise OperatorError("password must be >= 10 chars with a letter and a digit")
    user.password_hash = hash_password(password)
    user.password_changed_at = datetime.now(UTC)
    user.reset_requested_at = None
    await session.commit()


async def set_active(session: AsyncSession, user: User, active: bool) -> None:
    user.is_active = active
    await session.commit()


# ── Output ────────────────────────────────────────────────────────────


def site_url(origins: list[str], *, local_environment: bool, override: str | None = None) -> str:
    """The address of the site, for the link. Empty when it cannot be known.

    Without --site-url it is the one public origin the API accepts browser
    calls from (CORTEX_CORS_ALLOWED_ORIGINS), which is the site by
    definition. With several public origins the choice is the operator's.
    """
    if override:
        parts = urlsplit(override.strip())
        local = parts.hostname in _LOCAL_HOSTS
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            raise OperatorError("--site-url must look like https://app.example.com")
        if parts.scheme == "http" and not local:
            raise OperatorError("--site-url must start with https:// (a reset link is a secret)")
        return f"{parts.scheme}://{parts.netloc}"
    candidates = [o.rstrip("/") for o in origins if o.startswith(("https://", "http://"))]
    public = [o for o in candidates if urlsplit(o).hostname not in _LOCAL_HOSTS]
    if len(public) == 1:
        return public[0]
    if not public and local_environment and candidates:
        return candidates[0]
    return ""


def format_issued(issued: IssuedReset, site: str) -> str:
    path = f"{RESET_PAGE}?token={issued.token}"
    lines = [
        f"Reset link for {issued.email}",
        f"Single use. Valid until {_when(issued.expires_at)} UTC.",
        "",
    ]
    if site:
        lines.append(f"  {site}{path}")
    else:
        lines += [
            f"  {path}",
            "",
            "Put the address of your site in front of it (for example",
            "https://app.example.com), or run the command again with --site-url.",
        ]
    lines += [
        "",
        f"Send it to {issued.email} only: the address on the account. Whoever holds",
        "the link can set the password, so do not send it anywhere else.",
        "A link issued earlier for this account no longer works.",
    ]
    return "\n".join(lines)


def format_waiting(user: User, now: datetime) -> str:
    since = user.reset_requested_at
    name = f"  {user.full_name}" if user.full_name else ""
    waited = f" ({_waited(since, now)})" if since else ""
    return f"{user.email}{name}  waiting since {_when(since)} UTC{waited}"


def format_user(user: User, workspace: str) -> str:
    waiting = "  reset-requested" if user.reset_requested_at else ""
    return (
        f"{user.email}  role={user.role}  active={user.is_active}  workspace={workspace}{waiting}"
    )


# ── Command line ──────────────────────────────────────────────────────

_NEEDS_EMAIL = ("issue-reset", "dismiss-reset", "set-password", "deactivate", "activate")
COMMANDS = ("reset-requests", *_NEEDS_EMAIL, "list")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator commands for user accounts")
    parser.add_argument("--email", help="User email (case-insensitive)")
    parser.add_argument("--workspace-id", default=None, help="Disambiguate repeat emails")
    parser.add_argument("--limit", type=int, default=20, help="page size of the lists")
    parser.add_argument(
        "--valid-hours",
        type=int,
        default=DEFAULT_VALID_HOURS,
        help=f"issue-reset: how long the link works (1-{MAX_VALID_HOURS}, default "
        f"{DEFAULT_VALID_HOURS})",
    )
    parser.add_argument(
        "--site-url",
        default=None,
        help="issue-reset: address of the site, e.g. https://app.example.com",
    )
    parser.add_argument("command", choices=list(COMMANDS))
    return parser


async def _dispatch(args: argparse.Namespace, session: AsyncSession, settings: Any) -> int:
    from app.config import is_local_environment

    now = datetime.now(UTC)
    if args.command == "reset-requests":
        waiting = await waiting_reset_requests(session, limit=args.limit)
        for user in waiting:
            print(format_waiting(user, now))
        if not waiting:
            print("No account is waiting for a reset link.")
            return 0
        noun = "account is" if len(waiting) == 1 else "accounts are"
        print(f"{len(waiting)} {noun} waiting for a reset link. For each one:")
        print("  python scripts/admin_users.py issue-reset --email <address>")
        return 0

    if args.command == "list":
        users = (await session.execute(select(User).limit(args.limit))).scalars().all()
        ws_ids = {u.workspace_id for u in users}
        slugs: dict[Any, str] = {}
        if ws_ids:
            rows = (
                await session.execute(
                    select(Workspace.id, Workspace.slug).where(Workspace.id.in_(ws_ids))
                )
            ).all()
            slugs = {r[0]: r[1] for r in rows}
        for u in users:
            print(format_user(u, slugs.get(u.workspace_id, str(u.workspace_id))))
        return 0

    user = await find_user(session, args.email, args.workspace_id)
    if args.command == "issue-reset":
        site = site_url(
            list(getattr(settings, "cors_allowed_origins", []) or []),
            local_environment=is_local_environment(settings.env),
            override=args.site_url,
        )
        issued = await issue_reset(session, user, valid_hours=args.valid_hours, now=now)
        print(format_issued(issued, site))
        return 0
    if args.command == "dismiss-reset":
        if await dismiss_reset(session, user):
            print(f"ok: the reset request of {user.email} is closed; no link was issued")
        else:
            print(f"{user.email} has no reset request waiting")
        return 0
    if args.command == "set-password":
        password = getpass.getpass("New password (>=10 chars, letter+digit): ")
        await set_password(session, user, password)
        print(f"ok: password updated for {user.email}")
        return 0
    await set_active(session, user, args.command == "activate")
    print(f"ok: {user.email} is_active={args.command == 'activate'}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.infrastructure.database import close_db, get_session, init_db

    settings = get_settings()
    await init_db(settings.db_dsn)
    try:
        async with get_session() as session:
            try:
                return await _dispatch(args, session, settings)
            except OperatorError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
    finally:
        await close_db()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in _NEEDS_EMAIL and not args.email:
        parser.error("--email is required")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
