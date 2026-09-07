"""Nexus Ontology — Supply Chain World Model.

This module is the Phase A foundation for transforming Nexus from a graph
page into a decision-intelligence platform. It provides:

- core_types        : closed vocabularies for EntityKind, RelationshipKind, EntityDomain
- entities          : Entity, EntityQuery, EntityPage, StateSnapshot, ProvenanceRecord, etc.
- specialized       : typed views for supply-chain entities (Supplier, Warehouse, Plant,
                       Product, Component, PurchaseOrder, SalesOrder, InventoryPosition,
                       Signal, Disruption, Forecast, Decision)
- repository        : in-memory world-model repository with graph traversal, query,
                       change-event publication

The ontology is intentionally framework-agnostic: Pydantic models + a single
repository class. Persistence is layered on top (DB-backed repository) in a
later phase without changing the entity shapes.
"""

from app.modules.nexus_spine.ontology.core_types import (
    ENTITY_KIND_TO_DOMAIN,
    EntityDomain,
    EntityKind,
    RelationshipKind,
    domain_of,
)
from app.modules.nexus_spine.ontology.entities import (
    Entity,
    EntityPage,
    EntityQuery,
    PermissionGrant,
    ProvenanceRecord,
    RelationshipEdge,
    StateSnapshot,
)
from app.modules.nexus_spine.ontology.repository import (
    WorldModelRepository,
    canonical_state_hash,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.ontology.specialized import (
    ComponentEntity,
    DecisionEntity,
    DisruptionEntity,
    ForecastEntity,
    InventoryPositionEntity,
    PlantEntity,
    ProductEntity,
    PurchaseOrderEntity,
    SalesOrderEntity,
    SignalEntity,
    SupplierEntity,
    WarehouseEntity,
)

__all__ = [
    "ENTITY_KIND_TO_DOMAIN",
    "ComponentEntity",
    "DecisionEntity",
    "DisruptionEntity",
    "Entity",
    "EntityDomain",
    "EntityKind",
    "EntityPage",
    "EntityQuery",
    "ForecastEntity",
    "InventoryPositionEntity",
    "PermissionGrant",
    "PlantEntity",
    "ProductEntity",
    "ProvenanceRecord",
    "PurchaseOrderEntity",
    "RelationshipEdge",
    "RelationshipKind",
    "SalesOrderEntity",
    "SignalEntity",
    "StateSnapshot",
    "SupplierEntity",
    "WarehouseEntity",
    "WorldModelRepository",
    "canonical_state_hash",
    "domain_of",
    "get_world_model",
    "reset_world_model",
]
