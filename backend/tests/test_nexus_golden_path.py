"""v0.8.5-B3 — Golden-path API acceptance (launch blockers B4 + B8).

Covers the Day 7–10 slice:
  canonical risk registry (record/list/get/triage)   ✅
  canonical signals (PG-backed detection-on-read)    ✅
  canonical scenarios (create/list/get/simulate)     ✅
  decision evidence DAG (nodes/edges/graph)          ✅
  approver identity trail (B8) + lifecycle evidence  ✅
  cross-workspace isolation on every new endpoint    ✅ (403/404 via real JWT)

Requires real PostgreSQL (nexus_* tables); skips when unavailable.
AuthN is exercised through REAL JWTs (minted by the same ``issue_token``
the login path uses): tests run with CORTEX_ENV=pilot so
``get_current_user`` takes the strict JWT path (no dependency overrides
for identity). Identities are provisioned directly in the DB — the signup
HTTP path (and its rate-limit bucket) is B1's covered territory. Owners
carry the admin role, so role-gated tools (record/approve/execute) are
genuinely exercised.
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

# Ensure model tables register with Base.metadata.
import app.modules.access.models as _access_models  # noqa: F401
import app.modules.audit.models as _audit_models  # noqa: F401
import app.modules.nexus_spine.persistence.models as _spine_models  # noqa: F401
from app.api.v1 import auth as auth_router_module
from app.api.v1 import nexus_persistent
from app.common.enums import UserRole
from app.common.ids import uuid7_uuid
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.modules.access.models import Organization, User, Workspace
from app.modules.identity.jwt_auth import issue_token
from app.modules.nexus_spine.persistence.models import EventRecordDB

JWT_SECRET = "test-secret-0123456789abcdef0123456789"


def _email(tag: str) -> str:
    return f"b3-{tag}-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def strict_auth_env(monkeypatch):
    """Run with CORTEX_ENV=pilot so identity resolves via real JWT verify."""
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def pg_engine(request):
    """Real-Postgres engine with auth + audit + nexus tables created."""
    postgres_url = request.config.postgres_url
    try:
        engine = create_async_engine(postgres_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")

    wanted = {
        ("core", "organizations"),
        ("core", "workspaces"),
        ("core", "users"),
        ("core", "password_resets"),
        (None, "audit_events"),
    }
    tables = [
        t
        for t in Base.metadata.sorted_tables
        if (t.schema, t.name) in wanted or t.name.startswith("nexus_")
    ]
    if not tables:
        pytest.skip("nexus tables not registered on Base.metadata")
    async with engine.begin() as conn:
        meta = MetaData()
        for table in tables:
            table.to_metadata(meta)
        await conn.execute(CreateSchema("core", if_not_exists=True))
        await conn.run_sync(meta.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def api_client(pg_engine, strict_auth_env):
    """ASGI client with REAL JWT identity (no get_current_user override)."""
    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(auth_router_module.router, prefix="/api/v1/auth")
    test_app.include_router(nexus_persistent.router, prefix="/api/v1")

    async def _override_get_db():
        async with maker() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _identity(maker, org: str):
    """Provision an org + workspace + admin user directly, mint a REAL JWT.

    The signup HTTP path is owned (and rate-limited) by B1's coverage; going
    through it here would exhaust the shared per-process signup bucket when
    the whole suite runs in one process. The JWT is issued by the same
    ``issue_token`` the login path uses and verified through the strict
    pilot-mode path — identity is real, only the provisioning shortcut is
    direct. These identities never authenticate by password.
    """
    from datetime import UTC, datetime, timedelta

    email = _email(org.lower().replace(" ", ""))
    slug = f"{org.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    async with maker() as session:
        org_row = Organization(
            id=uuid7_uuid(),
            name=org,
            slug=slug,
            plan="trial",
            trial_ends_at=now + timedelta(days=7),
            created_at=now,
            updated_at=now,
        )
        session.add(org_row)
        await session.flush()
        ws_row = Workspace(
            id=uuid7_uuid(),
            organization_id=org_row.id,
            name=org,
            slug=slug,
            created_at=now,
            updated_at=now,
        )
        session.add(ws_row)
        await session.flush()
        user_row = User(
            id=uuid7_uuid(),
            workspace_id=ws_row.id,
            email=email,
            full_name=f"{org} Owner",
            password_hash="b3-provisioned",
            role=UserRole.ADMIN,
            is_active=True,
            created_at=now,
            password_changed_at=now,
        )
        session.add(user_row)
        await session.commit()
        token, _ = issue_token(
            user_id=user_row.id,
            workspace_id=ws_row.id,
            role=str(user_row.role),
            email=email,
        )
        return {
            "token": token,
            "user_id": str(user_row.id),
            "workspace_id": str(ws_row.id),
            "email": email,
        }


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _decision(client, ident, **kw) -> dict:
    body = {
        "workspace_id": ident["workspace_id"],
        "proposal_id": f"P-{uuid.uuid4().hex[:8]}",
        "world_state_version": 1,
        "world_state_hash": "test-hash",
        **kw,
    }
    resp = await client.post("/api/v1/nexus/decisions", json=body, headers=_h(ident["token"]))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["decision"]


async def _advance(client, ident, decision_id: str, phase: str, **kw):
    resp = await client.post(
        f"/api/v1/nexus/decisions/{decision_id}/advance",
        params={"workspace_id": ident["workspace_id"]},
        json={"target_phase": phase, **kw},
        headers=_h(ident["token"]),
    )
    return resp


async def _awaiting_approval(client, ident, decision_id: str) -> None:
    for phase in ("simulated", "policy_checked", "awaiting_approval"):
        resp = await _advance(client, ident, decision_id, phase)
        assert resp.status_code == 200, (phase, resp.text)


async def _outbox_events(maker, entity_type: str, entity_id: str) -> list:
    async with maker() as session:
        result = await session.execute(
            select(EventRecordDB).where(
                EventRecordDB.entity_type == entity_type,
                EventRecordDB.entity_id == entity_id,
            )
        )
        return list(result.scalars().all())


def _entity(*, tenant_id: str, workspace_id: str, kind: str, key: str, **state) -> dict:
    return {
        "entity_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "kind": kind,
        "natural_key": key,
        "name": key,
        "source": "b3-test",
        "state": state,
    }


# ─────────────────────────────────────────────────────────────────────
# Risks
# ─────────────────────────────────────────────────────────────────────


class TestRiskRegistry:
    async def test_record_get_list_triage(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Risk Org")
        ws, tok = me["workspace_id"], me["token"]
        ent = f"supplier-{uuid.uuid4().hex[:8]}"

        recorded = await client.post(
            "/api/v1/nexus/risks",
            json={
                "workspace_id": ws,
                "entity_id": ent,
                "entity_kind": "supplier",
                "severity": "HIGH",
                "title": "Supplier capacity fell",
                "world_state_version": 3,
                "risk_score": 0.71,
                "revenue_exposure": 4500000.0,
                "root_causes": ["port congestion"],
            },
            headers=_h(tok),
        )
        assert recorded.status_code == 201, recorded.text
        risk = recorded.json()["data"]["risk"]
        assert risk["severity"] == "HIGH"
        assert risk["status"] == "open"
        assert risk["workspace_id"] == ws

        got = await client.get(
            f"/api/v1/nexus/risks/{risk['risk_id']}",
            params={"workspace_id": ws},
            headers=_h(tok),
        )
        assert got.status_code == 200
        assert got.json()["data"]["risk"]["title"] == "Supplier capacity fell"

        listed = await client.get(
            "/api/v1/nexus/risks", params={"workspace_id": ws}, headers=_h(tok)
        )
        assert listed.status_code == 200
        ids = [r["risk_id"] for r in listed.json()["data"]["risks"]]
        assert risk["risk_id"] in ids

        # Severity filter excludes it at CRITICAL, includes at MEDIUM.
        hi = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": ws, "min_severity": "CRITICAL"},
            headers=_h(tok),
        )
        assert risk["risk_id"] not in [r["risk_id"] for r in hi.json()["data"]["risks"]]
        lo = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": ws, "min_severity": "MEDIUM"},
            headers=_h(tok),
        )
        assert risk["risk_id"] in [r["risk_id"] for r in lo.json()["data"]["risks"]]

        # Re-recording the same entity upserts (no duplicate open row).
        again = await client.post(
            "/api/v1/nexus/risks",
            json={
                "workspace_id": ws,
                "entity_id": ent,
                "entity_kind": "supplier",
                "severity": "CRITICAL",
                "title": "Supplier capacity fell further",
                "world_state_version": 4,
                "risk_score": 0.9,
            },
            headers=_h(tok),
        )
        assert again.status_code == 201
        assert again.json()["data"]["risk"]["risk_id"] == risk["risk_id"]
        assert again.json()["data"]["risk"]["severity"] == "CRITICAL"

        # Triage moves it out of the default (open) listing.
        triaged = await client.patch(
            f"/api/v1/nexus/risks/{risk['risk_id']}",
            json={"workspace_id": ws, "status": "mitigated"},
            headers=_h(tok),
        )
        assert triaged.status_code == 200, triaged.text
        assert triaged.json()["data"]["risk"]["status"] == "mitigated"
        reopened = await client.get(
            "/api/v1/nexus/risks", params={"workspace_id": ws}, headers=_h(tok)
        )
        assert risk["risk_id"] not in [r["risk_id"] for r in reopened.json()["data"]["risks"]]
        everything = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": ws, "status": "all"},
            headers=_h(tok),
        )
        assert risk["risk_id"] in [r["risk_id"] for r in everything.json()["data"]["risks"]]

    async def test_record_validation(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "RiskVal Org")
        ws, tok = me["workspace_id"], me["token"]
        base = {
            "workspace_id": ws,
            "entity_id": f"e-{uuid.uuid4().hex[:8]}",
            "entity_kind": "supplier",
            "severity": "HIGH",
            "title": "t",
            "world_state_version": 1,
        }
        bad_sev = await client.post(
            "/api/v1/nexus/risks", json={**base, "severity": "EXTREME"}, headers=_h(tok)
        )
        assert bad_sev.status_code == 400
        bad_score = await client.post(
            "/api/v1/nexus/risks", json={**base, "risk_score": 9.9}, headers=_h(tok)
        )
        assert bad_score.status_code == 400
        bad_status = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": ws, "status": "vibing"},
            headers=_h(tok),
        )
        assert bad_status.status_code == 400

    async def test_cross_workspace_isolation(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker, "RiskA Org")
        b = await _identity(maker, "RiskB Org")
        created = await client.post(
            "/api/v1/nexus/risks",
            json={
                "workspace_id": a["workspace_id"],
                "entity_id": f"e-{uuid.uuid4().hex[:8]}",
                "entity_kind": "plant",
                "severity": "LOW",
                "title": "A risk",
                "world_state_version": 1,
            },
            headers=_h(a["token"]),
        )
        risk_id = created.json()["data"]["risk"]["risk_id"]

        # B asking in A's workspace: 403 (workspace gate).
        forbidden = await client.get(
            f"/api/v1/nexus/risks/{risk_id}",
            params={"workspace_id": a["workspace_id"]},
            headers=_h(b["token"]),
        )
        assert forbidden.status_code == 403
        # B asking in B's workspace for A's row: 404 (no existence oracle).
        missing = await client.get(
            f"/api/v1/nexus/risks/{risk_id}",
            params={"workspace_id": b["workspace_id"]},
            headers=_h(b["token"]),
        )
        assert missing.status_code == 404
        # B's own listing never contains A's row.
        listed = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": b["workspace_id"]},
            headers=_h(b["token"]),
        )
        assert risk_id not in [r["risk_id"] for r in listed.json()["data"]["risks"]]
        # B cannot triage A's row either.
        triage = await client.patch(
            f"/api/v1/nexus/risks/{risk_id}",
            json={"workspace_id": b["workspace_id"], "status": "closed"},
            headers=_h(b["token"]),
        )
        assert triage.status_code == 404

    async def test_forged_token_is_401(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Risk401 Org")
        resp = await client.get(
            "/api/v1/nexus/risks",
            params={"workspace_id": me["workspace_id"]},
            headers={"Authorization": "Bearer forged-token"},
        )
        assert resp.status_code == 401

    async def test_risk_changed_event_emitted(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "RiskEvt Org")
        created = await client.post(
            "/api/v1/nexus/risks",
            json={
                "workspace_id": me["workspace_id"],
                "entity_id": f"e-{uuid.uuid4().hex[:8]}",
                "entity_kind": "port",
                "severity": "WATCH",
                "title": "watch",
                "world_state_version": 1,
            },
            headers=_h(me["token"]),
        )
        risk_id = created.json()["data"]["risk"]["risk_id"]
        events = await _outbox_events(maker, "risk", risk_id)
        assert [e.event_type for e in events] == ["risk_changed"]


# ─────────────────────────────────────────────────────────────────────
# Signals
# ─────────────────────────────────────────────────────────────────────


class TestCanonicalSignals:
    async def test_signals_envelope(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Sig Org")
        resp = await client.get(
            "/api/v1/nexus/signals",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["workspace_id"] == me["workspace_id"]
        assert isinstance(data["signals"], list)
        assert data["count"] == len(data["signals"])
        assert "snapshot_version" in data and "snapshot_hash" in data
        assert "request_id" in resp.json() and "timestamp" in resp.json()

    async def test_signals_foreign_workspace_403(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker, "SigA Org")
        b = await _identity(maker, "SigB Org")
        resp = await client.get(
            "/api/v1/nexus/signals",
            params={"workspace_id": a["workspace_id"]},
            headers=_h(b["token"]),
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────


class TestScenarios:
    def _mutations(self, supplier_id: str) -> list[dict]:
        return [
            {
                "kind": "supplier_failure",
                "target_entity_id": supplier_id,
                "parameters": {"availability_pct": 0.2},
            }
        ]

    async def test_create_get_list(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Scn Org")
        ws, tok = me["workspace_id"], me["token"]
        supplier_id = str(uuid.uuid4())
        created = await client.post(
            "/api/v1/nexus/scenarios",
            json={
                "workspace_id": ws,
                "name": "Port closure what-if",
                "world_state_version": 7,
                "description": "what if the port closes",
                "mutations": self._mutations(supplier_id),
            },
            headers=_h(tok),
        )
        assert created.status_code == 201, created.text
        scn = created.json()["data"]["scenario"]
        assert scn["status"] == "pending"
        assert len(scn["mutations"]) == 1

        got = await client.get(
            f"/api/v1/nexus/scenarios/{scn['scenario_id']}",
            params={"workspace_id": ws},
            headers=_h(tok),
        )
        assert got.status_code == 200
        assert got.json()["data"]["scenario"]["name"] == "Port closure what-if"

        listed = await client.get(
            "/api/v1/nexus/scenarios", params={"workspace_id": ws}, headers=_h(tok)
        )
        assert scn["scenario_id"] in [s["scenario_id"] for s in listed.json()["data"]["scenarios"]]

    async def test_create_bad_mutation_400(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "ScnBad Org")
        resp = await client.post(
            "/api/v1/nexus/scenarios",
            json={
                "workspace_id": me["workspace_id"],
                "name": "bad",
                "world_state_version": 1,
                "mutations": [{"kind": "teleport", "target_entity_id": str(uuid.uuid4())}],
            },
            headers=_h(me["token"]),
        )
        assert resp.status_code == 400

    async def test_simulate_deterministic_kpis(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Sim Org")
        ws, tok, tenant = me["workspace_id"], me["token"], me["user_id"]

        supplier = _entity(
            tenant_id=tenant,
            workspace_id=ws,
            kind="supplier",
            key="SUP-1",
            capacity_pct=100.0,
            lead_time_days=9.0,
        )
        order1 = _entity(
            tenant_id=tenant,
            workspace_id=ws,
            kind="sales_order",
            key="SO-1",
            revenue=1000.0,
            sla_risk_pct=0.2,
        )
        order2 = _entity(
            tenant_id=tenant,
            workspace_id=ws,
            kind="sales_order",
            key="SO-2",
            revenue=3000.0,
            sla_risk_pct=0.4,
        )
        created = await client.post(
            "/api/v1/nexus/scenarios",
            json={
                "workspace_id": ws,
                "name": "supplier shock",
                "world_state_version": 2,
                "mutations": self._mutations(supplier["entity_id"]),
            },
            headers=_h(tok),
        )
        scenario_id = created.json()["data"]["scenario"]["scenario_id"]

        simulated = await client.post(
            f"/api/v1/nexus/scenarios/{scenario_id}/simulate",
            json={
                "workspace_id": ws,
                "entities": [supplier, order1, order2],
                "world_state_version": 2,
            },
            headers=_h(tok),
        )
        assert simulated.status_code == 200, simulated.text
        payload = simulated.json()["data"]
        assert payload["scenario"]["status"] == "completed"
        kpis = payload["result"]["kpis"]
        # Deterministic twin core: revenue sums, SLA averages, mutation applied.
        assert kpis["revenue_at_risk"] == 4000.0
        assert kpis["sla_breach_pct"] == 0.3
        assert payload["result"]["affected_entity_ids"] == [supplier["entity_id"]]
        assert payload["result"]["world_state_version"] == 2
        assert payload["scenario"]["kpi_results"]["revenue_at_risk"] == 4000.0

        # Persisted: a fresh GET sees the completed run.
        got = await client.get(
            f"/api/v1/nexus/scenarios/{scenario_id}",
            params={"workspace_id": ws},
            headers=_h(tok),
        )
        assert got.json()["data"]["scenario"]["status"] == "completed"

        events = await _outbox_events(maker, "scenario", scenario_id)
        assert [e.event_type for e in events] == ["scenario_completed"]

    async def test_simulate_empty_snapshot_is_honest(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "SimEmpty Org")
        created = await client.post(
            "/api/v1/nexus/scenarios",
            json={
                "workspace_id": me["workspace_id"],
                "name": "empty world",
                "world_state_version": 1,
                "mutations": self._mutations(str(uuid.uuid4())),
            },
            headers=_h(me["token"]),
        )
        scenario_id = created.json()["data"]["scenario"]["scenario_id"]
        simulated = await client.post(
            f"/api/v1/nexus/scenarios/{scenario_id}/simulate",
            json={"workspace_id": me["workspace_id"], "entities": []},
            headers=_h(me["token"]),
        )
        assert simulated.status_code == 200
        result = simulated.json()["data"]["result"]
        assert result["kpis"]["revenue_at_risk"] == 0.0
        assert len(result["assumption_notes"]) == 1
        assert "skipped" in result["assumption_notes"][0]

    async def test_simulate_isolation(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker, "SimA Org")
        b = await _identity(maker, "SimB Org")
        created = await client.post(
            "/api/v1/nexus/scenarios",
            json={
                "workspace_id": a["workspace_id"],
                "name": "a-private",
                "world_state_version": 1,
            },
            headers=_h(a["token"]),
        )
        scenario_id = created.json()["data"]["scenario"]["scenario_id"]
        missing = await client.get(
            f"/api/v1/nexus/scenarios/{scenario_id}",
            params={"workspace_id": b["workspace_id"]},
            headers=_h(b["token"]),
        )
        assert missing.status_code == 404
        forbidden = await client.post(
            f"/api/v1/nexus/scenarios/{scenario_id}/simulate",
            json={"workspace_id": a["workspace_id"], "entities": []},
            headers=_h(b["token"]),
        )
        assert forbidden.status_code == 403
        not_found = await client.post(
            "/api/v1/nexus/scenarios/scn-nope/simulate",
            json={"workspace_id": b["workspace_id"], "entities": []},
            headers=_h(b["token"]),
        )
        assert not_found.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# Evidence
# ─────────────────────────────────────────────────────────────────────


class TestEvidence:
    async def test_nodes_edges_graph(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Evd Org")
        dec = await _decision(client, me)
        did = dec["decision_id"]

        risk_node = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/nodes",
            json={
                "node_type": "risk",
                "label": "Supplier risk R-1",
                "payload": {"risk_id": "R-1"},
                "source_entity_id": "SUP-1",
            },
            headers=_h(me["token"]),
        )
        assert risk_node.status_code == 201, risk_node.text
        n1 = risk_node.json()["data"]["node"]
        assert n1["checksum"]  # server-computed when omitted

        claim_node = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/nodes",
            json={"node_type": "claim", "label": "Mitigation works", "checksum": "abc123"},
            headers=_h(me["token"]),
        )
        n2 = claim_node.json()["data"]["node"]
        assert n2["checksum"] == "abc123"  # caller-supplied preserved

        edge = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/edges",
            json={
                "from_node_id": n1["node_id"],
                "to_node_id": n2["node_id"],
                "relation": "supports",
            },
            headers=_h(me["token"]),
        )
        assert edge.status_code == 201, edge.text

        dupe = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/edges",
            json={
                "from_node_id": n1["node_id"],
                "to_node_id": n2["node_id"],
                "relation": "supports",
            },
            headers=_h(me["token"]),
        )
        assert dupe.status_code == 409

        bad_rel = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/edges",
            json={
                "from_node_id": n1["node_id"],
                "to_node_id": n2["node_id"],
                "relation": "vibes_with",
            },
            headers=_h(me["token"]),
        )
        assert bad_rel.status_code == 400

        bad_type = await client.post(
            f"/api/v1/nexus/decisions/{did}/evidence/nodes",
            json={"node_type": "rumor", "label": "x"},
            headers=_h(me["token"]),
        )
        assert bad_type.status_code == 400

        graph = await client.get(f"/api/v1/nexus/decisions/{did}/evidence", headers=_h(me["token"]))
        assert graph.status_code == 200
        data = graph.json()["data"]
        assert data["node_count"] == 2
        assert data["edge_count"] == 1

        events = await _outbox_events(maker, "evidence_node", n1["node_id"])
        assert [e.event_type for e in events] == ["evidence_appended"]

    async def test_edge_across_decisions_rejected(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "EvdX Org")
        d1 = await _decision(client, me)
        d2 = await _decision(client, me)
        n1 = (
            await client.post(
                f"/api/v1/nexus/decisions/{d1['decision_id']}/evidence/nodes",
                json={"node_type": "claim", "label": "one"},
                headers=_h(me["token"]),
            )
        ).json()["data"]["node"]
        n2 = (
            await client.post(
                f"/api/v1/nexus/decisions/{d2['decision_id']}/evidence/nodes",
                json={"node_type": "claim", "label": "two"},
                headers=_h(me["token"]),
            )
        ).json()["data"]["node"]
        resp = await client.post(
            f"/api/v1/nexus/decisions/{d1['decision_id']}/evidence/edges",
            json={
                "from_node_id": n1["node_id"],
                "to_node_id": n2["node_id"],
                "relation": "informs",
            },
            headers=_h(me["token"]),
        )
        assert resp.status_code == 404

    async def test_evidence_cross_workspace_404(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker, "EvdA Org")
        b = await _identity(maker, "EvdB Org")
        dec = await _decision(client, a)
        resp = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/evidence", headers=_h(b["token"])
        )
        assert resp.status_code in (403, 404)
        posted = await client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/evidence/nodes",
            json={"node_type": "claim", "label": "intrusion"},
            headers=_h(b["token"]),
        )
        assert posted.status_code in (403, 404)


# ─────────────────────────────────────────────────────────────────────
# Approvals (B8) + lifecycle evidence
# ─────────────────────────────────────────────────────────────────────


class TestApprovalTrail:
    async def test_approve_writes_identity_trail(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Apr Org")
        dec = await _decision(client, me)
        await _awaiting_approval(client, me, dec["decision_id"])
        resp = await _advance(
            client,
            me,
            dec["decision_id"],
            "approved",
            reason="looks good",
            metadata={"policy_checks": {"budget": "pass"}},
        )
        assert resp.status_code == 200, resp.text

        approvals = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/approvals",
            headers=_h(me["token"]),
        )
        assert approvals.status_code == 200
        rows = approvals.json()["data"]["approvals"]
        assert len(rows) == 1
        row = rows[0]
        assert row["approver_id"] == me["user_id"]
        assert row["approver_role"] == "admin"
        assert row["approved"] is True
        assert row["rejection_reason"] is None
        assert row["policy_checks"] == {"budget": "pass"}

        # The row pins the exact decision hash it approved.
        current = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        assert row["decision_hash"] == current.json()["data"]["decision"]["deterministic_hash"]

        # ... and an approval node self-assembled in the evidence DAG.
        graph = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/evidence",
            headers=_h(me["token"]),
        )
        types = [n["node_type"] for n in graph.json()["data"]["nodes"]]
        assert types == ["approval"]

    async def test_reject_records_reason(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Rej Org")
        dec = await _decision(client, me)
        resp = await _advance(client, me, dec["decision_id"], "rejected", reason="too risky")
        assert resp.status_code == 200, resp.text
        approvals = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/approvals",
            headers=_h(me["token"]),
        )
        rows = approvals.json()["data"]["approvals"]
        assert len(rows) == 1
        assert rows[0]["approved"] is False
        assert rows[0]["rejection_reason"] == "too risky"

    async def test_execute_authorizes_and_appends_nodes(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Exe Org")
        dec = await _decision(client, me)
        await _awaiting_approval(client, me, dec["decision_id"])
        approved = await _advance(client, me, dec["decision_id"], "approved")
        assert approved.status_code == 200

        executed = await client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/execute",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        assert executed.status_code == 200, executed.text

        approvals = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/approvals",
            headers=_h(me["token"]),
        )
        rows = approvals.json()["data"]["approvals"]
        assert len(rows) == 2  # approved + authorized
        assert all(r["approved"] is True for r in rows)
        assert all(r["approver_role"] == "admin" for r in rows)

        graph = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/evidence",
            headers=_h(me["token"]),
        )
        types = sorted(n["node_type"] for n in graph.json()["data"]["nodes"])
        assert types == ["approval", "approval", "execution"]

    async def test_outcome_appends_outcome_node(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, "Out Org")
        dec = await _decision(client, me)
        await _awaiting_approval(client, me, dec["decision_id"])
        await _advance(client, me, dec["decision_id"], "approved")
        executed = await client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/execute",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        assert executed.status_code == 200

        outcome = await client.post(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/outcome",
            params={"workspace_id": me["workspace_id"]},
            json={"outcome_status": "succeeded", "actual_nev": 1200.5},
            headers=_h(me["token"]),
        )
        assert outcome.status_code == 200, outcome.text

        graph = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/evidence",
            headers=_h(me["token"]),
        )
        types = sorted(n["node_type"] for n in graph.json()["data"]["nodes"])
        assert types == ["approval", "approval", "execution", "outcome"]

    async def test_approvals_cross_workspace_404(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker, "AprA Org")
        b = await _identity(maker, "AprB Org")
        dec = await _decision(client, a)
        resp = await client.get(
            f"/api/v1/nexus/decisions/{dec['decision_id']}/approvals", headers=_h(b["token"])
        )
        assert resp.status_code in (403, 404)


# ─────────────────────────────────────────────────────────────────────
# Restart persistence (PG is truth; services are stateless)
# ─────────────────────────────────────────────────────────────────────


class TestRestartPersistence:
    async def test_fresh_service_reads_pg_truth(self, api_client) -> None:
        from app.modules.nexus_spine.p0_migration import AuthoritativeRegistryService

        client, maker = api_client
        me = await _identity(maker, "Rst Org")
        created = await client.post(
            "/api/v1/nexus/risks",
            json={
                "workspace_id": me["workspace_id"],
                "entity_id": f"e-{uuid.uuid4().hex[:8]}",
                "entity_kind": "supplier",
                "severity": "MEDIUM",
                "title": "restart-probe",
                "world_state_version": 1,
            },
            headers=_h(me["token"]),
        )
        risk_id = created.json()["data"]["risk"]["risk_id"]

        # A brand-new service instance over a brand-new session sees it:
        # nothing lives in process memory.
        fresh = AuthoritativeRegistryService()
        async with maker() as session:
            risk = await fresh.get_risk(session, risk_id)
        assert risk["title"] == "restart-probe"
