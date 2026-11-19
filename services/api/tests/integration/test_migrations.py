"""The migrations build the schema from an empty database, and take it down again."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from tests.conftest import alembic_config

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "workspaces",
    "projects",
    "suppliers",
    "equipment",
    "purchase_orders",
    "purchase_order_items",
    "milestones",
    "milestone_plan_versions",
    "supplier_commitment_versions",
    "ingestion_batches",
    "ingestion_rows",
}


@pytest.fixture
def empty_database(settings: Settings) -> Iterator[Engine]:
    """The test database with nothing in it: no table, no version row.

    The schema is dropped and recreated, which is what a new database looks
    like. Whatever happens in the test, the schema is migrated back to head
    afterwards so the rest of the suite finds what it expects.
    """
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    try:
        yield engine
    finally:
        command.upgrade(alembic_config(settings.database_url), "head")
        engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def applied_revisions(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))
        }


def test_metadata_holds_every_canonical_table() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_there_is_exactly_one_migration_head(settings: Settings) -> None:
    script = ScriptDirectory.from_config(alembic_config(settings.database_url))

    assert len(script.get_heads()) == 1
    assert script.get_bases() == ["0001"]


def test_an_empty_database_upgrades_to_head(empty_database: Engine, settings: Settings) -> None:
    config = alembic_config(settings.database_url)
    assert tables(empty_database) == set()

    command.upgrade(config, "head")

    assert tables(empty_database) == EXPECTED_TABLES | {"alembic_version"}
    assert applied_revisions(empty_database) == set(ScriptDirectory.from_config(config).get_heads())


def test_upgrade_twice_is_a_no_op(empty_database: Engine, settings: Settings) -> None:
    config = alembic_config(settings.database_url)
    command.upgrade(config, "head")
    with empty_database.begin() as connection:
        connection.execute(
            text("INSERT INTO workspaces (name, slug, status) VALUES ('Kept', 'kept', 'ACTIVE')")
        )

    command.upgrade(config, "head")

    with empty_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM workspaces")).scalar_one() == 1


def test_downgrade_to_base_and_upgrade_again(empty_database: Engine, settings: Settings) -> None:
    config = alembic_config(settings.database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "base")
    assert tables(empty_database) == {"alembic_version"}
    assert applied_revisions(empty_database) == set()

    command.upgrade(config, "head")
    assert tables(empty_database) == EXPECTED_TABLES | {"alembic_version"}


def test_the_migrated_schema_matches_the_models(empty_database: Engine, settings: Settings) -> None:
    """`alembic check`: autogenerate finds nothing to add after an upgrade."""
    config = alembic_config(settings.database_url)
    command.upgrade(config, "head")

    command.check(config)  # raises if the models and the schema differ


def test_constraints_and_indexes_exist_under_their_names(
    empty_database: Engine, settings: Settings
) -> None:
    command.upgrade(alembic_config(settings.database_url), "head")
    inspector = inspect(empty_database)

    def names(kind: str, table: str) -> set[str]:
        getter = getattr(inspector, f"get_{kind}")
        return {item["name"] for item in getter(table)}

    assert "uq_projects_workspace_id_code" in names("unique_constraints", "projects")
    assert "uq_suppliers_workspace_id_supplier_code" in names("unique_constraints", "suppliers")
    assert "uq_equipment_workspace_id_equipment_code" in names("unique_constraints", "equipment")
    assert "uq_purchase_orders_workspace_id_po_number" in names(
        "unique_constraints", "purchase_orders"
    )
    assert "uq_purchase_order_items_purchase_order_id_equipment_id" in names(
        "unique_constraints", "purchase_order_items"
    )
    assert "uq_milestones_purchase_order_id_type_sequence_no" in names(
        "unique_constraints", "milestones"
    )
    assert "uq_milestone_plan_versions_milestone_id_version_no" in names(
        "unique_constraints", "milestone_plan_versions"
    )
    assert "uq_supplier_commitment_versions_purchase_order_id_version_no" in names(
        "unique_constraints", "supplier_commitment_versions"
    )
    assert "uq_ingestion_rows_batch_id_row_number" in names("unique_constraints", "ingestion_rows")

    assert {
        "ck_purchase_order_items_quantity_positive",
        "ck_purchase_order_items_unit_price_not_negative",
    } <= names("check_constraints", "purchase_order_items")
    assert {
        "ck_milestones_status",
        "ck_milestones_milestone_type",
        "ck_milestones_actual_date_requires_completed",
    } <= names("check_constraints", "milestones")
    assert {
        "ck_purchase_orders_currency_format",
        "ck_purchase_orders_total_value_not_negative",
    } <= names("check_constraints", "purchase_orders")

    composite = {
        (fk["name"], tuple(fk["constrained_columns"]), fk["referred_table"])
        for table in (
            "equipment",
            "purchase_orders",
            "purchase_order_items",
            "milestones",
            "supplier_commitment_versions",
        )
        for fk in inspector.get_foreign_keys(table)
        if len(fk["constrained_columns"]) > 1
    }
    assert composite == {
        ("fk_equipment_workspace_project", ("workspace_id", "project_id"), "projects"),
        ("fk_purchase_orders_workspace_project", ("workspace_id", "project_id"), "projects"),
        ("fk_purchase_orders_workspace_supplier", ("workspace_id", "supplier_id"), "suppliers"),
        (
            "fk_purchase_order_items_purchase_order",
            ("workspace_id", "project_id", "purchase_order_id"),
            "purchase_orders",
        ),
        (
            "fk_purchase_order_items_equipment",
            ("workspace_id", "project_id", "equipment_id"),
            "equipment",
        ),
        (
            "fk_milestones_workspace_purchase_order",
            ("workspace_id", "purchase_order_id"),
            "purchase_orders",
        ),
        (
            "fk_supplier_commitment_versions_workspace_purchase_order",
            ("workspace_id", "purchase_order_id"),
            "purchase_orders",
        ),
    }

    checksum_index = next(
        index
        for index in inspector.get_indexes("ingestion_batches")
        if index["name"] == "uq_ingestion_batches_active_checksum"
    )
    assert checksum_index["unique"]
    assert checksum_index["column_names"] == ["workspace_id", "entity_type", "file_sha256"]
    assert "FAILED" in str(checksum_index["dialect_options"]["postgresql_where"])


def test_column_types_are_exact_and_timezone_aware(
    empty_database: Engine, settings: Settings
) -> None:
    command.upgrade(alembic_config(settings.database_url), "head")
    with empty_database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
        ).all()
    columns = {(row[0], row[1]): row[2:] for row in rows}

    assert columns[("purchase_order_items", "quantity")] == ("numeric", 18, 3)
    assert columns[("purchase_order_items", "unit_price")] == ("numeric", 18, 2)
    assert columns[("purchase_orders", "total_value")] == ("numeric", 18, 2)
    assert columns[("equipment", "required_on_site_date")][0] == "date"
    assert columns[("milestones", "actual_date")][0] == "date"
    assert columns[("ingestion_rows", "raw_data")][0] == "jsonb"
    assert columns[("equipment", "specification")][0] == "jsonb"
    timestamps = {key: value[0] for key, value in columns.items() if key[1].endswith("_at")}
    assert timestamps
    assert set(timestamps.values()) == {"timestamp with time zone"}
    # No floating-point column anywhere.
    assert not {key for key, value in columns.items() if value[0] in {"real", "double precision"}}
