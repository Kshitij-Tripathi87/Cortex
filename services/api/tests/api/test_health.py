"""Liveness, readiness and request ids."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.main import create_app
from tests.conftest import make_settings

UNREACHABLE = "postgresql+psycopg://nexus:nexus_test@127.0.0.1:1/cortex_nexus_test"


def test_liveness_reports_only_the_process(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.db
def test_readiness_is_ready_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {name: check["status"] for name, check in body["checks"].items()} == {
        "database": "ok",
        "migrations": "ok",
    }


def test_readiness_fails_and_liveness_holds_when_the_database_is_unreachable() -> None:
    app = create_app(make_settings(database_url=UNREACHABLE))

    with TestClient(app) as client:
        ready = client.get("/health/ready")
        live = client.get("/health/live")

    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "failed"
    assert body["checks"]["migrations"]["status"] == "failed"
    # The reason is a fixed text: no host, port, user or password.
    assert "127.0.0.1" not in ready.text
    assert "nexus_test" not in ready.text
    assert live.status_code == 200


@pytest.mark.db
def test_readiness_does_not_trust_a_connection_that_is_already_open(
    app: FastAPI, client: TestClient
) -> None:
    """PostgreSQL that refuses new clients is not ready, whatever the pool still holds.

    Found while building the service: during a shutdown PostgreSQL keeps
    serving connected clients and rejects new ones, and a probe that borrowed a
    pooled connection answered "ready". The state is reproduced here by
    closing the test database to new connections from the maintenance
    database. If this test is killed halfway, reopen it there with
    ``ALTER DATABASE cortex_nexus_test WITH ALLOW_CONNECTIONS true``.
    """
    database = app.state.database
    name = database.engine.url.database
    maintenance = create_engine(
        database.engine.url.set(database="postgres"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    # Leave one idle connection in the pool, as a served request would.
    with database.engine.connect() as warm_up:
        warm_up.execute(text("SELECT 1"))
    with maintenance.connect() as admin:
        admin.execute(text(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false'))
        try:
            with database.engine.connect() as pooled:
                still_served = pooled.execute(text("SELECT 1")).scalar_one()
            while_closed = client.get("/health/ready")
        finally:
            admin.execute(text(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS true'))
    maintenance.dispose()

    assert still_served == 1
    assert while_closed.status_code == 503
    assert while_closed.json()["checks"]["database"]["status"] == "failed"
    assert client.get("/health/ready").status_code == 200


def test_every_response_carries_a_generated_request_id(client: TestClient) -> None:
    first = client.get("/health/live").headers["X-Request-ID"]
    second = client.get("/health/live").headers["X-Request-ID"]

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_a_well_formed_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace-2026.11.19_0001"})

    assert response.headers["X-Request-ID"] == "trace-2026.11.19_0001"


@pytest.mark.parametrize("supplied", ["short", "has space in it", "x" * 200, "new\tline"])
def test_a_malformed_request_id_is_replaced(client: TestClient, supplied: str) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": supplied})

    assert response.headers["X-Request-ID"] != supplied
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
