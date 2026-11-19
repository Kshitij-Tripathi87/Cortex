"""Settings: mandatory values, safe validation, development-only bypass."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import Settings

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
GOOD_URL = "postgresql+psycopg://nexus:s3cr3t-pw@127.0.0.1:5432/cortex_nexus"


def build(**values: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "development",
        "database_url": GOOD_URL,
        "nexus_dev_workspace_id": WORKSPACE_ID,
    }
    base.update(values)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "DATABASE_URL", "TEST_DATABASE_URL", "NEXUS_DEV_WORKSPACE_ID"):
        monkeypatch.delenv(name, raising=False)


def test_valid_development_settings() -> None:
    settings = build()

    assert settings.is_development
    assert settings.is_local
    assert settings.max_upload_size_bytes == 20 * 1024 * 1024
    assert settings.sqlalchemy_url.database == "cortex_nexus"


def test_database_url_is_mandatory() -> None:
    with pytest.raises(ValidationError) as failure:
        Settings(_env_file=None, app_env="development", nexus_dev_workspace_id=WORKSPACE_ID)

    assert [error["loc"] for error in failure.value.errors()] == [("database_url",)]
    assert failure.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://nexus:s3cr3t-pw@127.0.0.1:5432/cortex_nexus",  # driver not named
        "postgresql+psycopg2://nexus:s3cr3t-pw@127.0.0.1:5432/cortex_nexus",  # other driver
        "sqlite:///nexus.db",
        "postgresql+psycopg://nexus:s3cr3t-pw@127.0.0.1:5432",  # no database
        "postgresql+psycopg:///cortex_nexus",  # no host
        "not a url s3cr3t-pw",
    ],
)
def test_invalid_database_url_is_rejected_without_echoing_it(url: str) -> None:
    with pytest.raises(ValidationError) as failure:
        build(database_url=url)

    # A mistyped URL still holds the password, so what a failed start prints
    # (the rendered exception) must not contain the value. pydantic keeps the
    # input on the exception object; only its rendering is hidden.
    assert "s3cr3t-pw" not in str(failure.value)
    assert "s3cr3t-pw" not in repr(failure.value)
    assert "s3cr3t-pw" not in repr(failure.value.errors(include_input=False, include_url=False))


def test_redacted_url_hides_the_password() -> None:
    settings = build()

    assert "s3cr3t-pw" not in settings.database_url_redacted
    assert settings.database_url_redacted.startswith("postgresql+psycopg://nexus:***@127.0.0.1")


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_workspace_bypass_is_refused_outside_local_environments(environment: str) -> None:
    with pytest.raises(ValidationError) as failure:
        build(app_env=environment)

    assert "development workspace bypass" in str(failure.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_without_bypass_a_non_local_environment_loads(environment: str) -> None:
    settings = build(app_env=environment, nexus_dev_workspace_id=None)

    assert not settings.is_local
    assert settings.nexus_dev_workspace_id is None


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_environments_require_the_workspace_id(environment: str) -> None:
    with pytest.raises(ValidationError) as failure:
        build(app_env=environment, nexus_dev_workspace_id=None)

    assert "NEXUS_DEV_WORKSPACE_ID is required" in str(failure.value)


@pytest.mark.parametrize("prefix", ["api/v1", "/api/v1/"])
def test_api_prefix_shape(prefix: str) -> None:
    with pytest.raises(ValidationError):
        build(api_v1_prefix=prefix)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_upload_size_mb", 0),
        ("max_import_rows", 0),
        ("max_import_columns", -1),
        ("max_import_cell_chars", 0),
        ("log_level", "LOUD"),
        ("app_env", "local"),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        build(**{field: value})
