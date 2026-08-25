"""Bootstrap script — create the first workspace and admin user.

Usage:

    python scripts/bootstrap_workspace.py \\
        --name "ACME Corp" \\
        --slug acme-corp \\
        --admin-email admin@acme.example \\
        --admin-password 'change-me-now'

Prereq: an empty PostgreSQL DB reachable via CORTEX_DB_DSN (or --dsn).
Idempotent: if the workspace already exists by slug, it is reused and
its admin user is left as-is.

The password is bcrypt-hashed in-place. Output prints the workspace_id
and user_id so the operator can wire up subsequent test data.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.config import get_settings
from app.infrastructure.database import get_session_factory, init_db
from app.modules.access.repository import UserRepository, WorkspaceRepository


async def _run(name: str, slug: str, admin_email: str, admin_password: str) -> tuple[UUID, UUID]:
    settings = get_settings()
    await init_db(settings.db_dsn)
    factory = get_session_factory()

    async with factory() as session:
        ws_repo = WorkspaceRepository(session)
        existing = await ws_repo.get_by_slug(slug)
        if existing is not None:
            print(f"Workspace slug '{slug}' already exists (id={existing.id}); reusing.")
            workspace = existing
        else:
            workspace = await ws_repo.create(name=name, slug=slug)
            await session.commit()
            print(
                f"Created workspace: name={workspace.name} slug={workspace.slug} id={workspace.id}"
            )

    # Re-query the user to avoid session-bound instances after the previous commit
    async with factory() as session:
        ws_repo = WorkspaceRepository(session)
        user_repo = UserRepository(session)
        workspace = await ws_repo.get_by_slug(slug)
        assert workspace is not None
        existing_user = await user_repo.get_by_email(workspace.id, admin_email)
        if existing_user is not None:
            print(f"Admin user already exists: email={admin_email} id={existing_user.id}")
            return workspace.id, existing_user.id

        # bcrypt hash via bcrypt library (it's already a project transitive
        # dependency through python-jose[cryptography]).
        import bcrypt

        hashed = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()
        user = await user_repo.create(
            workspace_id=workspace.id,
            email=admin_email,
            password_hash=hashed,
            role="admin",
        )
        await session.commit()
        print(f"Created admin user: email={user.email} id={user.id}")
        return workspace.id, user.id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Workspace display name")
    parser.add_argument("--slug", required=True, help="Workspace slug (unique)")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()

    ws_id, user_id = asyncio.run(
        _run(
            name=args.name,
            slug=args.slug,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
        )
    )
    print("\nBootstrap complete:")
    print(f"  WORKSPACE_ID={ws_id}")
    print(f"  ADMIN_USER_ID={user_id}")


if __name__ == "__main__":
    main()
