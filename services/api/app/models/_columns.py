"""Column building blocks shared by the models."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow

ENUM_LENGTH = 40


def enum_type(enum_class: type[StrEnum], name: str) -> Enum:
    """A text column restricted to the values of ``enum_class`` by a CHECK constraint.

    Not a native PostgreSQL enum: adding a value later is an ordinary
    constraint change, and a downgrade has no type to drop.
    """
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=ENUM_LENGTH,
        values_callable=lambda members: [member.value for member in members],
    )


class UUIDPrimaryKeyMixin:
    """A UUID primary key assigned by the service; the database default is a backstop."""

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        sort_order=-10,  # first column of the table
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), sort_order=100
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        sort_order=101,
    )
