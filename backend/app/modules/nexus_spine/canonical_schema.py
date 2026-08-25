"""Canonical Schema — Generic Data Layer for the Nexus Spine.

Defines the universal entity/table/dataset vocabulary that the operational graph
and every downstream module consumes. No domain-specific knowledge (Olist,
SAP, Oracle) lives here — those are relegated to *adapters* that produce a
``CanonicalDataset``.

Core contracts:
    * ``EntityType`` — closed set of entity kinds Nexus can reason about.
    * ``CanonicalEntity`` — one resolved, uniquely identifiable entity.
    * ``CanonicalTable`` — a typed collection of rows for one entity type.
    * ``SchemaMapping`` — source-column → canonical-field dictionary.
    * ``CanonicalDataset`` — workspace-scoped bundle of canonical tables.
    * ``OlistAdapter`` — concrete adapter for Olist-shaped CSVs.

Design invariants (A1):
    * The graph engine knows nothing about Olist.
    * No invented nodes — Nexus builds only what uploaded data substantiates.
    * Every row preserves source provenance (file name, row number).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Entity type vocabulary
# ─────────────────────────────────────────────────────────────────────────────


class EntityType(StrEnum):
    """Closed set of entity types the Nexus spine can reason about.

    Not every dataset needs to contain every entity type. Nexus builds only
    what uploaded data substantiates — see ``CanonicalDataset``.
    """

    ORGANIZATION = "ORGANIZATION"
    WORKSPACE = "WORKSPACE"
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"  # synonymous with Seller in logistics datasets
    SELLER = "SELLER"
    PRODUCT = "PRODUCT"
    ORDER = "ORDER"
    ORDER_ITEM = "ORDER_ITEM"
    LOCATION = "LOCATION"
    WAREHOUSE = "WAREHOUSE"
    ROUTE = "ROUTE"
    SHIPMENT = "SHIPMENT"
    CARRIER = "CARRIER"
    INVENTORY = "INVENTORY"
    PURCHASE_ORDER = "PURCHASE_ORDER"


# ─────────────────────────────────────────────────────────────────────────────
# Canonical primitives
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CanonicalEntity:
    """One resolved, uniquely identifiable entity.

    ``source_identifiers`` maps source system → source id, so an entity can be
    traced back to the original row(s) across systems.
    """

    canonical_id: str
    entity_type: EntityType
    source_identifiers: dict[str, str]  # {source_name: source_id}
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 1.0
    source_file: str | None = None
    source_row: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "entity_type": self.entity_type,
            "source_identifiers": dict(self.source_identifiers),
            "attributes": dict(self.attributes),
            "confidence_score": self.confidence_score,
            "source_file": self.source_file,
            "source_row": self.source_row,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class CanonicalTable:
    """A typed collection of rows for one entity type.

    ``column_types`` captures the inferred type of each column
    (``"str"``, ``"int"``, ``"float"``, ``"datetime"``, ``"bool"``) so that
    downstream schema inference / graph construction can use it without
    re-scanning the data.

    ``rows`` retain the canonical field names after schema mapping, plus an
    injected ``_source_row`` (int) and ``_source_file`` (str) for provenance.
    """

    entity_type: EntityType
    rows: list[dict[str, Any]]
    column_types: dict[str, str] = field(default_factory=dict)
    source_file: str | None = None
    schema_mapping: SchemaMapping | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class SchemaMapping:
    """Source-column → canonical-field dictionary for one source file.

    ``source_name`` identifies the uploaded file (e.g. ``"olist_orders"``).
    ``field_mappings`` maps the source column name to a canonical field name
    (e.g. ``{"seller_id": "supplier_id", "order_status": "status"}``).
    """

    source_name: str
    entity_type: EntityType
    field_mappings: dict[str, str] = field(default_factory=dict)

    def canonical_field(self, source_column: str) -> str:
        return self.field_mappings.get(source_column, source_column)

    def apply(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return a new dict with source columns renamed to canonical fields."""
        return {self.canonical_field(k): v for k, v in row.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Dataset container
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CanonicalDataset:
    """Workspace-scoped bundle of canonical tables.

    ``tables`` is keyed by ``EntityType``. Not every entity type needs to be
    present — the dataset contains only what the uploaded data substantiates.

    ``schema_version`` is a hash of (workspace_id, entity types present,
    schema mappings applied) used to version the graph.
    """

    tables: dict[EntityType, CanonicalTable] = field(default_factory=dict)
    workspace_id: str = ""
    organization_id: str = ""
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = ""

    def entity_types(self) -> list[EntityType]:
        return sorted(self.tables.keys(), key=lambda e: e.value)

    def has(self, entity_type: EntityType) -> bool:
        return entity_type in self.tables

    def get(self, entity_type: EntityType) -> CanonicalTable | None:
        return self.tables.get(entity_type)

    def total_rows(self) -> int:
        return sum(len(t) for t in self.tables.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "uploaded_at": self.uploaded_at.isoformat(),
            "schema_version": self.schema_version,
            "tables": {
                et.value: {"row_count": t.row_count(), "source_file": t.source_file}
                for et, t in self.tables.items()
            },
            "total_rows": self.total_rows(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Olist adapter
# ─────────────────────────────────────────────────────────────────────────────

# Mapping of Olist CSV file stems → canonical entity type and field mapping.
# This is the ONLY place that knows about Olist. The graph engine never sees
# these file names.
_OLIST_MAPPINGS: list[tuple[str, EntityType, dict[str, str]]] = [
    (
        "olist_sellers_dataset.csv",
        EntityType.SUPPLIER,
        {
            "seller_id": "supplier_id",
            "seller_zip_code_prefix": "zip_code",
            "seller_city": "city",
            "seller_state": "state",
        },
    ),
    (
        "olist_customers_dataset.csv",
        EntityType.CUSTOMER,
        {
            "customer_id": "customer_id",
            "customer_unique_id": "unique_id",
            "customer_zip_code_prefix": "zip_code",
            "customer_city": "city",
            "customer_state": "state",
        },
    ),
    (
        "olist_orders_dataset.csv",
        EntityType.ORDER,
        {
            "order_id": "order_id",
            "customer_id": "customer_id",
            "order_status": "status",
            "order_purchase_timestamp": "purchase_timestamp",
            "order_approved_at": "approved_at",
            "order_delivered_carrier_date": "delivered_carrier_date",
            "order_delivered_customer_date": "delivered_customer_date",
            "order_estimated_delivery_date": "estimated_delivery_date",
        },
    ),
    (
        "olist_order_items_dataset.csv",
        EntityType.ORDER_ITEM,
        {
            "order_id": "order_id",
            "order_item_id": "item_id",
            "product_id": "product_id",
            "seller_id": "supplier_id",
            "shipping_limit_date": "shipping_limit_date",
            "price": "price",
            "freight_value": "freight_value",
        },
    ),
    (
        "olist_products_dataset.csv",
        EntityType.PRODUCT,
        {
            "product_id": "product_id",
            "product_category_name": "category",
            "product_name_lenght": "name_length",
            "product_description_lenght": "description_length",
            "product_photos_qty": "photos_qty",
            "product_weight_g": "weight_g",
            "product_length_cm": "length_cm",
            "product_height_cm": "height_cm",
            "product_width_cm": "width_cm",
        },
    ),
]


def _infer_type(sample: str) -> str:
    """Best-effort type inference from a string sample."""
    if not sample:
        return "str"
    try:
        int(sample)
        return "int"
    except ValueError:
        pass
    try:
        float(sample)
        return "float"
    except ValueError:
        pass
    if sample.lower() in {"true", "false"}:
        return "bool"
    return "str"


def _coerce(value: str, column_type: str) -> Any:
    """Coerce a string value to its inferred type."""
    if not value:
        return None
    if column_type == "int":
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return value
    if column_type == "float":
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if column_type == "bool":
        return value.lower() == "true"
    return value


class OlistAdapter:
    """Converts Olist-shaped CSV files into a ``CanonicalDataset``.

    This is the only component that knows about Olist file names and column
    conventions. The graph engine and every downstream consumer works with the
    resulting ``CanonicalDataset`` exclusively.
    """

    def from_data_dir(
        self,
        data_dir: str,
        *,
        workspace_id: str = "",
        organization_id: str = "",
        max_orders: int = 10_000,
    ) -> CanonicalDataset:
        """Read Olist CSVs from ``data_dir`` and produce a canonical dataset.

        ``max_orders`` caps the ORDER table for test/perf scenarios.
        ORDER_ITEM and PRODUCT rows are capped proportionally.
        """
        tables: dict[EntityType, CanonicalTable] = {}
        order_limit = 0  # running count of orders ingested

        for filename, entity_type, field_mappings in _OLIST_MAPPINGS:
            path = os.path.join(data_dir, filename)
            if not os.path.exists(path):
                continue

            mapping = SchemaMapping(
                source_name=os.path.splitext(filename)[0],
                entity_type=entity_type,
                field_mappings=field_mappings,
            )

            rows: list[dict[str, Any]] = []
            column_types: dict[str, str] = {}
            sample_row_read = False

            with open(path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row_idx, raw_row in enumerate(reader):
                    # Per-type row caps
                    if entity_type == EntityType.ORDER and order_limit >= max_orders:
                        break
                    if entity_type == EntityType.ORDER_ITEM and order_limit >= max_orders * 3:
                        break
                    if entity_type == EntityType.PRODUCT and row_idx >= max_orders * 2:
                        break

                    # Type inference from first row
                    if not sample_row_read:
                        for col, val in raw_row.items():
                            column_types[mapping.canonical_field(col)] = _infer_type(val)
                        sample_row_read = True

                    # Apply schema mapping + inject provenance
                    canonical_row = mapping.apply(raw_row)
                    canonical_row["_source_file"] = filename
                    canonical_row["_source_row"] = row_idx + 1

                    # Coerce numeric types
                    for col, ctype in column_types.items():
                        if col in canonical_row and ctype in {"int", "float", "bool"}:
                            canonical_row[col] = _coerce(str(canonical_row[col]), ctype)

                    rows.append(canonical_row)
                    if entity_type == EntityType.ORDER:
                        order_limit += 1

            if rows:
                tables[entity_type] = CanonicalTable(
                    entity_type=entity_type,
                    rows=rows,
                    column_types=column_types,
                    source_file=filename,
                    schema_mapping=mapping,
                )

        dataset = CanonicalDataset(
            tables=tables,
            workspace_id=workspace_id,
            organization_id=organization_id,
            uploaded_at=datetime.now(UTC),
        )
        dataset.schema_version = self._compute_schema_version(dataset)
        return dataset

    @staticmethod
    def _compute_schema_version(dataset: CanonicalDataset) -> str:
        """Stable hash over (workspace_id, entity types, schema mappings)."""
        import hashlib

        parts = [dataset.workspace_id, dataset.organization_id]
        for et in sorted(dataset.tables.keys(), key=lambda e: e.value):
            table = dataset.tables[et]
            parts.append(f"{et.value}:{table.source_file or ''}:{len(table.rows)}")
            if table.schema_mapping:
                for src, canon in sorted(table.schema_mapping.field_mappings.items()):
                    parts.append(f"{src}={canon}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]
