"""Admission control for synchronous file-import requests.

The slot is acquired before FastAPI parses multipart bodies, so rejected
requests are not buffered or handed to the XLSX parser. The semaphore is
process-local by design; deployments with multiple workers must replace this
with a shared queue or external admission controller.
"""

import json
from threading import BoundedSemaphore

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.request_context import error_body

UPLOAD_PATH_SUFFIX = "/ingestion/preview"


class ImportConcurrencyMiddleware:
    """Allow at most the configured number of import requests per process."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_concurrent_imports: int,
        api_prefix: str,
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self._slots = BoundedSemaphore(max_concurrent_imports)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_import(scope):
            await self.app(scope, receive, send)
            return

        if not self._slots.acquire(blocking=False):
            await self._reject(scope, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            self._slots.release()

    def _is_import(self, scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        prefix = self.api_prefix + "/workspaces/"
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and path.startswith(prefix)
            and path.endswith(UPLOAD_PATH_SUFFIX)
        )

    @staticmethod
    async def _reject(scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(
            error_body(
                "IMPORT_CAPACITY_EXCEEDED",
                "Another import is being processed. Retry shortly.",
                request_id,
                [],
            )
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", b"2"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
