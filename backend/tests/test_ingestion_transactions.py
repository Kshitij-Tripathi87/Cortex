"""Transaction-boundary tests for strict and partial CSV ingestion."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.common.enums import MvpDatasetType
from app.modules.ingestion import service as ingestion_service


class _Row(BaseModel):
    name: str = Field(min_length=1)


class _LogRepository:
    def __init__(self, log: SimpleNamespace) -> None:
        self.log = log

    async def finalize(self, ingestion_id, **values) -> None:
        assert ingestion_id == self.log.id
        for key, value in values.items():
            setattr(self.log, key, value)

    async def get(self, ingestion_id):
        assert ingestion_id == self.log.id
        return self.log


@pytest_asyncio.fixture
async def transaction_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = MetaData()
    rows = Table(
        "ingestion_test_rows",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(64), nullable=False),
    )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session, rows
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_strict_ingestion_rolls_back_all_entity_rows(transaction_db, monkeypatch) -> None:
    session, rows = transaction_db
    monkeypatch.setitem(ingestion_service._DATASET_TO_SCHEMA, MvpDatasetType.SUPPLIERS, _Row)

    async def dispatch(*, session, row, **kwargs) -> None:
        await session.execute(insert(rows).values(name=row.name))

    monkeypatch.setattr(ingestion_service, "_dispatch_insert", dispatch)
    log = SimpleNamespace(id=uuid4())
    log_repo = _LogRepository(log)

    result = await ingestion_service._apply_ingestion_rows(
        session=session,
        log_repo=log_repo,
        log=log,
        workspace_id=uuid4(),
        dataset_type=MvpDatasetType.SUPPLIERS,
        rows=[{"name": "ACCEPTED-FIRST"}, {"name": ""}],
        strict=True,
    )

    stored = (await session.execute(select(rows.c.name))).scalars().all()
    assert stored == []
    assert result.status == "failed"
    assert result.rows_accepted == 0
    assert result.rows_rejected == 1
    assert "rolled back" in result.message


@pytest.mark.asyncio
async def test_partial_ingestion_isolates_a_failed_row_and_continues(
    transaction_db, monkeypatch
) -> None:
    session, rows = transaction_db
    monkeypatch.setitem(ingestion_service._DATASET_TO_SCHEMA, MvpDatasetType.SUPPLIERS, _Row)

    async def dispatch(*, session, row, **kwargs) -> None:
        await session.execute(insert(rows).values(name=row.name))
        if row.name == "DB-FAIL":
            raise ValueError("simulated persistence failure")

    monkeypatch.setattr(ingestion_service, "_dispatch_insert", dispatch)
    log = SimpleNamespace(id=uuid4())
    log_repo = _LogRepository(log)

    result = await ingestion_service._apply_ingestion_rows(
        session=session,
        log_repo=log_repo,
        log=log,
        workspace_id=uuid4(),
        dataset_type=MvpDatasetType.SUPPLIERS,
        rows=[{"name": "FIRST"}, {"name": "DB-FAIL"}, {"name": "LAST"}],
        strict=False,
    )

    stored = (await session.execute(select(rows.c.name).order_by(rows.c.id))).scalars().all()
    assert stored == ["FIRST", "LAST"]
    assert result.status == "partial"
    assert result.rows_accepted == 2
    assert result.rows_rejected == 1
    assert result.error_log[0]["phase"] == "persistence"
