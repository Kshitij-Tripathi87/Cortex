"""Program Q3 — Canonical Entity Layer & Entity Resolution.

Resolves heterogeneous source records into canonical, uniquely identifiable enterprise entities:
- Customer (canonical_customer_id)
- Seller (canonical_seller_id)
- Product (canonical_product_id)
- Order (canonical_order_id)
- Location (canonical_location_id)
- Route (canonical_route_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7


@dataclass
class CanonicalEntity:
    canonical_id: str
    entity_type: str  # "CUSTOMER" | "SUPPLIER" | "PRODUCT" | "ORDER" | "LOCATION" | "ROUTE" ("SELLER" is an ingest-time alias of "SUPPLIER")
    source_identifiers: dict[str, str]  # system_name -> source_id
    attributes: dict[str, Any]
    confidence_score: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "entity_type": self.entity_type,
            "source_identifiers": self.source_identifiers,
            "attributes": self.attributes,
            "confidence_score": self.confidence_score,
            "created_at": self.created_at.isoformat(),
        }


class EntityResolutionEngine:
    """Maintains mapping between raw external IDs and canonical Nexus entities."""

    def __init__(self) -> None:
        self._entities: dict[str, CanonicalEntity] = {}  # canonical_id -> CanonicalEntity
        self._source_index: dict[tuple[str, str], str] = {}  # (system, source_id) -> canonical_id

    def resolve_seller(
        self,
        source_id: str,
        zip_code: str,
        city: str,
        state: str,
        system_name: str = "olist",
    ) -> CanonicalEntity:
        key = (system_name, source_id)
        if key in self._source_index:
            return self._entities[self._source_index[key]]

        canonical_id = f"seller_{uuid7().replace('-', '')}"
        entity = CanonicalEntity(
            canonical_id=canonical_id,
            entity_type="SUPPLIER",  # canonical type; "SELLER" is normalized to this at ingest
            source_identifiers={system_name: source_id},
            attributes={"zip_code": zip_code, "city": city, "state": state},
        )
        self._entities[canonical_id] = entity
        self._source_index[key] = canonical_id
        return entity

    def resolve_customer(
        self,
        source_id: str,
        zip_code: str,
        city: str,
        state: str,
        system_name: str = "olist",
    ) -> CanonicalEntity:
        key = (system_name, source_id)
        if key in self._source_index:
            return self._entities[self._source_index[key]]

        canonical_id = f"cust_{uuid7().replace('-', '')}"
        entity = CanonicalEntity(
            canonical_id=canonical_id,
            entity_type="CUSTOMER",
            source_identifiers={system_name: source_id},
            attributes={"zip_code": zip_code, "city": city, "state": state},
        )
        self._entities[canonical_id] = entity
        self._source_index[key] = canonical_id
        return entity

    def resolve_product(
        self,
        source_id: str,
        category: str,
        weight_g: float,
        system_name: str = "olist",
    ) -> CanonicalEntity:
        key = (system_name, source_id)
        if key in self._source_index:
            return self._entities[self._source_index[key]]

        canonical_id = f"prod_{uuid7().replace('-', '')}"
        entity = CanonicalEntity(
            canonical_id=canonical_id,
            entity_type="PRODUCT",
            source_identifiers={system_name: source_id},
            attributes={"category": category, "weight_g": weight_g},
        )
        self._entities[canonical_id] = entity
        self._source_index[key] = canonical_id
        return entity

    def get_entity(self, canonical_id: str) -> CanonicalEntity | None:
        return self._entities.get(canonical_id)

    def total_entities_count(self) -> int:
        return len(self._entities)
