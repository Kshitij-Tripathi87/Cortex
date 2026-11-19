"""Helpers shared by the entity services."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ErrorDetail


def apply_changes(record: Any, changes: Mapping[str, Any]) -> list[str]:
    """Set the given attributes and return the names of those that actually changed."""
    changed: list[str] = []
    for name, value in changes.items():
        if getattr(record, name) != value:
            setattr(record, name, value)
            changed.append(name)
    return changed


def duplicate_key_error(entity: str, field: str) -> ConflictError:
    return ConflictError(
        f"A {entity} with this {field.replace('_', ' ')} already exists in the workspace.",
        code="DUPLICATE_NATURAL_KEY",
        details=[
            ErrorDetail(
                code="DUPLICATE_NATURAL_KEY",
                message="The value is already in use.",
                field=field,
            )
        ],
    )


@contextmanager
def unique_key_guard(session: Session, entity: str, field: str) -> Iterator[None]:
    """Turn a unique-constraint violation on flush into DUPLICATE_NATURAL_KEY.

    Services check the natural key before inserting. This covers the case
    where another transaction inserted the same key in between.
    """
    try:
        yield
        session.flush()
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise duplicate_key_error(entity, field) from exc
        # Anything else (a CHECK or a foreign key) is not a duplicate and must
        # not be reported as one.
        raise
