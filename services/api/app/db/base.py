"""The single declarative base and metadata registry of the service.

Every model inherits from :class:`Base`. Constraint and index names follow one
naming convention, so migrations are deterministic and a constraint can be
named in a test or an error log.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    """Base class of all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
