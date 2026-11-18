"""Sign-in limits protect an account without letting a stranger lock it.

Regression. The limits were keyed in ways that turned them into a weapon:

* wrong passwords were counted per EMAIL (20 per 15 minutes), before the
  password was checked: anyone who knew a user's address could send 20 wrong
  passwords and the real user was refused for 15 minutes, again and again;
* sign-up, password change and reset confirmation each had ONE bucket for the
  whole server: 30 sign-up calls an hour from one caller stopped sign-up for
  everybody, 10 password changes by one user stopped it for all users.

Limits are now keyed by who is making the attempt (client address, or the
signed-in user), and only failed sign-ins count.

Requires real PostgreSQL (core.* tables); skips when unavailable.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

import app.modules.access.models as _access_models  # noqa: F401
import app.modules.audit.models as _audit_models  # noqa: F401
from app.api.v1 import auth as auth_module
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.infrastructure.security import AttemptThrottle, KeyedRateLimiter, client_address

JWT_SECRET = "attempt-limit-secret-0123456789abcdef0123456789"
PASSWORD = "Correct-horse-9"

STRANGER = "203.0.113.50"
OFFICE = "198.51.100.7"

ClientFactory = Callable[[str], AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def strict_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CORTEX_LLM_API_KEY", "not-a-real-key-used-only-in-tests")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "https://model-gateway.test/v1")
    monkeypatch.setenv("CORTEX_LLM_MODEL", "test-only-model")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_limits() -> Iterator[None]:
    """Every test starts, and leaves the rest of the suite, with full budgets."""

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
async def clients(request: pytest.FixtureRequest, strict_env: None) -> AsyncIterator[ClientFactory]:
    """Factory for API clients that connect from a chosen network address."""
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

    yield _client
    await engine.dispose()


def _email(tag: str) -> str:
    return f"limits-{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _signup(client: AsyncClient, email: str) -> Any:
    return await client.post(
        "/api/v1/auth/signup",
        json={"organization_name": "Limits Org", "email": email, "password": PASSWORD},
    )


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> Any:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


class TestWrongPasswords:
    async def test_a_stranger_cannot_lock_the_real_user_out(self, clients: ClientFactory) -> None:
        email = _email("victim")
        async with clients(OFFICE) as office, clients(STRANGER) as stranger:
            assert (await _signup(office, email)).status_code == 201

            # Far more wrong passwords than the old lock threshold of 20.
            answers = [
                (await _login(stranger, email, "Wrong-guess-1")).status_code for _ in range(40)
            ]

            # The stranger is the one who gets refused ...
            assert answers[:10] == [401] * 10
            assert set(answers[10:]) == {429}
            # ... and the real user, on their own address, still signs in.
            signed_in = await _login(office, email)
            assert signed_in.status_code == 200, signed_in.text
            assert signed_in.json()["access_token"]

    async def test_the_blocked_client_stays_blocked_even_with_the_right_password(
        self, clients: ClientFactory
    ) -> None:
        """The limit still bounds guessing: once a client has used up its
        attempts on an account, a correct guess is refused too."""
        email = _email("guessed")
        async with clients(OFFICE) as office, clients(STRANGER) as stranger:
            assert (await _signup(office, email)).status_code == 201
            for _ in range(10):
                assert (await _login(stranger, email, "Wrong-guess-1")).status_code == 401

            blocked = await _login(stranger, email, PASSWORD)

            assert blocked.status_code == 429
            assert int(blocked.headers["Retry-After"]) >= 1
            assert "access_token" not in blocked.text

    async def test_successful_sign_ins_do_not_use_up_the_budget(
        self, clients: ClientFactory
    ) -> None:
        email = _email("regular")
        async with clients(OFFICE) as office:
            assert (await _signup(office, email)).status_code == 201

            # More sign-ins than the failure budget of 10.
            answers = [(await _login(office, email)).status_code for _ in range(15)]

            assert answers == [200] * 15
            # A few slips in between are fine as well.
            for _ in range(5):
                assert (await _login(office, email, "Typo-password-1")).status_code == 401
            assert (await _login(office, email)).status_code == 200

    async def test_one_client_cannot_spray_guesses_over_many_accounts(
        self, clients: ClientFactory
    ) -> None:
        async with clients(STRANGER) as stranger:
            answers = [
                (await _login(stranger, _email(f"spray{i}"), "Wrong-guess-1")).status_code
                for i in range(105)
            ]

        assert answers[:100] == [401] * 100
        assert answers[100:] == [429] * 5

    async def test_guessing_from_many_addresses_is_still_bounded(
        self, clients: ClientFactory
    ) -> None:
        """The per-account ceiling: 100 wrong passwords per 15 minutes in
        total, however many addresses they come from."""
        email = _email("distributed")
        answers: list[int] = []
        for host in range(1, 12):
            async with clients(f"192.0.2.{host}") as bot:
                for _ in range(10):
                    answers.append((await _login(bot, email, "Wrong-guess-1")).status_code)

        assert answers[:100] == [401] * 100
        assert answers[100:] == [429] * 10


class TestServerWideBucketsAreGone:
    async def test_one_caller_cannot_use_up_everyones_sign_ups(
        self, clients: ClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same shape as production, smaller numbers so the test stays quick.
        monkeypatch.setattr(
            auth_module, "_SIGNUPS", AttemptThrottle(address=(3, 3600.0), everyone=(300, 3600.0))
        )
        async with clients(STRANGER) as stranger, clients(OFFICE) as office:
            answers = [(await _signup(stranger, _email(f"flood{i}"))).status_code for i in range(5)]
            assert answers == [201, 201, 201, 429, 429]

            # Somebody else can still create their account.
            assert (await _signup(office, _email("newcustomer"))).status_code == 201

    async def test_password_change_is_limited_per_user_not_for_the_whole_server(
        self, clients: ClientFactory
    ) -> None:
        async with clients(OFFICE) as office:
            first = (await _signup(office, _email("changer"))).json()["access_token"]
            second = (await _signup(office, _email("bystander"))).json()["access_token"]
            wrong = {"current_password": "Not-my-password-1", "new_password": "Brand-new-pass-2"}

            answers = [
                (
                    await office.post(
                        "/api/v1/auth/change-password",
                        json=wrong,
                        headers={"Authorization": f"Bearer {first}"},
                    )
                ).status_code
                for _ in range(12)
            ]
            assert answers == [401] * 10 + [429] * 2

            # A different user is not affected by the first user's attempts.
            changed = await office.post(
                "/api/v1/auth/change-password",
                json={"current_password": PASSWORD, "new_password": "Brand-new-pass-2"},
                headers={"Authorization": f"Bearer {second}"},
            )
            assert changed.status_code == 200, changed.text

    async def test_reset_confirmation_is_limited_per_client(self, clients: ClientFactory) -> None:
        body = {"token": "x" * 43, "new_password": "Brand-new-pass-2"}
        async with clients(STRANGER) as stranger, clients(OFFICE) as office:
            answers = [
                (await stranger.post("/api/v1/auth/reset/confirm", json=body)).status_code
                for _ in range(12)
            ]
            assert answers == [400] * 10 + [429] * 2

            # Another client still reaches the handler (400: the token is not valid).
            assert (await office.post("/api/v1/auth/reset/confirm", json=body)).status_code == 400

    async def test_reset_requests_are_limited_per_client_and_account(
        self, clients: ClientFactory
    ) -> None:
        email = _email("resetme")
        async with clients(STRANGER) as stranger, clients(OFFICE) as office:
            answers = [
                (
                    await stranger.post("/api/v1/auth/reset/request", json={"email": email})
                ).status_code
                for _ in range(7)
            ]
            assert answers == [200] * 5 + [429] * 2

            mine = await office.post("/api/v1/auth/reset/request", json={"email": email})
            assert mine.status_code == 200


class TestLimiterPrimitives:
    def test_keyed_limiter_is_per_key_and_refills(self) -> None:
        limiter = KeyedRateLimiter(capacity=2, refill_per_s=1.0)

        assert limiter.try_consume("a", now=0.0)
        assert limiter.try_consume("a", now=0.0)
        assert not limiter.try_consume("a", now=0.0)
        assert limiter.try_consume("b", now=0.0)
        assert limiter.retry_after("a", now=0.0) >= 1
        # One second later one token is back.
        assert limiter.try_consume("a", now=1.0)
        assert not limiter.try_consume("a", now=1.0)

    def test_refund_gives_an_attempt_back_but_never_more_than_the_capacity(self) -> None:
        limiter = KeyedRateLimiter(capacity=2, refill_per_s=0.0)

        assert limiter.try_consume("a", now=0.0)
        limiter.refund("a", now=0.0)
        limiter.refund("a", now=0.0)
        limiter.refund("a", now=0.0)

        assert [limiter.try_consume("a", now=0.0) for _ in range(3)] == [True, True, False]

    def test_the_table_of_buckets_is_bounded(self) -> None:
        """A caller sending a new key on every request cannot grow memory."""
        limiter = KeyedRateLimiter(capacity=5, refill_per_s=0.0, max_keys=100)
        # A client that has used up its budget ...
        for _ in range(5):
            limiter.try_consume("blocked-client", now=0.0)

        for index in range(10_000):
            limiter.try_consume(f"spray-{index}", now=float(index))
            # ... and keeps trying while the spray is going on.
            if index % 50 == 0:
                assert not limiter.try_consume("blocked-client", now=float(index))

        assert len(limiter) <= 100
        # Its empty bucket was kept (recently used), so it is still refused.
        assert not limiter.try_consume("blocked-client", now=10_000.0)

    def test_full_buckets_are_dropped_first_when_pruning(self) -> None:
        limiter = KeyedRateLimiter(capacity=1, refill_per_s=1.0, max_keys=3)
        limiter.try_consume("old-and-refilled", now=0.0)
        limiter.try_consume("recent-1", now=99.4)
        limiter.try_consume("recent-2", now=99.5)

        limiter.try_consume("new", now=100.0)

        # The bucket that had refilled completely went; the two still
        # recovering were kept, so their limits were not forgotten.
        assert len(limiter) == 3
        assert not limiter.try_consume("recent-1", now=100.0)
        assert not limiter.try_consume("recent-2", now=100.0)

    def test_throttle_takes_nothing_when_any_limit_is_exhausted(self) -> None:
        throttle = AttemptThrottle(pair=(1, 3600.0), address=(5, 3600.0))
        keys = {"pair": "a|x", "address": "x"}
        throttle.acquire(keys)

        for _ in range(10):
            with pytest.raises(HTTPException) as refused:
                throttle.acquire(keys)
            assert refused.value.status_code == 429
            assert int((refused.value.headers or {})["Retry-After"]) >= 1

        # The ten refused attempts did not eat into the address budget:
        # four more accounts from the same address still get an attempt.
        for other in ("b", "c", "d", "e"):
            throttle.acquire({"pair": f"{other}|x", "address": "x"})
        with pytest.raises(HTTPException):
            throttle.acquire({"pair": "f|x", "address": "x"})

    def test_release_returns_the_attempt(self) -> None:
        throttle = AttemptThrottle(pair=(1, 3600.0))
        keys = {"pair": "a|x"}

        for _ in range(5):
            throttle.acquire(keys)
            throttle.release(keys)

        throttle.acquire(keys)
        with pytest.raises(HTTPException):
            throttle.acquire(keys)

    def test_client_address_reads_the_peer_and_ignores_forwarding_headers(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "client": ("198.51.100.7", 4242),
            # A caller can put anything here; it must not change the key.
            "headers": [(b"x-forwarded-for", b"10.0.0.1"), (b"x-real-ip", b"10.0.0.2")],
        }
        assert client_address(Request(scope)) == "198.51.100.7"
        assert client_address(Request({**scope, "client": None})) == "unknown"
        assert client_address(None) == "unknown"
