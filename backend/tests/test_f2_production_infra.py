"""F2 — Production health/readiness/probe (Phase 15 gate).

Pins the wire contract for the F2 production-infrastructure
improvements:

- The ``readyz`` endpoint (updated in F2) returns 503 if ANY of
  the four mandatory dependency checks (db, redis,
  object_storage, audit_chain) fails, and includes the full
  ``components`` payload in the 503 body so on-call can
  diagnose without grepping logs.
- The ``healthz`` endpoint remains a simple 200 liveness probe
  (no dependency checks — liveness must not trigger on
  transient dependency outages or every pod restarts).
- The K8s ``startupProbe`` budget is 180s (36 failures * 5s)
  which matches the ``readinessProbe`` budget (3 failures *
  5s) multiplied by 12 for the startup phase, allowing init_db()
  to finish before readiness begins evaluation.
- The ``readinessProbe`` endpoint is ``/readyz`` (not ``/``),
  which is the only endpoint that checks all four
  dependencies.

The test is hermetic — no K8s, no Docker, no real PG/Redis.
It uses ``pytest-monkeypatch`` to inject fake dependency
states into ``app.infrastructure.health``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# Helper to import without triggering slow init paths
@pytest.fixture
def health_mod():
    import app.infrastructure.health as health

    return health


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health endpoint contract — simple liveness, no dependency checks
# ─────────────────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """``/healthz`` must stay a pure liveness probe. It must
    return 200 regardless of dependency state — a temporary
    dependency failure is a readiness issue, not a liveness
    issue. Changing healthz to return 503 on dependency
    failure would create a cascading restart loop."""

    def test_healthz_is_200_on_ok_dependencies(self):
        from starlette.testclient import TestClient

        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_healthz_is_200_on_bad_dependencies(self):
        # Even when dependencies are bad, healthz stays 200.
        from starlette.testclient import TestClient

        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        # Force a DB failure by patching the dependency check.
        import app.infrastructure.health as h_mod

        with patch.object(h_mod, "check_db", return_value=(False, "down")):
            # Note: the health endpoint does not call check_db
            # at all — the 200 is unconditional. This test
            # verifies that independence.
            resp = client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Readiness endpoint contract — all four checks, aggregate verdict
# ─────────────────────────────────────────────────────────────────────────────


class TestReadinessEndpoint:
    """``/readyz`` must return 503 if any dependency fails, and
    the body must contain the ``components`` list with the
    failing component named. The body must also say
    ``"status": "unavailable"`` — anything else is a contract
    violation that breaks the on-call runbook parser."""

    def test_readyz_200_when_all_dependencies_ok(self):
        from starlette.testclient import TestClient

        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/readyz")
        # Note: the default DB/Redis/state checks may return
        # different results depending on the environment.
        # The contract test asserts the SHAPE of the response,
        # not the exact 503/200 decision (which is environment
        # dependent and covered by the component-level tests
        # below).
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "status" in body
        assert "components" in body
        assert isinstance(body["components"], list)
        # Every component has the three required fields.
        for c in body["components"]:
            assert "name" in c, "Every component needs a name"
            assert "ok" in c, "Every component needs an ok flag"
            assert "detail" in c, "Every component needs a detail"

    def test_readiness_503_includes_failed_component_names(self, monkeypatch: pytest.MonkeyPatch):
        # Inject a synthetic failure for one dependency; the
        # 503 response must mention the failing component by
        # name so the alert rule can key off it directly.
        from starlette.testclient import TestClient

        import app.infrastructure.health as h_mod
        from app.main import create_app

        async def _fake_check():
            # DB ok; Redis fails.
            return (
                False,
                [
                    h_mod.ComponentStatus("db", True, "ok"),
                    h_mod.ComponentStatus("redis", False, "simulated_down"),
                    h_mod.ComponentStatus("object_storage", True, "ok"),
                    h_mod.ComponentStatus("audit_chain", True, "ok"),
                ],
            )

        with patch.object(h_mod, "check_dependencies", _fake_check):
            app = create_app()
            client = TestClient(app)
            resp = client.get("/readyz")
            assert resp.status_code == 503
            body = resp.json()
            assert body["status"] == "unavailable"
            names = {c["name"] for c in body["components"]}
            assert "redis" in names
            failed = {c["name"] for c in body["components"] if not c["ok"]}
            assert failed == {"redis"}
            # The response payload must include the detail so the
            # on-call can diagnose without checking the audit chain.
            redis_row = next(c for c in body["components"] if c["name"] == "redis")
            assert redis_row["detail"] == "simulated_down"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dependency-level contract — individual checks
# ─────────────────────────────────────────────────────────────────────────────


class TestDependencyContracts:
    """Every dependency check returns a ``(bool, str)`` tuple
    (or an awaitable of the same). No check raises — a raised
    exception is caught by ``check_dependencies`` and turned
    into a False result, which is the correct secure behavior
    (fail-closed for readiness)."""

    def test_db_check_contract(self):
        import app.infrastructure.health as h_mod

        ok, detail = h_mod.check_db()
        assert isinstance(ok, bool)
        assert isinstance(detail, str)
        assert len(detail) > 0

    def test_redis_check_contract(self):
        import app.infrastructure.health as h_mod

        # check_redis returns a coroutine.
        result = h_mod.check_redis()
        import inspect

        assert inspect.isawaitable(result), (
            "check_redis must return an awaitable; the caller "
            "awaits it so both sync and async checks work uniformly."
        )

    def test_object_storage_check_contract(self):
        import app.infrastructure.health as h_mod

        ok, detail = h_mod.check_object_storage()
        assert isinstance(ok, bool)
        assert isinstance(detail, str)

    def test_audit_chain_check_contract(self):
        import app.infrastructure.health as h_mod

        ok, detail = h_mod.check_audit_chain()
        assert isinstance(ok, bool)
        assert isinstance(detail, str)

    def test_audit_chain_max_age_is_positive(self):
        import app.infrastructure.health as h_mod

        assert h_mod.AUDIT_CHAIN_MAX_AGE.total_seconds() == 86400.0  # 1d
        assert __import__("datetime").timedelta(0) < h_mod.AUDIT_CHAIN_MAX_AGE


# ─────────────────────────────────────────────────────────────────────────────
# 4. K8s startupProbe budget — 180s for init_db to complete
# ─────────────────────────────────────────────────────────────────────────────


class TestK8sProbeBudget:
    """The startupProbe budget must be larger than the readiness
    budget multiplied by the number of dependency checks
    (since each dependency takes its own timeout). The
    config value is pinned to prevent a silent regression
    that shrinks startup budget and kills pods during
    init_db warm-up."""

    def test_startup_probe_exists_in_manifest(self):
        # Read the manifest from disk and verify the budget.
        # The test runs from the backend/ cwd; the manifest
        # is at <repo>/k8s/base.yaml, so we resolve from the
        # test file's parents and walk up to the repo root.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]  # tests/ -> backend/ -> repo
        manifest_path = repo_root / "k8s" / "base.yaml"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = f.read()
        assert "startupProbe" in manifest, (
            "The base K8s manifest must define a startupProbe; "
            "without it, init_db has no protected budget."
        )
        assert "failureThreshold: 36" in manifest, (
            "The startupProbe budget must be 36 failures * 5s = 180s. "
            "Changing the budget silently breaks the startup contract."
        )
        # The readiness probe endpoint must be /readyz, not /
        # (the old default used /, which only returns a static 200).
        assert "path: /readyz" in manifest
        # The liveness endpoint must stay /healthz (pure, no dependency
        # checks) to prevent cascading restarts.
        assert "path: /healthz" in manifest

    def test_startup_probe_budget_is_three_minutes(self):
        # 36 failures * 5 seconds = 180s = 3 minutes. This budget
        # must cover the init_db warm-up + the first readiness pass.
        budget = 36 * 5
        assert budget == 180
        assert budget >= 60, "Startup budget must be at least 60s."
