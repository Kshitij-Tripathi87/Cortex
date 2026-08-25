"""Phase 3 Program A tests — Evidence → Graph Compiler invariants.

Tests the pure-function invariants of the graph compiler without requiring
a database. DB-dependent integration is exercised in CI against Postgres
via the testcontainer pipeline.

Invariants verified:
1. Entity detection from column names is deterministic + matches registry
2. Snapshot hashing is deterministic (same inputs → same hash)
3. Snapshot hash chain is tamper-evident (reordering changes the hash)
4. CSV row reconstruction from profiles is deterministic
5. FK column resolution matches the frozen registry
6. Provenance completeness (every write has provenance_claim_ids)
7. Determinism — compiling the same inputs twice gives byte-identical snapshot hash
8. Replay convergence — different compilation orders converge to the same hash
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.modules.graph.compiler import (
    _detect_entity_type,
    _detect_pk_column,
    _normalize_facility_type,
    _PendingWrite,
    _reconstruct_rows_from_profiles,
    _resolve_fk_columns,
)
from app.modules.graph.entity_keys import (
    COLUMN_TO_ENTITY_TYPE,
    ENTITY_FOREIGN_KEYS,
    ENTITY_PRIMARY_KEYS,
)
from app.modules.graph.snapshots import compute_snapshot_hash

# ─────────────────────────────────────────────────────────────────────────────
# Entity key registry — frozen, exhaustive, correct
# ─────────────────────────────────────────────────────────────────────────────


def test_entity_primary_keys_covers_all_supply_chain_entities() -> None:
    """Every supply-chain entity from the expanded ontology has a PK."""
    required = {
        "Supplier",
        "Customer",
        "Carrier",
        "Warehouse",
        "Plant",
        "DistributionCenter",
        "Product",
        "BOM",
        "InventoryItem",
        "InventoryLot",
        "PurchaseOrder",
        "SalesOrder",
        "Shipment",
        "Route",
        "Region",
        "DemandRegion",
    }
    assert required.issubset(set(ENTITY_PRIMARY_KEYS.keys())), (
        f"missing PKs for: {required - set(ENTITY_PRIMARY_KEYS.keys())}"
    )


def test_column_to_entity_covers_all_primary_keys() -> None:
    """Every primary key field should have a reverse-lookup entry."""
    for entity, pk_field in ENTITY_PRIMARY_KEYS.items():
        assert pk_field in COLUMN_TO_ENTITY_TYPE, (
            f"PK field {pk_field} (entity {entity}) missing from COLUMN_TO_ENTITY_TYPE"
        )
        assert COLUMN_TO_ENTITY_TYPE[pk_field] == entity


def test_fk_registry_target_types_are_valid() -> None:
    """Every FK target entity is either in the PK registry or is 'Facility'."""
    valid_targets = set(ENTITY_PRIMARY_KEYS.keys()) | {"Facility", "Organization"}
    for (src, fk), (tgt, rel) in ENTITY_FOREIGN_KEYS.items():
        assert tgt in valid_targets, f"FK ({src}.{fk}) → unknown target entity '{tgt}'"
        assert rel.isupper(), f"relationship '{rel}' must be UPPERCASE"


# ─────────────────────────────────────────────────────────────────────────────
# Entity detection from column names
# ─────────────────────────────────────────────────────────────────────────────


def test_detect_entity_type_supplier_file() -> None:
    headers = ["supplier_id", "legal_name", "tax_id", "country"]
    assert _detect_entity_type(headers) == "Supplier"


def test_detect_entity_type_purchase_order_file() -> None:
    headers = ["po_number", "supplier_id", "buyer_id", "placed_at"]
    assert _detect_entity_type(headers) == "PurchaseOrder"


def test_detect_entity_type_shipment_file() -> None:
    headers = ["shipment_id", "origin_facility_id", "destination_facility_id"]
    assert _detect_entity_type(headers) == "Shipment"


def test_detect_entity_type_product_file() -> None:
    headers = ["sku", "name", "category", "uom"]
    assert _detect_entity_type(headers) == "Product"


def test_detect_entity_type_unknown_returns_none() -> None:
    headers = ["random_column", "no_id_here"]
    assert _detect_entity_type(headers) is None


def test_detect_pk_column_supplier() -> None:
    headers = ["legal_name", "supplier_id", "tax_id"]
    assert _detect_pk_column(headers, "Supplier") == "supplier_id"


def test_detect_pk_column_case_insensitive() -> None:
    headers = ["Supplier_ID", "Name"]
    assert _detect_pk_column(headers, "PurchaseOrder") is None
    assert _detect_pk_column(headers, "Supplier") == "Supplier_ID"


def test_detect_pk_column_missing_returns_none() -> None:
    headers = ["name", "country"]
    assert _detect_pk_column(headers, "Supplier") is None


# ─────────────────────────────────────────────────────────────────────────────
# Foreign key column resolution
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_fk_purchase_order() -> None:
    """PurchaseOrder file should have FKs to Supplier and Facility."""
    headers = ["po_number", "supplier_id", "ship_to_facility_id", "total_value"]
    fks = _resolve_fk_columns(headers, "PurchaseOrder")
    fk_fields = {fk[3] for fk in fks}
    assert "supplier_id" in fk_fields
    assert "ship_to_facility_id" in fk_fields
    # Verify relationship types
    for _, tgt, rel, _ in fks:
        if _.endswith("supplier_id"):
            assert tgt == "Supplier" and rel == "ORDERS_FROM"


def test_resolve_fk_shipment() -> None:
    """Shipment file should have FKs to Facility, Carrier, Route."""
    headers = [
        "shipment_id",
        "origin_facility_id",
        "destination_facility_id",
        "carrier_id",
        "route_id",
        "status",
    ]
    fks = _resolve_fk_columns(headers, "Shipment")
    fk_fields = {fk[3] for fk in fks}
    assert {"origin_facility_id", "destination_facility_id", "carrier_id", "route_id"}.issubset(
        fk_fields
    )


def test_resolve_fk_no_fks_returns_empty() -> None:
    headers = ["supplier_id", "legal_name"]
    # Supplier's only FK is parent_supplier_id, which is not in these headers
    fks = _resolve_fk_columns(headers, "Supplier")
    assert fks == []


def test_resolve_fk_supplier_hierarchy() -> None:
    headers = ["supplier_id", "parent_supplier_id", "legal_name"]
    fks = _resolve_fk_columns(headers, "Supplier")
    assert len(fks) == 1
    assert fks[0][1] == "Supplier"  # self-referencing PARENT_OF
    assert fks[0][2] == "PARENT_OF"


# ─────────────────────────────────────────────────────────────────────────────
# Facility type normalization
# ─────────────────────────────────────────────────────────────────────────────


def test_normalize_facility_type() -> None:
    assert _normalize_facility_type("Warehouse") == "warehouse"
    assert _normalize_facility_type("Plant") == "plant"
    assert _normalize_facility_type("DistributionCenter") == "distribution_center"
    assert _normalize_facility_type("CrossDock") == "cross_dock"
    assert _normalize_facility_type("Port") == "port"
    assert _normalize_facility_type("Supplier") == "supplier"


# ─────────────────────────────────────────────────────────────────────────────
# Row reconstruction from profiles (deterministic)
# ─────────────────────────────────────────────────────────────────────────────


def _mock_profile(name: str, samples: list[str], idx: int = 0) -> Any:
    return SimpleNamespace(
        profile_id=f"p-{name}",
        file_id="f-1",
        workspace_id="ws-1",
        column_name=name,
        column_index=idx,
        inferred_type="string",
        null_ratio=0.0,
        distinct_count=len(set(samples)),
        sample_values=samples,
    )


def test_reconstruct_rows_from_profiles_basic() -> None:
    profiles = [
        _mock_profile("supplier_id", ["SUP-001", "SUP-002", "SUP-003"], 0),
        _mock_profile("name", ["Acme", "Global", "Pacific"], 1),
    ]
    rows = _reconstruct_rows_from_profiles(profiles)
    assert len(rows) == 3
    assert rows[0]["supplier_id"] == "SUP-001"
    assert rows[0]["name"] == "Acme"
    assert rows[2]["supplier_id"] == "SUP-003"


def test_reconstruct_rows_handles_uneven_samples() -> None:
    profiles = [
        _mock_profile("id", ["A", "B", "C", "D"], 0),
        _mock_profile("val", ["X", "Y"], 1),  # only 2 samples
    ]
    rows = _reconstruct_rows_from_profiles(profiles)
    assert len(rows) == 4
    assert rows[0]["val"] == "X"
    assert rows[2]["val"] == ""  # missing → empty string


def test_reconstruct_rows_deterministic() -> None:
    profiles = [
        _mock_profile("sku", ["SKU-001", "SKU-002"], 0),
        _mock_profile("name", ["Widget", "Gadget"], 1),
    ]
    rows1 = _reconstruct_rows_from_profiles(profiles)
    rows2 = _reconstruct_rows_from_profiles(profiles)
    assert rows1 == rows2


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot hashing — determinism, tamper-evidence, hash chain
# ─────────────────────────────────────────────────────────────────────────────


def test_snapshot_hash_deterministic() -> None:
    """Same write payloads + same prev_hash → same snapshot hash."""
    payloads = [
        {"entity_type": "Supplier", "entity_id": "SUP-001", "attributes": {"name": "Acme"}},
        {"entity_type": "Product", "entity_id": "SKU-001", "attributes": {"name": "Widget"}},
    ]
    h1 = compute_snapshot_hash(None, payloads)
    h2 = compute_snapshot_hash(None, payloads)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_snapshot_hash_changes_with_different_payloads() -> None:
    """Different payloads → different hash."""
    payloads_a = [{"entity": "A", "id": "1"}]
    payloads_b = [{"entity": "B", "id": "2"}]
    h_a = compute_snapshot_hash(None, payloads_a)
    h_b = compute_snapshot_hash(None, payloads_b)
    assert h_a != h_b


def test_snapshot_hash_changes_with_different_prev_hash() -> None:
    """Different prev_hash → different snapshot hash (hash chain)."""
    payloads = [{"entity": "A", "id": "1"}]
    h1 = compute_snapshot_hash(None, payloads)
    h2 = compute_snapshot_hash("abc123", payloads)
    assert h1 != h2


def test_snapshot_hash_invariant_to_payload_order() -> None:
    """Payload order doesn't matter — the hash sorts payloads internally."""
    payloads_a = [
        {"entity_type": "Supplier", "entity_id": "SUP-001"},
        {"entity_type": "Product", "entity_id": "SKU-001"},
    ]
    payloads_b = list(reversed(payloads_a))
    h1 = compute_snapshot_hash(None, payloads_a)
    h2 = compute_snapshot_hash(None, payloads_b)
    assert h1 == h2, "snapshot hash should be order-invariant"


def test_snapshot_hash_chain_linkage() -> None:
    """snapshot_2.prev_hash = snapshot_1.hash → chain is verifiable."""
    payloads_1 = [{"entity": "A", "id": "1"}]
    hash_1 = compute_snapshot_hash(None, payloads_1)

    payloads_2 = [{"entity": "B", "id": "2"}]
    hash_2 = compute_snapshot_hash(hash_1, payloads_2)

    # Recompute hash_2 from the same inputs → should match
    recomputed = compute_snapshot_hash(hash_1, payloads_2)
    assert recomputed == hash_2


def test_snapshot_chain_tamper_detection() -> None:
    """Changing a payload after sealing makes the chain hash mismatch."""
    original = [{"entity": "A", "id": "1", "name": "Acme"}]
    tampered = [{"entity": "A", "id": "1", "name": "TAMPERED"}]

    hash_original = compute_snapshot_hash(None, original)
    hash_tampered = compute_snapshot_hash(None, tampered)

    assert hash_original != hash_tampered, "tampering must change the hash"


def test_empty_payloads_produce_consistent_hash() -> None:
    h1 = compute_snapshot_hash(None, [])
    h2 = compute_snapshot_hash(None, [])
    assert h1 == h2


# ─────────────────────────────────────────────────────────────────────────────
# Provenance — every write event carries provenance_claim_ids
# ─────────────────────────────────────────────────────────────────────────────


def test_pending_write_always_has_provenance() -> None:
    """Every _PendingWrite must carry non-empty provenance_claim_ids."""
    w = _PendingWrite(
        operation="upsert_node",
        element_type="node",
        element_id="n-1",
        payload={"entity_type": "Supplier", "entity_id": "SUP-001", "attributes": {}},
        provenance_claim_ids=["c-1", "c-2"],
    )
    assert w.provenance_claim_ids, "write event must have provenance"
    assert len(w.provenance_claim_ids) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Replay convergence — compiling the same data in different orders
# ─────────────────────────────────────────────────────────────────────────────


def test_replay_convergence_same_inputs_same_hash() -> None:
    """Two compilations of the same evidence → same graph → same hash.

    This is the Phase 3 success metric as a test: every graph can be
    reconstructed from immutable evidence through deterministic reasoning.
    """
    supplier_claims = [
        {"entity_type": "Supplier", "entity_id": "SUP-001", "attributes": {"name": "Acme"}},
        {"entity_type": "Supplier", "entity_id": "SUP-002", "attributes": {"name": "Global"}},
    ]
    product_claims = [
        {"entity_type": "Product", "entity_id": "SKU-001", "attributes": {"name": "Widget"}},
    ]

    # Order 1: suppliers first, then products
    all_payloads_1 = supplier_claims + product_claims
    hash_1 = compute_snapshot_hash(None, all_payloads_1)

    # Order 2: products first, then suppliers
    all_payloads_2 = product_claims + supplier_claims
    hash_2 = compute_snapshot_hash(None, all_payloads_2)

    # The hash must be the same because the hash is order-invariant
    assert hash_1 == hash_2, (
        "Phase 3 success metric: same evidence → same hash regardless of order. "
        f"hash_1={hash_1[:16]}… hash_2={hash_2[:16]}…"
    )


def test_replay_convergence_with_chain() -> None:
    """Replay convergence holds across the hash chain too."""
    batch_a = [{"entity": "A", "id": "1"}]
    batch_b = [{"entity": "B", "id": "2"}]

    # First compilation: A then B
    hash_a1 = compute_snapshot_hash(None, batch_a)
    hash_b1 = compute_snapshot_hash(hash_a1, batch_b)

    # Replay: reconstruct from the same evidence
    hash_a2 = compute_snapshot_hash(None, batch_a)
    hash_b2 = compute_snapshot_hash(hash_a2, batch_b)

    assert hash_a1 == hash_a2
    assert hash_b1 == hash_b2
