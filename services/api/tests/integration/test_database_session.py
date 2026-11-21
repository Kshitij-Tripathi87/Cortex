"""The database spine: connectivity, session lifecycle and transaction boundaries."""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import Database, read_snapshot, transaction
from app.models import Workspace

pytestmark = pytest.mark.db

SCRATCH = "session_spine_scratch"


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    database = Database.from_settings(settings)
    with database.engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {SCRATCH}"))
        connection.execute(text(f"CREATE TABLE {SCRATCH} (id integer PRIMARY KEY)"))
    try:
        yield database
    finally:
        with database.engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {SCRATCH}"))
        database.dispose()


def count(database: Database) -> int:
    with database.engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {SCRATCH}")).scalar_one())


def test_the_test_database_is_postgresql_16(database: Database) -> None:
    with database.engine.connect() as connection:
        version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
        timezone = connection.execute(text("SHOW timezone")).scalar_one()

    assert 160000 <= version < 170000
    assert timezone == "UTC"


def test_transaction_commits_on_success(database: Database) -> None:
    with database.session() as session, transaction(session):
        session.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))

    assert count(database) == 1


def _write_two_rows_then_fail(session: Session) -> None:
    with transaction(session):
        session.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))
        session.execute(text(f"INSERT INTO {SCRATCH} VALUES (2)"))
        raise RuntimeError("failure after two writes")


def test_transaction_rolls_back_everything_on_error(database: Database) -> None:
    with database.session() as session:
        with pytest.raises(RuntimeError):
            _write_two_rows_then_fail(session)
        # The session is usable again after the rollback.
        with transaction(session):
            session.execute(text(f"INSERT INTO {SCRATCH} VALUES (3)"))

    assert count(database) == 1


def test_a_closed_session_leaves_nothing_behind(database: Database) -> None:
    """Work that was never committed disappears when the session is closed."""
    with database.session() as session:
        session.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))

    assert count(database) == 0


def _fail_inside_a_session(database: Database, captured: list[Session]) -> None:
    with database.session() as session:
        captured.append(session)
        session.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))
        raise RuntimeError("request failed")


def test_session_is_closed_when_the_block_raises(database: Database) -> None:
    captured: list[Session] = []

    with pytest.raises(RuntimeError):
        _fail_inside_a_session(database, captured)

    assert not captured[0].in_transaction()
    assert count(database) == 0
    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_each_session_has_its_own_connection_and_transaction(database: Database) -> None:
    with database.session() as first, database.session() as second:
        first.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))
        seen_by_second = second.execute(text(f"SELECT count(*) FROM {SCRATCH}")).scalar_one()

    assert seen_by_second == 0


def test_read_snapshot_sees_one_state_and_cannot_write(database: Database) -> None:
    with database.session() as reader, read_snapshot(reader):
        before = reader.execute(text(f"SELECT count(*) FROM {SCRATCH}")).scalar_one()
        with database.session() as writer, transaction(writer):
            writer.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))
        after = reader.execute(text(f"SELECT count(*) FROM {SCRATCH}")).scalar_one()
        with pytest.raises((InternalError, ProgrammingError)):
            reader.execute(text(f"INSERT INTO {SCRATCH} VALUES (2)"))

    assert (before, after) == (0, 0)
    assert count(database) == 1


def test_isolation_level_is_restored_after_a_snapshot(database: Database) -> None:
    with database.session() as session:
        with read_snapshot(session):
            inside = session.execute(text("SHOW transaction_isolation")).scalar_one()
        outside = session.execute(text("SHOW transaction_isolation")).scalar_one()
        with transaction(session):
            session.execute(text(f"INSERT INTO {SCRATCH} VALUES (1)"))

    assert inside == "repeatable read"
    assert outside == "read committed"
    assert count(database) == 1


def test_a_snapshot_refuses_unwritten_work_instead_of_throwing_it_away(
    database: Database,
) -> None:
    """A projection is read-only; pending changes mean a caller forgot to commit.

    Opening the snapshot rolls the transaction back, because the isolation
    level of a running transaction cannot be changed. That used to take the
    caller's unwritten records with it.
    """
    with database.session() as session:
        session.add(Workspace(slug="uncommitted", name="Uncommitted"))

        with pytest.raises(RuntimeError, match="unwritten changes"), read_snapshot(session):
            pytest.fail("the snapshot must not open over unwritten changes")

        assert len(session.new) == 1
        session.rollback()
