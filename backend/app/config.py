"""Cortex configuration — typed env-based config that fails fast on missing required values.

All operational configuration lives here. Nothing hardcoded in business logic.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration loaded from environment. No silent defaults."""

    # Core
    # NOTE: the field MUST stay named `env` (not `cortex_env`): with
    # env_prefix="CORTEX_" a field named `cortex_env` binds to
    # `CORTEX_CORTEX_ENV`, silently ignoring the documented `CORTEX_ENV`
    # variable — which kept every deployment in dev identity mode
    # (v0.8.5-B fix; per-field prefix opt-out is not supported).
    env: str = Field(default="dev", description="dev|test|staging|pilot|prod")
    log_level: str = Field(default="info", description="trace|debug|info|warn|error")
    app_name: str = "cortex-backend"

    # Database
    db_dsn: str = Field(
        default="sqlite+aiosqlite:///./cortex_dev.db", description="PostgreSQL async DSN"
    )
    db_pool_min: int = Field(default=4, description="Minimum DB pool size")
    db_pool_max: int = Field(default=20, description="Maximum DB pool size")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Object storage (S3-compatible)
    s3_endpoint: str = Field(default="http://localhost:9000")
    s3_bucket: str = Field(default="cortex-uploads")
    s3_region: str = Field(default="us-east-1")
    s3_access_key: str = Field(default="")
    s3_secret_key: str = Field(default="")
    s3_use_path_style: bool = Field(default=True)

    # Upload limits
    upload_max_bytes: int = Field(default=200 * 1024 * 1024, description="200 MB default")
    upload_allowed_mime: str = Field(
        default="text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Query bounds
    query_timeout_ms: int = 5000
    tx_timeout_ms: int = 10000

    # Worker
    worker_concurrency: int = 8
    worker_job_timeout_s: int = 300

    # Observability
    otel_exporter_endpoint: str = Field(default="http://localhost:4317")
    metrics_port: int = 8001

    # Data quality thresholds
    quality_min_completeness: float = 0.8
    quality_min_consistency: float = 0.9
    quality_min_validity: float = 0.95

    # Conflict thresholds
    conflict_severity_blocking: list[str] = Field(
        default_factory=lambda: ["major", "critical"],
        description="Severity levels that block readiness",
    )

    # Pagination
    default_page_size: int = 50
    max_page_size: int = 200

    # Retry
    max_retries: int = 3
    retry_delay_s: int = 1

    # Outbox relay (v0.8.5-B4 — durable outbox → Redis → SSE/WS).
    # The sweeper runs in-process in the API by default; FOR UPDATE
    # SKIP LOCKED makes N API replicas a safe publisher pool. A dedicated
    # relay worker (app.workers.outbox_relay) may run instead/also.
    outbox_publisher_enabled: bool = Field(
        default=True,
        description="Run the OutboxPublisher sweeper in this process",
    )
    outbox_publisher_id: str = Field(
        default="",
        description="Stable publisher identity (dedicated relay worker); "
        "empty = random per-process id",
    )
    outbox_sweep_interval_s: float = Field(
        default=1.0, ge=0.05, description="Idle delay between outbox sweep passes"
    )
    outbox_batch_size: int = Field(
        default=100, ge=1, le=5000, description="Max outbox rows claimed per sweep pass"
    )
    outbox_lease_s: float = Field(
        default=30.0,
        ge=1.0,
        description="Claim lease: a claimed-but-unpublished row becomes "
        "reclaimable by a peer after this long (worker-crash recovery)",
    )
    outbox_retry_base_s: float = Field(
        default=1.0, ge=0.0, description="Failed-publish backoff base (doubles per attempt)"
    )
    outbox_retry_max_s: float = Field(
        default=60.0, ge=1.0, description="Failed-publish backoff cap"
    )
    outbox_max_attempts: int = Field(
        default=50,
        ge=1,
        description="Attempts after which an unpublished row is flagged poison "
        "(loudly metriced; still retried with capped backoff, never dropped)",
    )

    # Realtime delivery (v0.8.5-B4).
    realtime_replay_limit: int = Field(
        default=500, ge=1, le=5000, description="Max events per replay page"
    )
    realtime_resync_threshold: int = Field(
        default=1000,
        ge=1,
        description="Gap size above which clients must snapshot/resync "
        "instead of replaying event-by-event",
    )
    realtime_sse_heartbeat_s: float = Field(
        default=15.0, ge=1.0, description="SSE keepalive comment interval"
    )

    # Security
    rate_limit_default_rps: float = 10.0
    rate_limit_default_burst: int = 100
    rate_limit_expensive_rps: float = 1.0
    rate_limit_expensive_burst: int = 10
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_timeout: float = 30.0

    # MVP authentication. Header identity is dev/test-only; pilot/prod use HS256 JWT.
    jwt_secret: str = Field(default="", description="HS256 signing secret; required in pilot/prod")
    jwt_algorithm: str = Field(default="HS256")
    jwt_audience: str = Field(default="cortex-api")
    jwt_expiry_minutes: int = Field(default=60, ge=5, le=1440)

    # CORS
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins (comma-separated)",
    )
    cors_allowed_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    )
    cors_allowed_headers: list[str] = Field(
        default_factory=lambda: ["*"],
    )
    cors_allow_credentials: bool = Field(default=True)

    # Nexus v0.8.2 routing flip: the persistent PG-backed router owns
    # /nexus/* (canonical). The v0.7 in-memory Nexus routers are demoted to
    # /v07-legacy/nexus/* and are NOT mounted at all unless this flag is set
    # (unit tests, explicit migration tooling, historical v0.7 demos).
    # Temporary migration affordance — remove in v0.9.
    nexus_v07_legacy_routes: bool = Field(
        default=False,
        description="Mount the v0.7 in-memory Nexus routers under /v07-legacy/nexus/* "
        "(default False). Never enable in production.",
    )

    # Feature flags (ADR-0008). Settings-based in MVP; Phase 2 may move to
    # DB-backed or remote service. Read via `get_settings().feature_flags[name]`.
    feature_flags: dict[str, bool] = Field(
        default_factory=lambda: {
            "FEATURE_BACKTEST": True,
            "FEATURE_SIMULATION": False,
            "FEATURE_CONNECTORS": False,
            "FEATURE_DECISION_MEMORY": True,
            "FEATURE_EVENT_STORE": True,
            "FEATURE_WORLD_STATE": True,
            "FEATURE_DIGITAL_TWIN": False,
            "FEATURE_KNOWLEDGE": False,
        },
        description="Feature flag toggles. Each flag is a boolean.",
    )

    @model_validator(mode="after")
    def validate_production_requirements(self) -> Settings:
        """Fail fast on missing required secrets in production-like environments."""
        if self.env in {"pilot", "prod", "production", "staging"}:
            if not self.jwt_secret:
                raise ValueError(
                    "CORTEX_JWT_SECRET must be set when CORTEX_ENV is pilot, prod, or staging"
                )
            if len(self.jwt_secret) < 32:
                raise ValueError("CORTEX_JWT_SECRET must be at least 32 characters for HS256")
        return self

    model_config = {
        "env_prefix": "CORTEX_",
        "env_file": ".env",
        "extra": "ignore",
        "populate_by_name": True,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
