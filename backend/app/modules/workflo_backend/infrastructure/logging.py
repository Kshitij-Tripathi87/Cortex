"""Structured logging with OpenTelemetry trace context injection.

Every log line includes:
- timestamp (ISO-8601 UTC)
- level
- message
- logger name
- request_id (if present)
- correlation_id (if present)
- workspace_id (if present)
- tenant_id (if present)
- trace_id (from OTel context)
- span_id (from OTel context)

Logs are JSON-formatted for machine parsing.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter with OTel context injection."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add OTel trace context if available
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            log_data["trace_id"] = f"{ctx.trace_id:032x}"
            log_data["span_id"] = f"{ctx.span_id:016x}"

        # Add custom fields from record
        if hasattr(record, "request_id") and record.request_id:
            log_data["request_id"] = record.request_id
        if hasattr(record, "correlation_id") and record.correlation_id:
            log_data["correlation_id"] = record.correlation_id
        if hasattr(record, "workspace_id") and record.workspace_id:
            log_data["workspace_id"] = record.workspace_id
        if hasattr(record, "tenant_id") and record.tenant_id:
            log_data["tenant_id"] = record.tenant_id
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)  # type: ignore[attr-defined]

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str, separators=(",", ":"))


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured JSON output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding structured fields to log records."""

    def __init__(self, **kwargs: Any) -> None:
        self.fields = kwargs
        self.old_factory = logging.getLogRecordFactory()

    def __enter__(self) -> None:
        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = self.old_factory(*args, **kwargs)
            record.extra_fields = {**getattr(record, "extra_fields", {}), **self.fields}  # type: ignore[attr-defined]
            return record

        logging.setLogRecordFactory(factory)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        logging.setLogRecordFactory(self.old_factory)
