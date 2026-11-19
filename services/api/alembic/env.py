"""Alembic environment.

The target database is, in this order:

1. ``alembic -x database_url=...`` given on the command line;
2. ``config.attributes["database_url"]`` set by a caller that drives Alembic
   from Python (the test suite);
3. ``DATABASE_URL`` from the application settings.

The URL is never logged.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (imports every model, so the metadata is complete)
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    from_command_line = context.get_x_argument(as_dictionary=True).get("database_url")
    if from_command_line:
        return from_command_line
    from_caller = config.attributes.get("database_url")
    if from_caller:
        return str(from_caller)
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Write the migration SQL to standard output instead of running it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against the target database in one transaction."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
