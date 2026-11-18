"""The older upload route, ``POST /api/v1/mvp/ingest``.

Two faults, both found by sending it a file:

* every valid upload ended in a server error, because the staged copy was
  opened write-only and then read back;
* the route's form offered a field holding the server's whole settings object
  (file store address and keys, database address, signing secret), because a
  helper with an optional ``settings`` argument was used as a request
  dependency. A form field can only carry text, so it could not be filled in,
  but the file store client is created once per process by whoever asks first:
  that choice must not be expressible in a request at all.
"""

from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.common.enums import MvpDatasetType
from app.modules.ingestion import service as ingestion_service

CSV = (
    b"name,country,tier,lead_time_days\nAcme Metals,IN,tier_1,12\nBorealis Plastics,DE,tier_2,30\n"
)


class _Session:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


class _LogRepository:
    def __init__(self, session, workspace_id) -> None:
        self.session = session
        self.workspace_id = workspace_id

    async def create(self, log):
        log.id = uuid4()
        return log

    async def mark_running(self, ingestion_id) -> None:
        return None


class _Storage:
    def __init__(self) -> None:
        self.stored: list[tuple[str, bytes, str]] = []

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.stored.append((key, data, content_type))


@pytest.fixture
def staged(monkeypatch):
    """The upload service with the database and the row writer replaced."""
    seen: dict = {}

    async def apply_rows(*, log, rows, strict, **kwargs):
        seen["rows"] = rows
        seen["strict"] = strict
        return log

    monkeypatch.setattr(ingestion_service, "IngestionLogRepository", _LogRepository)
    monkeypatch.setattr(ingestion_service, "_apply_ingestion_rows", apply_rows)
    return seen


def _upload(data: bytes, name: str = "suppliers.csv") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, size=len(data))


@pytest.mark.asyncio
async def test_an_uploaded_file_is_read_stored_and_handed_on(staged) -> None:
    storage = _Storage()
    workspace_id = uuid4()

    log = await ingestion_service.ingest_csv_streaming(
        session=_Session(),
        workspace_id=workspace_id,
        user_id=None,
        storage=storage,
        dataset_type=MvpDatasetType.SUPPLIERS,
        file=_upload(CSV),
        file_name="suppliers.csv",
    )

    # The file store received exactly what was sent, under this workspace.
    assert len(storage.stored) == 1
    key, stored_bytes, content_type = storage.stored[0]
    assert stored_bytes == CSV
    assert content_type == "text/csv"
    assert key.startswith(f"cortex/ingestion/{workspace_id}/")
    assert key.endswith("/suppliers.csv")
    # The rows that go on to validation are the rows of the file.
    assert [row["name"] for row in staged["rows"]] == ["Acme Metals", "Borealis Plastics"]
    assert staged["rows"][0]["tier"] == "tier_1"
    # The record of the upload carries the real size and fingerprint.
    assert log.file_size_bytes == len(CSV)
    assert log.file_sha256 == hashlib.sha256(CSV).hexdigest()


@pytest.mark.asyncio
async def test_a_file_larger_than_one_read_is_kept_whole(staged) -> None:
    """The upload is read a megabyte at a time; nothing may be lost between reads."""
    rows = b"".join(b"Supplier %06d,IN,tier_1,12\n" % n for n in range(60_000))
    data = b"name,country,tier,lead_time_days\n" + rows
    assert len(data) > 1024 * 1024
    storage = _Storage()

    log = await ingestion_service.ingest_csv_streaming(
        session=_Session(),
        workspace_id=uuid4(),
        user_id=None,
        storage=storage,
        dataset_type=MvpDatasetType.SUPPLIERS,
        file=_upload(data),
        file_name="many.csv",
    )

    assert storage.stored[0][1] == data
    assert len(staged["rows"]) == 60_000
    assert staged["rows"][-1]["name"] == "Supplier 059999"
    assert log.file_sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_a_file_over_the_limit_is_refused_and_not_stored(staged, monkeypatch) -> None:
    monkeypatch.setattr(
        ingestion_service, "get_settings", lambda: SimpleNamespace(upload_max_bytes=40)
    )
    storage = _Storage()

    with pytest.raises(HTTPException) as refused:
        await ingestion_service.ingest_csv_streaming(
            session=_Session(),
            workspace_id=uuid4(),
            user_id=None,
            storage=storage,
            dataset_type=MvpDatasetType.SUPPLIERS,
            file=_upload(CSV),
            file_name="suppliers.csv",
        )

    assert refused.value.status_code == 413
    assert storage.stored == []
    assert "rows" not in staged


def _api_document() -> dict:
    from app.main import app

    return app.openapi()


def test_the_upload_form_asks_only_for_the_file_and_where_it_goes() -> None:
    document = _api_document()
    form = document["components"]["schemas"]["Body_post_ingest_api_v1_mvp_ingest_post"]
    assert sorted(form["properties"]) == ["dataset_type", "file", "strict", "workspace_id"]


def test_no_request_can_carry_the_servers_settings() -> None:
    """No route, form or query may be described in terms of the settings object.

    The API document lists every model a request or an answer can contain. The
    settings object holds the signing secret, the database address and the file
    store keys; if it shows up there, some route reads it from the caller.
    """
    from app.config import Settings

    document = _api_document()
    schemas = document["components"]["schemas"]
    assert "Settings" not in schemas
    setting_names = set(Settings.model_fields)
    telltale = {"jwt_secret", "db_dsn", "s3_secret_key", "llm_api_key"}
    assert telltale <= setting_names
    for name, schema in schemas.items():
        described = set(schema.get("properties") or {})
        assert not (described & telltale), f"{name} exposes server settings: {described & telltale}"
