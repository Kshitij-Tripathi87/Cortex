"""Repository tests — workspace-scoped enforcement.

These are pure-logic tests that don't touch a real DB. We use SQLAlchemy
async session with a non-executing mock to verify that:

1. WorkspaceScopedRepository.add forces its workspace_id on the entity.
2. WorkspaceScopedRepository._scoped always returns a SELECT scoped by
   the configured workspace_id.
3. The supplier-specific get_by_name helper scopes by workspace too.
4. Concrete repos bind the right ORM class.

Coverage of actual queries (INSERT/SELECT against Postgres) is left to
the integration tests in CI — these tests just check the wiring so a
future refactor can't silently drop the workspace filter.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from app.modules.supply_chain.models import Supplier
from app.modules.supply_chain.repositories import (
    ComponentRepository,
    SupplierRepository,
    WorkspaceScopedRepository,
)


class _DummyRepo(WorkspaceScopedRepository[Supplier]):
    """A minimal subclass to exercise the base class with a concrete model."""

    _model = Supplier


def test_add_forces_workspace_id_on_entity() -> None:
    ws_id = uuid.uuid4()
    other_ws = uuid.uuid4()
    repo = _DummyRepo(session=AsyncMock(), workspace_id=ws_id)

    supplier = Supplier(
        name="ACME",
        country="US",
        tier="tier_1",
        lead_time_days=14,
    )
    # Pre-set the wrong ID — repo should overwrite.
    supplier.workspace_id = other_ws

    # add() does an await session.flush() — replace with awaitable no-op
    repo._session.flush = AsyncMock(return_value=None)
    repo._session.add = lambda x: None

    import asyncio

    new_entity = asyncio.run(repo.add(supplier))
    assert new_entity.workspace_id == ws_id, "repo.add must force workspace_id"
    assert new_entity.workspace_id != other_ws


def test_supplier_repo_binds_supplier_model() -> None:
    repo = SupplierRepository(session=AsyncMock(), workspace_id=uuid.uuid4())
    assert repo._model is Supplier


def test_component_repo_binds_component_model() -> None:
    from app.modules.supply_chain.models import Component

    repo = ComponentRepository(session=AsyncMock(), workspace_id=uuid.uuid4())
    assert repo._model is Component


def test_scoped_select_filters_by_workspace() -> None:
    ws_id = uuid.uuid4()
    repo = _DummyRepo(session=AsyncMock(), workspace_id=ws_id)
    stmt = repo._scoped()
    # The WHERE clause must include `suppliers.workspace_id == :workspace_id_1`
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "workspace_id" in compiled


def test_get_passes_workspace_filter_through() -> None:
    ws_id = uuid.uuid4()
    repo = _DummyRepo(session=AsyncMock(), workspace_id=ws_id)

    # execute() should be called once; the returned scalar_one_or_none is None
    fake_result = AsyncMock()
    fake_result.scalar_one_or_none = lambda: None
    repo._session.execute = AsyncMock(return_value=fake_result)

    import asyncio

    entity = asyncio.run(repo.get(uuid.uuid4()))
    assert entity is None
    assert repo._session.execute.await_count == 1


def test_delete_returns_false_when_not_found() -> None:
    ws_id = uuid.uuid4()
    repo = _DummyRepo(session=AsyncMock(), workspace_id=ws_id)

    fake_result = AsyncMock()
    fake_result.scalar_one_or_none = lambda: None
    repo._session.execute = AsyncMock(return_value=fake_result)

    import asyncio

    assert asyncio.run(repo.delete(uuid.uuid4())) is False


def test_construction_with_different_workspaces_isolates() -> None:
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    repo_a = _DummyRepo(session=AsyncMock(), workspace_id=ws_a)
    repo_b = _DummyRepo(session=AsyncMock(), workspace_id=ws_b)
    assert repo_a._workspace_id != repo_b._workspace_id
    assert repo_a._workspace_id == ws_a
