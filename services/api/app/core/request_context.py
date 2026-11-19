"""Per-request correlation.

Every HTTP request gets a request id: the caller's ``X-Request-ID`` when it is
well formed, a generated one otherwise. The id is returned in the response
header, written into every log line of the request and included in every
error envelope. This middleware is also the last line of defence: an
exception nobody handled is logged here and answered with a generic 500.
"""

import json
import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# Only ids that are safe to echo into headers and logs are taken from callers.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

_request_id: ContextVar[str | None] = ContextVar("nexus_request_id", default=None)

_access_log = logging.getLogger("app.request")
_error_log = logging.getLogger("app.error")

INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Quote the request id when reporting it."


def current_request_id() -> str | None:
    """Request id of the request being served, if any."""
    return _request_id.get()


def new_request_id() -> str:
    return uuid4().hex


def error_body(
    code: str, message: str, request_id: str | None, details: list[dict[str, object]]
) -> dict[str, object]:
    """The standard error envelope (see docs/engineering/api-contract.md)."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


class RequestContextMiddleware:
    """Assigns the request id, logs the request and contains unhandled errors."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = (
            supplied if supplied and _SAFE_REQUEST_ID.fullmatch(supplied) else new_request_id()
        )
        token = _request_id.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        response_started = False
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # The stack trace stays in the log; the client gets a generic body.
            _error_log.exception("Unhandled error while serving %s", scope.get("path", ""))
            if response_started:
                raise
            await self._send_internal_error(send_with_request_id, request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            path = scope.get("path", "")
            level = logging.DEBUG if path.startswith("/health/") else logging.INFO
            # The query string is left out on purpose: it is not needed to
            # correlate a request and may carry values a log should not keep.
            _access_log.log(
                level,
                "%s %s -> %s",
                scope.get("method", ""),
                path,
                status_code,
                extra={
                    "http_method": scope.get("method", ""),
                    "http_path": path,
                    "http_status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            _request_id.reset(token)

    @staticmethod
    async def _send_internal_error(send: Send, request_id: str) -> None:
        body = json.dumps(
            error_body(INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE, request_id, [])
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
