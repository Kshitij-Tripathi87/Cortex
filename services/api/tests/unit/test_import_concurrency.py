"""Import admission control tests: rejected bodies never reach the route."""

import asyncio
from collections.abc import Callable
from typing import Any

from starlette.types import Message, Receive, Scope, Send

from app.api.import_concurrency import ImportConcurrencyMiddleware


def _scope(path: str, method: str = "POST") -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "state": {"request_id": "request-123456"},
    }


def _invoke(
    app: ImportConcurrencyMiddleware, scope: Scope
) -> tuple[list[Message], Callable[[], Any]]:
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    async def run() -> None:
        await app(scope, receive, send)

    return messages, run


def test_second_import_is_rejected_before_the_route_runs() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        route_calls = 0

        async def route(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal route_calls
            route_calls += 1
            if route_calls == 1:
                entered.set()
                await release.wait()
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        app = ImportConcurrencyMiddleware(route, max_concurrent_imports=1, api_prefix="/api/v1")
        first_messages, first_run = _invoke(app, _scope("/api/v1/workspaces/123/ingestion/preview"))
        first = asyncio.create_task(first_run())
        await asyncio.wait_for(entered.wait(), timeout=1)

        second_messages, second_run = _invoke(
            app, _scope("/api/v1/workspaces/123/ingestion/preview")
        )
        await second_run()
        # Always release the first request before asserting. If the admission
        # check is removed, the second request reaches the route and returns
        # immediately, so the defect is detected rather than deadlocking here.
        release.set()
        await first

        assert route_calls == 1
        assert second_messages[0]["status"] == 429
        headers = dict(second_messages[0]["headers"])
        assert headers[b"retry-after"] == b"2"
        assert b"IMPORT_CAPACITY_EXCEEDED" in second_messages[1]["body"]
        assert first_messages[0]["status"] == 204

    asyncio.run(scenario())


def test_non_import_requests_do_not_consume_import_slots() -> None:
    async def scenario() -> None:
        entered = 0

        async def route(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal entered
            entered += 1
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        app = ImportConcurrencyMiddleware(route, max_concurrent_imports=1, api_prefix="/api/v1")
        for _ in range(2):
            _, run = _invoke(app, _scope("/api/v1/health/ready", method="GET"))
            await run()

        assert entered == 2

    asyncio.run(scenario())
