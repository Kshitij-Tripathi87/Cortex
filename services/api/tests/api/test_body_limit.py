"""Request bodies are bounded before they are buffered."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.body_limit import DEFAULT_MAX_BODY_BYTES
from app.main import create_app
from app.models import Workspace
from tests.conftest import error_of, make_settings

pytestmark = pytest.mark.db


def test_an_oversized_json_body_is_refused(client: TestClient, workspace: Workspace) -> None:
    body = b'{"code": "P1", "name": "' + b"x" * DEFAULT_MAX_BODY_BYTES + b'"}'

    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/projects",
        content=body,
        headers={"content-type": "application/json"},
    )

    error_of(response, 413, "REQUEST_TOO_LARGE")
    assert client.get(f"/api/v1/workspaces/{workspace.id}/projects").json()["total"] == 0


def test_a_body_without_a_declared_length_is_counted_while_it_arrives(workspace: Workspace) -> None:
    """Chunked upload: no Content-Length to check, so the bytes are counted as they come."""
    app = create_app(make_settings(max_upload_size_mb=1))
    boundary = "nexus-test-boundary"

    def chunks() -> Iterator[bytes]:
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="entity_type"\r\n\r\nproject\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="p.csv"\r\n'
            "Content-Type: text/csv\r\n\r\nProject Code,Project Name\n"
        ).encode()
        for _ in range(40):
            yield b"P,x\n" * 16_384  # 64 KiB per chunk, 2.5 MiB in total
        yield f"\r\n--{boundary}--\r\n".encode()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{workspace.id}/ingestion/preview",
            content=chunks(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        batches = client.get(f"/api/v1/workspaces/{workspace.id}/ingestion/batches").json()

    assert "content-length" not in {key.lower() for key in response.request.headers}
    error_of(response, 413, "FILE_TOO_LARGE")
    assert batches["total"] == 0


def test_a_normal_request_passes_through(client: TestClient, workspace: Workspace) -> None:
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/projects", json={"code": "P1", "name": "x" * 150}
    )

    assert response.status_code == 201
