"""Nexus v0.8.2 — Routing-flip + dual-path-removal regression tests.

v0.8.2 closeout gate (canonical production routing / legacy authority
removed):

  1. The persistent PostgreSQL-backed router OWNS /api/v1/nexus/*.
     Every authoritative operation terminates at
     AsyncSession → PostgreSQL → Authoritative* services.
  2. The v0.7 in-memory routers are NOT mounted by default. They are
     only reachable under /api/v1/v07-legacy/nexus/* when
     CORTEX_NEXUS_V07_LEGACY_ROUTES is explicitly enabled.
  3. The canonical routes can never invoke the legacy in-memory
     singletons (DecisionLifecycleManager / DecisionMemory / TruthLoop /
     ObservationStore) — enforced by tripwire during a full HTTP
     lifecycle and by a static source check.
  4. Route compatibility is preserved: envelopes (request_id /
     correlation_id / timestamp / data), status codes, error envelopes,
     and workspace authorization behave exactly as before the flip —
     only the backing implementation changed.

The real-PostgreSQL FOR UPDATE concurrency guarantee is covered
separately in tests/test_nexus_v082_pg_concurrency.py.
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ensure nexus models register with Base.metadata.
from app.modules.nexus_spine.persistence import models as _spine_models  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT = "flip-test-tenant"
WS = "WS-FLIP"

# The exact canonical production surface (from app.api.v1.nexus_persistent).
CANONICAL_NEXUS_PATHS = {
    ("POST", "/api/v1/nexus/decisions"),
    ("GET", "/api/v1/nexus/decisions"),
    ("GET", "/api/v1/nexus/decisions/{decision_id}"),
    ("POST", "/api/v1/nexus/decisions/{decision_id}/advance"),
    ("POST", "/api/v1/nexus/decisions/{decision_id}/execute"),
    ("POST", "/api/v1/nexus/decisions/{decision_id}/outcome"),
    ("POST", "/api/v1/nexus/decisions/{decision_id}/memory"),
    ("POST", "/api/v1/nexus/memory/analogous"),
    ("GET", "/api/v1/nexus/memory/recent"),
    ("POST", "/api/v1/nexus/forecasts"),
    ("POST", "/api/v1/nexus/observations"),
    ("GET", "/api/v1/nexus/calibration"),
    ("GET", "/api/v1/nexus/bias"),
    ("POST", "/api/v1/nexus/vanessa/ask"),
}

# Authoritative operations that used to live on the v0.7 in-memory router
# under /api/v1/nexus/*. After the flip they MUST NOT exist there.
OLD_IN_MEMORY_OPS_AT_CANONICAL_PATH = [
    ("POST", "/api/v1/nexus/decisions/analogous"),  # old in-memory shape
    ("PATCH", "/api/v1/nexus/decisions/{id}/outcome"),  # old in-memory shape
    ("POST", "/api/v1/nexus/forecasts/observe"),  # old truth-loop shape
    ("POST", "/api/v1/nexus/governance/decisions/{id}/advance"),
    ("POST", "/api/v1/nexus/governance/decisions/{id}/approve"),
    ("POST", "/api/v1/nexus/governance/decisions/{id}/reject"),
    ("POST", "/api/v1/nexus/governance/decisions/{id}/mark-stale"),
    ("GET", "/api/v1/nexus/governance/decisions/{id}/audit-trail"),
    ("GET", "/api/v1/nexus/vanessa/tools"),
]


# ─────────────────────────────────────────────────────────────────────
# Fixtures — full application (real mount table) + SQLite DB override
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def flip_app(nexus_db_engine):
    """The REAL application (app.main.create_app) with get_db overridden
    to the shared test SQLite engine, so the full mount table — not a
    hand-built subset — is under test."""
    os.environ.setdefault("CORTEX_ENV", "test")
    from app.infrastructure.database import get_db as _real_get_db
    from app.main import create_app

    app = create_app()
    sf = async_sessionmaker(nexus_db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_db():
        async with sf() as session:
            yield session

    app.dependency_overrides[_real_get_db] = _override_db
    return app


@pytest.fixture
async def flip_client(flip_app):
    from httpx import ASGITransport, AsyncClient

    from app.infrastructure.security import AuthContext, get_current_user

    async def _fake_user(request: Request) -> AuthContext:
        return AuthContext(
            user_id="flip-user",
            email="flip@example.com",
            roles=["operator"],
            workspace_ids=[],  # any-workspace policy (dev principal)
            is_anonymous=False,
        )

    flip_app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=flip_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _create_decision(client, **overrides) -> dict[str, Any]:
    body: dict[str, Any] = {
        "workspace_id": WS,
        "situation": "routing-flip regression decision",
        "options": [{"option_id": "O1", "nev": 100.0, "sla": 0.95, "cost": 50.0}],
        "recommended_option_id": "O1",
        "world_state_version": 1,
        "world_state_hash": "flip-h1",
    }
    body.update(overrides)
    r = await client.post("/api/v1/nexus/decisions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]["decision"]


async def _advance_to(client, decision_id: str, phase: str) -> None:
    r = await client.post(
        f"/api/v1/nexus/decisions/{decision_id}/advance",
        headers={"X-Workspace-Id": WS},
        json={"target_phase": phase},
    )
    assert r.status_code == 200, f"{phase}: {r.text}"


# ─────────────────────────────────────────────────────────────────────
# 1. Canonical production routing
# ─────────────────────────────────────────────────────────────────────


class TestCanonicalRouting:
    def test_persistent_router_owns_nexus_namespace(self, flip_app):
        spec = flip_app.openapi()
        found = {
            (method.upper(), path)
            for path, ops in spec["paths"].items()
            if path.startswith("/api/v1/nexus")
            for method in ops
        }
        assert found == CANONICAL_NEXUS_PATHS, (
            f"canonical surface drift: missing={CANONICAL_NEXUS_PATHS - found} "
            f"unexpected={found - CANONICAL_NEXUS_PATHS}"
        )

    def test_no_dual_mount_of_persistent_router(self, flip_app):
        """The pre-release /nexus/persistent/* mount must be gone — one
        implementation, one route."""
        spec = flip_app.openapi()
        assert not [p for p in spec["paths"] if "/nexus/persistent" in p]

    def test_old_authoritative_ops_gone_from_canonical_paths(self, flip_app):
        """Every authoritative decision/memory/truth operation that the
        v0.7 in-memory router served under /api/v1/nexus/* must be gone."""
        spec = flip_app.openapi()
        for _, path in OLD_IN_MEMORY_OPS_AT_CANONICAL_PATH:
            assert path not in spec["paths"], f"legacy op still mounted: {path}"

    async def test_old_authoritative_ops_return_404_over_http(self, flip_client):
        did = f"D-flip-{uuid.uuid4().hex[:8]}"
        probes = [
            ("POST", f"/api/v1/nexus/governance/decisions/{did}/advance"),
            ("POST", "/api/v1/nexus/forecasts/observe"),
            ("GET", "/api/v1/nexus/vanessa/tools"),
            ("POST", "/api/v1/nexus/decisions/analogous"),
            ("POST", "/api/v1/nexus/persistent/decisions"),
        ]
        for method, url in probes:
            r = await flip_client.request(method, url, params={"workspace_id": WS}, json={})
            # 404 = route gone entirely; 405 = path matched a *different*
            # canonical method (the old in-memory handler is gone either way).
            assert r.status_code in (404, 405), (
                f"{method} {url} -> {r.status_code} (expected 404/405)"
            )


# ─────────────────────────────────────────────────────────────────────
# 2. Legacy demotion — /v07-legacy/*, opt-in only
# ─────────────────────────────────────────────────────────────────────


class TestLegacyDemotion:
    def test_legacy_routes_not_mounted_by_default(self, flip_app):
        spec = flip_app.openapi()
        assert not [p for p in spec["paths"] if "/v07-legacy" in p], (
            "v0.7 in-memory routes must not be mounted without CORTEX_NEXUS_V07_LEGACY_ROUTES"
        )

    def test_legacy_routes_mount_only_with_explicit_flag(self, monkeypatch):
        """With the flag on, the v0.7 in-memory surface appears under
        /api/v1/v07-legacy/nexus/* — for unit tests, migration tooling,
        and historical v0.7 demos only."""
        from fastapi import FastAPI

        from app.config import get_settings

        monkeypatch.setenv("CORTEX_NEXUS_V07_LEGACY_ROUTES", "1")
        get_settings.cache_clear()
        try:
            router_mod = importlib.reload(importlib.import_module("app.api.v1.router"))
            app = FastAPI()
            app.include_router(router_mod.api_router, prefix="/api/v1")
            spec = app.openapi()

            legacy = [p for p in spec["paths"] if p.startswith("/api/v1/v07-legacy/nexus")]
            # The old in-memory surface (world, entities, governance, ...) is
            # preserved verbatim under the legacy namespace.
            assert "/api/v1/v07-legacy/nexus/world" in legacy
            assert "/api/v1/v07-legacy/nexus/decisions" in legacy
            assert "/api/v1/v07-legacy/nexus/governance/decisions/{decision_id}/advance" in legacy

            # The canonical surface is untouched and still persistent-only.
            canonical = [p for p in spec["paths"] if p.startswith("/api/v1/nexus/")]
            assert len(canonical) == len({p for _, p in CANONICAL_NEXUS_PATHS})
            assert "/api/v1/nexus/persistent/decisions" not in spec["paths"]
        finally:
            monkeypatch.delenv("CORTEX_NEXUS_V07_LEGACY_ROUTES", raising=False)
            get_settings.cache_clear()
            importlib.reload(importlib.import_module("app.api.v1.router"))


# ─────────────────────────────────────────────────────────────────────
# 3. Migration regression — legacy manager MUST NOT BE CALLED
# ─────────────────────────────────────────────────────────────────────


_LEGACY_NAMESPACES = {
    # defining modules
    "app.modules.nexus_spine.governance.lifecycle": [
        "get_decision_lifecycle_manager",
        "DecisionLifecycleManager",
    ],
    "app.modules.nexus_spine.memory.decision_memory": [
        "get_decision_memory",
        "DecisionMemory",
    ],
    "app.modules.nexus_spine.demand.truth_loop": ["get_truth_loop", "TruthLoop"],
    "app.modules.nexus_spine.observability.accuracy": [
        "ObservationStore",
        "get_observation",
    ],
    # modules that bound the singletons into their own namespace
    "app.api.v1.nexus": [
        "get_decision_lifecycle_manager",
        "DecisionLifecycleManager",
        "get_decision_memory",
        "get_truth_loop",
    ],
    "app.modules.nexus_spine.vanessa.builtin_tools": [
        "get_truth_loop",
        "get_decision_memory",
    ],
}


def _install_legacy_tripwires(monkeypatch) -> list[str]:
    """Patch every legacy-singleton getter AND class constructor so that
    any invocation from any module raises AssertionError. Returns the
    list of patched target names (for the failure message)."""
    patched: list[str] = []

    def _trip(name: str):
        def _raise(*args: Any, **kwargs: Any):
            raise AssertionError(f"LEGACY SINGLETON INVOKED: {name}")

        return _raise

    for module_name, names in _LEGACY_NAMESPACES.items():
        module = importlib.import_module(module_name)
        for name in names:
            # A missing attribute is the STRONGEST pass state: the legacy
            # name was removed from the module entirely, so there is nothing
            # left to invoke. (The 2026-09 lint paydown removed the vestigial
            # unused re-exports from app.api.v1.nexus.)
            target = getattr(module, name, None)
            if target is None:
                continue
            if isinstance(target, type):
                # Patch the constructor — catches direct instantiation.
                monkeypatch.setattr(target, "__init__", _trip(f"{module_name}.{name}"))
            else:
                monkeypatch.setattr(module, name, _trip(f"{module_name}.{name}"), raising=True)
            patched.append(f"{module_name}.{name}")
    return patched


class TestMigrationRegression:
    async def test_canonical_lifecycle_never_invokes_legacy_manager(
        self, flip_client, nexus_db_engine, monkeypatch
    ):
        """THE v0.8.2 migration regression.

        /api/v1/nexus/decisions
                ↓
        AuthoritativeDecisionService
                ↓
        PostgreSQL (test engine)

        and explicitly:

        legacy DecisionLifecycleManager / DecisionMemory / TruthLoop /
        ObservationStore  →  MUST NOT BE CALLED.
        """
        _install_legacy_tripwires(monkeypatch)

        # Full canonical HTTP lifecycle under tripwires.
        dec = await _create_decision(flip_client)
        did = dec["decision_id"]
        assert dec["phase"] == "proposed"

        for phase in ("simulated", "policy_checked", "awaiting_approval", "approved"):
            await _advance_to(flip_client, did, phase)

        r = await flip_client.post(
            f"/api/v1/nexus/decisions/{did}/execute", params={"workspace_id": WS}
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["decision"]["phase"] == "executed"

        r = await flip_client.post(
            f"/api/v1/nexus/decisions/{did}/outcome",
            params={"workspace_id": WS},
            json={
                "outcome_status": "succeeded",
                "financial_impact": 42.0,
                "actual_result_text": "ok",
                "actual_nev": 90,
                "actual_sla": 0.96,
                "actual_cost": 48,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["decision"]["phase"] == "outcome_recorded"

        r = await flip_client.post(
            f"/api/v1/nexus/decisions/{did}/memory", params={"workspace_id": WS}
        )
        assert r.status_code == 200, r.text

        fid = f"F-flip-{uuid.uuid4().hex[:8]}"
        r = await flip_client.post(
            "/api/v1/nexus/forecasts",
            params={"workspace_id": WS},
            json={
                "forecast_id": fid,
                "sku": "SKU-FLIP",
                "p50": 100,
                "p80": 120,
                "p95": 140,
                "mean": 100,
                "std_dev": 20,
                "world_state_version": 1,
            },
        )
        assert r.status_code == 201, r.text
        r = await flip_client.post(
            "/api/v1/nexus/observations",
            params={"workspace_id": WS},
            json={"forecast_id": fid, "sku": "SKU-FLIP", "actual_value": 110},
        )
        assert r.status_code == 201, r.text

        r = await flip_client.post(
            "/api/v1/nexus/vanessa/ask",
            params={"workspace_id": WS},
            json={"query": "what is the state of the world?"},
        )
        assert r.status_code == 200, r.text
        # No legacy trip fired — the canonical path is fully persistent.

        # And the state actually terminated at the database.
        from app.modules.nexus_spine.persistence.models import (
            DecisionRecordDB,
            DecisionTransitionDB,
        )

        sf = async_sessionmaker(nexus_db_engine, expire_on_commit=False, class_=AsyncSession)
        async with sf() as s:
            rec = (
                await s.execute(select(DecisionRecordDB).where(DecisionRecordDB.decision_id == did))
            ).scalar_one_or_none()
            assert rec is not None, "decision row must exist in the database"
            assert rec.phase == "outcome_recorded"
            transitions = (
                (
                    await s.execute(
                        select(DecisionTransitionDB).where(DecisionTransitionDB.decision_id == did)
                    )
                )
                .scalars()
                .all()
            )
            # created + 4 advances + 3 execute steps + outcome = 9, no dupes
            assert len(transitions) == 9
            pairs = [(t.from_phase, t.to_phase) for t in transitions]
            assert len(set(pairs)) == len(pairs), "duplicate audit transition"
            assert transitions[-1].to_phase == "outcome_recorded"

    def test_persistent_router_source_references_no_legacy_singletons(self):
        """Static guarantee: the canonical router module may only use the
        Authoritative* services (p0_migration) — no legacy singleton
        getters, constructors, or imports may appear (prose mentions in
        the docstring are excluded by checking call/getter forms)."""
        src = (REPO_ROOT / "backend" / "app" / "api" / "v1" / "nexus_persistent.py").read_text()
        for forbidden in (
            "get_decision_lifecycle_manager",
            "DecisionLifecycleManager(",
            "get_decision_memory",
            "get_truth_loop",
            "TruthLoop(",
            "ObservationStore(",
            "get_world_model(",
            "get_vanessa(",
        ):
            assert forbidden not in src, (
                f"nexus_persistent.py must not reference legacy singleton: {forbidden}"
            )
        assert "from app.modules.nexus_spine.p0_migration import" in src
        assert "get_authoritative_decision_service" in src

    async def test_canonical_writes_reach_the_database_not_memory(
        self, flip_client, nexus_db_engine
    ):
        """A fresh worker (brand-new service instances = simulated restart)
        sees the decision created over HTTP — proof the write terminated
        at the database rather than process memory."""
        from app.modules.nexus_spine.p0_migration import AuthoritativeDecisionService
        from app.modules.nexus_spine.persistence.models import DecisionRecordDB

        dec = await _create_decision(flip_client, situation="restart-visibility check")
        sf = async_sessionmaker(nexus_db_engine, expire_on_commit=False, class_=AsyncSession)
        fresh = AuthoritativeDecisionService()  # no shared cache with the router
        async with sf() as s:
            # Bypass the projection cache with a direct DB read.
            rec = (
                await s.execute(
                    select(DecisionRecordDB).where(
                        DecisionRecordDB.decision_id == dec["decision_id"]
                    )
                )
            ).scalar_one()
            assert rec.situation == "restart-visibility check"
            # And a fresh service instance (new "worker") reads it.
            fetched = await fresh.get(s, dec["decision_id"])
        assert fetched is not None and fetched["phase"] == "proposed"


# ─────────────────────────────────────────────────────────────────────
# 4. Route compatibility (contract preserved across the flip)
# ─────────────────────────────────────────────────────────────────────


class TestRouteCompatibility:
    async def test_envelope_request_and_correlation_ids(self, flip_client):
        r = await flip_client.post(
            "/api/v1/nexus/decisions",
            json={
                "workspace_id": WS,
                "situation": "envelope check",
                "options": [],
                "world_state_version": 1,
                "world_state_hash": "h",
            },
            headers={"X-Request-ID": "req-flip-1", "X-Correlation-Id": "corr-flip-1"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert set(body.keys()) == {"request_id", "correlation_id", "timestamp", "data"}
        assert body["request_id"] == "req-flip-1"
        assert body["correlation_id"] == "corr-flip-1"
        assert "decision" in body["data"]

    async def test_workspace_authorization_enforced(self, flip_app):
        """A principal scoped to another workspace gets 403 with the
        structured error envelope — unchanged by the flip."""
        from httpx import ASGITransport, AsyncClient

        from app.infrastructure.security import AuthContext, get_current_user

        async def _other_workspace_user(request: Request) -> AuthContext:
            return AuthContext(
                user_id="intruder",
                roles=["operator"],
                workspace_ids=["WS-OTHER"],
                is_anonymous=False,
            )

        flip_app.dependency_overrides[get_current_user] = _other_workspace_user
        transport = ASGITransport(app=flip_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await client.post(
                "/api/v1/nexus/decisions",
                json={
                    "workspace_id": WS,
                    "situation": "should be denied",
                    "options": [],
                    "world_state_version": 1,
                    "world_state_hash": "h",
                },
            )
            assert r.status_code == 403
            detail = r.json()["detail"]
            assert detail["error"] == "forbidden"
            assert detail["workspace_id"] == WS

            r = await client.get("/api/v1/nexus/decisions", params={"workspace_id": WS})
            assert r.status_code == 403

    async def test_status_codes_and_error_envelopes(self, flip_client):
        dec = await _create_decision(flip_client)

        # 404 — unknown decision
        r = await flip_client.get(
            "/api/v1/nexus/decisions/D-does-not-exist", params={"workspace_id": WS}
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "decision not found"

        # 400 — invalid phase
        r = await flip_client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/advance",
            headers={"X-Workspace-Id": WS},
            json={"target_phase": "not-a-phase"},
        )
        assert r.status_code == 400

        # 409 — invalid transition (re-advance to the same phase)
        await _advance_to(flip_client, dec["decision_id"], "simulated")
        r = await flip_client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/advance",
            headers={"X-Workspace-Id": WS},
            json={"target_phase": "simulated"},
        )
        assert r.status_code == 409
        assert "Invalid transition" in r.json()["detail"]

        # 422 — schema violation (extra="forbid" request model)
        r = await flip_client.post(
            "/api/v1/nexus/decisions",
            json={"workspace_id": WS, "decision_id": "caller-supplied-id"},
        )
        assert r.status_code == 422

    async def test_list_and_get_roundtrip(self, flip_client):
        dec = await _create_decision(flip_client, situation="list/get roundtrip")
        r = await flip_client.get(
            "/api/v1/nexus/decisions", params={"workspace_id": WS, "limit": 200}
        )
        assert r.status_code == 200
        ids = [d["decision_id"] for d in r.json()["data"]["decisions"]]
        assert dec["decision_id"] in ids

        r = await flip_client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}", params={"workspace_id": WS}
        )
        assert r.status_code == 200
        assert r.json()["data"]["decision"]["situation"] == "list/get roundtrip"
