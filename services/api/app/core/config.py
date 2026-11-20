"""Typed application settings.

Values come from environment variables, then from the ``.env`` file at the
repository root. Nothing here has a default that would be unsafe outside a
developer machine: the database URL is mandatory and the development
workspace bypass refuses to load anywhere else.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

# services/api/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]

REQUIRED_DRIVER = "postgresql+psycopg"

# Environments in which the development workspace bypass may exist.
LOCAL_ENVIRONMENTS = frozenset({"development", "test"})

AppEnvironment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration of the API service."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # A rejected value must never be echoed: it may be a database password.
        hide_input_in_errors=True,
    )

    app_env: AppEnvironment = "development"
    app_name: str = Field(default="cortex-nexus-api", min_length=1, max_length=80)
    api_v1_prefix: str = "/api/v1"

    database_url: str
    test_database_url: str | None = None

    log_level: LogLevel = "INFO"

    max_upload_size_mb: int = Field(default=20, gt=0, le=100)
    max_import_rows: int = Field(default=10_000, gt=0, le=1_000_000)
    max_import_columns: int = Field(default=100, gt=0, le=1_000)
    max_import_cell_chars: int = Field(default=2_000, gt=0, le=32_767)
    # Synchronous XLSX parsing is CPU and memory intensive. This semaphore is
    # process-local; multi-worker deployments need a shared job queue instead.
    max_concurrent_imports: int = Field(default=1, ge=1, le=4)

    # The single workspace this process serves. This is a development
    # stand-in for authentication, not authentication.
    nexus_dev_workspace_id: UUID | None = None

    # Reference date of the synthetic demo dataset (never the machine clock).
    nexus_demo_as_of: date | None = None

    @field_validator("api_v1_prefix")
    @classmethod
    def _check_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("must start with '/' and must not end with '/'")
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _check_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            url = make_url(value)
        except ArgumentError:
            # `from None`: the original message must not carry the URL.
            raise ValueError(
                f"must be a URL of the form {REQUIRED_DRIVER}://user:password@host:port/database"
            ) from None
        if url.drivername != REQUIRED_DRIVER:
            raise ValueError(f"must use the {REQUIRED_DRIVER} driver")
        if not url.host or not url.database:
            raise ValueError("must name a host and a database")
        return value

    @model_validator(mode="after")
    def _check_workspace_bypass(self) -> Self:
        if self.app_env in LOCAL_ENVIRONMENTS:
            if self.nexus_dev_workspace_id is None:
                raise ValueError(
                    "NEXUS_DEV_WORKSPACE_ID is required when APP_ENV is development or test"
                )
        elif self.nexus_dev_workspace_id is not None:
            raise ValueError(
                "NEXUS_DEV_WORKSPACE_ID enables the development workspace bypass, which is "
                "allowed only when APP_ENV is development or test. This release has no "
                "production authentication; unset it outside a developer machine."
            )
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_local(self) -> bool:
        """True where the development workspace bypass and the API docs are allowed."""
        return self.app_env in LOCAL_ENVIRONMENTS

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def sqlalchemy_url(self) -> URL:
        return make_url(self.database_url)

    @property
    def database_url_redacted(self) -> str:
        """The database URL with the password masked, safe to log."""
        return self.sqlalchemy_url.render_as_string(hide_password=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings of this process, read once from the environment."""
    return Settings()
