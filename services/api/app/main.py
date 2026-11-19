"""Application factory.

``create_app`` builds a fully wired FastAPI application from explicit
settings; tests call it directly. ``app.main:app`` (what uvicorn imports) is
created lazily from the environment the first time it is accessed, so
importing this module has no side effects and opens no connection.

The schema is never created or changed here. Alembic owns it.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware
from app.db.health import migration_heads
from app.db.session import Database

API_TITLE = "Cortex Nexus API"
API_VERSION = "0.1.0"
API_DESCRIPTION = (
    "Canonical procurement data foundation for critical-equipment projects: "
    "workspace-scoped records, import preview and commit with provenance, and a "
    "World State projection read from PostgreSQL. Local prototype."
)

_log = logging.getLogger("app.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Opens no database connection."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    database = Database.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _log.info(
            "Starting %s",
            settings.app_name,
            extra={"app_env": settings.app_env, "database": settings.database_url_redacted},
        )
        try:
            yield
        finally:
            database.dispose()
            _log.info("Stopped %s", settings.app_name)

    application = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        # The OpenAPI document and the interactive docs exist for developers only.
        openapi_url="/openapi.json" if settings.is_local else None,
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.migration_heads = migration_heads()

    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)

    application.include_router(health.router)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Create ``app`` on first access (PEP 562), for ``uvicorn app.main:app``."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
