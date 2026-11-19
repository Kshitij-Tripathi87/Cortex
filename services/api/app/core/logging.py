"""Structured logging.

One JSON object per line with timestamp, level, logger, message and the
request id. Messages pass through :func:`redact` before they are written, so a
connection string or an authorization header that reaches a log call by
mistake does not reach the log.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_request_id

_MASK = "***"
_HANDLER_NAME = "cortex-nexus-json"

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:password@host -> scheme://user:***@host
    (re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@"), rf"\1:{_MASK}@"),
    # Authorization: Bearer abc, Cookie: ..., X-Api-Key: ...
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key)"
            r"(\"?\s*[:=]\s*\"?)[^\r\n\"]+"
        ),
        rf"\1\2{_MASK}",
    ),
    # password=..., secret: ..., token=..., api_key=...
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\"&,;]+"
        ),
        rf"\1\2{_MASK}",
    ),
)

# Attributes every LogRecord has; anything else was passed through `extra=`.
# `color_message` is uvicorn's copy of the message with terminal colour codes.
_STANDARD_ATTRIBUTES = frozenset(
    logging.LogRecord("", logging.INFO, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName", "color_message"}


def redact(text: str) -> str:
    """Mask credentials in a string that is about to be logged."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonLogFormatter(logging.Formatter):
    """Formats a record as one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": current_request_id(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRIBUTES or key.startswith("_"):
                continue
            payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Route all logging of the process through the JSON formatter. Idempotent."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    handler.set_name(_HANDLER_NAME)

    root = logging.getLogger()
    for existing in list(root.handlers):
        # Replace only the handler this function installed earlier; handlers of
        # the host (a test runner capturing logs, for example) stay.
        if existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; let its records use ours instead. Its
    # access log duplicates the request line this service writes itself.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
