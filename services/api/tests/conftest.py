"""Shared fixtures.

Tests never read the developer's settings implicitly: every Settings object
is built here from explicit values. Database-backed tests use the dedicated
test database only and refuse to run against anything else.
"""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.core.config import REPO_ROOT, Settings
from app.main import create_app

DEV_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
DEMO_AS_OF = date(2026, 11, 19)

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


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
