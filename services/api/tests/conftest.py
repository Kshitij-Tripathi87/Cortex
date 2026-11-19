"""Shared fixtures.

Tests never read the developer's settings implicitly: every Settings object
is built here from explicit values. Database-backed tests use the dedicated
test database only and refuse to run against anything else.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, Settings
from app.db.base import Base
from app.db.health import SERVICE_ROOT
from app.db.session import Database
from app.main import create_app
from app.models import Workspace
from tests import factories
from tests.constants import DEMO_AS_OF, DEV_WORKSPACE_ID

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://nexus:nexus_test@127.0.0.1:5433/cortex_nexus_test"


class _TestEnvironment(BaseSettings):
    """Where the test database is: TEST_DATABASE_URL from the environment or .env."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    test_database_url: str = DEFAULT_TEST_DATABASE_URL


def test_database_url() -> str:
    url = _TestEnvironment().test_database_url
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        # The suite truncates tables. It must never be pointed at real data.
        raise RuntimeError(
            "TEST_DATABASE_URL must name a database ending in '_test'; refusing to run."
        )
    return url


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "app_name": "cortex-nexus-api-test",
        "api_v1_prefix": "/api/v1",
        "database_url": test_database_url(),
        "log_level": "WARNING",
        "max_upload_size_mb": 20,
        "max_import_rows": 10_000,
        "max_import_columns": 100,
        "max_import_cell_chars": 2_000,
        "nexus_dev_workspace_id": DEV_WORKSPACE_ID,
        "nexus_demo_as_of": DEMO_AS_OF,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def alembic_config(database_url: str) -> Config:
    """Alembic configuration aimed at ``database_url``, without touching logging."""
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def migrated_database(settings: Settings) -> Iterator[Database]:
    """The test database with the schema created by the migrations, never by create_all."""
    command.upgrade(alembic_config(settings.database_url), "head")
    database = Database.from_settings(settings)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def db(migrated_database: Database) -> Database:
    """A migrated test database with every table empty."""
    # Children first. DELETE is much faster than TRUNCATE for a handful of rows.
    with migrated_database.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(text(f'DELETE FROM "{table.name}"'))
    return migrated_database


@pytest.fixture
def session(db: Database) -> Iterator[Session]:
    with db.session() as database_session:
        yield database_session


@pytest.fixture
def app(settings: Settings, db: Database) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def workspace(session: Session) -> Workspace:
    """The configured development workspace, present and active."""
    return factories.make_workspace(session)


@pytest.fixture
def api(client: TestClient, workspace: Workspace) -> "Api":
    """HTTP helper bound to the configured workspace."""
    return Api(client, workspace.id)


class Api:
    """Thin wrapper that prefixes paths with the workspace and keeps tests readable."""

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.base = f"/api/v1/workspaces/{workspace_id}"

    def get(self, path: str = "", **kwargs: Any) -> Response:
        return self.client.get(self.base + path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.client.post(self.base + path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Response:
        return self.client.patch(self.base + path, **kwargs)

    def create(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST and return the created record; fails the test on anything but 201."""
        response = self.post(path, json=body)
        assert response.status_code == 201, response.text
        created: dict[str, Any] = response.json()
        return created


def error_of(response: Response, status: int, code: str) -> dict[str, Any]:
    """Assert the standard error envelope and return its ``error`` object."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code, error
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


def detail_codes(error: dict[str, Any]) -> set[tuple[str | None, str]]:
    """The (field, code) pairs of an error envelope."""
    return {(detail.get("field"), detail["code"]) for detail in error["details"]}
