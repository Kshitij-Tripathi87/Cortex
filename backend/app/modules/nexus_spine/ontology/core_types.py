"""Nexus Ontology — Supply Chain World Model Core Types.

Defines the closed vocabulary of entity types that make up the operational
supply-chain world model. These types are the substrate for everything else:
graph traversal, signal propagation, decision memory, Vanessa's tool registry,
and the stable /v1/entities API surface.

Design principles:
- Closed enum (StrEnum) — every entity MUST be one of these types. Unknown
  types are rejected at the API boundary (fail-closed, no silent defaulting).
- Subclassed by domain (org, supply, demand, flow, time) for clear ownership
  and version-stable grouping.
- Stable string values (snake_case) — these are persisted to PostgreSQL and
  used as natural keys in message-bus events; renaming breaks world history.
"""

from __future__ import annotations

from enum import StrEnum


class EntityKind(StrEnum):
    """Closed vocabulary of entity types in the Nexus world model.

    Every entity, signal, decision, and scenario is typed by exactly one of
    these values. New entity types require a deliberate migration step.
    """

    # ── Organizational / structural ──────────────────────────────────────────
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    TEAM = "team"
    USER = "user"

    # ── Supply-side entities ────────────────────────────────────────────────
    SUPPLIER = "supplier"
    MANUFACTURER = "manufacturer"
    PLANT = "plant"
    FACTORY = "factory"
    WAREHOUSE = "warehouse"
    PORT = "port"

    # ── Product / material entities ──────────────────────────────────────────
    PRODUCT = "product"
    SKU = "sku"
    COMPONENT = "component"
    MATERIAL = "material"
    BILL_OF_MATERIALS = "bill_of_materials"

    # ── Flow entities ───────────────────────────────────────────────────────
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    SHIPMENT = "shipment"
    ROUTE = "route"
    CARRIER = "carrier"
    INVENTORY_POSITION = "inventory_position"

    # ── Customer / commercial ───────────────────────────────────────────────
    CUSTOMER = "customer"
    CONTRACT = "contract"
    CAPACITY = "capacity"
    DEMAND = "demand"
    FORECAST = "forecast"
    LEAD_TIME = "lead_time"

    # ── Operational intelligence ─────────────────────────────────────────────
    DISRUPTION = "disruption"
    SIGNAL = "signal"
    SCENARIO = "scenario"
    SIMULATION = "simulation"
    DECISION = "decision"
    RECOMMENDATION = "recommendation"
    EXECUTION = "execution"
    OUTCOME = "outcome"
    EVIDENCE = "evidence"

    # ── AI / agent surfaces ──────────────────────────────────────────────────
    AGENT = "agent"
    TOOL = "tool"
    POLICY = "policy"
    APPROVAL = "approval"


class RelationshipKind(StrEnum):
    """Closed vocabulary of relationships between entities.

    Relationships are directed (from -> to). Every world-model edge carries
    exactly one of these values. Closed vocabulary enables deterministic
    graph traversal in O(1) per edge.
    """

    # Supply structure
    SUPPLIES = "supplies"
    USED_IN = "used_in"
    PRODUCES = "produces"
    HOLDS = "holds"
    SHIPS_TO = "ships_to"

    # Customer / commercial
    ORDERED_BY = "ordered_by"
    CONTAINS = "contains"
    REQUIRES = "requires"

    # Flow
    TRAVELS_VIA = "travels_via"
    PASSES_THROUGH = "passes_through"
    CARRIED_BY = "carried_by"

    # Causal
    AFFECTS = "affects"
    CAUSES = "causes"
    IMPACTS = "impacts"
    MITIGATED_BY = "mitigated_by"

    # Decision provenance
    DERIVED_FROM = "derived_from"
    EVIDENCED_BY = "evidenced_by"
    RECOMMENDS = "recommends"
    APPROVES = "approves"
    EXECUTES = "executes"
    RESULTED_IN = "resulted_in"

    # Capacity / time
    HAS_CAPACITY = "has_capacity"
    HAS_LEAD_TIME = "has_lead_time"
    FORECASTS = "forecasts"
    DEMANDS = "demands"


class EntityDomain(StrEnum):
    """Top-level grouping of entity kinds — used for permission scoping and
    schema partitioning. Each EntityKind maps to exactly one domain."""

    ORG = "org"
    SUPPLY = "supply"
    PRODUCT = "product"
    FLOW = "flow"
    COMMERCIAL = "commercial"
    OPS = "ops"
    AI = "ai"


ENTITY_KIND_TO_DOMAIN: dict[EntityKind, EntityDomain] = {
    EntityKind.ORGANIZATION: EntityDomain.ORG,
    EntityKind.WORKSPACE: EntityDomain.ORG,
    EntityKind.TEAM: EntityDomain.ORG,
    EntityKind.USER: EntityDomain.ORG,
    EntityKind.SUPPLIER: EntityDomain.SUPPLY,
    EntityKind.MANUFACTURER: EntityDomain.SUPPLY,
    EntityKind.PLANT: EntityDomain.SUPPLY,
    EntityKind.FACTORY: EntityDomain.SUPPLY,
    EntityKind.WAREHOUSE: EntityDomain.SUPPLY,
    EntityKind.PORT: EntityDomain.SUPPLY,
    EntityKind.PRODUCT: EntityDomain.PRODUCT,
    EntityKind.SKU: EntityDomain.PRODUCT,
    EntityKind.COMPONENT: EntityDomain.PRODUCT,
    EntityKind.MATERIAL: EntityDomain.PRODUCT,
    EntityKind.BILL_OF_MATERIALS: EntityDomain.PRODUCT,
    EntityKind.PURCHASE_ORDER: EntityDomain.FLOW,
    EntityKind.SALES_ORDER: EntityDomain.FLOW,
    EntityKind.SHIPMENT: EntityDomain.FLOW,
    EntityKind.ROUTE: EntityDomain.FLOW,
    EntityKind.CARRIER: EntityDomain.FLOW,
    EntityKind.INVENTORY_POSITION: EntityDomain.FLOW,
    EntityKind.CUSTOMER: EntityDomain.COMMERCIAL,
    EntityKind.CONTRACT: EntityDomain.COMMERCIAL,
    EntityKind.CAPACITY: EntityDomain.COMMERCIAL,
    EntityKind.DEMAND: EntityDomain.COMMERCIAL,
    EntityKind.FORECAST: EntityDomain.COMMERCIAL,
    EntityKind.LEAD_TIME: EntityDomain.COMMERCIAL,
    EntityKind.DISRUPTION: EntityDomain.OPS,
    EntityKind.SIGNAL: EntityDomain.OPS,
    EntityKind.SCENARIO: EntityDomain.OPS,
    EntityKind.SIMULATION: EntityDomain.OPS,
    EntityKind.DECISION: EntityDomain.OPS,
    EntityKind.RECOMMENDATION: EntityDomain.OPS,
    EntityKind.EXECUTION: EntityDomain.OPS,
    EntityKind.OUTCOME: EntityDomain.OPS,
    EntityKind.EVIDENCE: EntityDomain.OPS,
    EntityKind.AGENT: EntityDomain.AI,
    EntityKind.TOOL: EntityDomain.AI,
    EntityKind.POLICY: EntityDomain.AI,
    EntityKind.APPROVAL: EntityDomain.AI,
}


def domain_of(kind: EntityKind) -> EntityDomain:
    """Return the domain that owns an entity kind."""
    return ENTITY_KIND_TO_DOMAIN[kind]
