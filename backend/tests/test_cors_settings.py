"""Which sites may call the API from a browser (CORTEX_CORS_ALLOWED_ORIGINS).

The deployment files never set the variable and the default lists only a
developer machine, so a deployed site on its own address could not sign
anyone in: the browser refused every call. The variable also had to be a JSON
list although its description said "comma-separated", and PATCH was not an
allowed method although the API serves a PATCH route.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, cors_allows_only_local_sites, get_settings
from app.main import create_app, warn_if_no_site_may_call

SECRET = "cors-test-secret-0123456789abcdef0123456789"
SITE = "https://app.example.com"


def _local(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in ("ALLOWED_ORIGINS", "ALLOWED_METHODS", "ALLOWED_HEADERS"):
        monkeypatch.delenv(f"CORTEX_CORS_{name}", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None, env="test")  # type: ignore[call-arg]


def _deployed(**changes: object) -> Settings:
    values: dict[str, object] = {
        "env": "staging",
        "jwt_secret": SECRET,
        "llm_provider": "openai_compatible",
        "llm_model": "configured-model",
        "llm_api_key": "configured-key",
        "llm_base_url": "https://model-gateway.example/v1",
    }
    values.update(changes)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestHowTheVariableIsWritten:
    def test_the_default_suits_a_developer_machine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _local(monkeypatch)

        assert settings.cors_allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]

    @pytest.mark.parametrize(
        ("written", "read"),
        [
            (SITE, [SITE]),
            (f" {SITE} , https://www.example.com ", [SITE, "https://www.example.com"]),
            # A JSON list, the only form that used to be accepted, still works.
            (f'["{SITE}"]', [SITE]),
            # What a browser sends is lower case and has no trailing slash.
            ("HTTPS://App.Example.com/", [SITE]),
            (f"{SITE},{SITE}/", [SITE]),
            (
                "http://localhost:3000,https://app.example.com:8443",
                ["http://localhost:3000", "https://app.example.com:8443"],
            ),
        ],
    )
    def test_addresses_are_read_as_an_operator_writes_them(
        self, monkeypatch: pytest.MonkeyPatch, written: str, read: list[str]
    ) -> None:
        settings = _local(monkeypatch, CORTEX_CORS_ALLOWED_ORIGINS=written)

        assert settings.cors_allowed_origins == read

    @pytest.mark.parametrize(
        "written",
        ["app.example.com", f"{SITE}/app", f"{SITE}?next=1", "ftp://files.example.com"],
    )
    def test_something_that_is_not_a_site_address_stops_start_up(
        self, monkeypatch: pytest.MonkeyPatch, written: str
    ) -> None:
        """It would never match what a browser sends, so it is not accepted in silence."""
        with pytest.raises(ValueError, match="is not a site address"):
            _local(monkeypatch, CORTEX_CORS_ALLOWED_ORIGINS=written)

    def test_methods_can_be_written_with_commas_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _local(monkeypatch, CORTEX_CORS_ALLOWED_METHODS="GET, POST")

        assert settings.cors_allowed_methods == ["GET", "POST"]


class TestDeployedEnvironments:
    def test_any_website_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must name the site's own address"):
            _deployed(cors_allowed_origins=["*"])

    def test_a_named_site_is_accepted(self) -> None:
        assert _deployed(cors_allowed_origins=[SITE]).cors_allowed_origins == [SITE]

    def test_a_local_environment_may_allow_any_website(self) -> None:
        settings = Settings(_env_file=None, env="dev", cors_allowed_origins=["*"])  # type: ignore[call-arg]

        assert settings.cors_allowed_origins == ["*"]


class TestTheStartUpWarning:
    @pytest.mark.parametrize(
        ("origins", "local_only"),
        [
            (["http://localhost:3000", "http://127.0.0.1:3000"], True),
            ([], True),
            (["http://localhost:3000", SITE], False),
            ([SITE], False),
        ],
    )
    def test_whether_only_a_developer_machine_is_listed(
        self, origins: list[str], local_only: bool
    ) -> None:
        assert cors_allows_only_local_sites(origins) is local_only

    def test_a_deployment_without_a_site_address_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="cortex.startup"):
            warned = warn_if_no_site_may_call(_deployed())

        assert warned is True
        assert "CORTEX_CORS_ALLOWED_ORIGINS names no site address" in caplog.text
        assert "http://localhost:3000" in caplog.text

    def test_a_deployment_with_its_site_address_is_quiet(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="cortex.startup"):
            warned = warn_if_no_site_may_call(_deployed(cors_allowed_origins=[SITE]))

        assert warned is False
        assert caplog.text == ""

    def test_a_developer_machine_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="cortex.startup"):
            warned = warn_if_no_site_may_call(_local(monkeypatch))

        assert warned is False


@pytest.fixture
def site_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncClient]:
    """The real application, configured for a site on its own address."""
    monkeypatch.setenv("CORTEX_CORS_ALLOWED_ORIGINS", SITE)
    get_settings.cache_clear()
    try:
        app = create_app()
        yield AsyncClient(transport=ASGITransport(app=app), base_url="http://api.test")
    finally:
        get_settings.cache_clear()


def _preflight(origin: str, method: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "authorization,content-type",
    }


@pytest.mark.asyncio
class TestWhatABrowserIsTold:
    async def test_the_configured_site_may_call_the_api(self, site_client: AsyncClient) -> None:
        async with site_client as client:
            response = await client.options("/api/v1/auth/login", headers=_preflight(SITE, "POST"))

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == SITE
        assert "authorization" in response.headers["access-control-allow-headers"].lower()

    async def test_another_website_may_not(self, site_client: AsyncClient) -> None:
        async with site_client as client:
            response = await client.options(
                "/api/v1/auth/login", headers=_preflight("https://elsewhere.example", "POST")
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    async def test_a_developer_machine_is_no_longer_listed_once_a_site_is(
        self, site_client: AsyncClient
    ) -> None:
        async with site_client as client:
            response = await client.options(
                "/api/v1/auth/login", headers=_preflight("http://localhost:3000", "POST")
            )

        assert response.status_code == 400

    async def test_the_patch_route_can_be_called_from_the_site(
        self, site_client: AsyncClient
    ) -> None:
        """Risk triage is a PATCH; the method was missing from the allowed list."""
        async with site_client as client:
            response = await client.options(
                "/api/v1/nexus/risks/some-risk", headers=_preflight(SITE, "PATCH")
            )

        assert response.status_code == 200
        assert "PATCH" in response.headers["access-control-allow-methods"]
