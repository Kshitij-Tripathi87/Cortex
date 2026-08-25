# 02 — Operational Ontology

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Product Architect |
| Depends on | `01-architecture.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and scope

This document freezes **the supply-chain world Cortex understands**: the
canonical entities, the relationships between them, and the rules that govern
identity, uniqueness, lifecycle, provenance, confidence, and validation. Graph
construction, entity resolution, conflict detection, and validation all depend
on this document and must not invent entities, relationships, or rules that
contradict it.

Scope:
- In scope: entities, relationships, ontology rules for each.
- Out of scope: physical table layouts (see `06-database-strategy.md`), event
  schemas (see `04-graph-and-events.md`), API payloads (see `05-api-standards.md`).

---

## 2. How to read this document

Entities use the format in §5; relationships use the format in §8. The fields
are uniform so that the implementation can treat this as a schema source.

Common fields explained:
- **Canonical name**: the single in-system identifier; never aliased internally.
- **Allowed aliases**: source-system labels that map to this entity. Used by
  schema mapping only; never stored as primary identity.
- **Required properties**: must be present and non-null to create the entity.
- **Optional properties**: may be absent; absence is recorded as `MISSING`, never
  silently defaulted (see `03-canonical-data-model.md`).
- **Identity rules**: how two candidate records are judged to be the same entity
  (used by entity resolution).
- **Uniqueness rules**: the key(s) that prevent duplicate canonical entities
  within a workspace.
- **Lifecycle state**: the value of `lifecycle_state`, a closed enum.
- **Confidence if derived**: how a confidence in `[0,1]` is computed for derived
  entities (e.g. resolved duplicates, inferred instances). Non-derived entities
  have confidence `1.0` upon canonicalization.
- **Provenance fields**: the minimal provenance tuple attached at creation and
  to every attribute claim (see `01-architecture.md` §Cross-cutting identifiers).
- **Allowed source systems**: the categories of source that may supply this
  entity. A category is a closed enum: `erp`, `wms`, `tms`, `oms`, `mes`,
  `scm_planning`, `spreadsheet`, `manual`, `external_feed`, `ml_candidate`.
  `ml_candidate` is never allowed to *create* an entity; it may only propose
  attribute claims for review.
- **Validation constraints**: predicates every candidate must pass.

---

## 3. Shared value conventions

These are frozen for every entity and relationship in this document.

| Field | Convention |
|---|---|
| `workspace_id` | UUIDv7. Every entity and edge is scoped by it. |
| `id` (canonical id) | UUIDv7. Assigned at first canonicalization. Stable forever. |
| `version` | Integer ≥1. Incremented on each accepted attribute change. |
| `valid_from`, `valid_to` | Point-in-time timestamps (UTC). Current record: `valid_to IS NULL`. |
| `external_ids` | Array of `{source_system, external_id}`. Not unique system-wide. |
| `provenance` | The provenance tuple defined in `01-architecture.md`. |
| `confidence` | Decimal in `[0,1]` to 4 dp. Derived-only otherwise `1.0`. |
| `lifecycle_state` | Closed enum (entity-specific). |
| `notes` | Optional human-readable string. |
| `created_at`, `updated_at` | UTC timestamps; `updated_at` is the last accepted change. |

### 3.1 Unit model (frozen)

Cortex is supply-chain software; units are first-class. Every quantity carries
a unit from the frozen unit registry. Phase 1 registry:

| Measure | Allowed units |
|---|---|
| Mass | `kg`, `g`, `t` (metric tonne), `lb` |
| Volume | `L`, `m3`, `gal_us` |
| Count | `each`, `case`, `pallet` |
| Distance | `km`, `mi`, `m` |
| Currency | ISO 4217 (e.g. `USD`, `EUR`, `CNY`) |
| Time duration | `s`, `min`, `h`, `day` |
| Timestamps | UTC ISO-8601 |

`normalize_unit(value, unit, target_unit)` is a pure function defined once in
`domain.units`. Storing a quantity without a unit is forbidden; source rows that
omit a unit are recorded as claims with state `pending_review` and a
`missing_unit` conflict.

### 3.2 Missing-value sentinel

A single sentinel `MISSING` represents an absent value at the canonical layer.
`MISSING` is never serialized as `null` over the API; the API returns the field
absent with an `evidence` array empty (see `03-canonical-data-model.md` §6).

---

## 4. Entity registry (summary)

The closed set of canonical entity types Phase 1 freezes:

| Index | Canonical name | Category | Source systems | Derivable? |
|---|---|---|---|---|
| E1 | Supplier | Party | erp, scm_planning, spreadsheet, manual, external_feed | No |
| E2 | Warehouse | Facility | wms, erp, scm_planning, manual | No |
| E3 | Plant | Facility | erp, mes, scm_planning, manual | No |
| E4 | Facility | Facility (abstract supertype) | wms, erp, mes, tms, manual | No |
| E5 | Product | Catalog | erp, mes, spreadsheet, manual, external_feed | No |
| E6 | InventoryItem | Operational | wms, erp, mes | No |
| E7 | PurchaseOrder | Operational | erp, manual | No |
| E8 | Shipment | Operational | tms, erp, wms, external_feed | No |
| E9 | Route | Operational | tms, scm_planning, manual | No |
| E10 | Customer | Party | erp, oms, spreadsheet, manual, external_feed | No |
| E11 | SalesOrder | Operational | erp, oms, manual | No |
| E12 | Event | Intelligence | cortex (deterministic), ml_candidate (review only) | Yes (detected) |
| E13 | Scenario | Intelligence | cortex | Yes (generated) |
| E14 | Recommendation | Intelligence | cortex | Yes (generated) |
| E15 | DecisionRecord | Intelligence | cortex | Yes (recorded) |

`Facility` is an abstract supertype; `Warehouse` and `Plant` are concrete
subtypes. Roles such as `Port` or `DC` are represented by `Facility` with
`facility_type`, not by new entity types. Adding a subtype is allowed without an
ACR; adding a new top-level entity type requires an ACR.

---

## 5. Entity definitions

### E1 — Supplier

| Field | Value |
|---|---|
| Canonical name | `Supplier` |
| Allowed aliases | `Vendor`, `VendorMaster`, `SupplierMaster`, `BusinessPartner-S` |
| Source systems | erp, scm_planning, spreadsheet, manual, external_feed |
| Derivable? | No (confidence 1.0 on canonicalization) |

Required properties:
- `workspace_id` (scoped)
- `legal_name` (non-empty string; normalized per `03-canonical-data-model.md` §4)
- `external_ids` (≥1 entry)

Optional properties:
- `tax_id`, `duns_number`, `country`, `region`, `city`, `address_line`
- `currency` (ISO 4217)
- `risk_tier` (enum: `low`, `medium`, `high`, `critical`; default `medium` pending review)
- `primary_contact_ref` (pointer to a Contact claim, out of Phase 1 scope)

Identity rules (any one resolves to the same Supplier):
1. Same `external_id` from the same `source_system`.
2. Same (`tax_id`, `country`) when both non-null and ≥6 chars.
3. Same `duns_number` when non-null (DUNS is globally unique).

Uniqueness rules: unique on `external_ids` per workspace. A second record
claiming an overlapping external id triggers `entity_resolution_conflict`.

Lifecycle states: `draft`, `active`, `suspended`, `deprecated`, `merged`.

Validation constraints:
- `legal_name` length ≤ 512.
- `country` is a valid ISO 3166-1 alpha-2.
- `risk_tier` ∈ closed enum.

Provenance: required at entity and per-attribute claim level.

### E2 — Warehouse

| Canonical name | `Warehouse` |
|---|---|
| Allowed aliases | `DistributionCenter`, `DC`, `WarehouseMaster`, `Site` |
| Source systems | wms, erp, scm_planning, manual |
| Supertype | `Facility` |

Required: `workspace_id`, `facility_type="warehouse"`, `name`, `country`, `external_ids`.
Optional: `region`, `city`, `address_line`, `capacity_cube`, `capacity_unit`, `operator_ref` (Supplier id), `timezone`.
Identity: same `external_id` per source; or same (`name`, `country`, `city`) if provided.
Uniqueness: per workspace, unique on `external_ids`.
Lifecycle: `draft`, `active`, `closed`, `deprecated`.
Validation: `country` ISO alpha-2; `capacity_unit` ∈ unit registry.

### E3 — Plant

| Canonical name | `Plant` |
|---|---|
| Allowed aliases | `Factory`, `ManufacturingSite`, `ProductionLine` (if line-level) |
| Source systems | erp, mes, scm_planning, manual |
| Supertype | `Facility` |

Required: `workspace_id`, `facility_type="plant"`, `name`, `country`, `external_ids`.
Optional: `region`, `city`, `address_line`, `capacity_units_per_day`, `capacity_unit`, `operator_ref`, `timezone`.
Identity, uniqueness, lifecycle, validation: same as Warehouse with `facility_type="plant"`.

### E4 — Facility (abstract supertype)

| Canonical name | `Facility` |
|---|---|
| Allowed aliases | `Site`, `Location`, `Node` (when location-like) |
| Source systems | wms, erp, mes, tms, manual |

`Facility` is never instantiated directly; it is the union type for graph
operations that act on any physical node (Warehouse, Plant, or future subtypes).
Required union fields: `workspace_id`, `facility_type`, `name`, `country`,
`external_ids`. `facility_type` is the closed enum
`{warehouse, plant, port, cross_dock, dc, supplier_site, customer_site, other}` —
new subtypes reuse this enum value rather than a new entity type.

### E5 — Product

| Canonical name | `Product` |
|---|---|
| Allowed aliases | `SKU`, `ItemMaster`, `Material`, `PartNumber` |
| Source systems | erp, mes, spreadsheet, manual, external_feed |

Required: `workspace_id`, `sku` (canonical SKU, normalized to uppercase, trimmed, ≤64 chars), `name`, `external_ids`.
Optional: `category`, `subcategory`, `uom` (base unit of measure), `hs_code`, `weight_unit`, `weight_per_unit`, `volume_unit`, `volume_per_unit`, `hazmat` (bool, default false), `shelf_life_days`.
Identity: same `external_id` per source; or same normalized `sku` per workspace.
Uniqueness: per workspace, unique on normalized `sku`.
Lifecycle: `draft`, `active`, `discontinued`, `deprecated`.
Validation: `uom` ∈ unit registry; `hs_code` matches `^\d{6,10}$` if present; weights/volumes ≥ 0.

### E6 — InventoryItem

| Canonical name | `InventoryItem` |
|---|---|
| Allowed aliases | `Stock`, `OnHand`, `InventoryBalance`, `StockPosition` |
| Source systems | wms, erp, mes |

Required: `workspace_id`, `facility_ref` (Facility canonical id), `product_ref` (Product canonical id), `quantity`, `unit`, `external_ids`.
Optional: `lot_number`, `serial_number`, `condition` (`new`, `in_transit`, `damaged`, `quarantined`, `reserved`), `as_of` (point-in-time snapshot timestamp; defaults to source `extracted_at`).
Identity: same (`facility_ref`, `product_ref`, `lot_number`?, `condition`?) for the same `as_of` window — lot/condition keys are optional only when the source omits them; if one source provides them, the identity rule applies to the provided fields.
Uniqueness: per workspace, one current InventoryItem per
  (`facility_ref`, `product_ref`, `lot_number`, `condition`) key; new
  values replace by closing the prior `valid_to`.
Lifecycle: `on_hand`, `reserved`, `in_transit`, `quarantined`, `depleted`.
Validation: `quantity` ≥ 0; `unit` ∈ unit registry and dimensionally equal to the product `uom` family; `as_of` ≤ now UTC.

### E7 — PurchaseOrder

| Canonical name | `PurchaseOrder` |
|---|---|
| Allowed aliases | `PO`, `PurchaseOrderLine` (line modeling in §9) |
| Source systems | erp, manual |

Required: `workspace_id`, `po_number` (normalized, trimmed, ≤64), `supplier_ref`, `buyer_ref` (Customer or internal org id), `external_ids`.
Optional: `status_ref`, `currency`, `placed_at`, `promised_delivery_at`, `ship_to_ref` (Facility), `incoterm`, `total_value` (with currency).
Identity: same `external_id` (po_number) per source; or normalized `po_number` per workspace.
Uniqueness: per workspace, unique on normalized `po_number`.
Lifecycle: `draft`, `open`, `confirmed`, `partially_received`, `received`, `closed`, `cancelled`.
Validation: `currency` ISO 4217; dates ≤ now UTC; `total_value ≥ 0`.

### E8 — Shipment

| Canonical name | `Shipment` |
|---|---|
| Allowed aliases | `Load`, `Trip`, `Consignment`, `Movement`, `Freight` |
| Source systems | tms, erp, wms, external_feed |

Required: `workspace_id`, `shipment_id` (normalized, trimmed, ≤64), `origin_ref` (Facility or Supplier id), `destination_ref` (Facility or Customer id), `external_ids`.
Optional: `carrier`, `mode` (`road`, `rail`, `sea`, `air`, `multimodal`), `etd`, `atd`, `eta`, `ata`, `status_ref`, `route_ref` (Route id), `equipment_type`, `hazardous` (bool, default false), `cost_currency`, `cost`.
Identity: same `external_id` per source; or normalized `shipment_id` per workspace.
Uniqueness: per workspace, unique on normalized `shipment_id`.
Lifecycle: `planned`, `dispatched`, `in_transit`, `arrived`, `delayed`, `exception`, `delivered`, `cancelled`.
Validation: dates ≤ now UTC; `eta ≥ etd` when both present; mode ∈ closed enum.

### E9 — Route

| Canonical name | `Route` |
|---|---|
| Allowed aliases | `Lane`, `Routing`, `Corridor` |
| Source systems | tms, scm_planning, manual |

Required: `workspace_id`, `route_id` (normalized), `origin_ref`, `destination_ref`, `external_ids`.
Optional: `mode`, `distance_value`, `distance_unit`, `transit_time_value`, `transit_time_unit`, `cost_value`, `cost_currency`, `risk_index` (decimal in `[0,1]`).
Identity: same `external_id` per source; or same (`origin_ref`, `destination_ref`, `mode`) per workspace.
Uniqueness: per workspace, one current Route per (`origin_ref`, `destination_ref`, `mode`).
Lifecycle: `draft`, `active`, `disrupted`, `deprecated`.
Validation: `distance_unit`/`transit_time_unit` ∈ unit registry; `risk_index` ∈ `[0,1]`.

### E10 — Customer

| Canonical name | `Customer` |
|---|---|
| Allowed aliases | `Account`, `BusinessPartner-C`, `CustomerMaster`, `ShipTo` |
| Source systems | erp, oms, spreadsheet, manual, external_feed |

Required: `workspace_id`, `legal_name`, `external_ids`.
Optional: `tax_id`, `country`, `region`, `city`, `address_line`, `currency`, `segment`, `credit_status`.
Identity: same `external_id` per source; or same (`tax_id`, `country`) when both non-null ≥6 chars.
Uniqueness: per workspace, unique on `external_ids`.
Lifecycle: `draft`, `active`, `suspended`, `deprecated`, `merged`.
Validation: `country` ISO alpha-2; `currency` ISO 4217.

### E11 — SalesOrder

| Canonical name | `SalesOrder` |
|---|---|
| Allowed aliases | `SO`, `Order`, `OrderLine` (line modeling in §9) |
| Source systems | erp, oms, manual |

Required: `workspace_id`, `so_number` (normalized), `customer_ref`, `external_ids`.
Optional: `status_ref`, `currency`, `placed_at`, `promised_delivery_at`, `ship_from_ref` (Facility id), `incoterm`, `total_value`.
Identity: same `external_id` per source; or normalized `so_number` per workspace.
Uniqueness: per workspace, unique on normalized `so_number`.
Lifecycle: `draft`, `open`, `confirmed`, `partially_fulfilled`, `fulfilled`, `closed`, `cancelled`.
Validation: same as PurchaseOrder.

### E12 — Event

`Event` here is the **operational event** entity (an observed or detected
occurrence in the supply chain). It is distinct from the *system* event in the
event model (`04-graph-and-events.md`), which records that this operational event
was created/detected.

| Canonical name | `Event` |
|---|---|
| Allowed aliases | `Disruption`, `Alert`, `Incident`, `SignalOccurrence` |
| Source systems | cortex (deterministic detection), external_feed, manual; `ml_candidate` may only propose, not create. |
| Derivable? | Yes (confidence computed). |

Required: `workspace_id`, `event_type` (closed enum: `delay`, `disruption`, `stockout`, `quality_issue`, `capacity_loss`, `weather`, `regulatory`, `demand_spike`, `demand_drop`, `cost_change`, `supplier_insolvency`), `occurred_at`, `severity` (`info`, `warning`, `major`, `critical`), `external_ids`.
Optional: `description`, `affected_refs` (array of canonical ids), `source_event_ref`, `expires_at`, `geography`.
Identity: same `event_type` and overlapping affected refs in the same window ⇒ deduplicated; otherwise distinct.
Lifecycle: `detected`, `confirmed`, `mitigating`, `resolved`, `false_positive`.
Confidence: deterministic detection rule ⇒ `1.0`; external feed unrepeated ⇒ `0.7` until confirmed; ml_candidate ⇒ carried confidence is kept ≤ `0.5` until reviewed.
Validation: `occurred_at` ≤ now UTC; severity ∈ closed enum.

### E13 — Scenario

| Canonical name | `Scenario` |
|---|---|
| Source systems | cortex |
| Derivable? | Yes |

Required: `workspace_id`, `scenario_type` (`counterfactual`, `projected`, `comparative`), `name`, `basis_snapshot_id` (graph snapshot), `created_at`, `created_by_ref`.
Optional: `description`, `horizon_days`, `assumptions` (key/value pairs, each value carries evidence ref + confidence), `param_overrides` (deterministic overrides of graph attributes with provenance), `expires_at`.
Identity: distinct by `id` (every generated scenario gets a fresh canonical id).
Uniqueness: unique on `id`.
Lifecycle: `draft`, `active`, `superseded`, `archived`.
Confidence: not applicable; scenarios are hypotheses. Each `assumptions` entry has its own confidence.
Validation: `basis_snapshot_id` must reference an existing snapshot; `assumptions.*.evidence_ref` must be resolvable.

### E14 — Recommendation

| Canonical name | `Recommendation` |
|---|---|
| Source systems | cortex |
| Derivable? | Yes |

Required: `workspace_id`, `recommendation_type` (closed enum: `reroute`, `buffer_stock`, `split_source`, `expedite`, `cancel_order`, `reschedule`, `substitute_product`, `escalate`, `request_review`), `scenario_ref`, `target_refs` (array of canonical ids), `rationale` (human-readable), `explanation` (machine-readable: rule id + policy_version + evidence refs + input hash), `priority` (`p0`–`p4`), `created_at`, `created_by_ref`.
Optional: `expected_impact` (signed dict per impact vector: `on_time_delivery`, `cost`, `risk`, `coverage`), `expires_at`.
Identity: distinct by `id`.
Uniqueness: unique on `id`. A *duplicate policy firing* on the same inputs and policy version is deduplicated by input hash.
Lifecycle: `proposed`, `in_review`, `approved`, `rejected`, `superseded`, `implemented`.
Confidence: deterministic ⇒ `1.0` policy + bounded ML candidate (if used) contributes as an evidence candidate with its own confidence.
Validation: `explanation.evidence_refs` non-empty; `policy_version` non-null; `input_hash` non-null; `target_refs` non-empty.

### E15 — DecisionRecord

| Canonical name | `DecisionRecord` |
|---|---|
| Source systems | cortex |
| Derivable? | No; it is recorded, not inferred. |

Required: `workspace_id`, `decision_type` (`accept_recommendation`, `override`, `manual_action`, `no_action`), `decision_target_ref` (Recommendation id or other target), `decided_by_ref`, `decided_at`, `policy_version`, `input_snapshot_id`, `explanation` (machine-readable: rule id + evidence refs + input hash).
Optional: `decision_rationale`, `follows_recommendation` (bool), `expected_outcome`, `actual_outcome` (filled later), `outcome_snapshot_id`.
Identity: distinct by `id`.
Uniqueness: unique on `id`.
Lifecycle: `recorded`, `in_effect`, `reverted`, `observed`, `closed`.
Validation: `decided_by_ref` non-null; `input_snapshot_id` references a snapshot; for `accept_recommendation`, `decision_target_ref` resolves to a `Recommendation`.

---

## 6. Line modeling

Many operational entities (PurchaseOrder, SalesOrder, Shipment tending to) carry
**lines**. Lines are modeled as second-class objects, not new bare canonical
entities, to keep the entity registry closed. Concretely:

- A `PurchaseOrder` carries `lines`: array of `{line_no, product_ref, quantity, unit, unit_price, promised_delivery_at, external_id}`.
- A `SalesOrder` carries `lines`: array of `{line_no, product_ref, quantity, unit, requested_delivery_at, external_id}`.
- A `Shipment` carries `stops` and `cargo_lines`: arrays describing sequence and cargo.

Lines participate in the graph as edges (e.g. `CONSUMES`, `FULFILLS`) anchored to
the parent entity, not as standalone nodes. A future ACR may promote lines if
operational reasoning requires it; Phase 1 does not.

---

## 7. Lifecycle state shared rules

For every entity:
- A `deprecated`/`merged` state is terminal for identity; the record is retained
  for audit and graph history. It never reverts to `active`.
- `merged` records point to a `merged_into` canonical id (entity resolution).
- Transitions occur through the centralized state machine in `resolution`; raw
  UPDATEs to `lifecycle_state` outside that module are forbidden.
- Every transition emits an entity event (see `04-graph-and-events.md`).

---

## 8. Relationship registry (summary)

Closed set of relationship (edge) types Phase 1 freezes:

| Index | Edge type | Domain | Range | Meaning | Directional? | Evidence-linked? | Derivable? |
|---|---|---|---|---|---|---|---|
| R1 | `SUPPLIES` | Supplier | Product | Supplier provides Product | Yes | Required | No |
| R2 | `STORES` | Facility | Product | Facility holds Product (via InventoryItem) | Yes | Required | Yes (from InventoryItem) |
| R3 | `SHIPS` | Facility/Supplier | Shipment | Origin of a shipment | Yes | Required | No |
| R4 | `SHIPS_DEST` | Shipment | Facility/Customer | Destination of a shipment | Yes | Required | No |
| R5 | `FULFILLS` | Shipment/Inventory | SalesOrder | Resource satisfies SalesOrder (line) | Yes | Required | Yes (planning) |
| R6 | `DEPENDS_ON` | Product | Product | BoM dependency, or order-to-order dependency | Yes | Required | No |
| R7 | `ROUTES_THROUGH` | Shipment | Route | Shipment traverses a Route | Yes | Required | No |
| R8 | `CONSUMES` | PurchaseOrder/SalesOrder | Product | Order consumes Product (line) | Yes | Required | No |
| R9 | `DELIVERS_TO` | Facility/Shipment | Customer | Last-mile destination party | Yes | Required | No |
| R10 | `TRIGGERS` | Event | Entity | Operational event starts/changes an entity state | Yes | Required | No |
| R11 | `AFFECTS` | Event/Scenario | Entity | Event/Scenario influences entity (non-causal) | Yes | Required | No |
| R12 | `MITIGATES` | Recommendation/Action | Event/Risk | Action reduces severity/probability of an Event or risk | Yes | Required | No |
| R13 | `DERIVED_FROM` | Entity/Edge | Entity/Edge | This was derived from that (entity resolution, snapshot, scenario) | Yes | Required | No |
| R14 | `EVIDENCED_BY` | Claim/Edge | Evidence | A claim or edge is backed by this evidence | Yes | Required (it IS the evidence link) | No |

Notes:
- Phase 1 freezes these 14 edge types. Adding one requires an ACR.
- Every edge is **evidence-linked**: it must carry ≥1 evidence ref via
  `EVIDENCED_BY`. An edge with no evidence is forbidden. This is the graph
- encoding of "evidence first" and is enforced by the graph writer.
- `DERIVED_FROM` forms the lineage DAG. Cycles are forbidden; the writer asserts
  acyclicity and rejects cycle-creating writes.
- "Derivable? Yes" means the edge may be materialized automatically from other
  canonical records (the deriving record's provenance becomes the edge's
  evidence).

---

## 9. Edge semantics and rules

The shared edge record is:

| Field | Convention |
|---|---|
| `workspace_id` | scoped |
| `id` | UUIDv7 |
| `edge_type` | one of R1..R14 |
| `source_node_id`, `target_node_id` | canonical ids, validated to types in §8 |
| `valid_from`, `valid_to` | UTC; current edge `valid_to IS NULL` |
| `version` | integer |
| `directional` | bool, fixed per type |
| `evidence_refs` | array of evidence ids, non-empty |
| `provenance` | provenance tuple |
| `confidence` | decimal `[0,1]`; `1.0` unless derived with uncertainty |
| `properties` | key/value map; typed per edge type below |

### 9.1 Per-edge properties and constraints

- **SUPPLIES**: properties `{ lead_time_days, lead_time_confidence, primary (bool) }`. Identity: (Supplier, Product) per workspace; one current edge; new `(lead_time_days)` closes prior `valid_to`.
- **STORES**: properties `{ inventory_item_ref, on_hand_quantity, unit, condition }`. Identity: (Facility, Product, lot, condition) per `as_of`. Derivable from InventoryItem.
- **SHIPS / SHIPS_DEST**: properties `{ shipment_ref, role ("origin"/"destination") }`. Identity: anchored on Shipment id. New shipment ⇒ new edge pair.
- **FULFILLS**: properties `{ fulfillment_type, quantity, unit, sales_order_line_ref, shipment_ref?, inventory_item_ref? }`. Identity: (SalesOrder line ref, fulfilling resource) per workspace.
- **DEPENDS_ON**: properties `{ bom_quantity, unit, substitution_allowed }`. Identity: (Product, Product) per workspace.
- **ROUTES_THROUGH**: properties `{ transit_time_value, transit_time_unit, planned_etd, planned_eta }`. Identity: (Shipment, Route) per workspace.
- **CONSUMES**: properties `{ line_ref, quantity, unit }`. Identity: (order, product, line_ref).
- **DELIVERS_TO**: properties `{ shipment_ref? }`. Identity: (delivering resource, Customer).
- **TRIGGERS**: properties `{ change }`. Identity: (Event, Entity); one current edge per pair.
- **AFFECTS**: properties `{ effect_magnitude }`. Identity: (Event/Scenario, Entity).
- **MITIGATES**: properties `{ target_ref, expected_reduction }`. Identity: (mitigator, target).
- **DERIVED_FROM**: properties `{ derivation_method }`. Identity: (derived, source); acyclic.
- **EVIDENCED_BY**: properties `{ claim_ref }`. Identity: (claim/edge, evidence); 1:1 per claim/evidence pair.

### 9.2 Universal edge rules

1. **Type-valid endpoints.** The writer rejects any edge whose
   `source_node_id`/`target_node_id` entity type does not match §8 Domain/Range.
2. **Evidence required.** `evidence_refs` must be non-empty and each ref resolves
   to an existing evidence record.
3. **Directionality.** Edges typed directional are stored with explicit
   orientation; traversal honors direction unless explicitly queried as "either".
4. **No self-loops.** `source_node_id ≠ target_node_id`.
5. **Single current edge per identity.** New version ⇒ prior `valid_to` filled.
6. **No inferred edge without explicit derivation method.** Inferred edges must
   carry `DERIVED_FROM` back to their derivation and the derivation's evidence.
7. **No cycles in `DERIVED_FROM`.**

---

## 10. Allowed aliases registry (summary)

Phase 1 maintains the alias mapping in the schema-mapping module. Aliases are
NOT authoritative; they exist so source-system columns can be recognized. The
canonical name is the only identity in code.

| Canonical | Aliases (non-exhaustive; mapping table is append-only) |
|---|---|
| Supplier | vendor, vendor_master, vendormaster, bp_supplier |
| Warehouse | dc, distribution_center, wh, wh_master |
| Plant | factory, mfg_site, production_site |
| Facility | site, location, node, facility |
| Product | sku, item, material, partno, part_number |
| InventoryItem | stock, on_hand, inventory_balance, stock_position |
| PurchaseOrder | po, purchase_order, po_line |
| Shipment | load, trip, consignment, movement, freight |
| Route | lane, routing, corridor |
| Customer | account, bp_customer, customer_master, ship_to |
| SalesOrder | so, order, so_line |
| Event | disruption, alert, incident |
| Scenario | scenario, what_if |
| Recommendation | rec, recommendation, action |
| DecisionRecord | decision |

Relationship aliases:
- `SUPPLIES` — `supplies`, `provides`, `delivers_product`
- `STORES` — `stores`, `holds`, `has_stock`
- `SHIPS`/`SHIPS_DEST` — `ships_from`, `ships_to`, `origin_of`, `dest_of`
- `FULFILLS` — `fulfills`, `satisfies`
- `DEPENDS_ON` — `depends_on`, `bom_dep`, `requires`
- `ROUTES_THROUGH` — `routes_through`, `uses_route`
- `CONSUMES` — `consumes`, `ordered_qty`
- `DELIVERS_TO` — `delivers_to`, `delivered_to`
- `TRIGGERS` — `triggers`, `caused_by_inv`
- `AFFECTS` — `affects`, `impacts`
- `MITIGATES` — `mitigates`, `remediates`
- `DERIVED_FROM` — `derived_from`, `from`
- `EVIDENCED_BY` — `evidenced_by`, `supported_by`

---

## 11. Identity and uniqueness across phases

Entity resolution is run in two modes:
1. **Within-source** — duplicates inside one upload/source. Closed on ingest.
2. **Across-source** — the same entity supplied by multiple systems. Closed by
   the resolution module and produces `DERIVED_FROM` edges plus audit events
   (see `04-graph-and-events.md`). Conflicts are surfaced for human review.

A canonical entity always retains all matched `external_ids`. Merged entities
keep `merged_into` pointers and never re-resolve to a different surviving id.

---

## 12. Confidence model (frozen)

Confidence is the only numeric measure of belief Cortex attaches to a claim,
edge, or derived entity. It is in `[0,1]` with 4 decimal places.

- Source-stated value (no derivation): `1.0`. (The system trusts the source as a
  claim; whether the claim is correct is a separate conflict/review concern.)
- Deterministic derivation in Cortex: `1.0`.
- External feed unrepeated: `0.7`, raised to `0.85` on independent second source.
- ML candidate: constrained to `≤0.5` at proposal, regardless of model output.
- Human-approved: promoted to `1.0` for the accepted attribute, with the human
  reviewer stored in provenance.

Confidence never aggregates silently. Where policies combine multiple confidences
(decisions, recommendations) the combining function is named in
`policy_version` and recorded in the explanation.

---

## 12A. Frozen enums summary

To make implementation mechanical, the closed enums are summarized here. They are
the authoritative source; duplicates in the per-entity text are for readability.

- `lifecycle_state` per entity (see §5).
- `facility_type`: `warehouse`, `plant`, `port`, `cross_dock`, `dc`, `supplier_site`, `customer_site`, `other`.
- `inventory condition`: `new`, `in_transit`, `damaged`, `quarantined`, `reserved`.
- Inventory `lifecycle_state`: `on_hand`, `reserved`, `in_transit`, `quarantined`, `depleted`.
- `shipment mode`: `road`, `rail`, `sea`, `air`, `multimodal`.
- Shipment/Purchase/Sales lifecycle states: see §5.
- `event_type`: see E12.
- `severity`: `info`, `warning`, `major`, `critical`.
- `scenario_type`: `counterfactual`, `projected`, `comparative`.
- `recommendation_type`: see E14.
- `priority`: `p0`, `p1`, `p2`, `p3`, `p4`.
- `decision_type`: `accept_recommendation`, `override`, `manual_action`, `no_action`.
- Decision lifecycle: `recorded`, `in_effect`, `reverted`, `observed`, `closed`.
- `risk_tier`: `low`, `medium`, `high`, `critical`.
- Source system categories (closed): `erp`, `wms`, `tms`, `oms`, `mes`,
  `scm_planning`, `spreadsheet`, `manual`, `external_feed`, `ml_candidate`.

---

## 13. Validation constraints, summarized

For every entity and edge, validation is performed at acceptance time in the
`resolution` module and gates whether a candidate becomes canonical.

1. Required properties non-null and non-empty (strings), concrete (refs).
2. Enum fields valid.
3. Units ∈ unit registry; quantities ≥ 0.
4. Dates ≤ now UTC where the field represents a past/present instant;
   `eta ≥ etd` where both present; `promised ≥ placed` where both present.
5. Refs resolve to an existing canonical entity of the correct type.
6. Country ISO 3166-1 alpha-2; currency ISO 4217.
7. Identity/uniqueness satisfied within the workspace.
8. Evidence attached (edges and material attributes).
9. Confidence within `[0,0.5]` for any ml_candidate source and `[0,1]` otherwise.
10. Self-loops and `DERIVED_FROM` cycles rejected.

Invalid candidates do not become canonical; they are stored as
`pending_review` claims with a `validation_issue_type` for human action.

---

## 14. Frozen decisions summary

- Closed set of 15 entity types (E1–E15) and 14 edge types (R1–R14).
- `Facility` is an abstract supertype; new physical-node subtypes reuse
  `facility_type`, not a new entity type.
- Lines are modeled within their parent order/shipment entity; not bare entities.
- Every edge must carry evidence (no orphan edges).
- Confidence model is fixed §12 and cyclometric forbidden in `DERIVED_FROM`.
- Adding an entity or edge type requires an ACR.

Phase 1 proceeds to `03-canonical-data-model.md` (how sources become these
canonical records) on this basis.
