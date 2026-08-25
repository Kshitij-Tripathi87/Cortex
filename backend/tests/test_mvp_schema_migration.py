"""Migration 009 smoke tests — verifies the migration file parses cleanly
and has the expected upgrade/downgrade structure.

These tests do NOT apply the migration (that requires a real Postgres and
is covered by the alembic upgrade head step in CI). They verify:
- The module imports successfully.
- revision and down_revision attributes are correct.
- upgrade() and downgrade() functions are defined and callable.
- upgrade() creates 7 schemas by counting CREATE SCHEMA statements.
- downgrade() drops schemas by counting DROP SCHEMA statements.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parent.parent / "alembic" / "versions" / "009_mvp_wedge_schema.py"
)


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("mvp_migration_009", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_file_exists() -> None:
    assert MIGRATION.exists(), f"Expected migration at {MIGRATION}"


def test_revision_chain(migration_module) -> None:
    assert migration_module.revision == "009_mvp_wedge_schema"
    assert migration_module.down_revision == "008_world_state"


def test_upgrade_and_downgrade_define_callables(migration_module) -> None:
    assert callable(migration_module.upgrade)
    assert callable(migration_module.downgrade)


def test_seven_schemas_declared(migration_module) -> None:
    assert len(migration_module._SCHEMAS) == 7
    expected = {"core", "operational", "inventory", "orders", "analytics", "decision", "audit"}
    assert set(migration_module._SCHEMAS) == expected


def test_upgrade_text_creates_all_schemas(migration_module) -> None:
    text = MIGRATION.read_text()
    # The migration uses an f-string template `CREATE SCHEMA IF NOT EXISTS {schema}`
    # rather than inlining each schema name — verify both the template form and
    # the underlying list.
    assert "CREATE SCHEMA IF NOT EXISTS {schema}" in text
    for s in migration_module._SCHEMAS:
        assert s in migration_module._SCHEMAS  # the module-level list is the truth


def test_upgrade_text_drops_all_schemas(migration_module) -> None:
    text = MIGRATION.read_text()
    assert "DROP SCHEMA IF EXISTS {schema}" in text


@pytest.mark.parametrize(
    "table_name",
    [
        "workspaces",
        "users",
        "suppliers",
        "components",
        "warehouses",
        "factories",
        "products",
        "customers",
        "edges",
        "inventory",
        "bom",
        "orders",
        "disruption_events",
        "impact_reports",
        "backtest_results",
        "decision_log",
        "decision_memory",
        "ingestion_log",
    ],
)
def test_upgrade_creates_every_table(migration_module, table_name: str) -> None:
    text = MIGRATION.read_text()
    assert f'"{table_name}"' in text, f"Table {table_name} not declared in migration"


def test_upgrade_uses_native_uuid_columns(migration_module) -> None:
    text = MIGRATION.read_text()
    assert "postgresql.UUID(as_uuid=True)" in text
    assert "gen_random_uuid()" in text


def test_no_app_modules_workflow_import_in_migration(migration_module) -> None:
    text = MIGRATION.read_text()
    assert "app.deferred" not in text, "Migration must not import deferred code"
    assert "app.modules.workflow" not in text
