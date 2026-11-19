"""One command that says whether the build is sound.

Usage (from services/api):
    uv run python ../../scripts/verify_sprint.py
    uv run python ../../scripts/verify_sprint.py --e2e
    uv run python ../../scripts/verify_sprint.py --e2e-only
    uv run python ../../scripts/verify_sprint.py --summary ../../artifacts/tmp/verify.json

Runs the verification chain in a fixed order and stops at the first failure.
The exit code is 0 only when every step passed; a failing subprocess is never
swallowed. The databases must already be running and migrated (`make db-up`,
`make migrate`). The chain itself changes no data.

--e2e adds the end-to-end demonstration, which does write to the development
database: it starts the API, imports the demo dataset through the services,
checks it over HTTP, saves the World State, stops the API, restarts
PostgreSQL without deleting its data, starts the API again and checks that
the World State is identical. By default PostgreSQL is restarted with
`make db-down` and `make db-up`, which removes and recreates the container and
keeps the named volume. --db-restart-cmd replaces that command where the
database is not run by Docker Compose.
"""

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.config import REPO_ROOT, Settings, get_settings

API_DIR = REPO_ROOT / "services" / "api"
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_E2E_DIR = REPO_ROOT / "artifacts" / "tmp" / "e2e"
DEFAULT_DB_RESTART = "make db-down && make db-up"
API_START_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class Step:
    """One link of the chain: a command to run or a function to call."""

    name: str
    command: tuple[str, ...] | None = None
    action: Callable[[], str] | None = None


@dataclass(frozen=True)
class Result:
    name: str
    passed: bool
    seconds: float
    detail: str


class StepFailed(Exception):
    """A step of the end-to-end run did not succeed."""


# --- checks that are functions --------------------------------------------------------


def check_configuration() -> str:
    settings = get_settings()
    if not settings.test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is not configured")
    if settings.test_database_url == settings.database_url:
        raise RuntimeError("TEST_DATABASE_URL must not be the development database")
    return f"APP_ENV={settings.app_env}, database {settings.database_url_redacted}"


def _query(url: str, statement: str) -> str:
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            return str(connection.execute(text(statement)).scalar_one())
    except SQLAlchemyError as exc:
        raise RuntimeError(f"not reachable ({type(exc).__name__})") from None
    finally:
        engine.dispose()


def check_databases() -> str:
    settings: Settings = get_settings()
    assert settings.test_database_url is not None
    development = _query(settings.database_url, "SHOW server_version")
    test = _query(settings.test_database_url, "SHOW server_version")
    for label, version in (("development", development), ("test", test)):
        if not version.startswith("16."):
            raise RuntimeError(f"the {label} database runs PostgreSQL {version}, expected 16.x")
    return f"development PostgreSQL {development}, test PostgreSQL {test}"


# --- the end-to-end demonstration -----------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_port(host: str) -> int:
    with socket.socket() as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def _run(command: list[str], *, cwd: Path = API_DIR, shell_text: str | None = None) -> None:
    """Run a command, show its output, and fail the run if it fails."""
    shown = shell_text or " ".join(command)
    print(f"$ {shown}", flush=True)
    completed = (
        subprocess.run(shell_text, cwd=cwd, shell=True, check=False)
        if shell_text
        else subprocess.run(command, cwd=cwd, check=False)
    )
    if completed.returncode != 0:
        raise StepFailed(f"`{shown}` exited with {completed.returncode}")


@contextmanager
def running_api(host: str, port: int, log_path: Path) -> Iterator[int]:
    """Start the API as its own process, wait until it is ready, stop it afterwards."""
    command = ["uv", "run", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    print(f"$ {' '.join(command)}   (log: {log_path.name})", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=API_DIR, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + API_START_TIMEOUT_SECONDS
        ready = False
        while time.monotonic() < deadline and process.poll() is None:
            try:
                ready = (
                    httpx2.get(f"http://{host}:{port}/health/ready", timeout=2).status_code == 200
                )
            except httpx2.HTTPError:
                ready = False
            if ready:
                break
            time.sleep(0.5)
        if not ready:
            raise StepFailed(f"the API did not become ready on {host}:{port}; see {log_path}")
        print(f"API ready on http://{host}:{port} (pid {process.pid})", flush=True)
        yield process.pid
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        print(f"API stopped (pid {process.pid})", flush=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_e2e(host: str, db_restart_command: str, evidence_dir: Path) -> str:
    """Import, check, restart everything, check again. Writes the evidence files."""
    settings = get_settings()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    before_file = evidence_dir / "world-state-before-restart.json"
    after_file = evidence_dir / "world-state-after-restart.json"
    api_log = evidence_dir / "api.log"
    api_log.write_text("", encoding="utf-8")
    python = ["uv", "run", "python"]
    smoke = [*python, str(SCRIPTS_DIR / "smoke_test.py")]
    proof: list[str] = ["End-to-end demonstration and restart proof", ""]

    def note(line: str) -> None:
        proof.append(f"{_now()}  {line}")

    started_before = _query(settings.database_url, "SELECT pg_postmaster_start_time()")
    port = _free_port(host)
    with running_api(host, port, api_log) as pid:
        note(f"API started (pid {pid}) on {host}:{port}; readiness 200")
        _run([*python, str(SCRIPTS_DIR / "seed_demo_data.py")])
        note("demo dataset imported through the preview and commit services (seed_demo_data.py)")
        _run(
            [
                *smoke,
                "--base-url",
                f"http://{host}:{port}",
                "--import-demo",
                "--save-world-state",
                str(before_file),
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
        note(
            "dataset sent again over HTTP: every file resolved to its batch, every commit a replay"
        )
        note(f"World State saved without generated_at: sha256 {_sha256(before_file)}")
    note(f"API stopped (pid {pid})")

    _run([], cwd=REPO_ROOT, shell_text=db_restart_command)
    _run([*python, str(SCRIPTS_DIR / "wait_for_db.py")])
    started_after = _query(settings.database_url, "SELECT pg_postmaster_start_time()")
    if started_after == started_before:
        raise StepFailed("PostgreSQL reports the same start time as before: it was not restarted")
    note(f"PostgreSQL restarted with: {db_restart_command}")
    note(f"PostgreSQL start time before {started_before}, after {started_after}")

    port = _free_port(host)
    with running_api(host, port, api_log) as pid:
        note(f"API started again (pid {pid}) on {host}:{port}; readiness 200")
        _run(
            [
                *smoke,
                "--base-url",
                f"http://{host}:{port}",
                "--compare-world-state",
                str(before_file),
                "--save-world-state",
                str(after_file),
            ]
        )
    note(f"World State read again: sha256 {_sha256(after_file)}")
    identical = _sha256(before_file) == _sha256(after_file)
    note(f"World State before and after the restart identical: {'yes' if identical else 'NO'}")
    (evidence_dir / "day3-restart-proof.txt").write_text("\n".join(proof) + "\n", encoding="utf-8")
    if not identical:
        raise StepFailed("the World State changed across the restart")
    return f"World State identical across the restart; evidence in {evidence_dir}"


# --- the chain ------------------------------------------------------------------------


def uv_run(*arguments: str) -> tuple[str, ...]:
    return ("uv", "run", *arguments)


def build_steps(arguments: argparse.Namespace) -> list[Step]:
    steps = [
        Step("configuration is valid", action=check_configuration),
        Step("lockfile matches pyproject.toml", command=("uv", "lock", "--check")),
        Step("PostgreSQL 16 is reachable (development and test)", action=check_databases),
        Step("migrations: models match the applied schema", command=uv_run("alembic", "check")),
        Step("ruff lint", command=uv_run("ruff", "check", str(REPO_ROOT))),
        Step("ruff format", command=uv_run("ruff", "format", "--check", str(REPO_ROOT))),
        Step("mypy", command=uv_run("mypy", "app")),
        Step("unit tests", command=uv_run("pytest", "tests/unit", "-q")),
        Step("API tests", command=uv_run("pytest", "tests/api", "-q")),
        Step("integration tests", command=uv_run("pytest", "tests/integration", "-q")),
        Step(
            "OpenAPI document is up to date",
            command=uv_run("python", str(SCRIPTS_DIR / "export_openapi.py"), "--check"),
        ),
    ]
    if arguments.e2e_only:
        # The chain was run step by step elsewhere (CI does); keep the two
        # checks the demonstration depends on.
        steps = [step for step in steps if step.action is not None]
    if arguments.e2e or arguments.e2e_only:
        steps.append(
            Step(
                "end to end: import, World State, restart of API and PostgreSQL, compare",
                action=lambda: run_e2e(
                    arguments.e2e_host, arguments.db_restart_cmd, arguments.evidence_dir
                ),
            )
        )
    return steps


def run_step(step: Step) -> Result:
    print(f"\n=== {step.name} ===", flush=True)
    started = time.monotonic()
    if step.action is not None:
        try:
            detail = step.action()
            passed = True
        except Exception as exc:
            detail, passed = f"{type(exc).__name__}: {exc}", False
        print(detail, flush=True)
    else:
        assert step.command is not None
        print("$ " + " ".join(step.command), flush=True)
        completed = subprocess.run(step.command, cwd=API_DIR, check=False)
        passed = completed.returncode == 0
        detail = f"exit code {completed.returncode}"
    return Result(step.name, passed, round(time.monotonic() - started, 2), detail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, help="write the result summary as JSON here")
    parser.add_argument("--e2e", action="store_true", help="add the end-to-end demonstration")
    parser.add_argument(
        "--e2e-only",
        action="store_true",
        help="only the end-to-end demonstration, after the configuration and database checks",
    )
    parser.add_argument("--e2e-host", default="127.0.0.1", help="address the API binds to")
    parser.add_argument(
        "--db-restart-cmd",
        default=DEFAULT_DB_RESTART,
        help="shell command, run from the repository root, that restarts the development "
        f"PostgreSQL and keeps its data (default: {DEFAULT_DB_RESTART})",
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_E2E_DIR)
    arguments = parser.parse_args()

    steps = build_steps(arguments)
    results: list[Result] = []
    for step in steps:
        result = run_step(step)
        results.append(result)
        if not result.passed:
            break

    not_run = [step.name for step in steps[len(results) :]]
    print("\n=== summary ===")
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}  {result.name}  ({result.seconds}s)")
    for name in not_run:
        print(f"NOT RUN  {name}")

    all_passed = len(results) == len(steps) and all(result.passed for result in results)
    print("\nVERIFICATION PASSED" if all_passed else "\nVERIFICATION FAILED")

    if arguments.summary:
        arguments.summary.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary.write_text(
            json.dumps(
                {
                    "passed": all_passed,
                    "steps": [vars(result) for result in results],
                    "not_run": not_run,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
