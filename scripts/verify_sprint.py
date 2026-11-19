"""One command that says whether the build is sound.

Usage (from services/api):
    uv run python ../../scripts/verify_sprint.py
    uv run python ../../scripts/verify_sprint.py --summary ../../artifacts/tmp/verify.json

Runs the verification chain in a fixed order and stops at the first failure.
The exit code is 0 only when every step passed; a failing subprocess is never
swallowed. Nothing here changes data: the databases must already be running
and migrated (`make db-up`, `make migrate`).
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.config import REPO_ROOT, Settings, get_settings

API_DIR = REPO_ROOT / "services" / "api"
SCRIPTS_DIR = REPO_ROOT / "scripts"


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


def check_configuration() -> str:
    settings = get_settings()
    if not settings.test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is not configured")
    if settings.test_database_url == settings.database_url:
        raise RuntimeError("TEST_DATABASE_URL must not be the development database")
    return f"APP_ENV={settings.app_env}, database {settings.database_url_redacted}"


def _server_version(url: str) -> str:
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            return str(connection.execute(text("SHOW server_version")).scalar_one())
    except SQLAlchemyError as exc:
        raise RuntimeError(f"not reachable ({type(exc).__name__})") from None
    finally:
        engine.dispose()


def check_databases() -> str:
    settings: Settings = get_settings()
    assert settings.test_database_url is not None
    development = _server_version(settings.database_url)
    test = _server_version(settings.test_database_url)
    for label, version in (("development", development), ("test", test)):
        if not version.startswith("16."):
            raise RuntimeError(f"the {label} database runs PostgreSQL {version}, expected 16.x")
    return f"development PostgreSQL {development}, test PostgreSQL {test}"


def uv_run(*arguments: str) -> tuple[str, ...]:
    return ("uv", "run", *arguments)


def build_steps() -> list[Step]:
    return [
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
    parser.add_argument(
        "--summary", type=Path, help="write the result summary as JSON to this file"
    )
    arguments = parser.parse_args()

    steps = build_steps()
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
