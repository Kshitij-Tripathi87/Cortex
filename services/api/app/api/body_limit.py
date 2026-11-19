"""Request-body size guard.

A request body is refused before or while it is read, not after it has been
buffered. The declared Content-Length is checked first; a body sent without
one (chunked) is counted as it arrives. Uploads get the configured upload
limit plus room for the multipart framing; every other request gets a small
fixed limit.
"""

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import error_body

UPLOAD_PATH_SUFFIX = "/ingestion/preview"
# Room for multipart boundaries, part headers and the small form fields.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_upload_bytes: int) -> None:
        self.app = app
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_upload = str(scope.get("path", "")).endswith(UPLOAD_PATH_SUFFIX)
        limit = (
            self.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
            if is_upload
            else DEFAULT_MAX_BODY_BYTES
        )

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(scope, send, is_upload)
            return

        received = 0
        exceeded = False
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if exceeded:
                # The framework turns a failure while reading the body into its
                # own "bad request" answer. The body was too large, and that is
                # what the caller is told: the framework's answer is replaced.
                if not response_started:
                    response_started = True
                    await self._reject(scope, send, is_upload)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(scope, send, is_upload)

    async def _reject(self, scope: Scope, send: Send, is_upload: bool) -> None:
        if is_upload:
            megabytes = self.max_upload_bytes // (1024 * 1024)
            code = "FILE_TOO_LARGE"
            message = f"The file is larger than {megabytes} MB. Split it."
        else:
            code = "REQUEST_TOO_LARGE"
            message = "The request body is too large."
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(error_body(code, message, request_id, [])).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    # The rest of the body will not be read.
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
