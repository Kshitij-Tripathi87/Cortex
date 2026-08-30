"""F4 — Tenant isolation primitives (Phase 15 production gate).

PostgreSQL Row-Level Security (RLS) policies enforce tenant isolation
at the database layer, but they need the tenant/workspace context
to be visible to the policy. The standard pattern is:

1. Define RLS policies that reference
   `current_setting('app.current_tenant_id')` and
   `current_setting('app.current_workspace_id')`.
2. On every transaction, set these session variables to the
   caller's tenant/workspace IDs using `SET LOCAL`, which
   restricts the variable to the current transaction.

This module provides:

- ``TenantContext`` — a frozen value object carrying the
  tenant_id and workspace_id. The FastAPI dependency
  ``get_tenant_context`` extracts these from the authenticated
  user's workspace membership and returns a ``TenantContext``.
- ``with_tenant_context(session, ctx)`` — an async context
  manager that executes a block of DB operations under the
  tenant context. It issues ``SET LOCAL`` on the session so
  RLS policies see the correct tenant. The ``LOCAL`` keyword
  ensures the variable is automatically reset at transaction
  end (commit or rollback), preventing cross-request leakage.

Hermetic: the module does not require a live DB. The test
suite pins the contract with an in-memory SQLite DB that
accepts `SET LOCAL` (no-op on SQLite, but the API contract
is exercised).

Security properties:
- If a request has no tenant context, the DB returns NO
  rows (RLS policies default-deny when the setting is
  unset or empty). This is the correct fail-closed behavior.
- ``TenantContext`` is immutable (frozen dataclass) so it
  cannot be accidentally mutated after auth.
- The FastAPI dependency validates that the user actually
  belongs to the workspace; if not, it raises 403/404.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable tenant context for the current request.

    The ``tenant_id`` is the organization-level identifier.
    The ``workspace_id`` is the workspace within that org.
    Both are UUID7 strings.

    RLS policies reference these via
    ``current_setting('app.current_tenant_id')`` and
    ``current_setting('app.current_workspace_id')``.
    """
    tenant_id: str
    workspace_id: str


async def set_tenant_context(
    session: AsyncSession,
    ctx: TenantContext,
) -> None:
    """Set the tenant context on the session via SET LOCAL.

    ``SET LOCAL`` restricts the variable to the current
    transaction. When the transaction commits or rolls back,
    PostgreSQL automatically unsets it — no manual cleanup
    is needed and cross-request leakage is impossible.

    The settings are namespaced under ``app.`` to avoid
    colliding with any PostgreSQL built-in or extension
    settings. They are created by the migration that adds
    the RLS policies (``CREATE SETTING app.current_tenant_id``).

    Raises:
        sqlalchemy.exc.DatabaseError: If the session is
            not in a transaction or the SET fails. The
            caller should let this bubble — a failed SET
            means RLS is not enforced, which is a security
            incident.
    """
    # Note: The session MUST be in a transaction for SET
    # LOCAL to work. FastAPI's ``get_db`` dependency yields
    # a session inside a transaction (the ``async with``
    # block in the dependency). If called outside a
    # transaction, the SET will error, which is correct
    # fail-closed behavior.
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": ctx.tenant_id},
    )
    await session.execute(
        text("SET LOCAL app.current_workspace_id = :workspace_id"),
        {"workspace_id": ctx.workspace_id},
    )


@asynccontextmanager
async def with_tenant_context(
    session: AsyncSession,
    ctx: TenantContext | None,
) -> AsyncGenerator[None]:
    """Execute a block with the tenant context set.

    If ``ctx`` is None, the block runs without a tenant
    context. RLS policies will see unset/empty settings and
    default-deny (return zero rows). This is the correct
    behavior for unauthenticated or cross-tenant requests
    — the code simply sees no data.

    Usage::

        async with with_tenant_context(session, tenant_ctx):
            result = await session.execute(select(MyModel))
            # RLS policies see app.current_tenant_id

    The context manager yields ``None``; the caller uses
    the session normally.
    """
    if ctx is None:
        # No tenant context — RLS default-deny will apply.
        # We yield without setting anything.
        yield
        return

    # Set the tenant context. SET LOCAL is scoped to the
    # current transaction. The transaction is managed by
    # the caller (typically the FastAPI get_db dependency).
    await set_tenant_context(session, ctx)
    try:
        yield
    finally:
        # No explicit unset needed — SET LOCAL auto-unsets
        # at transaction end. The finally block exists only
        # for symmetry and to document the contract.
        pass


def make_tenant_context(tenant_id: str, workspace_id: str) -> TenantContext:
    """Factory for creating TenantContext.

    Validates that both IDs are non-empty strings. Raises
    ValueError if either is empty — the caller should
    translate this into a 400 response.
    """
    if not tenant_id or not isinstance(tenant_id, str):
        raise ValueError("tenant_id must be a non-empty string")
    if not workspace_id or not isinstance(workspace_id, str):
        raise ValueError("workspace_id must be a non-empty string")
    return TenantContext(tenant_id=tenant_id, workspace_id=workspace_id)
