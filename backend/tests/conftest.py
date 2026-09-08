"""Test fixtures for Cortex backend tests."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.infrastructure.database import Base
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_service import WorldStateService


def pytest_addoption(parser):
    """Add PostgreSQL URL option for integration tests."""
    parser.addoption(
        "--postgres-url",
        action="store",
        default=None,
        help="PostgreSQL connection URL for integration tests",
    )


def pytest_configure(config):
    """Resolve the PostgreSQL test URL once at session start."""
    postgres_url = config.getoption("--postgres-url")
    if postgres_url is None:
        postgres_url = os.environ.get("CORTEX_TEST_DATABASE_URL")
    if postgres_url is None:
        postgres_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/cortex_test"
    config.postgres_url = postgres_url

    # Install an in-memory OpenTelemetry TracerProvider for
    # tests that assert on the captured span tree. The OTel
    # SDK only allows setting the global TracerProvider ONCE
    # per process; doing it here (before any test) means the
    # in-memory provider is the active one for the entire
    # session. The F3 trace-context regression tests rely on
    # this to capture the spans they assert on.
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import TracerProvider as _SDKTP

    _sdk_provider = _SDKTP()
    try:  # noqa: SIM105
        _otel_trace.set_tracer_provider(_sdk_provider)
    except Exception:
        # Already set by an earlier session; ignore — the
        # already-installed provider is used.
        pass


# Eagerly import access.models so `core.workspaces` and `core.users` register
# in Base.metadata BEFORE any test imports another module with FK references
# to them. Without this, FKs from later-loaded models (e.g.,
# ingestion_log.user_id -> core.users.id) are left unresolved and trigger
# NoReferencedTableError when the db_engine fixture walks sorted_tables.
from app.modules.access import models as _access_models  # noqa: F401,E402

# ─────────────────────────────────────────────────────────────────────────────
# Database fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine() -> AsyncGenerator[Any]:
    """Create an in-memory SQLite database engine for testing.

    SQLite has no schema concept, so schema-qualified tables (the MVP wedge
    tables under core/operational/etc.) are excluded — they're tested by
    integration tests against real Postgres in CI. This fixture only
    creates the legacy/public-schema tables from Base.metadata.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    # Build a SQLite-compatible MetaData by copying only tables that
    # have no schema attribute set. Schema-qualified tables (the MVP
    # wedge) belong to production Postgres only.
    sqlite_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.schema is None:
            table.to_metadata(sqlite_metadata)

    async with engine.begin() as conn:
        await conn.run_sync(sqlite_metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: Any) -> AsyncGenerator[AsyncSession]:
    """Create a database session for testing."""
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL fixtures
# ─────────────────────────────────────────────────────────────────────────────
#
# Concurrency tests must run against real PostgreSQL: SQLite (via the shared
# StaticPool session above) cannot run concurrent transactions, and the
# advisory world write lock is a no-op on SQLite. These fixtures skip
# automatically when PostgreSQL is unavailable.


@pytest.fixture
async def postgres_engine(request):
    """Create an async engine connected to real PostgreSQL.

    Skips test if PostgreSQL is not available.
    """
    postgres_url = request.config.postgres_url

    try:
        engine = create_async_engine(
            postgres_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
        )

        # Verify connection works
        async with engine.begin() as conn:
            await conn.execute(select(1))

        return engine
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
async def postgres_sessionmaker(
    postgres_engine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """Create a sessionmaker bound to the PostgreSQL engine.

    Concurrent tests must open one session per concurrent task — mirroring
    production, where each HTTP request gets its own session — because a
    single AsyncSession cannot run concurrent operations.
    """
    maker = async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield maker
    finally:
        await postgres_engine.dispose()


@pytest.fixture
async def postgres_session(postgres_sessionmaker) -> AsyncGenerator[AsyncSession]:
    """Create a database session for PostgreSQL integration tests."""
    async with postgres_sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
def postgres_repo(postgres_session: AsyncSession) -> StateRepository:
    """Create a repository with PostgreSQL session."""
    return StateRepository(db=postgres_session)


@pytest.fixture
def postgres_service(postgres_repo: StateRepository) -> WorldStateService:
    """Create a service with PostgreSQL repository."""
    return WorldStateService(repository=postgres_repo, snapshot_interval=100)


@pytest.fixture
def submit_in_own_session() -> Any:
    """Submit one event using its own dedicated session + service.

    Returns an async callable ``(maker, event, idempotency_key) -> result``.
    Concurrent tests must open one session per task — mirroring production,
    where each HTTP request gets its own session — because a single
    AsyncSession cannot run concurrent operations.
    """

    async def _submit(
        maker: async_sessionmaker[AsyncSession],
        event: Any,
        idempotency_key: str,
    ) -> Any:
        async with maker() as session:
            repo = StateRepository(db=session)
            service = WorldStateService(repository=repo, snapshot_interval=100)
            try:
                return await service.submit_event(event, idempotency_key=idempotency_key)
            finally:
                await session.rollback()

    return _submit


# ─────────────────────────────────────────────────────────────────────
# Nexus v0.8 persistent-manager tests — file-based async SQLite
# ─────────────────────────────────────────────────────────────────────

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


@pytest.fixture(scope="session")
def nexus_db_path(tmp_path_factory):
    base = tmp_path_factory.mktemp("nexus-persistent")
    return base / "nexus.sqlite3"


@pytest.fixture(scope="session")
async def nexus_db_engine(nexus_db_path):
    import app.modules.nexus_spine.persistence.models  # noqa: F401
    from app.infrastructure.database import Base

    url = f"sqlite+aiosqlite:///{nexus_db_path}"
    engine = create_async_engine(url, echo=False, future=True)

    # Create ONLY the nexus_* tables. Their foreign keys are self-contained
    # (nexus_* → nexus_*), so no other modules' tables are needed. Copying
    # to a fresh MetaData keeps this fixture independent of whatever other
    # model modules earlier tests in the session may have registered on
    # Base.metadata — creating ALL of Base.metadata made the v0.8 suite
    # order-dependent (e.g. schema-qualified tables from unrelated modules
    # break SQLite create_all).
    nexus_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("nexus_"):
            table.to_metadata(nexus_metadata)

    # SQLite has no schemas — strip any schema qualifier defensively.
    for table in nexus_metadata.tables.values():
        table.schema = None
        for col in table.columns:
            for fk in list(col.foreign_keys):
                if fk._colspec and fk._colspec.count(".") == 2:
                    # schema.table.col → table.col
                    parts = fk._colspec.split(".")
                    fk._colspec = f"{parts[1]}.{parts[2]}"

    async with engine.begin() as conn:
        await conn.run_sync(nexus_metadata.create_all)
    yield engine
    await engine.dispose()
