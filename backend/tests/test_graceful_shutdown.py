"""The API stops when asked, and finishes the request it is serving first.

Regression. The application installed its own SIGTERM and SIGINT handlers
during start-up. They replaced the web server's handlers and only set a flag
that nothing waited for, so the process ignored both signals:

* ``docker stop`` and Kubernetes rollouts waited out their grace period and
  then killed the process, cutting off whatever it was doing;
* Ctrl-C did not stop a local server.

This test runs the real application in a real server process, because the
fault only exists in the interplay between the two.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX signals; the deployment target is Linux"
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_serving(port: int, process: subprocess.Popen[bytes], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server exited during start-up with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as conn:
                conn.sendall(b"GET /healthz HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
                if conn.recv(64).startswith(b"HTTP/1.1 200"):
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise AssertionError("server did not start serving in time")


ServerFactory = Callable[..., tuple["subprocess.Popen[bytes]", int, Path]]


@pytest.fixture
def start_server(tmp_path: Path) -> Iterator[ServerFactory]:
    """Start the real application in a real uvicorn process."""
    started: list[subprocess.Popen[bytes]] = []

    def _start(**extra_env: str) -> tuple[subprocess.Popen[bytes], int, Path]:
        port = _free_port()
        log = tmp_path / f"server-{port}.log"
        env = {
            **os.environ,
            "CORTEX_ENV": "test",
            # Self-contained: no external database, cache or relay is needed
            # to observe how the process reacts to a signal.
            "CORTEX_DB_DSN": f"sqlite+aiosqlite:///{tmp_path / 'shutdown.db'}",
            "CORTEX_OUTBOX_PUBLISHER_ENABLED": "false",
            "PYTHONPATH": str(BACKEND_ROOT),
            "PYTHONUNBUFFERED": "1",
            **extra_env,
        }
        env.pop("CORTEX_TEST_DATABASE_URL", None)
        if "UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN" not in extra_env:
            env.pop("UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN", None)
        with log.open("wb") as sink:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, test-only
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=BACKEND_ROOT,
                env=env,
                stdout=sink,
                stderr=subprocess.STDOUT,
            )
        started.append(process)
        _wait_until_serving(port, process, timeout_s=90.0)
        return process, port, log

    yield _start
    for process in started:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture
def server(start_server: ServerFactory) -> tuple[subprocess.Popen[bytes], int, Path]:
    return start_server()


def _stopped_cleanly(process: subprocess.Popen[bytes], log: Path, sig: signal.Signals) -> None:
    # Recent uvicorn finishes its shutdown and then re-raises the signal so the
    # exit status reports it; older versions return 0. Both are a clean stop.
    assert process.returncode in (0, -sig), f"unexpected exit status {process.returncode}"
    output = log.read_text(errors="replace")
    assert "Application shutdown complete" in output, output[-2000:]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_the_server_stops_when_signalled(
    server: tuple[subprocess.Popen[bytes], int, Path], sig: signal.Signals
) -> None:
    process, _port, log = server

    process.send_signal(sig)

    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the server ignored {sig.name}: still running after 20 seconds")
    _stopped_cleanly(process, log, sig)


# A request whose body is only half sent: the server has accepted it and is
# waiting for the rest. (The body is invalid on purpose: the answer is a 422
# produced without touching the database.)
_BODY = b'{"email": "someone@example.com"}'
_HEAD = (
    b"POST /api/v1/auth/login HTTP/1.1\r\n"
    b"Host: test\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: " + str(len(_BODY)).encode() + b"\r\n"
    b"Connection: close\r\n\r\n"
)


def test_a_request_in_flight_is_answered_before_the_server_stops(
    server: tuple[subprocess.Popen[bytes], int, Path],
) -> None:
    process, port, log = server
    body = _BODY
    with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
        conn.sendall(_HEAD + body[:10])
        time.sleep(0.5)

        process.send_signal(signal.SIGTERM)
        time.sleep(1.0)

        # Still running: it is waiting for the request it already accepted ...
        assert process.poll() is None, "the server exited with a request still in flight"
        # ... and it no longer accepts new work.
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1.0).close()

        conn.sendall(body[10:])
        answer = b""
        while chunk := conn.recv(4096):
            answer += chunk

    assert answer.startswith(b"HTTP/1.1 422"), answer[:200]
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pytest.fail("the server did not stop after answering the request in flight")
    _stopped_cleanly(process, log, signal.SIGTERM)


def test_a_connection_that_never_finishes_cannot_hold_the_server_open(
    start_server: ServerFactory,
) -> None:
    """Live streams (the realtime feed every signed-in page keeps open) never
    finish on their own, so an unbounded wait would turn every stop into a
    kill. With the bound the image sets, the server closes what is still open
    and completes its own shutdown."""
    process, port, log = start_server(UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN="2")
    with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
        # Never finished: stands in for a stream that stays open.
        conn.sendall(_HEAD + _BODY[:10])
        time.sleep(0.5)

        process.send_signal(signal.SIGTERM)

        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail("an open connection kept the server running after SIGTERM")
    _stopped_cleanly(process, log, signal.SIGTERM)


def test_the_image_bounds_the_wait_below_the_orchestrator_kill_timeout() -> None:
    """``docker stop`` kills after 10 seconds by default. The image must give
    up waiting for open connections before that, or shutdown never completes
    while any live stream is open."""
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text()
    values = [
        line.split("=", 1)[1].strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=")
    ]

    assert len(values) == 1, "backend/Dockerfile must set UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN once"
    assert 1 <= int(values[0]) <= 9
