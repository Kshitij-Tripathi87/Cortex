"""Engine, sessions and transaction boundaries.

* One :class:`Database` (engine + session factory) per application instance.
* One :class:`~sqlalchemy.orm.Session` per request, never shared between
  requests, always closed.
* Services own transactions through :func:`transaction`. Repositories never
  commit.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings

CONNECT_TIMEOUT_SECONDS = 5


def _connect_args(settings: Settings) -> dict[str, object]:
    return {
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        "application_name": settings.app_name,
        # Timestamps come back in UTC whatever the server default is.
        "options": "-c timezone=UTC",
    }


def build_engine(settings: Settings) -> Engine:
    """Create the pooled engine. No connection is opened until it is first used."""
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args=_connect_args(settings),
    )


def build_probe_engine(settings: Settings) -> Engine:
    """An engine without a pool: every use opens a new connection."""
    return create_engine(
        settings.sqlalchemy_url, poolclass=NullPool, connect_args=_connect_args(settings)
    )


class Database:
    """Engines and session factory of one application instance."""

    def __init__(self, engine: Engine, probe_engine: Engine) -> None:
        self.engine = engine
        self._probe_engine = probe_engine
        # expire_on_commit=False: what a service returns stays readable after
        # its transaction ended. Timestamps and ids are assigned in Python, so
        # nothing is left to be fetched from the server.
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(build_engine(settings), build_probe_engine(settings))

    @contextmanager
    def probe_connection(self) -> Iterator[Connection]:
        """A brand-new connection, for readiness.

        A pooled connection keeps working while PostgreSQL is shutting down
        and already refuses new clients. Readiness must not report that state
        as healthy, so it never borrows from the pool.
        """
        with self._probe_engine.connect() as connection:
            yield connection

    def new_session(self) -> Session:
        return self._session_factory()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session that is closed on success and on error alike."""
        session = self.new_session()
        try:
            yield session
        finally:
            # close() rolls back whatever a failed operation left open.
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
        self._probe_engine.dispose()


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """The transaction boundary of one service operation.

    Everything inside the block is committed together, or rolled back together
    when the block raises. The rollback is visible here on purpose: no
    repository and no helper commits behind a service's back.
    """
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise


@contextmanager
def read_snapshot(session: Session) -> Iterator[Session]:
    """A read-only transaction in which every query sees the same data.

    A projection assembled from several queries (World State) must not mix
    data from before and after a concurrent commit. REPEATABLE READ gives all
    statements of the block one snapshot; READ ONLY makes a stray write fail.
    """
    if session.in_transaction():
        # The isolation level of a running transaction cannot be changed.
        session.rollback()
    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    session.execute(text("SET TRANSACTION READ ONLY"))
    try:
        yield session
    finally:
        session.rollback()
