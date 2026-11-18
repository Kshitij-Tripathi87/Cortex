"""Requests sent through the public site are really saved.

Regression. The demo request form showed "Your request was received" with a
reference number invented in the browser and saved nothing, and the contact
pages listed placeholder email addresses. A request now goes to
``POST /api/v1/public/contact-requests``, is stored, and the reference the
visitor sees is the reference of the stored row.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import contact as contact_module
from app.api.v1.router import api_router
from app.infrastructure.database import get_db
from app.infrastructure.security import AttemptThrottle
from app.modules.contact.models import STATUS_HANDLED, STATUS_NEW, TOPICS, ContactRequest
from scripts import contact_requests as operator

URL = "/api/v1/public/contact-requests"
OFFICE = "198.51.100.7"
ELSEWHERE = "203.0.113.50"

ClientFactory = Callable[[str], AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture(autouse=True)
def fresh_limits() -> Iterator[None]:
    contact_module._REQUESTS.reset()
    yield
    contact_module._REQUESTS.reset()


@pytest.fixture
def clients(db_session: AsyncSession) -> ClientFactory:
    """API clients that connect from a chosen network address."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")

    async def _db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _db

    @asynccontextmanager
    async def _client(address: str) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=app, client=(address, 50000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    return _client


def _message(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "topic": "general",
        "full_name": "Asha Rao",
        "email": "Asha.Rao@Example.com",
        "company": "Meridian Pumps",
        "message": "Can Cortex read our purchase orders from spreadsheets?",
        "consent": True,
    }
    body.update(changes)
    return body


def _demo(**changes: Any) -> dict[str, Any]:
    return _message(
        topic="demo",
        message="We need to evaluate rerouting options when a port is congested.",
        details={
            "job_title": "Head of Supply Chain",
            "primary_role": "operations",
            "country": "India",
            "company_size": "501-2000",
            "challenges": ["Supplier Disruption", "Inventory Risk"],
            "current_systems": ["ERP Systems", "Spreadsheets"],
            "desired_outcome": "Fewer stock-outs",
            "timeline": "short",
        },
        **changes,
    )


async def _count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(ContactRequest))).scalar_one()
    )


class TestSaving:
    async def test_a_demo_request_is_stored_and_the_reference_is_the_stored_one(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(OFFICE) as site:
            answer = await site.post(URL, json=_demo())

        assert answer.status_code == 201, answer.text
        receipt = answer.json()
        assert set(receipt) == {"reference", "received_at"}
        assert re.fullmatch(r"REQ-[2-9A-HJKMNP-Z]{8}", receipt["reference"])

        rows = (await db_session.execute(select(ContactRequest))).scalars().all()
        assert len(rows) == 1
        saved = rows[0]
        assert saved.reference == receipt["reference"]
        assert saved.topic == "demo"
        assert saved.full_name == "Asha Rao"
        assert saved.email == "asha.rao@example.com"
        assert saved.company == "Meridian Pumps"
        assert saved.message.startswith("We need to evaluate rerouting")
        assert saved.consent is True
        assert saved.status == STATUS_NEW
        assert saved.handled_at is None
        assert saved.details == {
            "job_title": "Head of Supply Chain",
            "primary_role": "operations",
            "country": "India",
            "company_size": "501-2000",
            "challenges": ["Supplier Disruption", "Inventory Risk"],
            "current_systems": ["ERP Systems", "Spreadsheets"],
            "desired_outcome": "Fewer stock-outs",
            "timeline": "short",
        }

    @pytest.mark.parametrize("topic", TOPICS)
    async def test_every_topic_the_site_offers_is_accepted(
        self, clients: ClientFactory, db_session: AsyncSession, topic: str
    ) -> None:
        async with clients(OFFICE) as site:
            answer = await site.post(URL, json=_message(topic=topic))

        assert answer.status_code == 201, answer.text
        saved = (await db_session.execute(select(ContactRequest))).scalars().one()
        assert saved.topic == topic
        assert saved.details == {}

    async def test_each_request_gets_its_own_reference(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(OFFICE) as site:
            references = [
                (await site.post(URL, json=_message())).json()["reference"] for _ in range(5)
            ]

        assert len(set(references)) == 5
        assert await _count(db_session) == 5

    async def test_a_reference_already_in_use_is_never_handed_out_twice(
        self,
        clients: ClientFactory,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        produced = iter(["REQ-AAAAAAAA", "REQ-AAAAAAAA", "REQ-AAAAAAAA", "REQ-BBBBBBBB"])
        monkeypatch.setattr(contact_module, "_new_reference", lambda: next(produced))

        async with clients(OFFICE) as site:
            first = await site.post(URL, json=_message())
            second = await site.post(URL, json=_message(full_name="Second Sender"))

        assert first.json()["reference"] == "REQ-AAAAAAAA"
        assert second.status_code == 201
        assert second.json()["reference"] == "REQ-BBBBBBBB"
        assert await _count(db_session) == 2

    async def test_text_is_trimmed_and_an_empty_company_is_stored_as_none(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(OFFICE) as site:
            answer = await site.post(
                URL,
                json=_message(full_name="  Asha Rao  ", company="   ", message="  Hello.  "),
            )

        assert answer.status_code == 201, answer.text
        saved = (await db_session.execute(select(ContactRequest))).scalars().one()
        assert (saved.full_name, saved.company, saved.message) == ("Asha Rao", None, "Hello.")


class TestRefusals:
    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"consent": False}, "consent"),
            ({"consent": None}, "consent"),
            ({"email": "not-an-email"}, "email"),
            ({"email": "a@b"}, "email"),
            ({"email": "two words@example.com"}, "email"),
            ({"full_name": ""}, "full_name"),
            ({"full_name": "    "}, "full_name"),
            ({"full_name": "x" * 201}, "full_name"),
            ({"message": ""}, "message"),
            ({"message": "   "}, "message"),
            ({"message": "x" * 4001}, "message"),
            ({"company": "x" * 201}, "company"),
            ({"topic": "complaints"}, "topic"),
            ({"topic": ""}, "topic"),
            ({"status": "handled"}, "status"),
            ({"reference": "REQ-MINE0000"}, "reference"),
            ({"details": {"challenges": ["x"] * 13}}, "details"),
            ({"details": {"challenges": ["x" * 101]}}, "details"),
            ({"details": {"unknown": "field"}}, "details"),
            ({"details": {"desired_outcome": "x" * 501}}, "details"),
        ],
    )
    async def test_an_invalid_request_is_refused_and_nothing_is_stored(
        self,
        clients: ClientFactory,
        db_session: AsyncSession,
        change: dict[str, Any],
        field: str,
    ) -> None:
        async with clients(OFFICE) as site:
            answer = await site.post(URL, json=_message(**change))

        assert answer.status_code == 422, answer.text
        assert field in {str(part) for error in answer.json()["detail"] for part in error["loc"]}
        assert await _count(db_session) == 0

    @pytest.mark.parametrize("missing", ["topic", "full_name", "email", "message", "consent"])
    async def test_every_required_field_is_required(
        self, clients: ClientFactory, db_session: AsyncSession, missing: str
    ) -> None:
        body = _message()
        del body[missing]

        async with clients(OFFICE) as site:
            answer = await site.post(URL, json=body)

        assert answer.status_code == 422
        assert await _count(db_session) == 0

    async def test_the_table_cannot_be_read_or_changed_through_the_api(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(OFFICE) as site:
            reference = (await site.post(URL, json=_message())).json()["reference"]

            for method, path in (
                ("get", URL),
                ("get", f"{URL}/{reference}"),
                ("delete", f"{URL}/{reference}"),
                ("put", f"{URL}/{reference}"),
                ("patch", f"{URL}/{reference}"),
            ):
                answer = await getattr(site, method)(path)
                assert answer.status_code in (404, 405), f"{method} {path}: {answer.status_code}"
                assert "Asha" not in answer.text

        assert await _count(db_session) == 1


class TestLimits:
    async def test_one_address_is_limited_and_others_are_not_affected(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(ELSEWHERE) as flood, clients(OFFICE) as office:
            answers = [(await flood.post(URL, json=_message())).status_code for _ in range(13)]

            assert answers == [201] * 10 + [429] * 3
            refused = await flood.post(URL, json=_message())
            assert int(refused.headers["Retry-After"]) >= 1

            # Somebody else can still write in.
            assert (await office.post(URL, json=_message())).status_code == 201

        # Refused requests stored nothing.
        assert await _count(db_session) == 11

    async def test_the_whole_server_has_a_ceiling(
        self, clients: ClientFactory, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """However many addresses the requests come from, the table grows at a
        bounded rate. Same shape as production, smaller numbers."""
        monkeypatch.setattr(
            contact_module, "_REQUESTS", AttemptThrottle(address=(10, 3600.0), everyone=(4, 3600.0))
        )
        answers = []
        for host in range(1, 7):
            async with clients(f"192.0.2.{host}") as site:
                answers.append((await site.post(URL, json=_message())).status_code)

        assert answers == [201, 201, 201, 201, 429, 429]
        assert await _count(db_session) == 4

    async def test_requests_that_store_nothing_do_not_use_up_the_budget(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        """The limit bounds what gets stored. A visitor who is told to correct
        the form several times must still be able to send it."""
        async with clients(ELSEWHERE) as visitor:
            for _ in range(15):
                assert (await visitor.post(URL, json=_message(consent=False))).status_code == 422

            assert (await visitor.post(URL, json=_message())).status_code == 201

        assert await _count(db_session) == 1


class TestOperatorScript:
    async def test_the_team_can_list_read_and_close_a_request(
        self, clients: ClientFactory, db_session: AsyncSession
    ) -> None:
        async with clients(OFFICE) as site:
            general = (await site.post(URL, json=_message())).json()["reference"]
            demo = (await site.post(URL, json=_demo(full_name="Dev Mehta"))).json()["reference"]
            security = (
                await site.post(URL, json=_message(topic="security", message="XSS on /demo"))
            ).json()["reference"]

        # Newest first; only unanswered ones by default.
        listed = await operator.list_requests(db_session)
        assert [row.reference for row in listed] == [security, demo, general]
        assert [
            row.reference for row in await operator.list_requests(db_session, topic="security")
        ] == [security]
        assert len(await operator.list_requests(db_session, limit=2)) == 2

        row = operator.format_row(listed[1])
        assert demo in row and "Dev Mehta" in row and "demo" in row and "Meridian Pumps" in row

        # The reference is found however it is typed.
        found = await operator.find_request(db_session, f"  {demo.lower()} ")
        assert found is not None
        shown = operator.format_request(found)
        assert "Head of Supply Chain" in shown
        assert "Supplier Disruption, Inventory Risk" in shown
        assert "We need to evaluate rerouting" in shown
        assert "asha.rao@example.com" in shown

        closed = await operator.mark_handled(db_session, demo, "replied by phone")
        assert closed is not None
        assert closed.status == STATUS_HANDLED
        assert closed.handled_at is not None
        assert closed.handled_note == "replied by phone"

        assert [row.reference for row in await operator.list_requests(db_session)] == [
            security,
            general,
        ]
        assert [
            row.reference for row in await operator.list_requests(db_session, status=STATUS_HANDLED)
        ] == [demo]
        assert len(await operator.list_requests(db_session, status="all")) == 3

    async def test_an_unknown_reference_is_reported_not_invented(
        self, db_session: AsyncSession
    ) -> None:
        assert await operator.find_request(db_session, "REQ-NOTHERE1") is None
        assert await operator.mark_handled(db_session, "REQ-NOTHERE1") is None

    def test_the_command_line_is_what_the_documentation_says(self) -> None:
        parser = operator.build_parser()

        listing = parser.parse_args(["list"])
        assert (listing.status, listing.topic, listing.limit) == (STATUS_NEW, None, 20)
        filtered = parser.parse_args(
            ["list", "--status", "all", "--topic", "security", "--limit", "50"]
        )
        assert (filtered.status, filtered.topic, filtered.limit) == ("all", "security", 50)
        assert parser.parse_args(["show", "REQ-7K3F9Q2M"]).reference == "REQ-7K3F9Q2M"
        handled = parser.parse_args(["handle", "REQ-7K3F9Q2M", "--note", "replied 18 Nov"])
        assert (handled.reference, handled.note) == ("REQ-7K3F9Q2M", "replied 18 Nov")
        with pytest.raises(SystemExit):
            parser.parse_args(["list", "--topic", "complaints"])
