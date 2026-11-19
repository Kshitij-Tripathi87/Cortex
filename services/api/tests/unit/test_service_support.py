"""Helpers shared by the entity services: what a refused write is taken for."""

from typing import Any, cast

import psycopg.errors
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.services._support import apply_changes, unique_key_guard


class _Flush:
    """Stands in for a session whose flush is refused by the database, or is not."""

    def __init__(self, refusal: BaseException | None = None) -> None:
        self._refusal = refusal
        self.flushed = 0

    def flush(self) -> None:
        self.flushed += 1
        if self._refusal is not None:
            raise IntegrityError("INSERT INTO suppliers", {}, self._refusal)


def _session(refusal: BaseException | None = None) -> tuple[Session, _Flush]:
    stand_in = _Flush(refusal)
    return cast(Session, stand_in), stand_in


def test_a_unique_key_refused_on_flush_is_a_duplicate_of_the_natural_key() -> None:
    session, _ = _session(psycopg.errors.UniqueViolation("duplicate key"))

    with pytest.raises(ConflictError) as failure, unique_key_guard(session, "supplier", "code"):
        pass

    assert failure.value.code == "DUPLICATE_NATURAL_KEY"
    assert [detail.field for detail in failure.value.details] == ["code"]


@pytest.mark.parametrize(
    "refusal",
    [
        psycopg.errors.ForeignKeyViolation("violates foreign key"),
        psycopg.errors.CheckViolation("violates check"),
        psycopg.errors.NotNullViolation("null value"),
    ],
)
def test_any_other_refusal_is_not_reported_as_a_duplicate(refusal: BaseException) -> None:
    """A missing reference or a forbidden value says nothing about the key being taken."""
    session, _ = _session(refusal)

    with pytest.raises(IntegrityError) as failure, unique_key_guard(session, "supplier", "code"):
        pass

    assert failure.value.orig is refusal


def test_the_guard_flushes_so_that_the_refusal_happens_inside_it() -> None:
    session, stand_in = _session()

    with unique_key_guard(session, "supplier", "code"):
        assert stand_in.flushed == 0

    assert stand_in.flushed == 1


def test_apply_changes_reports_only_what_actually_changed() -> None:
    class Record:
        name = "Acme"
        city: Any = None

    record = Record()

    assert apply_changes(record, {"name": "Acme", "city": "Pune"}) == ["city"]
    assert (record.name, record.city) == ("Acme", "Pune")
