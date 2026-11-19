"""Every error leaves the API in one envelope, with a request id and no internals."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    ErrorDetail,
    FileTooLargeError,
    InvalidStateError,
    NotFoundError,
    UnsupportedFileError,
    ValidationFailedError,
    WorkspaceNotAvailableError,
)
from app.main import create_app
from tests.conftest import make_settings


class _Body(BaseModel):
    name: str = Field(min_length=1, max_length=5)
    quantity: int = Field(gt=0)


@pytest.fixture
def probe_app(settings: Settings) -> FastAPI:
    """The real application plus routes that fail in each known way."""
    app = create_app(settings)

    def boom() -> None:
        raise RuntimeError("secret detail: /etc/passwd SELECT * FROM workspaces")

    def conflict() -> None:
        raise ConflictError(
            "A project with this code already exists.",
            code="DUPLICATE_NATURAL_KEY",
            details=[ErrorDetail(code="DUPLICATE_NATURAL_KEY", message="Taken.", field="code")],
        )

    def raise_error(kind: str) -> None:
        errors = {
            "not-found": NotFoundError("The project was not found."),
            "workspace": WorkspaceNotAvailableError(),
            "state": InvalidStateError("Not committable.", code="BATCH_NOT_COMMITTABLE"),
            "validation": ValidationFailedError("Invalid."),
            "unsupported": UnsupportedFileError("Only CSV and XLSX files are accepted."),
            "too-large": FileTooLargeError("The file is too large."),
        }
        raise errors[kind]

    def echo(body: _Body) -> _Body:
        return body

    app.add_api_route("/_probe/boom", boom, methods=["GET"])
    app.add_api_route("/_probe/conflict", conflict, methods=["GET"])
    app.add_api_route("/_probe/error/{kind}", raise_error, methods=["GET"])
    app.add_api_route("/_probe/echo", echo, methods=["POST"])
    return app


@pytest.fixture
def probe(probe_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(probe_app) as client:
        yield client


def assert_envelope(response, status: int, code: str) -> dict:  # type: ignore[no-untyped-def]
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert error["message"]
    assert isinstance(error["details"], list)
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


def test_unknown_route(probe: TestClient) -> None:
    assert_envelope(probe.get("/api/v1/nothing-here"), 404, "NOT_FOUND")


def test_method_not_allowed(probe: TestClient) -> None:
    assert_envelope(probe.post("/health/live"), 405, "METHOD_NOT_ALLOWED")


def test_unexpected_error_is_generic_and_leaks_nothing(probe: TestClient) -> None:
    response = probe.get("/_probe/boom", headers={"X-Request-ID": "trace-0000-0001"})

    error = assert_envelope(response, 500, "INTERNAL_ERROR")
    assert error["request_id"] == "trace-0000-0001"
    assert error["details"] == []
    for leaked in ("secret detail", "/etc/passwd", "SELECT", "RuntimeError", "Traceback"):
        assert leaked not in response.text


def test_unexpected_error_is_logged_with_the_request_id(
    probe: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR", logger="app.error"):
        probe.get("/_probe/boom")

    records = [record for record in caplog.records if record.name == "app.error"]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_domain_error_with_details(probe: TestClient) -> None:
    error = assert_envelope(probe.get("/_probe/conflict"), 409, "DUPLICATE_NATURAL_KEY")

    assert error["details"] == [
        {"code": "DUPLICATE_NATURAL_KEY", "message": "Taken.", "field": "code"}
    ]


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not-found", 404, "NOT_FOUND"),
        ("workspace", 404, "WORKSPACE_NOT_AVAILABLE"),
        ("state", 409, "BATCH_NOT_COMMITTABLE"),
        ("validation", 422, "VALIDATION_ERROR"),
        ("unsupported", 415, "UNSUPPORTED_FILE"),
        ("too-large", 413, "FILE_TOO_LARGE"),
    ],
)
def test_each_domain_error_has_its_status(
    probe: TestClient, kind: str, status: int, code: str
) -> None:
    assert_envelope(probe.get(f"/_probe/error/{kind}"), status, code)


def test_request_validation_names_field_and_rule_but_not_the_value(probe: TestClient) -> None:
    response = probe.post("/_probe/echo", json={"name": "confidential-value", "quantity": 0})

    error = assert_envelope(response, 422, "VALIDATION_ERROR")
    assert {(detail["field"], detail["code"]) for detail in error["details"]} == {
        ("name", "VALUE_TOO_LONG"),
        ("quantity", "MUST_BE_POSITIVE"),
    }
    assert "confidential-value" not in response.text


def test_missing_field(probe: TestClient) -> None:
    error = assert_envelope(
        probe.post("/_probe/echo", json={"name": "ok"}), 422, "VALIDATION_ERROR"
    )

    assert error["details"] == [
        {"code": "REQUIRED_FIELD_MISSING", "message": "Field required", "field": "quantity"}
    ]


def test_malformed_json_is_a_400(probe: TestClient) -> None:
    response = probe.post(
        "/_probe/echo", content=b'{"name": ', headers={"content-type": "application/json"}
    )

    assert_envelope(response, 400, "MALFORMED_REQUEST")


def test_openapi_is_served_to_developers(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "Cortex Nexus API"
    assert {"/health/live", "/health/ready"} <= set(document["paths"])


def test_openapi_and_docs_are_not_served_outside_local_environments() -> None:
    app = create_app(make_settings(app_env="production", nexus_dev_workspace_id=None))

    with TestClient(app) as client:
        assert_envelope(client.get("/openapi.json"), 404, "NOT_FOUND")
        assert_envelope(client.get("/docs"), 404, "NOT_FOUND")
        assert client.get("/health/live").status_code == 200
