"""A password reset works without email, and the site can say so honestly.

Regression. Cortex sends no email, yet the sign-in page answered a reset
request with "a reset link is on its way". On a deployed server the link was
created and thrown away, so the user waited for a message that could not
arrive, and the only way out (an operator running ``issue-reset``) was not
connected to the request at all. Worse, every such request deleted the user's
live reset token, so anyone who knew an address could keep cancelling a link
an operator had already sent.

Now a request is recorded on the user row, the team lists the waiting
requests and issues the link by hand, and the public route no longer touches
tokens outside dev/test.

Requires real PostgreSQL (core.* tables); skips when unavailable.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

import app.modules.access.models as _access_models  # noqa: F401
import app.modules.audit.models as _audit_models  # noqa: F401
from app.api.v1 import auth as auth_module
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.modules.access.models import PasswordResetToken, User
from app.modules.audit.models import AuditEvent
from scripts import admin_users as operator

JWT_SECRET = "reset-request-secret-0123456789abcdef0123456789"
PASSWORD = "Correct-horse-9"
NEW_PASSWORD = "Fresh-saddle-42"

OFFICE = "198.51.100.7"
STRANGER = "203.0.113.50"

ClientFactory = Callable[[str], AbstractAsyncContextManager[AsyncClient]]


@dataclass
class Stack:
    client: ClientFactory
    sessions: async_sessionmaker[AsyncSession]


def _set_environment(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("CORTEX_ENV", name)
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CORTEX_LLM_API_KEY", "not-a-real-key-used-only-in-tests")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "https://model-gateway.test/v1")
    monkeypatch.setenv("CORTEX_LLM_MODEL", "test-only-model")
    get_settings.cache_clear()


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A server real users reach (pilot): nothing is handed back in-band."""
    _set_environment(monkeypatch, "pilot")
    yield
    get_settings.cache_clear()


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's or CI machine (test)."""
    _set_environment(monkeypatch, "test")
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_limits() -> Iterator[None]:
    def _reset() -> None:
        auth_module._LOGIN_FAILURES.reset()
        auth_module._SIGNUPS.reset()
        auth_module._RESET_REQUESTS.reset()
        auth_module.change_password.limiter.reset()  # type: ignore[attr-defined]
        auth_module.confirm_password_reset.limiter.reset()  # type: ignore[attr-defined]

    _reset()
    yield
    _reset()


@pytest.fixture
async def stack(request: pytest.FixtureRequest) -> AsyncIterator[Stack]:
    try:
        engine = create_async_engine(request.config.postgres_url, echo=False)  # type: ignore[attr-defined]
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
    async with engine.begin() as conn:
        meta = MetaData()
        for table in Base.metadata.sorted_tables:
            if (table.schema, table.name) in wanted:
                table.to_metadata(meta)
        await conn.execute(CreateSchema("core", if_not_exists=True))
        await conn.run_sync(meta.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/v1/auth")

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    @asynccontextmanager
    async def _client(address: str) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=app, client=(address, 50000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    yield Stack(client=_client, sessions=maker)
    await engine.dispose()


def _email(tag: str) -> str:
    return f"reset-{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _signup(client: AsyncClient, email: str) -> None:
    answer = await client.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Reset Org",
            "email": email,
            "password": PASSWORD,
            "full_name": "Asha Rao",
        },
    )
    assert answer.status_code == 201, answer.text


async def _ask(client: AsyncClient, email: str) -> Any:
    return await client.post("/api/v1/auth/reset/request", json={"email": email})


async def _redeem(client: AsyncClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return await client.post(
        "/api/v1/auth/reset/confirm", json={"token": token, "new_password": password}
    )


async def _login(client: AsyncClient, email: str, password: str) -> Any:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _user(stack: Stack, email: str) -> User:
    async with stack.sessions() as session:
        return (await session.execute(select(User).where(User.email == email))).scalar_one()


async def _tokens(stack: Stack, email: str) -> int:
    async with stack.sessions() as session:
        stmt = (
            select(func.count())
            .select_from(PasswordResetToken)
            .join(User, User.id == PasswordResetToken.user_id)
            .where(User.email == email)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _waiting(stack: Stack) -> list[str]:
    async with stack.sessions() as session:
        return [u.email for u in await operator.waiting_reset_requests(session, limit=10_000)]


@pytest.mark.usefixtures("deployed")
class TestARequestOnADeployedServer:
    async def test_it_is_recorded_for_the_team_and_no_token_is_created(self, stack: Stack) -> None:
        email = _email("asks")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            before = datetime.now(UTC)
            answer = await _ask(site, email)

        assert answer.status_code == 200, answer.text
        # Nothing usable leaves the server: no token in the answer ...
        assert answer.json() == {"requested": True, "reset_token": None}
        # ... and none in the database either: nobody would receive it.
        assert await _tokens(stack, email) == 0
        # The request itself is recorded, so a person can act on it.
        user = await _user(stack, email)
        assert user.reset_requested_at is not None
        assert before - timedelta(seconds=5) <= user.reset_requested_at <= datetime.now(UTC)
        assert email in await _waiting(stack)

    async def test_an_unknown_address_gets_the_same_answer_and_records_nothing(
        self, stack: Stack
    ) -> None:
        known, unknown = _email("known"), _email("ghost")
        async with stack.client(OFFICE) as site:
            await _signup(site, known)
            waiting_before = set(await _waiting(stack))
            for_known = await _ask(site, known)
            for_unknown = await _ask(site, unknown)

        # Same status, same body: the answer does not say whether the account exists.
        assert for_unknown.status_code == for_known.status_code == 200
        assert for_unknown.json() == for_known.json()
        assert set(await _waiting(stack)) - waiting_before == {known}

    async def test_asking_again_keeps_the_time_of_the_first_request(self, stack: Stack) -> None:
        email = _email("twice")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            assert (await _ask(site, email)).status_code == 200
            first = (await _user(stack, email)).reset_requested_at
            assert (await _ask(site, email)).status_code == 200
            assert (await _ask(site, email)).status_code == 200

        # "Waiting since" stays the first request, and the list has one line.
        assert (await _user(stack, email)).reset_requested_at == first
        assert (await _waiting(stack)).count(email) == 1

    async def test_a_stranger_cannot_cancel_a_link_the_team_has_sent(self, stack: Stack) -> None:
        """The old route deleted the user's live token on every request, so
        anyone who knew the address could keep the user locked out."""
        email = _email("victim")
        async with stack.client(OFFICE) as office, stack.client(STRANGER) as stranger:
            await _signup(office, email)
            assert (await _ask(office, email)).status_code == 200
            async with stack.sessions() as session:
                user = await operator.find_user(session, email)
                issued = await operator.issue_reset(session, user)

            # A stranger asks for a reset of the same account, again and again.
            for _ in range(5):
                assert (await _ask(stranger, email)).status_code == 200

            # The link the team sent still works ...
            redeemed = await _redeem(office, issued.token)
            assert redeemed.status_code == 200, redeemed.text
            # ... and the user is back in with the new password.
            assert (await _login(office, email, NEW_PASSWORD)).status_code == 200
            assert (await _login(office, email, PASSWORD)).status_code == 401

    async def test_a_deactivated_account_records_nothing(self, stack: Stack) -> None:
        email = _email("left")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            async with stack.sessions() as session:
                await operator.set_active(session, await operator.find_user(session, email), False)

            answer = await _ask(site, email)

        assert answer.json() == {"requested": True, "reset_token": None}
        assert (await _user(stack, email)).reset_requested_at is None
        assert email not in await _waiting(stack)

    async def test_changing_the_password_closes_the_waiting_request(self, stack: Stack) -> None:
        """The user remembered the password after all: nothing is left to do."""
        email = _email("remembered")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            assert (await _ask(site, email)).status_code == 200
            token = (await _login(site, email, PASSWORD)).json()["access_token"]

            changed = await site.post(
                "/api/v1/auth/change-password",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert changed.status_code == 200, changed.text
        assert (await _user(stack, email)).reset_requested_at is None
        assert email not in await _waiting(stack)


@pytest.mark.usefixtures("local")
class TestARequestOnADeveloperMachine:
    async def test_dev_and_test_still_get_a_token_they_can_redeem(self, stack: Stack) -> None:
        """Developers and the browser tests finish a reset without an operator."""
        email = _email("dev")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            answer = await _ask(site, email)
            token = answer.json()["reset_token"]

            assert answer.status_code == 200 and token
            assert (await _user(stack, email)).reset_requested_at is not None

            assert (await _redeem(site, token)).status_code == 200
            assert (await _login(site, email, NEW_PASSWORD)).status_code == 200

        # Redeeming the link closes the request.
        assert (await _user(stack, email)).reset_requested_at is None

    async def test_an_unknown_address_gets_no_token(self, stack: Stack) -> None:
        async with stack.client(OFFICE) as site:
            answer = await _ask(site, _email("ghost"))

        assert answer.json() == {"requested": True, "reset_token": None}


@pytest.mark.usefixtures("deployed")
class TestTheOperatorScript:
    async def test_the_waiting_list_names_who_asked_oldest_first(self, stack: Stack) -> None:
        first, second = _email("first"), _email("second")
        async with stack.client(OFFICE) as site:
            await _signup(site, first)
            await _signup(site, second)
            assert (await _ask(site, first)).status_code == 200
            assert (await _ask(site, second)).status_code == 200

        waiting = await _waiting(stack)
        assert waiting.index(first) < waiting.index(second)

        line = operator.format_waiting(await _user(stack, first), datetime.now(UTC))
        assert line.startswith(f"{first}  Asha Rao  waiting since ")
        assert line.endswith("UTC (under an hour)")

    async def test_a_link_works_once_and_closes_the_request(self, stack: Stack) -> None:
        email = _email("helped")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            assert (await _ask(site, email)).status_code == 200
            moment = datetime.now(UTC)
            async with stack.sessions() as session:
                user = await operator.find_user(session, email.upper())
                issued = await operator.issue_reset(session, user, now=moment)

            # A day by default: the link travels in a person's mail.
            assert issued.expires_at == moment + timedelta(hours=24)
            assert email not in await _waiting(stack)

            text = operator.format_issued(issued, "https://app.cortex.example")
            link = f"https://app.cortex.example/auth/reset-password?token={issued.token}"
            assert link in text
            assert f"Send it to {email} only" in text

            assert (await _redeem(site, issued.token)).status_code == 200
            assert (await _login(site, email, NEW_PASSWORD)).status_code == 200
            # Single use.
            again = await _redeem(site, issued.token, "Another-pass-77")
            assert again.status_code == 400
            assert (await _login(site, email, "Another-pass-77")).status_code == 401

    async def test_a_link_stops_working_when_its_time_is_up(self, stack: Stack) -> None:
        email = _email("late")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            async with stack.sessions() as session:
                user = await operator.find_user(session, email)
                issued = await operator.issue_reset(
                    session, user, valid_hours=2, now=datetime.now(UTC) - timedelta(hours=3)
                )

            late = await _redeem(site, issued.token)

            assert late.status_code == 400
            assert (await _login(site, email, PASSWORD)).status_code == 200

    async def test_a_new_link_cancels_the_one_before(self, stack: Stack) -> None:
        email = _email("resent")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            async with stack.sessions() as session:
                user = await operator.find_user(session, email)
                old = await operator.issue_reset(session, user)
                new = await operator.issue_reset(session, user)

            assert (await _redeem(site, old.token)).status_code == 400
            assert (await _redeem(site, new.token)).status_code == 200
        assert await _tokens(stack, email) == 1

    @pytest.mark.parametrize("hours", [0, -1, 73, 1000])
    async def test_the_validity_is_bounded(self, stack: Stack, hours: int) -> None:
        email = _email("bounds")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
        async with stack.sessions() as session:
            user = await operator.find_user(session, email)
            with pytest.raises(operator.OperatorError, match="between 1 and 72"):
                await operator.issue_reset(session, user, valid_hours=hours)

        assert await _tokens(stack, email) == 0

    async def test_a_deactivated_account_gets_no_link(self, stack: Stack) -> None:
        email = _email("gone")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
        async with stack.sessions() as session:
            user = await operator.find_user(session, email)
            await operator.set_active(session, user, False)
            with pytest.raises(operator.OperatorError, match="deactivated"):
                await operator.issue_reset(session, user)

        assert await _tokens(stack, email) == 0

    async def test_a_request_can_be_closed_without_a_link(self, stack: Stack) -> None:
        email = _email("dismissed")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            assert (await _ask(site, email)).status_code == 200
        async with stack.sessions() as session:
            user = await operator.find_user(session, email)
            assert await operator.dismiss_reset(session, user) is True
            assert await operator.dismiss_reset(session, user) is False

        assert email not in await _waiting(stack)
        assert await _tokens(stack, email) == 0

    async def test_setting_a_password_by_hand_closes_the_request(self, stack: Stack) -> None:
        email = _email("phoned")
        async with stack.client(OFFICE) as site:
            await _signup(site, email)
            assert (await _ask(site, email)).status_code == 200
            async with stack.sessions() as session:
                user = await operator.find_user(session, email)
                with pytest.raises(operator.OperatorError, match="letter and a digit"):
                    await operator.set_password(session, user, "short")
                await operator.set_password(session, user, NEW_PASSWORD)

            assert (await _login(site, email, NEW_PASSWORD)).status_code == 200
        assert email not in await _waiting(stack)

    async def test_an_unknown_address_is_reported_not_guessed(self, stack: Stack) -> None:
        async with stack.sessions() as session:
            with pytest.raises(operator.OperatorError, match="no account with the email"):
                await operator.find_user(session, _email("nobody"))

    async def test_what_the_team_does_is_in_the_audit_trail(self, stack: Stack) -> None:
        issued_for, dismissed_for = _email("audited"), _email("closed")
        async with stack.client(OFFICE) as site:
            await _signup(site, issued_for)
            await _signup(site, dismissed_for)
            assert (await _ask(site, dismissed_for)).status_code == 200
        async with stack.sessions() as session:
            await operator.issue_reset(
                session, await operator.find_user(session, issued_for), valid_hours=4
            )
            await operator.dismiss_reset(session, await operator.find_user(session, dismissed_for))

        async with stack.sessions() as session:
            for email, event_type in (
                (issued_for, "auth.reset_issued"),
                (dismissed_for, "auth.reset_dismissed"),
            ):
                user = (await session.execute(select(User).where(User.email == email))).scalar_one()
                events = (
                    (
                        await session.execute(
                            select(AuditEvent).where(
                                AuditEvent.subject_id == str(user.id),
                                AuditEvent.event_type == event_type,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(events) == 1, (email, event_type)
                assert events[0].actor_type == "operator"
                assert events[0].workspace_id == str(user.workspace_id)
                # The link itself is a secret and is never written down.
                assert "token" not in str(events[0].payload).lower()


class TestTheSiteAddressInTheLink:
    def test_the_one_public_origin_is_the_site(self) -> None:
        origins = ["http://localhost:3000", "https://app.cortex.example/"]

        assert operator.site_url(origins, local_environment=False) == "https://app.cortex.example"

    def test_with_several_public_origins_the_operator_chooses(self) -> None:
        origins = ["https://app.cortex.example", "https://staging.cortex.example"]

        assert operator.site_url(origins, local_environment=False) == ""
        chosen = operator.site_url(
            origins, local_environment=False, override="https://app.cortex.example/"
        )
        assert chosen == "https://app.cortex.example"

    def test_a_developer_machine_uses_its_local_site(self) -> None:
        origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

        assert operator.site_url(origins, local_environment=True) == "http://localhost:3000"
        # A deployed server never guesses a local address.
        assert operator.site_url(origins, local_environment=False) == ""

    @pytest.mark.parametrize(
        "address", ["app.cortex.example", "ftp://app.cortex.example", "http://app.cortex.example"]
    )
    def test_an_address_that_would_leak_or_break_the_link_is_refused(self, address: str) -> None:
        with pytest.raises(operator.OperatorError):
            operator.site_url([], local_environment=False, override=address)

    def test_without_an_address_the_operator_is_told_to_add_one(self) -> None:
        issued = operator.IssuedReset(
            email="asha@example.com",
            token="t0ken",
            expires_at=datetime(2026, 11, 19, 5, 40, tzinfo=UTC),
        )

        text = operator.format_issued(issued, "")

        assert "  /auth/reset-password?token=t0ken" in text
        assert "Put the address of your site in front of it" in text
        assert "Valid until 2026-11-19 05:40 UTC" in text


class TestTheCommandLine:
    @pytest.mark.parametrize(
        "argv",
        [
            ["reset-requests"],
            ["issue-reset", "--email", "user@example.com"],
            ["issue-reset", "--email", "user@example.com", "--valid-hours", "4"],
            ["issue-reset", "--email", "user@example.com", "--site-url", "https://a.example"],
            ["dismiss-reset", "--email", "user@example.com"],
            ["set-password", "--email", "user@example.com"],
            ["deactivate", "--email", "user@example.com"],
            ["activate", "--email", "user@example.com"],
            ["list", "--limit", "20"],
        ],
    )
    def test_every_documented_command_is_accepted(self, argv: list[str]) -> None:
        args = operator.build_parser().parse_args(argv)

        assert args.command == argv[0]

    def test_the_default_validity_is_a_day(self) -> None:
        args = operator.build_parser().parse_args(["issue-reset", "--email", "u@example.com"])

        assert args.valid_hours == 24

    @pytest.mark.parametrize("command", ["issue-reset", "dismiss-reset", "set-password"])
    def test_a_command_about_one_account_needs_its_address(
        self, command: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as stopped:
            operator.main([command])

        assert stopped.value.code == 2
        assert "--email is required" in capsys.readouterr().err
