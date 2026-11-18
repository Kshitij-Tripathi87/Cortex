"""When a trial ends the user is told, and the team can do something about it.

Regression. Every sign-up starts a 7-day trial. After it, creating, running
and approving tasks answered HTTP 402 with a line of internals
("Subscription for organization ... expired at 2026-11-10T05:00:00+00:00"),
the site kept showing "trial · ends <a date in the past>", and nothing could
change a plan short of editing the database by hand.

The block stays. What changed: ``GET /auth/me`` carries the server's verdict
so the site can explain the pause, the refusal is written in plain words, and
``scripts/admin_orgs.py`` extends a trial or sets a plan.

The database tests require real PostgreSQL (core.* tables) and skip without it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

import app.modules.access.models as _access_models  # noqa: F401
import app.modules.audit.models as _audit_models  # noqa: F401
import app.modules.contact.models as _contact_models  # noqa: F401
from app.api.v1 import auth as auth_module
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.modules.access.models import Organization, User, Workspace
from app.modules.audit.models import AuditEvent
from app.modules.billing import EntitlementDenied, EntitlementService
from app.modules.billing.plans import (
    KNOWN_PLANS,
    PAUSED_ACTIONS,
    describe_inactive,
    subscription_is_active,
)
from app.modules.contact.models import STATUS_NEW, ContactRequest
from scripts import admin_orgs as operator
from scripts import operator_inbox

JWT_SECRET = "plans-and-trials-secret-0123456789abcdef0123456789"
PASSWORD = "Correct-horse-9"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


class TestWhenAPlanIsActive:
    def test_a_trial_is_active_until_its_end_and_not_after(self) -> None:
        ends = NOW + timedelta(days=3)

        assert subscription_is_active("trial", ends, now=NOW) is True
        assert subscription_is_active("trial", ends, now=ends) is True
        assert subscription_is_active("trial", ends, now=ends + timedelta(seconds=1)) is False

    def test_a_trial_without_an_end_date_does_not_end(self) -> None:
        assert subscription_is_active("trial", None, now=NOW) is True

    @pytest.mark.parametrize("plan", ["free", "pro", "enterprise"])
    def test_the_other_plans_do_not_end(self, plan: str) -> None:
        long_ago = NOW - timedelta(days=400)

        assert subscription_is_active(plan, long_ago, now=NOW) is True
        assert subscription_is_active(plan, None, now=NOW) is True

    @pytest.mark.parametrize("plan", ["", "starter", "TRIAL", "Pro"])
    def test_a_plan_nobody_defined_is_not_active(self, plan: str) -> None:
        assert subscription_is_active(plan, NOW + timedelta(days=30), now=NOW) is False

    def test_a_date_read_back_without_a_time_zone_is_taken_as_utc(self) -> None:
        naive_end = (NOW + timedelta(hours=1)).replace(tzinfo=None)

        assert subscription_is_active("trial", naive_end, now=NOW) is True
        assert subscription_is_active("trial", naive_end, now=NOW + timedelta(hours=2)) is False

    def test_every_plan_that_can_be_given_is_a_plan_that_can_be_active(self) -> None:
        """Nothing may write a plan that the gate would then treat as expired."""
        for plan in KNOWN_PLANS:
            assert subscription_is_active(plan, NOW + timedelta(days=1), now=NOW) is True


class TestWhatARefusedCallerReads:
    def test_an_ended_trial_is_explained_in_plain_words(self) -> None:
        ended = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)

        text = describe_inactive("Meridian Pumps", "trial", ended)

        assert text == (
            "The trial of 'Meridian Pumps' ended on 10 Nov 2026. "
            "Creating, running and approving tasks is paused; existing data stays available. "
            "Contact the Cortex team to continue."
        )
        # No timestamps or field names from the database.
        assert "T05:00" not in text and "+00:00" not in text and "expired at" not in text

    def test_a_plan_that_is_not_known_is_named(self) -> None:
        text = describe_inactive("Meridian Pumps", "starter", None)

        assert text.startswith("The plan 'starter' of 'Meridian Pumps' is not active. ")
        assert PAUSED_ACTIONS in text


# ── With a database ───────────────────────────────────────────────────


@dataclass
class Stack:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CORTEX_LLM_API_KEY", "not-a-real-key-used-only-in-tests")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "https://model-gateway.test/v1")
    monkeypatch.setenv("CORTEX_LLM_MODEL", "test-only-model")
    get_settings.cache_clear()
    auth_module._SIGNUPS.reset()
    auth_module._RESET_REQUESTS.reset()
    yield
    auth_module._SIGNUPS.reset()
    auth_module._RESET_REQUESTS.reset()
    get_settings.cache_clear()


@pytest.fixture
async def stack(request: pytest.FixtureRequest, deployed: None) -> AsyncIterator[Stack]:
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
        (None, "contact_requests"),
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
    transport = ASGITransport(app=app, client=("198.51.100.7", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Stack(client=client, sessions=maker)
    await engine.dispose()


@dataclass
class Customer:
    email: str
    slug: str
    workspace_id: uuid.UUID
    headers: dict[str, str]


async def _customer(stack: Stack, tag: str) -> Customer:
    email = f"plans-{tag}-{uuid.uuid4().hex[:10]}@example.com"
    signed_up = await stack.client.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": f"Plans {tag} {uuid.uuid4().hex[:6]}",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert signed_up.status_code == 201, signed_up.text
    body = signed_up.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = (await stack.client.get("/api/v1/auth/me", headers=headers)).json()
    return Customer(
        email=email,
        slug=me["organization"]["slug"],
        workspace_id=uuid.UUID(body["workspace_id"]),
        headers=headers,
    )


async def _me(stack: Stack, customer: Customer) -> dict[str, Any]:
    answer = await stack.client.get("/api/v1/auth/me", headers=customer.headers)
    assert answer.status_code == 200, answer.text
    organization: dict[str, Any] = answer.json()["organization"]
    return organization


async def _end_trial(stack: Stack, customer: Customer, *, days_ago: int = 1) -> datetime:
    ended = datetime.now(UTC) - timedelta(days=days_ago)
    async with stack.sessions() as session:
        org = await operator.find_organization(session, slug=customer.slug)
        org.plan = "trial"
        org.trial_ends_at = ended
        await session.commit()
    return ended


async def _gate(stack: Stack, customer: Customer) -> None:
    """The check the task routes run before creating, running or approving."""
    service = EntitlementService(session_factory=stack.sessions)
    await service.check_subscription(workspace_id=customer.workspace_id)


class TestWhatTheSiteIsTold:
    async def test_a_new_account_is_on_a_running_seven_day_trial(self, stack: Stack) -> None:
        customer = await _customer(stack, "new")

        organization = await _me(stack, customer)

        assert organization["plan"] == "trial"
        assert organization["subscription_active"] is True
        ends = datetime.fromisoformat(organization["trial_ends_at"])
        assert timedelta(days=6, hours=23) < ends - datetime.now(UTC) <= timedelta(days=7)

    async def test_after_the_trial_the_user_still_signs_in_and_is_told_it_ended(
        self, stack: Stack
    ) -> None:
        customer = await _customer(stack, "ended")
        await _end_trial(stack, customer)

        # Signing in and reading the account still work ...
        signed_in = await stack.client.post(
            "/api/v1/auth/login", json={"email": customer.email, "password": PASSWORD}
        )
        assert signed_in.status_code == 200, signed_in.text
        organization = await _me(stack, customer)
        # ... and the answer says the plan is not active, so the site can explain.
        assert organization["plan"] == "trial"
        assert organization["subscription_active"] is False

        # The verdict is the gate's own: the same organization is refused there.
        with pytest.raises(EntitlementDenied) as refused:
            await _gate(stack, customer)
        assert refused.value.http_status == 402
        assert refused.value.message.startswith("The trial of 'Plans ended ")
        assert PAUSED_ACTIONS in refused.value.message

    async def test_a_paid_plan_is_active_whatever_the_old_trial_date_says(
        self, stack: Stack
    ) -> None:
        customer = await _customer(stack, "paid")
        await _end_trial(stack, customer, days_ago=30)
        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            await operator.set_plan(session, org, "pro")

        organization = await _me(stack, customer)

        assert organization["plan"] == "pro"
        assert organization["subscription_active"] is True
        await _gate(stack, customer)


class TestTheOperatorScript:
    async def test_extending_an_ended_trial_lifts_the_block(self, stack: Stack) -> None:
        customer = await _customer(stack, "extend")
        await _end_trial(stack, customer, days_ago=3)
        with pytest.raises(EntitlementDenied):
            await _gate(stack, customer)

        moment = datetime.now(UTC)
        async with stack.sessions() as session:
            org = await operator.find_organization(session, email=customer.email.upper())
            change = await operator.extend_trial(
                session, org, 14, note="asked by phone", now=moment
            )

        # An ended trial restarts from now, not from the old end date.
        organization = await _me(stack, customer)
        assert datetime.fromisoformat(organization["trial_ends_at"]) == moment + timedelta(days=14)
        assert organization["subscription_active"] is True
        await _gate(stack, customer)
        assert change.organization == customer.slug
        assert change.before.startswith("trial, ended ")
        assert change.after.startswith("trial, ends ")

    async def test_extending_a_running_trial_adds_to_its_end_date(self, stack: Stack) -> None:
        customer = await _customer(stack, "running")
        before = datetime.fromisoformat((await _me(stack, customer))["trial_ends_at"])

        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            await operator.extend_trial(session, org, 10)

        after = datetime.fromisoformat((await _me(stack, customer))["trial_ends_at"])
        assert after == before + timedelta(days=10)

    @pytest.mark.parametrize("days", [None, 0, -5, 366])
    async def test_the_length_of_an_extension_is_bounded(
        self, stack: Stack, days: int | None
    ) -> None:
        customer = await _customer(stack, "bounds")
        ended = await _end_trial(stack, customer)

        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            with pytest.raises(operator.OperatorError, match="--days"):
                await operator.extend_trial(session, org, days)

        organization = await _me(stack, customer)
        assert datetime.fromisoformat(organization["trial_ends_at"]) == ended
        assert organization["subscription_active"] is False

    async def test_only_a_trial_can_be_extended(self, stack: Stack) -> None:
        customer = await _customer(stack, "notrial")
        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            await operator.set_plan(session, org, "free")
            with pytest.raises(operator.OperatorError, match="not a trial"):
                await operator.extend_trial(session, org, 7)

        assert (await _me(stack, customer))["plan"] == "free"

    async def test_a_plan_can_be_set_and_a_trial_restarted(self, stack: Stack) -> None:
        customer = await _customer(stack, "plans")
        await _end_trial(stack, customer)
        moment = datetime.now(UTC)

        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            to_enterprise = await operator.set_plan(session, org, "enterprise", now=moment)
            assert (to_enterprise.before[:12], to_enterprise.after) == (
                "trial, ended",
                "enterprise",
            )
            assert (await _me(stack, customer))["subscription_active"] is True

            back = await operator.set_plan(session, org, "trial", days=30, now=moment)
            assert back.before == "enterprise" and back.after.startswith("trial, ends ")

        organization = await _me(stack, customer)
        assert organization["plan"] == "trial"
        assert datetime.fromisoformat(organization["trial_ends_at"]) == moment + timedelta(days=30)

    async def test_a_plan_change_that_makes_no_sense_changes_nothing(self, stack: Stack) -> None:
        customer = await _customer(stack, "refused")
        before = await _me(stack, customer)

        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            with pytest.raises(operator.OperatorError, match="unknown plan"):
                await operator.set_plan(session, org, "platinum")
            with pytest.raises(operator.OperatorError, match="--days is required"):
                await operator.set_plan(session, org, "trial")
            with pytest.raises(operator.OperatorError, match="does not end"):
                await operator.set_plan(session, org, "pro", days=30)

        assert await _me(stack, customer) == before

    async def test_an_organization_is_found_by_slug_or_by_a_users_address(
        self, stack: Stack
    ) -> None:
        customer = await _customer(stack, "found")

        async with stack.sessions() as session:
            by_slug = await operator.find_organization(session, slug=customer.slug.upper())
            by_email = await operator.find_organization(session, email=customer.email)
            assert by_slug.id == by_email.id
            assert await operator.count_users(session, by_slug) == 1

            with pytest.raises(operator.OperatorError, match="no organization with the slug"):
                await operator.find_organization(session, slug="no-such-organization")
            with pytest.raises(operator.OperatorError, match="no organization has a user"):
                await operator.find_organization(session, email="nobody@example.com")
            with pytest.raises(operator.OperatorError, match="exactly one of"):
                await operator.find_organization(session)
            with pytest.raises(operator.OperatorError, match="exactly one of"):
                await operator.find_organization(session, slug="a", email="b@example.com")

    async def test_the_paused_list_shows_ended_trials_only(self, stack: Stack) -> None:
        running = await _customer(stack, "listrun")
        ended = await _customer(stack, "listend")
        await _end_trial(stack, ended)

        async with stack.sessions() as session:
            paused = {o.slug for o in await operator.list_organizations(session, only_ended=True)}
            everyone = {o.slug for o in await operator.list_organizations(session, limit=100_000)}
            ended_org = await operator.find_organization(session, slug=ended.slug)
            text = operator.format_organization(ended_org, 1)

        assert ended.slug in paused and running.slug not in paused
        assert {running.slug, ended.slug} <= everyone
        assert "State        : paused" in text
        assert PAUSED_ACTIONS in text

    async def test_every_change_is_in_the_organizations_audit_trail(self, stack: Stack) -> None:
        customer = await _customer(stack, "audit")
        await _end_trial(stack, customer)
        async with stack.sessions() as session:
            org = await operator.find_organization(session, slug=customer.slug)
            await operator.extend_trial(session, org, 14, note="  pilot agreed on 18 Nov  ")
            await operator.set_plan(session, org, "pro")
            organization_id = str(org.id)

        async with stack.sessions() as session:
            events = (
                (
                    await session.execute(
                        select(AuditEvent)
                        .where(AuditEvent.subject_id == organization_id)
                        .order_by(AuditEvent.occurred_at.asc())
                    )
                )
                .scalars()
                .all()
            )

        assert [e.event_type for e in events] == ["billing.trial_extended", "billing.plan_changed"]
        extended, changed = events
        assert extended.actor_type == changed.actor_type == "operator"
        # Filed under the customer's own workspace, where their admin can read it.
        assert extended.workspace_id == str(customer.workspace_id)
        assert extended.tenant_id == organization_id
        assert extended.payload["note"] == "pilot agreed on 18 Nov"
        assert extended.payload["before"].startswith("trial, ended ")
        assert extended.payload["after"].startswith("trial, ends ")
        assert (changed.payload["before"][:11], changed.payload["after"]) == ("trial, ends", "pro")


class TestTheDailyInbox:
    async def test_it_counts_what_waits_for_a_person(self, stack: Stack) -> None:
        async with stack.sessions() as session:
            before = await operator_inbox.read_inbox(session)

        asks_reset = await _customer(stack, "inboxreset")
        trial_over = await _customer(stack, "inboxover")
        await _end_trial(stack, trial_over)
        asked = await stack.client.post(
            "/api/v1/auth/reset/request", json={"email": asks_reset.email}
        )
        assert asked.status_code == 200, asked.text
        async with stack.sessions() as session:
            session.add(
                ContactRequest(
                    reference=f"REQ-{uuid.uuid4().hex[:8].upper()}",
                    topic="security",
                    full_name="Dev Mehta",
                    email="dev.mehta@example.com",
                    message="A report.",
                    details={},
                    consent=True,
                    status=STATUS_NEW,
                )
            )
            await session.commit()

        async with stack.sessions() as session:
            after = await operator_inbox.read_inbox(session)

        assert after.site_requests == before.site_requests + 1
        assert after.reset_requests == before.reset_requests + 1
        assert after.paused_organizations == before.paused_organizations + 1
        assert after.needs_a_person is True

    def test_the_printout_names_the_command_for_each_line(self) -> None:
        inbox = operator_inbox.Inbox(
            site_requests=3,
            oldest_site_request=NOW - timedelta(days=2, hours=1),
            reset_requests=1,
            oldest_reset_request=NOW - timedelta(hours=5),
            paused_organizations=2,
        )

        text = operator_inbox.format_inbox(inbox, NOW)

        assert "Site requests unanswered : 3, oldest 2 days ago" in text
        assert "python scripts/contact_requests.py list" in text
        assert "Password resets waiting  : 1, oldest 5 h ago" in text
        assert "python scripts/admin_users.py reset-requests" in text
        assert "Paused organizations     : 2 (for information)" in text
        assert "python scripts/admin_orgs.py list --ended" in text
        assert "Nothing needs an answer." not in text

    def test_an_empty_inbox_says_so_and_paused_trials_alone_do_not_alert(self) -> None:
        inbox = operator_inbox.Inbox(
            site_requests=0,
            oldest_site_request=None,
            reset_requests=0,
            oldest_reset_request=None,
            paused_organizations=4,
        )

        assert inbox.needs_a_person is False
        assert "Nothing needs an answer." in operator_inbox.format_inbox(inbox, NOW)
        assert operator_inbox.build_parser().parse_args(["--check"]).check is True
        assert operator_inbox.build_parser().parse_args([]).check is False


class TestTheCommandLine:
    @pytest.mark.parametrize(
        "argv",
        [
            ["list"],
            ["list", "--ended"],
            ["show", "--email", "user@example.com"],
            ["extend-trial", "--email", "user@example.com", "--days", "14"],
            ["set-plan", "--org", "meridian-pumps", "--plan", "pro"],
            ["set-plan", "--org", "meridian-pumps", "--plan", "trial", "--days", "30"],
            ["extend-trial", "--org", "meridian-pumps", "--days", "7", "--note", "why"],
        ],
    )
    def test_every_documented_command_is_accepted(self, argv: list[str]) -> None:
        args = operator.build_parser().parse_args(argv)

        assert args.command == argv[0]

    def test_a_plan_outside_the_list_is_refused_before_anything_runs(self) -> None:
        with pytest.raises(SystemExit):
            operator.build_parser().parse_args(["set-plan", "--org", "a", "--plan", "platinum"])

    def test_the_plan_phrase_reads_the_same_everywhere(self) -> None:
        ends = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)

        assert operator.describe_plan("trial", ends, now=NOW) == "trial, ends 2026-11-25 09:00 UTC"
        assert (
            operator.describe_plan("trial", ends, now=ends + timedelta(days=1))
            == "trial, ended 2026-11-25 09:00 UTC"
        )
        assert operator.describe_plan("trial", None, now=NOW) == "trial, no end date"
        assert operator.describe_plan("pro", ends, now=NOW) == "pro"
        assert operator.describe_plan("starter", None, now=NOW) == (
            "starter (not a known plan: paused)"
        )


# Referenced so the models stay registered on Base.metadata for the fixture.
_ = (Organization, User, Workspace)
