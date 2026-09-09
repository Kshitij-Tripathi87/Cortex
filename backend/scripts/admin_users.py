"""Admin user operations — account rescue until Day-15 email exists.

Usage (from backend/, with CORTEX_DB_DSN set):
    python scripts/admin_users.py issue-reset --email user@example.com
    python scripts/admin_users.py set-password --email user@example.com
    python scripts/admin_users.py deactivate --email user@example.com
    python scripts/admin_users.py activate --email user@example.com
    python scripts/admin_users.py list --limit 20

Security: run only from a trusted operator machine with DB access. `issue-reset`
prints a single-use token (30-min TTL) to stdout — relay it to the user over a
trusted channel, then it is redeemed via POST /auth/reset/confirm.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.infrastructure.database import close_db, init_db  # noqa: E402
from app.modules.access.models import PasswordResetToken, User, Workspace  # noqa: E402
from app.modules.identity.jwt_auth import hash_password  # noqa: E402

RESET_TOKEN_TTL_MINUTES = 30


async def cmd_issue_reset(email: str, workspace_id: str | None) -> int:
    from app.common.ids import uuid7_uuid
    from app.infrastructure.database import get_session

    async with get_session() as session:
        stmt = select(User).where(User.email == email.strip().lower())
        if workspace_id:
            stmt = stmt.where(User.workspace_id == workspace_id)
        users = (await session.execute(stmt)).scalars().all()
        if len(users) != 1:
            print(f"error: expected exactly 1 user, found {len(users)}", file=sys.stderr)
            return 1
        user = users[0]
        await session.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session.add(
            PasswordResetToken(
                id=uuid7_uuid(),
                user_id=user.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
                created_at=now,
            )
        )
        await session.commit()
        print(f"user: {user.email} (workspace {user.workspace_id})")
        print(f"reset_token: {raw_token}")
        print(f"expires_at: {(now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)).isoformat()}")
        return 0


async def cmd_set_password(email: str, workspace_id: str | None) -> int:
    from app.infrastructure.database import get_session

    password = getpass.getpass("New password (>=10 chars, letter+digit): ")
    if (
        len(password) < 10
        or not any(c.isalpha() for c in password)
        or not any(c.isdigit() for c in password)
    ):
        print("error: password must be >= 10 chars with a letter and a digit", file=sys.stderr)
        return 1
    async with get_session() as session:
        stmt = select(User).where(User.email == email.strip().lower())
        if workspace_id:
            stmt = stmt.where(User.workspace_id == workspace_id)
        users = (await session.execute(stmt)).scalars().all()
        if len(users) != 1:
            print(f"error: expected exactly 1 user, found {len(users)}", file=sys.stderr)
            return 1
        user = users[0]
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(UTC)
        await session.commit()
        print(f"ok: password updated for {user.email}")
        return 0


async def cmd_set_active(email: str, workspace_id: str | None, active: bool) -> int:
    from app.infrastructure.database import get_session

    async with get_session() as session:
        stmt = select(User).where(User.email == email.strip().lower())
        if workspace_id:
            stmt = stmt.where(User.workspace_id == workspace_id)
        users = (await session.execute(stmt)).scalars().all()
        if len(users) != 1:
            print(f"error: expected exactly 1 user, found {len(users)}", file=sys.stderr)
            return 1
        user = users[0]
        user.is_active = active
        await session.commit()
        print(f"ok: {user.email} is_active={active}")
        return 0


async def cmd_list(limit: int) -> int:
    from app.infrastructure.database import get_session

    async with get_session() as session:
        users = (await session.execute(select(User).limit(limit))).scalars().all()
        ws_ids = {u.workspace_id for u in users}
        slugs = {}
        if ws_ids:
            rows = (
                await session.execute(
                    select(Workspace.id, Workspace.slug).where(Workspace.id.in_(ws_ids))
                )
            ).all()
            slugs = {r[0]: r[1] for r in rows}
        for u in users:
            print(
                f"{u.email}  role={u.role}  active={u.is_active}  "
                f"workspace={slugs.get(u.workspace_id, u.workspace_id)}"
            )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Admin user operations")
    parser.add_argument("--email", help="User email (case-insensitive)")
    parser.add_argument("--workspace-id", default=None, help="Disambiguate repeat emails")
    parser.add_argument("--limit", type=int, default=20, help="list page size")
    parser.add_argument(
        "command", choices=["issue-reset", "set-password", "deactivate", "activate", "list"]
    )
    args = parser.parse_args()

    async def _run() -> int:
        settings = get_settings()
        await init_db(settings.db_dsn)
        try:
            if args.command == "issue-reset":
                if not args.email:
                    parser.error("--email is required")
                return await cmd_issue_reset(args.email, args.workspace_id)
            if args.command == "set-password":
                if not args.email:
                    parser.error("--email is required")
                return await cmd_set_password(args.email, args.workspace_id)
            if args.command == "deactivate":
                if not args.email:
                    parser.error("--email is required")
                return await cmd_set_active(args.email, args.workspace_id, False)
            if args.command == "activate":
                if not args.email:
                    parser.error("--email is required")
                return await cmd_set_active(args.email, args.workspace_id, True)
            return await cmd_list(args.limit)
        finally:
            await close_db()

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
