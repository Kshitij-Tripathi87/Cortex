"""The product must work when its database role is an ordinary one.

Migrations 002 and 003 put forced row-level security on fourteen tables, but
the application never supplied what the policies compare against. A superuser
skips policies, so the test suite and the compose files never noticed. Under
any other role (a managed database, a least-privilege role) the first upload
failed with ``new row violates row-level security policy for table
"source_batches"``. Migration 026 removes those policies.

The first test drives upload -> prepare -> review -> publish and then reads
the result back, with every database connection signed in as a freshly
created role that is neither a superuser nor exempt from row security. The
second test fails if a later migration switches row security on for a table
without anyone deciding how the application satisfies it.

Both need PostgreSQL and skip without it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateSchema

from app.api.v1 import audit, graph, sources
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext
from app.modules.access.models import Organization, Workspace
from app.modules.audit.models import AuditEvent
from app.modules.compiler.models import (
    ConflictResolution,
    EvidenceClaim,
    EvidenceConflict,
    ReadinessAssessment,
)
from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphWriteEvent,
    ProvenanceLink,
)
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile

MODELS = (
    Organization,
    Workspace,
    SourceBatch,
    SourceFile,
    SourceColumnProfile,
    EvidenceClaim,
    EvidenceConflict,
    ConflictResolution,
    ReadinessAssessment,
    GraphNode,
    GraphEdge,
    GraphSnapshot,
    GraphWriteEvent,
    ProvenanceLink,
    AuditEvent,
)

SUPPLIERS_CSV = (
    b"supplier_id,supplier_name,country\n"
    b"S-100,Acme Metals GmbH,DE\n"
    b"S-101,Bharat Castings Pvt Ltd,IN\n"
    b"S-102,Nordic Seals AB,SE\n"
)

# Tables that may carry row-level security, each with the reason the
# application can read and write it as an ordinary role. Empty on purpose:
# see ``docs/architecture/TENANT_ISOLATION.md`` before adding one.
ROW_SECURITY_THE_APPLICATION_SATISFIES: dict[str, str] = {}


class _MemoryStorage:
    """Stand-in for the file store; the database is the subject of this test."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.objects[key] = bytes(data)

    def get_object(self, key: str) -> bytes:
        return self.objects[key]


async def _owner_engine(request: Any) -> AsyncEngine:
    try:
        engine = create_async_engine(request.config.postgres_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:  # any connection failure means "no PostgreSQL here"
        pytest.skip(f"PostgreSQL not available: {exc}")
    return engine


@pytest.fixture
async def ordinary_role(request: Any) -> AsyncGenerator[tuple[AsyncEngine, str]]:
    """An engine whose connections sign in as a new, unprivileged role."""
    owner = await _owner_engine(request)
    role = f"cortex_ordinary_{uuid4().hex[:12]}"
    password = uuid4().hex
    async with owner.begin() as conn:
        may_create_roles = (
            await conn.execute(
                text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar()
    if not may_create_roles:
        await owner.dispose()
        pytest.skip("the test database user may not create roles")

    # A migrated database (CI) already has these tables; create_all is then a no-op.
    metadata = MetaData()
    for model in MODELS:
        model.__table__.to_metadata(metadata)
    schemas = sorted({table.schema or "public" for table in metadata.tables.values()})
    async with owner.begin() as conn:
        await conn.execute(CreateSchema("core", if_not_exists=True))
        await conn.run_sync(metadata.create_all)
        await conn.execute(
            text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS")
        )
        for schema in schemas:
            await conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
            await conn.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} "
                    f"TO {role}"
                )
            )
            await conn.execute(
                text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}")
            )

    url = make_url(request.config.postgres_url).set(username=role, password=password)
    engine = create_async_engine(url, echo=False)
    try:
        yield engine, role
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f"DROP OWNED BY {role}"))
            await conn.execute(text(f"DROP ROLE {role}"))
        await owner.dispose()


@pytest.fixture
async def site(
    ordinary_role: tuple[AsyncEngine, str], monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[AsyncClient, str, async_sessionmaker[AsyncSession]]]:
    engine, _role = ordinary_role
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(graph.router, prefix="/api/v1/graph")
    app.include_router(audit.router, prefix="/api/v1/audit")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        # One session per request, as in production.
        async with sessions() as session:
            yield session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    # Override the dependency object each router captured at import.
    for module in (sources, graph, audit):
        app.dependency_overrides[module.get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, workspace_id, sessions


async def test_upload_review_and_publish_work_as_an_ordinary_role(
    ordinary_role: tuple[AsyncEngine, str],
    site: tuple[AsyncClient, str, async_sessionmaker[AsyncSession]],
) -> None:
    engine, role = ordinary_role
    client, workspace_id, sessions = site
    query = {"workspace_id": workspace_id}

    # The connections really are the ordinary role: nothing here is skipped
    # because of who is asking.
    async with engine.connect() as conn:
        who = (
            await conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    assert tuple(who) == (role, False, False)

    upload = await client.post(
        "/api/v1/sources/upload",
        data={"workspace_id": workspace_id, "source_system_hint": "erp"},
        files={"file": ("suppliers.csv", SUPPLIERS_CSV, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    batch_id = str(upload.json()["batch_id"])

    prepared = await client.post(f"/api/v1/sources/batches/{batch_id}/compile", params=query)
    assert prepared.status_code == 200, prepared.text

    claims = await client.get(
        f"/api/v1/sources/batches/{batch_id}/claims", params={**query, "limit": 500}
    )
    assert claims.status_code == 200, claims.text
    assert len(claims.json()) == 3 * 3
    for claim in claims.json():
        review = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim['claim_id']}/review",
            params=query,
            json={
                "decision": "accepted",
                "rationale": "Checked against the supplier master.",
                "canonical_entity": "Supplier",
                "canonical_field": claim["source_column"],
            },
        )
        assert review.status_code == 200, review.text

    published = await client.post(f"/api/v1/graph/batches/{batch_id}/compile", params=query)
    assert published.status_code == 200, published.text

    # What was published can be read back through the API ...
    nodes = await client.get("/api/v1/graph/nodes", params=query)
    assert nodes.status_code == 200, nodes.text
    assert sorted(node["entity_id"] for node in nodes.json()) == ["S-100", "S-101", "S-102"]
    snapshots = await client.get("/api/v1/graph/snapshots", params=query)
    assert snapshots.status_code == 200, snapshots.text
    assert [snapshot["version"] for snapshot in snapshots.json()] == [1]
    events = await client.get("/api/v1/audit", params=query)
    assert events.status_code == 200, events.text
    assert events.json(), "the activity log of the workspace is empty"

    # ... and is in the tables, seen by the same ordinary role.
    async with sessions() as session:
        for model, expected in (
            (SourceBatch, 1),
            (SourceFile, 1),
            (EvidenceClaim, 9),
            (GraphNode, 3),
            (GraphSnapshot, 1),
        ):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
            assert count == expected, model.__tablename__
        logged = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
        )
        assert logged and logged > 0


async def test_no_table_carries_row_security_the_application_does_not_satisfy(
    request: Any,
) -> None:
    owner = await _owner_engine(request)
    try:
        async with owner.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT n.nspname || '.' || c.relname "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relkind = 'r' AND c.relrowsecurity "
                        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "ORDER BY 1"
                    )
                )
            ).all()
    finally:
        await owner.dispose()
    unexplained = [name for (name,) in rows if name not in ROW_SECURITY_THE_APPLICATION_SATISFIES]
    assert not unexplained, (
        f"Row-level security is switched on for {', '.join(unexplained)}, but nothing in the "
        "application supplies what its policies compare against. Under an ordinary database "
        "role those tables cannot be written. Either make the application satisfy the policy "
        "(and cover the table in the test above), or do not enable it. "
        "See docs/architecture/TENANT_ISOLATION.md."
    )
