"""Smoke test of a running Cortex Nexus API.

Usage (from services/api, with the API running):
    uv run python ../../scripts/smoke_test.py --base-url http://127.0.0.1:8000

Every check talks to the API over HTTP, the way a client would. The script
prints one line per check and exits 1 if any check fails.
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2

REQUEST_ID_HEADER = "X-Request-ID"


@dataclass
class Report:
    """Collects check results; a failed check does not stop the later ones."""

    failures: list[str] = field(default_factory=list)
    passed: int = 0

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            print(f"PASS  {name}" + (f"  [{detail}]" if detail else ""))
        else:
            self.failures.append(name)
            print(f"FAIL  {name}" + (f"  [{detail}]" if detail else ""))
        return condition


def check_health(client: httpx2.Client, report: Report) -> None:
    live = client.get("/health/live")
    report.check("liveness answers 200", live.status_code == 200, f"HTTP {live.status_code}")
    report.check(
        "every response carries a request id",
        bool(live.headers.get(REQUEST_ID_HEADER)),
    )

    ready = client.get("/health/ready")
    checks = ready.json().get("checks", {}) if ready.status_code in (200, 503) else {}
    summary = ", ".join(f"{name}={check['status']}" for name, check in checks.items())
    report.check(
        "readiness: database reachable and schema at the migration head",
        ready.status_code == 200,
        f"HTTP {ready.status_code}; {summary}",
    )


def check_contract(client: httpx2.Client, report: Report) -> None:
    document = client.get("/openapi.json")
    paths = document.json().get("paths", {}) if document.status_code == 200 else {}
    report.check(
        "OpenAPI document is served",
        document.status_code == 200 and "/health/ready" in paths,
        f"{len(paths)} paths",
    )

    missing = client.get(
        "/api/v1/this-route-does-not-exist", headers={REQUEST_ID_HEADER: "smoke-test-0001"}
    )
    body = missing.json() if missing.headers.get("content-type") == "application/json" else {}
    error = body.get("error", {})
    report.check(
        "errors use the standard envelope and echo the request id",
        missing.status_code == 404
        and set(error) == {"code", "message", "details", "request_id"}
        and error.get("request_id") == "smoke-test-0001",
        f"HTTP {missing.status_code}; code={error.get('code')}",
    )


CHECKS: tuple[Callable[[httpx2.Client, Report], None], ...] = (check_health, check_contract)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args()

    report = Report()
    try:
        with httpx2.Client(base_url=arguments.base_url, timeout=arguments.timeout) as client:
            for run_checks in CHECKS:
                run_checks(client, report)
    except httpx2.HTTPError as exc:
        print(f"FAIL  the API at {arguments.base_url} is not reachable ({type(exc).__name__})")
        return 1

    total = report.passed + len(report.failures)
    print(f"\n{report.passed} of {total} checks passed.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
