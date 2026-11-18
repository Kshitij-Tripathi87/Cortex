"""Tenant context primitives. Not in use: read this before relying on them.

These helpers write two transaction-local settings, ``app.tenant_id`` and
``app.workspace_id``, that a row-level security policy could compare rows
against. No such policy exists any more:

* migrations 002 and 003 created policies on fourteen tables, but the
  application wrote these settings in one place only (the audit log) and
  never filled the ``tenant_id`` column most policies compared on;
* connected as a superuser, PostgreSQL skipped the policies; connected as
  any other role, the first upload failed. They protected nothing and made
  the API depend on a superuser connection;
* migration 026 removed them.

Nothing in the application calls this module now. Separation between
customers is enforced by the application on every request, not by the
database: ``docs/architecture/TENANT_ISOLATION.md`` says how, how it is
tested, and what a database-level barrier would need (a role that cannot
bypass policies, the settings written at the start of every transaction and
not once per request, the workers that read across workspaces, and policies
on every table that holds customer data, not fourteen of them).

What the helpers do, should they be used again:

- ``TenantContext`` is an immutable pair of tenant and workspace ids.
- ``set_tenant_context(session, ctx)`` writes both settings with
  ``set_config(..., true)``, the bind-parameter-safe form of ``SET LOCAL``.
  The settings last until the transaction ends, so a request that commits
  more than once must write them again after each commit.
- ``with_tenant_context(session, ctx)`` does the same around a block, and
  does nothing when ``ctx`` is None.
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

    A policy would read them as ``current_setting('app.tenant_id', true)``
    and ``current_setting('app.workspace_id', true)``.
    """

    tenant_id: str
    workspace_id: str


async def set_tenant_context(
    session: AsyncSession,
    ctx: TenantContext,
) -> None:
    """Set the tenant context on the session via SET LOCAL.

    The settings last until the current transaction commits or rolls
    back; PostgreSQL then clears them, so nothing leaks into the next
    request on the same connection. A request that commits and carries on
    must call this again.

    The names are namespaced under ``app.``; PostgreSQL accepts any such
    name without it being declared first.
    """
    # set_config(..., true) is the bind-parameter-safe form of SET LOCAL:
    # utility commands (SET LOCAL) cannot take bind params through the
    # extended protocol. The names are the ones the removed policies of
    # migration 002 read: app.tenant_id / app.workspace_id.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": ctx.tenant_id},
    )
    await session.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": ctx.workspace_id},
    )


@asynccontextmanager
async def with_tenant_context(
    session: AsyncSession,
    ctx: TenantContext | None,
) -> AsyncGenerator[None]:
    """Execute a block with the tenant context set.

    If ``ctx`` is None, the block runs without the settings.

    Usage::

        async with with_tenant_context(session, tenant_ctx):
            result = await session.execute(select(MyModel))

    The context manager yields ``None``; the caller uses
    the session normally.
    """
    if ctx is None:
        # No tenant context: nothing is written.
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
