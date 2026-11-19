"""Readiness checks against PostgreSQL.

Readiness answers two questions: can the service reach its database, and is
the schema at the migration head this code was written for. A reason is
returned as a short fixed text; connection details never leave the process.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import Database

_log = logging.getLogger("app.health")

# services/api/app/db/health.py -> services/api
SERVICE_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSION_TABLE = "alembic_version"


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    ok: bool
    detail: str


@lru_cache(maxsize=1)
def migration_heads() -> frozenset[str]:
    """Revision ids at the head of the migration scripts shipped with this code.

    Read once per process: the scripts are part of the code that is running.
    """
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def check_database(database: Database, expected_heads: frozenset[str]) -> dict[str, CheckOutcome]:
    """Run the readiness checks. Never raises."""
    try:
        with database.probe_connection() as connection:
            connection.execute(text("SELECT 1"))
            if inspect(connection).has_table(ALEMBIC_VERSION_TABLE):
                rows = connection.execute(text(f"SELECT version_num FROM {ALEMBIC_VERSION_TABLE}"))
                applied = frozenset(row[0] for row in rows)
            else:
                applied = frozenset()
    except SQLAlchemyError as exc:
        _log.warning("Readiness: database check failed", extra={"error_type": type(exc).__name__})
        return {
            "database": CheckOutcome(False, "The database is not reachable."),
            "migrations": CheckOutcome(False, "Not checked: the database is not reachable."),
        }

    if applied == expected_heads:
        migrations = CheckOutcome(True, "The schema is at the migration head.")
    else:
        migrations = CheckOutcome(
            False, "The schema is not at the migration head. Run the migrations."
        )
    return {
        "database": CheckOutcome(True, "The database accepts queries."),
        "migrations": migrations,
    }
