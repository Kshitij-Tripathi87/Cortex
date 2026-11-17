"""One value per field of a record reaches the published graph.

Regressions covered here, all reproduced over HTTP before the fix:

* two rows of a file described the same supplier with different values, no
  conflict was raised (the page never sends an entity key) and publishing kept
  the first row without telling anyone;
* when a conflict did exist, "approve" and "reject" answered 409 because they
  only worked on pending claims while conflicts only form between accepted ones;
* a value whose claim the reviewer rejected was published anyway.

The rule now: the record a claim describes is identified by the primary-key
cell of its own row; different accepted values for one field of one record
block publishing until a reviewer keeps one (the others are superseded),
rejects them, or suppresses the finding; and only accepted cells are published.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import graph, sources
from app.common.enums import ClaimState
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.compiler.models import (
    ConflictResolution,  # noqa: F401
    EvidenceClaim,
    EvidenceConflict,
    ReadinessAssessment,  # noqa: F401
)
from app.modules.compiler.service import resolve_conflict
from app.modules.graph.entity_keys import canonical_column_name, infer_entity_type
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot  # noqa: F401
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401

# Rows 1 and 2 describe supplier S-1 with a different name and country.
DUPLICATE_SUPPLIER = (
    b"supplier_id,supplier_name,country\n"
    b"S-1,Acme Metals,DE\n"
    b"S-1,Acme Metals GmbH,AT\n"
    b"S-2,Borealis Plastics,SE\n"
)


class _MemoryStorage:
    """Stand-in for the S3 client: keeps uploaded bytes in memory."""

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


class Intake:
    def __init__(self, client: AsyncClient, workspace_id: str) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.query = {"workspace_id": workspace_id}

    async def prepare(self, name: str, content: bytes) -> str:
        upload = await self.client.post(
            "/api/v1/sources/upload",
            data={"workspace_id": self.workspace_id, "source_system_hint": "erp"},
            files={"file": (name, content, "text/csv")},
        )
        assert upload.status_code == 200, upload.text
        batch_id = str(upload.json()["batch_id"])
        prepared = await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/compile", params=self.query
        )
        assert prepared.status_code == 200, prepared.text
        return batch_id

    async def claims(self, batch_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"/api/v1/sources/batches/{batch_id}/claims", params={**self.query, "limit": 500}
        )
        assert response.status_code == 200, response.text
        items: list[dict[str, Any]] = response.json()
        return items

    async def review(
        self, batch_id: str, claim: dict[str, Any], decision: str, entity: str
    ) -> dict[str, Any]:
        # Exactly what the evidence page sends: no entity key.
        body: dict[str, Any] = {"decision": decision, "rationale": "Checked against the ERP."}
        if decision == "accepted":
            body["canonical_entity"] = entity
            body["canonical_field"] = canonical_column_name(claim["source_column"], entity)
        response = await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim['claim_id']}/review",
            params=self.query,
            json=body,
        )
        assert response.status_code == 200, response.text
        reviewed: dict[str, Any] = response.json()
        return reviewed

    async def accept_all(
        self, batch_id: str, content: bytes, *, reject: set[tuple[int, str]] | None = None
    ) -> None:
        entity = infer_entity_type(content.decode().splitlines()[0].split(","))
        assert entity is not None
        for claim in await self.claims(batch_id):
            cell = (claim["row_number"], claim["source_column"])
            decision = "rejected" if reject and cell in reject else "accepted"
            await self.review(batch_id, claim, decision, entity)

    async def conflicts(self, batch_id: str) -> dict[str, dict[str, Any]]:
        response = await self.client.get(
            f"/api/v1/sources/batches/{batch_id}/conflicts", params=self.query
        )
        assert response.status_code == 200, response.text
        return {str(item["canonical_field"]): item for item in response.json()}

    async def claim_of_row(self, batch_id: str, conflict: dict[str, Any], row_number: int) -> str:
        by_id = {claim["claim_id"]: claim for claim in await self.claims(batch_id)}
        return next(
            claim_id
            for claim_id in conflict["claim_ids"]
            if by_id[claim_id]["row_number"] == row_number
        )

    async def resolve(
        self, conflict: dict[str, Any], action: str, selected_claim_id: str | None = None
    ) -> Any:
        return await self.client.post(
            f"/api/v1/sources/conflicts/{conflict['conflict_id']}/resolve",
            params=self.query,
            json={
                "selected_claim_id": selected_claim_id,
                "action": action,
                "rationale": "Confirmed with the supplier master owner.",
            },
        )

    async def publish(self, batch_id: str) -> Any:
        return await self.client.post(
            f"/api/v1/graph/batches/{batch_id}/compile", params=self.query
        )

    async def states(self, batch_id: str) -> dict[tuple[int, str], str]:
        return {
            (claim["row_number"], claim["source_column"]): claim["claim_state"]
            for claim in await self.claims(batch_id)
        }


@pytest.fixture
async def intake(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[Intake]:
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(graph.router, prefix="/api/v1/graph")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    for module in (sources, graph):
        app.dependency_overrides[module.get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Intake(client, workspace_id)


async def _published(db_session: AsyncSession, workspace_id: str) -> dict[str, dict[str, Any]]:
    nodes = await db_session.scalars(
        select(GraphNode).where(GraphNode.workspace_id == workspace_id)
    )
    return {node.entity_id: dict(node.attributes) for node in nodes.all()}


async def test_rows_that_disagree_about_one_record_raise_a_blocking_conflict(
    intake: Intake, db_session: AsyncSession
) -> None:
    batch_id = await intake.prepare("suppliers.csv", DUPLICATE_SUPPLIER)
    await intake.accept_all(batch_id, DUPLICATE_SUPPLIER)

    conflicts = await intake.conflicts(batch_id)

    # The page sent no entity key: the server took it from each row's supplier_id.
    assert set(conflicts) == {"supplier_name", "country"}
    assert all(item["status"] == "open" and item["blocking"] for item in conflicts.values())
    assert all(len(item["claim_ids"]) == 2 for item in conflicts.values())
    # The supplier_id cells agree ("S-1" twice), so they are not a conflict.
    assert "supplier_id" not in conflicts

    blocked = await intake.publish(batch_id)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["blocking_conflict_count"] == 2
    assert await _published(db_session, intake.workspace_id) == {}


async def test_a_row_accepted_later_joins_the_conflict_still_under_review(intake: Intake) -> None:
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-1,Acme Metals,DE\n"
        b"S-1,Acme Metals,AT\n"
        b"S-1,Acme Metals,CH\n"
    )
    batch_id = await intake.prepare("suppliers.csv", content)
    claims = sorted(await intake.claims(batch_id), key=lambda claim: claim["row_number"])

    for claim in claims:
        if claim["row_number"] <= 2:
            await intake.review(batch_id, claim, "accepted", "Supplier")
    opened = (await intake.conflicts(batch_id))["country"]
    assert len(opened["claim_ids"]) == 2

    # Row 3 brings a third value while the finding is still open.
    for claim in claims:
        if claim["row_number"] == 3:
            await intake.review(batch_id, claim, "accepted", "Supplier")
    listed = (
        await intake.client.get(
            f"/api/v1/sources/batches/{batch_id}/conflicts", params=intake.query
        )
    ).json()
    # One finding per field of a record, now covering all three rows.
    assert [item["conflict_id"] for item in listed] == [opened["conflict_id"]]
    assert len(listed[0]["claim_ids"]) == 3

    # Keeping one value withdraws both of the others.
    kept = await intake.claim_of_row(batch_id, listed[0], 3)
    assert (await intake.resolve(listed[0], "approved", kept)).status_code == 200
    states = await intake.states(batch_id)
    assert [states[(row, "country")] for row in (1, 2, 3)] == [
        "superseded",
        "superseded",
        "accepted",
    ]


async def test_keeping_one_claim_supersedes_the_others_and_publishes_that_value(
    intake: Intake, db_session: AsyncSession
) -> None:
    batch_id = await intake.prepare("suppliers.csv", DUPLICATE_SUPPLIER)
    await intake.accept_all(batch_id, DUPLICATE_SUPPLIER)
    conflicts = await intake.conflicts(batch_id)

    # Keep row 2's name and row 1's country.
    name = await intake.resolve(
        conflicts["supplier_name"],
        "approved",
        await intake.claim_of_row(batch_id, conflicts["supplier_name"], 2),
    )
    country = await intake.resolve(
        conflicts["country"],
        "approved",
        await intake.claim_of_row(batch_id, conflicts["country"], 1),
    )
    assert name.status_code == 200, name.text
    assert country.status_code == 200, country.text

    states = await intake.states(batch_id)
    assert states[(2, "supplier_name")] == "accepted"
    assert states[(1, "supplier_name")] == "superseded"
    assert states[(1, "country")] == "accepted"
    assert states[(2, "country")] == "superseded"
    assert {item["status"] for item in (await intake.conflicts(batch_id)).values()} == {"resolved"}

    published = await intake.publish(batch_id)
    assert published.status_code == 200, published.text
    assert await _published(db_session, intake.workspace_id) == {
        "S-1": {"supplier_id": "S-1", "supplier_name": "Acme Metals GmbH", "country": "DE"},
        "S-2": {"supplier_id": "S-2", "supplier_name": "Borealis Plastics", "country": "SE"},
    }

    # A decided conflict cannot be decided again.
    again = await intake.resolve(conflicts["country"], "rejected")
    assert again.status_code == 409
    assert again.json()["detail"] == "Conflict is already resolved"


async def test_rejecting_every_claim_publishes_neither_value(
    intake: Intake, db_session: AsyncSession
) -> None:
    batch_id = await intake.prepare("suppliers.csv", DUPLICATE_SUPPLIER)
    await intake.accept_all(batch_id, DUPLICATE_SUPPLIER)
    conflicts = await intake.conflicts(batch_id)

    assert (await intake.resolve(conflicts["country"], "rejected")).status_code == 200
    assert (
        await intake.resolve(
            conflicts["supplier_name"],
            "approved",
            await intake.claim_of_row(batch_id, conflicts["supplier_name"], 1),
        )
    ).status_code == 200

    states = await intake.states(batch_id)
    assert states[(1, "country")] == states[(2, "country")] == "rejected"
    assert (await intake.publish(batch_id)).status_code == 200
    supplier = (await _published(db_session, intake.workspace_id))["S-1"]
    # Neither DE nor AT was accepted, so the record has no country at all.
    assert supplier == {"supplier_id": "S-1", "supplier_name": "Acme Metals"}


async def test_rejecting_one_claim_closes_the_conflict_once_the_rest_agree(
    intake: Intake, db_session: AsyncSession
) -> None:
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-1,Acme Metals,DE\n"
        b"S-1,Acme Metals,AT\n"
        b"S-1,Acme Metals,DE\n"
        b"S-1,Acme Metals,CH\n"
    )
    batch_id = await intake.prepare("suppliers.csv", content)
    await intake.accept_all(batch_id, content)

    listed = (
        await intake.client.get(
            f"/api/v1/sources/batches/{batch_id}/conflicts", params=intake.query
        )
    ).json()
    # One finding for the field, however many rows joined the disagreement. A
    # separate finding per newly accepted row would leave conflicts that
    # overlap and cannot all be closed.
    assert [
        (item["canonical_field"], item["status"], len(item["claim_ids"])) for item in listed
    ] == [("country", "open", 4)]
    conflict = listed[0]

    first = await intake.resolve(
        conflict, "rejected", await intake.claim_of_row(batch_id, conflict, 2)
    )
    assert first.status_code == 200, first.text
    # DE (twice) and CH are still accepted: the conflict stays open and blocks.
    assert (await intake.conflicts(batch_id))["country"]["status"] == "open"
    assert (await intake.publish(batch_id)).status_code == 409

    second = await intake.resolve(
        conflict, "rejected", await intake.claim_of_row(batch_id, conflict, 4)
    )
    assert second.status_code == 200, second.text
    # Only DE is left, and both remaining claims say it.
    assert (await intake.conflicts(batch_id))["country"]["status"] == "resolved"
    assert (await intake.publish(batch_id)).status_code == 200
    assert (await _published(db_session, intake.workspace_id))["S-1"]["country"] == "DE"


async def test_a_suppressed_disagreement_is_not_raised_again_by_a_repeated_value(
    intake: Intake,
) -> None:
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-1,Acme Metals,DE\n"
        b"S-1,Acme Metals,AT\n"
        b"S-1,Acme Metals,DE\n"
        b"S-1,Acme Metals,CH\n"
    )
    batch_id = await intake.prepare("suppliers.csv", content)
    entity = "Supplier"
    claims = sorted(await intake.claims(batch_id), key=lambda claim: claim["row_number"])

    for claim in claims:
        if claim["row_number"] <= 2:
            await intake.review(batch_id, claim, "accepted", entity)
    conflict = (await intake.conflicts(batch_id))["country"]
    assert (await intake.resolve(conflict, "suppressed")).status_code == 200

    # Row 3 repeats DE, a value the suppressed finding already covered.
    for claim in claims:
        if claim["row_number"] == 3:
            await intake.review(batch_id, claim, "accepted", entity)
    assert [item["status"] for item in (await intake.conflicts(batch_id)).values()] == [
        "suppressed"
    ]

    # Row 4 brings a value nobody has looked at: that is a new finding.
    for claim in claims:
        if claim["row_number"] == 4:
            await intake.review(batch_id, claim, "accepted", entity)
    listed = (
        await intake.client.get(
            f"/api/v1/sources/batches/{batch_id}/conflicts", params=intake.query
        )
    ).json()
    assert sorted((item["status"], len(item["claim_ids"])) for item in listed) == [
        ("open", 4),
        ("suppressed", 2),
    ]


async def test_suppressing_a_finding_keeps_the_first_rows_value(
    intake: Intake, db_session: AsyncSession
) -> None:
    batch_id = await intake.prepare("suppliers.csv", DUPLICATE_SUPPLIER)
    await intake.accept_all(batch_id, DUPLICATE_SUPPLIER)
    conflicts = await intake.conflicts(batch_id)
    assert set(conflicts) == {"supplier_name", "country"}
    for conflict in conflicts.values():
        assert (await intake.resolve(conflict, "suppressed")).status_code == 200
    assert (await intake.conflicts(batch_id))["country"]["status"] == "suppressed"

    # Suppressing accepts nothing and withdraws nothing.
    assert set((await intake.states(batch_id)).values()) == {"accepted"}
    assert (await intake.publish(batch_id)).status_code == 200
    assert (await _published(db_session, intake.workspace_id))["S-1"] == {
        "supplier_id": "S-1",
        "supplier_name": "Acme Metals",
        "country": "DE",
    }


async def test_an_escalated_conflict_still_blocks_publishing(intake: Intake) -> None:
    batch_id = await intake.prepare("suppliers.csv", DUPLICATE_SUPPLIER)
    await intake.accept_all(batch_id, DUPLICATE_SUPPLIER)
    conflicts = await intake.conflicts(batch_id)
    assert (await intake.resolve(conflicts["country"], "escalated")).status_code == 200
    assert (await intake.resolve(conflicts["supplier_name"], "suppressed")).status_code == 200

    assert (await intake.publish(batch_id)).status_code == 409

    # It can still be decided afterwards.
    kept = await intake.claim_of_row(batch_id, conflicts["country"], 2)
    assert (await intake.resolve(conflicts["country"], "approved", kept)).status_code == 200
    assert (await intake.publish(batch_id)).status_code == 200


async def test_a_rejected_cell_is_not_published(intake: Intake, db_session: AsyncSession) -> None:
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-1,Acme Metals,DE\n"
        b"S-2,Borealis Plastics,SE\n"
        b"S-3,Castle Forge,GB\n"
    )
    batch_id = await intake.prepare("suppliers.csv", content)
    # The reviewer rejects S-2's country, and S-3's identifier.
    await intake.accept_all(batch_id, content, reject={(2, "country"), (3, "supplier_id")})

    assert (await intake.publish(batch_id)).status_code == 200
    assert await _published(db_session, intake.workspace_id) == {
        "S-1": {"supplier_id": "S-1", "supplier_name": "Acme Metals", "country": "DE"},
        # The rejected value is absent, not published as before.
        "S-2": {"supplier_id": "S-2", "supplier_name": "Borealis Plastics"},
        # A row whose identifier was rejected cannot be identified: not published.
    }


async def test_a_later_row_supplies_fields_the_first_row_lacks(
    intake: Intake, db_session: AsyncSession
) -> None:
    content = (
        b"supplier_id,supplier_name,country,parent_supplier_id\n"
        # S-9 is referred to as a parent before its own row appears.
        b"S-1,Acme Metals,,S-9\n"
        b"S-1,Acme Metals,DE,S-9\n"
        b"S-9,Acme Holding,CH,\n"
    )
    batch_id = await intake.prepare("suppliers.csv", content)
    await intake.accept_all(batch_id, content)

    # The two S-1 rows do not disagree: one simply has no country.
    assert await intake.conflicts(batch_id) == {}
    assert (await intake.publish(batch_id)).status_code == 200
    published = await _published(db_session, intake.workspace_id)
    assert published["S-1"] == {
        "supplier_id": "S-1",
        "supplier_name": "Acme Metals",
        "country": "DE",
        "parent_supplier_id": "S-9",
    }
    # The parent's own row is published in full even though an earlier row
    # had only referred to it.
    assert published["S-9"] == {
        "supplier_id": "S-9",
        "supplier_name": "Acme Holding",
        "country": "CH",
    }


def _claim(workspace_id: str, batch_id: str, value: str, state: str) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=str(uuid4()),
        workspace_id=workspace_id,
        source_file_id=str(uuid4()),
        batch_id=batch_id,
        row_number=1,
        source_column="country",
        canonical_entity="Supplier",
        canonical_field="country",
        raw_value=value,
        normalized_value=value,
        confidence=1.0,
        claim_state=state,
        provenance={"entity_key": "S-1"},
        requires_review=False,
    )


async def test_a_withdrawn_claim_cannot_be_kept_or_rejected_again(db_session: AsyncSession) -> None:
    workspace_id, batch_id = str(uuid4()), str(uuid4())
    accepted = _claim(workspace_id, batch_id, "DE", ClaimState.ACCEPTED.value)
    superseded = _claim(workspace_id, batch_id, "AT", ClaimState.SUPERSEDED.value)
    conflict = EvidenceConflict(
        conflict_id=str(uuid4()),
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[accepted.claim_id, superseded.claim_id],
        canonical_entity="Supplier",
        canonical_field="country",
        severity="major",
        blocking=True,
        status="open",
        review_required=True,
        explanation="Conflicting values for resolved Supplier.country entity.",
    )
    db_session.add_all([accepted, superseded, conflict])
    await db_session.flush()

    for action in ("approved", "rejected"):
        with pytest.raises(ValueError, match="only a pending or accepted claim"):
            await resolve_conflict(
                db_session,
                workspace_id,
                conflict.conflict_id,
                superseded.claim_id,
                action,
                "Trying to revive a withdrawn value.",
                str(uuid4()),
            )
    assert superseded.claim_state == ClaimState.SUPERSEDED.value
    assert accepted.claim_state == ClaimState.ACCEPTED.value
    assert conflict.status == "open"
