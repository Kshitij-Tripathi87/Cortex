"""Small result types returned by services."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.models.enums import CanonicalEntityType, RowOutcome


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    """One bounded page of records and the total number that match."""

    items: Sequence[ItemT]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class Applied:
    """What applying one source record did to the canonical data."""

    entity_type: CanonicalEntityType
    entity_id: UUID
    outcome: RowOutcome
    # Versions appended as part of the record: plan or commitment versions.
    versions_created: int = 0
