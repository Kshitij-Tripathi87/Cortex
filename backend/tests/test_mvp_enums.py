"""MVP enums sanity tests — make sure every enum declares the documented
members and that `MvpDatasetType` covers all 10 dataset types the
ingestion endpoint and row-schema map expect."""

from __future__ import annotations

from app.common.enums import (
    DecisionOutcome,
    DisruptionEventType,
    DisruptionSeverity,
    DisruptionStatus,
    EdgeType,
    ImpactStatus,
    IngestionStatus,
    MvpDatasetType,
    NodeType,
    OrderStatus,
    SupplierStatus,
    SupplierTier,
    UserRole,
)

EXPECTED_DATASETS = {
    "suppliers",
    "components",
    "warehouses",
    "factories",
    "products",
    "customers",
    "edges",
    "inventory",
    "bom",
    "orders",
}


def test_mvp_dataset_type_covers_all_ten_datasets() -> None:
    actual = {m.value for m in MvpDatasetType}
    assert actual == EXPECTED_DATASETS


def test_supplier_status_values() -> None:
    assert {m.value for m in SupplierStatus} == {"active", "disrupted", "disabled"}


def test_supplier_tier_values() -> None:
    assert {m.value for m in SupplierTier} == {"tier_1", "tier_2", "tier_3"}


def test_node_type_values() -> None:
    assert {m.value for m in NodeType} == {
        "supplier",
        "component",
        "warehouse",
        "factory",
        "product",
        "customer",
    }


def test_edge_type_values() -> None:
    assert {m.value for m in EdgeType} == {
        "supplies",
        "stored_in",
        "consumes",
        "makes",
        "ships_from",
        "orders",
    }


def test_disruption_status_values() -> None:
    assert {m.value for m in DisruptionStatus} == {
        "open",
        "investigating",
        "resolved",
        "cancelled",
    }


def test_disruption_severity_values() -> None:
    assert {m.value for m in DisruptionSeverity} == {
        "info",
        "warning",
        "major",
        "critical",
    }


def test_disruption_event_type_values() -> None:
    assert {m.value for m in DisruptionEventType} == {
        "supplier_failure",
        "logistics_disruption",
        "quality_recall",
        "geopolitical",
        "natural_disaster",
        "labor_dispute",
        "other",
    }


def test_impact_status_values() -> None:
    assert {m.value for m in ImpactStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
    }


def test_ingestion_status_values() -> None:
    assert {m.value for m in IngestionStatus} == {
        "received",
        "running",
        "completed",
        "failed",
        "partial",
    }


def test_decision_outcome_values() -> None:
    assert {m.value for m in DecisionOutcome} == {
        "accepted_recommendation",
        "rejected_recommendation",
        "modified_recommendation",
        "deferred",
    }


def test_user_role_values() -> None:
    assert {m.value for m in UserRole} == {"admin", "operator", "analyst", "viewer"}


def test_order_status_values() -> None:
    assert {m.value for m in OrderStatus} == {
        "pending",
        "confirmed",
        "in_production",
        "shipped",
        "delivered",
        "cancelled",
        "delayed",
    }


def test_all_mvp_enums_are_strenum_subclasses() -> None:
    """Every MVP enum must derive from StrEnum so JSON serialization works."""
    from enum import StrEnum

    for enum_cls in (
        MvpDatasetType,
        SupplierStatus,
        SupplierTier,
        NodeType,
        EdgeType,
        DisruptionStatus,
        DisruptionSeverity,
        DisruptionEventType,
        ImpactStatus,
        IngestionStatus,
        DecisionOutcome,
        UserRole,
        OrderStatus,
    ):
        assert issubclass(enum_cls, StrEnum), f"{enum_cls.__name__} must inherit StrEnum"
