# 04 — Graph Model, Event Model, and Operational Intelligence Layers

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `02-ontology.md`, `03-canonical-data-model.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## Part I — Graph Model

### 1. Purpose

The graph is **not** a visualization layer. It is the **operational memory and
reasoning substrate** of Cortex. Every downstream intelligence component (signals,
scenarios, recommendations, decision memory) reads the graph and writes back to
it through versioned, audited operations. This part of the document freezes the
graph's conceptual structure, its versioning, snapshots, replay/diff/temporal
behavior, and its MVP scope.

Physical storage of the graph is a SQL adjacency representation in PostgreSQL
(see `06-database-strategy.md`). Phase 1/2 deliberately does not introduce a
separate graph database; the operational graph must remain transactional with
the canonical/audit models so that evidence and graph coherence is guaranteed.

---

### 2. Node types

Nodes are the canonical entities from `02-ontology.md`. A node record:

| Field | Convention |
|---|---|
| `node_id` | canonical entity id (UUIDv7) |
| `workspace_id` | scoped |
| `node_type` | one of E1–E15 |
| `entity_type` | equals `node_type` for E1..E13; E14/E15 (Recommendation/DecisionRecord) are also nodes |
| `version` | current entity version |
| `valid_from`, `valid_to` | node lifecycle window |
| `lifecycle_state` | per `02-ontology.md` |
| `attributes` | reference to the canonical attribute envelope (read-through, not copied) |
| `first_evidence_id`, `latest_evidence_id` | hot path |

Node-type closure mirrors the entity-type closure. Adding a node type requires
an ACR (same gate as adding an entity type).

---

### 3. Edge types

Edges are the 14 relationship types from `02-ontology.md` §8 (R1–R14).
Every edge carries the edge record from `02-ontology.md` §9 plus the
graph-specific fields below.

| Field | Convention |
|---|---|
| `edge_id` | UUIDv7 |
| `workspace_id` | scoped |
| `edge_type` | R1..R14 |
| `source_node_id`, `target_node_id` | canonical ids |
| `directional` | bool, fixed per type |
| `valid_from`, `valid_to` | UTC; open = `NULL` |
| `version` | integer |
| `evidence_refs` | non-empty array |
| `provenance` | tuple |
| `confidence` | `[0,1]` |
| `inferred` | bool; true ⇒ must carry `DERIVED_FROM` |
| `derivation_ref` | UUIDv7? required if `inferred=true`; points to the derivation record |
| `properties` | per-type (see `02-ontology.md` §9.1) |

Universal edge rules (`02-ontology.md` §9.2) apply: type-valid endpoints,
non-empty evidence, directionality honored, no self-loops, single current edge
per identity, inferred edges require explicit derivation, no `DERIVED_FROM`
cycles.

---

### 4. Evidence-linked vs inferred edges

This distinction is first-class and enforced.

- **Evidence-linked edge** — backed directly by at least one evidence record
  (the `evidence_refs` array is non-empty and each ref resolves). These are the
  default. Every edge is at least evidence-linked.
- **Inferred edge** — additionally marked `inferred=true` and rooted in a
  derivation:
  - `STORES` edges are inferred from `InventoryItem` claims: deriving an
    InventoryItem canonical record produces a `STORES` edge with
    `derivation_ref` to the InventoryItem id and the InventoryItem's evidence
    becomes the edge's evidence.
  - `FULFILLS` edges are inferred when a planning or fulfilment rule matches a
    shipment/inventory to a sales-order line; the rule id and policy_version
    are stored in `derivation_ref` and the matched records' evidence becomes the
    edge's evidence.
  - `TRIGGERS`/`AFFECTS` edges from signal detection are inferred; the signal
    detection record (itself versioned and auditable) is the `derivation_ref`.

Inferred edges are deterministic functions of (graph state, policy_version).
Replay of the same policy version on the same inputs MUST reproduce identical
inferred edges. Inferred edges never come from ML.

---

### 5. Snapshots

A snapshot is an immutable, sealed point-in-time view of the entire workspace
graph. The graph is queried through snapshots to guarantee temporal
consistency for downstream reasoning.

### 5.1 Snapshot record

| Field | Notes |
|---|---|
| `snapshot_id` | UUIDv7 |
| `workspace_id` | scoped |
| `parent_snapshot_id`? | previous sealed snapshot (`DERIVED_FROM`) |
| `created_at` | timestamps |
| `created_by_ref` | user or `system` |
| `policy_version` | the policy version under which inferred edges were (re)computed |
| `sealed` | bool; false during construction, true forever once sealed |
| `sealed_at`? | when sealed |
| `node_count`, `edge_count`, `inferred_edge_count` | stats |
| `readiness_score` | per `03-canonical-data-model.md` §11.3 |
| `readiness_state` | `ready`, `blocked` |
| `content_hash` | sha256 over the deterministic canonical serialization (`§8.3`) |
| `object_ref` | object-storage pointer to the materialized snapshot artifact |

Invariants:
- `sealed=true` ⇒ immutable. A sealed snapshot is never edited; corrections
  arrive as a new snapshot with `parent_snapshot_id` set.
- `parent_snapshot_id` chains form a linear, append-only mainline per workspace.
- Branch snapshots (e.g. scenarios) fork from a base and never become the
  mainline; see Part IV-Scenarios.
- `content_hash` enables tamper-evidence without re-reading bytes and enables
  cheap equality checks.

### 5.2 Construction

A snapshot is constructed by a background job (`graph.snapshot.build`) that:
1. Locks the workspace for snapshotting (briefly; only new appends block).
2. Reads current `(valid_to IS NULL)` nodes and edges.
3. Recomputes inferred edges for the `policy_version` if requested (else reuses
   the prior snapshot's inferred edges whose inputs are unchanged — see §6.2).
4. Writes the materialized artifact to object storage and writes the `snapshots`
   row, then seals it and emits `graph.snapshot.sealed`.
5. Runs the readiness contract and emits `graph.readiness.determined`.

### 5.3 MVP scope of snapshots

Phase 2 ships on-demand and on-event snapshot build. Phase 1 freezes the
contract; implementation is later. Phase 1 does not require incremental
snapshot maintenance — whole-snapshot rebuild is acceptable for pilot scale.

---

### 6. Replay, diff, history, temporal behavior

#### 6.1 Replay (deterministic recompute)

Replay takes a sealed snapshot's inputs (canonical state as of
`parent_snapshot_id` + accepted claims/evidence + policy_version) and recomputes
the graph. Because every operation is deterministic and policy-versioned, replay
MUST produce a snapshot with identical `content_hash`.

Replay is used by:
- audit (an external auditor can re-derive any sealed snapshot),
- the regression suite (`10-testing-and-ci-cd.md`),
- migrations that change a policy version (recompute forward from a base).

Replay over a *different* policy version produces a new snapshot; the diff is
captured (§6.2) and stored as part of the policy-version upgrade audit.

#### 6.2 Diff

A diff is the structural delta between two snapshots of the same workspace
mainline (or between a scenario and its base snapshot). A diff record:

| Field | Notes |
|---|---|
| `diff_id` | UUIDv7 |
| `from_snapshot_id`, `to_snapshot_id` | |
| `node_added`/`node_removed`/`node_changed` | arrays |
| `edge_added`/`edge_removed`/`edge_changed` | arrays |
| `attributes_changed` | per node, per attribute (with old/new envelopes) |
| `inferred_impact` | which inferred edges changed due to the diff |
| `computed_at` | |
| `content_hash` | over the canonical diff serialization |

Diffs are themselves stored and versioned so that "why did the graph change" is
queryable without replaying. Phase 1 ships the diff schema; Phase 2 implements
diff computation.

#### 6.3 History (per-node and per-edge)

History queries return the temporal sequence of accepted versions of a node or
edge. The canonical attribute envelope (`03-canonical-data-model.md` §5.2)
already carries `(valid_from, valid_to)` per attribute, so history is a
projection, not a separate store. The graph API exposes history through
`GET /graph/nodes/{id}/history` and `GET /graph/edges/{id}/history`
(`05-api-standards.md`).

#### 6.4 Temporal queries

The graph supports queries at a point in time or over an interval, using the
valid windows on nodes/edges/attributes. Temporal query params:
- `as_of` — point in time (returns the version valid at that time).
- `from`, `to` — interval (returns versions whose window intersects).
- `policy_version` — fix the inferred-edge policy (for replay-equivalence).

Temporal queries on a *sealed snapshot* return the snapshot's view at its
`created_at`, plus optional `as_of` for time-before-snapshot reasoning.

#### 6.5 Provenance behavior in the graph

- Every read surface of the graph that returns an edge or node must also return
  a path to evidence (`evidence_refs`, `provenance`, `derivation_ref` if
  inferred). There is no "graph only" API that strips evidence.
- Every write surface of the graph must reject writes with non-resolving
  evidence refs (`evidence_required` enforced at the writer).
- The lineage DAG (DERIVED_FROM) must reach evidence within ≤3 hops from any
  canonical fact, consistent with `03-canonical-data-model.md` §10.2.

---

### 7. What the graph *cannot* do in the MVP

Defining scope boundaries explicitly:

1. **No automatic graph mutation from incoming data.** New claims update
   canonical entities and produce attribute-envelope versions; the graph is
   materialized on snapshot build, not on every claim. This keeps the graph
   consistent and auditable.
2. **No ML-driven edge creation.** ML candidates are claims awaiting review and
   may never create edges directly.
3. **No cross-workspace edges.** Edges live within a single workspace. Cross-
   workspace modeling (a supplier shared across two business units) is done by
   separate canonical entities in each workspace, with optional cross-workspace
   reference indexes outside the graph (see `06-database-strategy.md`).
4. **No "live" graph read at the same consistency level as a transaction.**
   Snapshots are the read unit. The default graph APIs read the latest sealed
   snapshot. A separate "staging" read mode is provided for review queue
   inspection of unreviewed changes (clearly labeled, never used for decisions).
5. **No ad-hoc UPDATE/DELETE on adjacency.** All edges are versioned via append
   and `valid_to` is set only through the graph writer, which is the sole
   touched module.

---

### 8. Graph API surface (read)

This defines the read contract (URLs formalized in `05-api-standards.md`):

- `node(id)` → node + attributes + evidence preview + lineage summary
- `edge(id)` → edge + evidence + derivation
- `neighbors(node_id, types?, depth?, as_of?)` → paginated nodes/edges
- `path(src, dst, edge_types?, as_of?)` → shortest paths + alternatives
- `impact(node_id, edge_types?, as_of?)` → forward-reachable subgraph
- `history(node_id|edge_id, from?, to?)` → version sequence
- `diff(from_snapshot_id, to_snapshot_id)` → diff record
- `snapshot(workspace_id, as_of?)` → latest sealed snapshot metadata + counts

Every read returns evidence and confidence inline. Paginated endpoints enforce
the pagination contract (`05-api-standards.md`).

---

## Part II — Event Model

### 9. Purpose and shape

Cortex uses an **append-only event log** to record every meaningful state change
in and around the graph and the platform foundation flow. The event model is the
spine of audit, replay, lineage, and observability. Every system component can
rely on this event log.

Audit events are different from `Event` operational entities (`02-ontology.md`
E12). Audit events record *system and human actions*; operational `Event`
entities record *observed supply-chain occurrences*. Both share the structural
contract in this part for consistency, but they live in distinct tables and have
distinct type prefixes (`04-graph-and-events.md` §11).

### 10. Event record (frozen shape)

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUIDv7 | unique, time-sortable |
| `workspace_id` | UUIDv7? | null only for tenant/global events |
| `tenant_id` | UUIDv7 | never null |
| `event_type` | string | namespaced identifier (see §11) |
| `event_version` | integer | schema version of this event type |
| `occurred_at` | timestamp UTC | wall clock at action time |
| `recorded_at` | timestamp UTC | when persisted (may differ on async paths) |
| `actor_type` | enum | `user`, `system`, `worker`, `ml_candidate`(note: ML only proposes; never writes audit writes itself) |
| `actor_id` | UUIDv7?, | user/worker id; `system` uses a fixed role id |
| `subject_type` | enum?, | the affected object category |
| `subject_id` | UUIDv7? | affected object id |
| `causation_id` | UUIDv7? | the event that caused this (causation chain) |
| `correlation_id` | UUIDv7?, | request/job correlation (cross-bounded-context) |
| `request_id` | string?, | idempotency/request id of the API call, if any |
| `job_id` | UUIDv7?, | background job id, if produced by a worker |
| `payload` | jsonb | event-type-specific, schema-versioned |
| `payload_schema_version` | integer | tracks `payload` shape |
| `policy_version` | string?, | required for any deterministic-policy action |
| `input_hash` | string?, | required for any deterministic decision/recommendation |
| `checksum` | string | sha256 over the canonical serialization (§12.3) |
| `prev_event_id` | UUIDv7? | previous event for this workspace (hash chain) |
| `prev_event_hash` | string? | hash of the prior event (tamper-evident chain) |
| `metadata` | jsonb | free-form diagnostic metadata |

### 11. Event types (closed namespace)

Event types are a closed set grouped by lifecycle stage. Adding a type requires
an ACR.

#### 11.1 Platform foundation events (MVP)
- `upload.received` — raw upload enqueued for processing.
- `upload.validated` — validation result (ok or issues).
- `upload.rejected` — validation failed terminally.
- `schema_mapping.applied` — source columns → canonical attributes.
- `evidence.extracted` — evidence + claims created from source object.
- `claim.created` — a claim was written (often batched in `evidence.extracted`).
- `claim.validation_issue` — validation issue raised.
- `conflict.detected` — conflict raised.
- `conflict.resolved` — conflict resolved (chosen claim, rationale).
- `claim.review.requested` — human review requested.
- `claim.review.completed` — review result.
- `entity.created`, `entity.version_added`, `entity.lifecycle_changed`,
  `entity.merged`, `entity.rewritten`.
- `edge.created`, `edge.version_added`, `edge.superseded`.
- `graph.snapshot.build.requested`, `graph.snapshot.sealed`.
- `graph.readiness.determined` — readiness decision.

#### 11.2 Operational intelligence events (later phases)
- `signal.detected`, `signal.superseded`.
- `scenario.created`, `scenario.updated`, `scenario.archived`.
- `recommendation.proposed`, `recommendation.review.requested`,
  `recommendation.approved`, `recommendation.rejected`,
  `recommendation.superseded`, `recommendation.implemented`.
- `decision.recorded`, `decision.reverted`, `decision.observed`.
- `outcome.recorded`.

#### 11.3 System / admin events
- `workspace.created`, `workspace.updated`, `workspace.archived`.
- `user.invited`, `user.role_changed`, `user.deactivated`.
- `policy.published` — a new `policy_version` published.
- `ml.model.promoted`, `ml.model.shadow_started`, `ml.model.shadow_stopped`.
- `ml.candidate.proposed` — ML submitted a candidate claim.

### 12. Event model invariants

#### 12.1 Immutability
- The `audit_events` table is INSERT-only at the DB grant level. There is no
  UPDATE, no DELETE, no TRUNCATE by the application role. Deletions for
  retention are done by a separate role with explicit, logged, time-bounded
  authority (see `09-security.md`).

#### 12.2 Linkage
- **Source linkage**: `subject_type`/`subject_id` identify the affected object.
- **Causation linkage**: `causation_id` points to the event that caused this
  one (causation is a chain, not a tree).
- **Correlation linkage**: `correlation_id` ties events across the same
  request/job, including downstream worker events.

#### 12.3 Checksum and chain
- `checksum` = sha256 over the canonical JSON serialization of the event
  payload, sorted keys, no whitespace, UTF-8.
- `prev_event_id` / `prev_event_hash` form a hash chain per `(tenant_id,
  workspace_id)` key space. A verification job recomputes the chain and alerts
  on any break (tamper-evidence). The chain is best-effort on the hot path and
  repaired by background verifier; a broken chain blocks release gates.

#### 12.4 Versioning
- `event_type` + `event_version` + `payload_schema_version` uniquely identify a
  schema in the schema registry (see `05-api-standards.md` §contract versioning).
- Backward-compatible field additions bump `payload_schema_version` only;
  breaking changes bump `event_version` and require an explicit migration in
  the producer and a reader policy (old version retained until consumers migrate).
- Frozen in Phase 1: events are append-only and never edited; corrections are
  new events of type `*.corrected` that reference the original by `causation_id`.

#### 12.5 Timestamping
- `occurred_at` is the action time; `recorded_at` is the persistence time. Neither
  may be edited. Worker events may have `occurred_at` ≠ `recorded_at` because of
  async processing; the gap is monitored.

### 13. Event emission discipline

- Every state-changing operation emits exactly the events defined here. The
  `audit` module is the only writer; other modules call `audit.emit(event)`.
- Events are emitted in the same DB transaction as the state change where
  possible (strong audit); where the change is in object storage, the event is
  emitted after the storage write succeeds and carries the object's `content_hash`
  to bind the two.
- Idempotency: an event carries the originating `request_id`/`job_id`; duplicate
  dispatch of the same idempotent job does not produce duplicate events (the
  `audit_events` unique constraint on `(correlation_id, event_type, subject_id)`
  plus `request_id` dedupes — see `06-database-strategy.md`).

### 14. Operational `Event` entity vs audit events (clarification)

- Operational `Event` (E12) captures a *supply-chain occurrence* (e.g. a port
  closure). It is a canonical entity and participates in the graph as a node.
- When Cortex detects an operational event via a signal rule, the system emits
  an audit event `signal.detected` whose `subject` is the operational Event
  entity and whose `payload` records the rule. The operational Event node is
  thus the *subject*, the audit event the *record of detection*.

This separation is fixed: never conflate "an event happened in the supply chain"
with "an event happened in Cortex".

---

## Part III — Signals Layer

### 15. Purpose

Signals are **deterministic detections** of conditions in the canonical graph
that warrant attention. A signal is not a recommendation; it is an observation.
Signals feed scenarios and recommendations; they never act on their own and
never modify the graph.

### 16. Signal record

| Field | Notes |
|---|---|
| `signal_id` | UUIDv7 |
| `workspace_id` | scoped |
| `signal_type` | closed enum (below) |
| `snapshot_id` | the sealed snapshot the signal was computed on |
| `policy_version` | the rule-pack version |
| `input_hash` | sha256 over deterministic inputs |
| `target_refs` | array of canonical node/edge ids the signal concerns |
| `severity` | `info`, `warning`, `major`, `critical` |
| `evidence_refs` | non-empty (the graph facts that support it) |
| `explanation` | human-readable + machine-readable (rule id, evidence ids, input hash) |
| `confidence` | deterministic ⇒ 1.0 (an ML candidate supporting score is a separate evidence candidate ≤0.5) |
| `detected_at` | |
| `lifecycle_state` | `active`, `acknowledged`, `superseded`, `dismissed` |
| `superseded_by`? | new signal id |
| `algorithm_version` | | 

### 17. Signal types (closed)

- `single_source_dependency` — a Product is supplied by exactly one Supplier
  for a facility.
- `lead_time_drift` — observed lead time deviates from declared by ≥N% over M
  shipments.
- `inventory_below_safety_stock` — on-hand minus reserved < safety stock for ≥1
  period.
- `shipment_delay_predicted` — ETA exceeds promised window by ≥N% (also emitted
  after the fact as `shipment_delay_actual`).
- `route_disruption` — a Route's `risk_index` crosses a threshold (an external
  event-driven subtype is `route_disruption_event`).
- `supplier_concentration` — a buyer's spend with top-1 supplier exceeds X%.
- `stock_out_imminent` — projected depletion before next replenishment.
- `quality_trend` — quality-issue Event density per supplier exceeds threshold.
- `cost_anomaly` — unit cost moves beyond band vs. historical.
- `graph_inconsistency` — internal graph violation (orphan ref, missing-unit
  cluster) detected by a graph-health rule.

A signal type is added via an ACR. Each type has a versioned, deterministic
definition (algorithm version + policy version + thresholds).

### 18. Signal computation contract

- Deterministic: same graph snapshot + same policy_version ⇒ same signals and
  same `input_hash`.
- Backed by evidence: `evidence_refs` reference graph facts (edges/nodes) that
  exist in the snapshot; ML candidates may **only** appear as additional
  evidence candidates, not as the sole support.
- Emitted as `signal.detected`; supersession emits `signal.superseded`.
- A signal references the operational `Event` entity when one exists; otherwise it
  is a pure observation (an `Event` node may be created by human or by a rule
  that promotes the signal to a confirmed Event — a state-machine transition
  audited separately).

### 19. MVP scope

Phase 1 freezes signal types and the contract. Phase 2 ships a deterministic
subset (`single_source_dependency`, `inventory_below_safety_stock`,
`shipment_delay_predicted`) computed over sealed snapshots. The full catalog
ships in later phases.

---

## Part IV — Scenarios Layer

### 20. Purpose

A scenario is a **what-if graph variant** — a counterfactual, projected, or
comparative branch off a base snapshot. Scenarios let Cortex reason about "what
might happen if …" without touching the canonical mainline.

### 21. Scenario record (see E13)

In addition to E13 fields, the scenario carries:

| Field | Notes |
|---|---|
| `base_snapshot_id` | the sealed mainline snapshot it forks from |
| `branch_snapshot_id` | the sealed branch snapshot containing the scenario's graph state |
| `param_overrides` | key/value: deterministic overrides of graph attributes (e.g. set Route X `risk_index=0.9`; assume Supplier Y `lifecycle_state=suspended`) |
| `assumptions` | array of {key, value, evidence_ref, confidence} |
| `recompute_inferred` | bool; whether inferred edges were recomputed under the scenario policy |
| `horizon_days` | projection horizon if `scenario_type=projected` |
| `created_by_ref` | user or system |
| `status` | `draft`, `active`, `superseded`, `archived` |

### 22. Creation semantics (frozen)

1. A scenario is always created from a sealed base snapshot (`DERIVED_FROM`).
2. `param_overrides` are deterministic and typed; each override carries
   provenance + evidence_ref + confidence (no override without evidence).
3. The scenario reads the base snapshot, applies overrides, optionally
   recomputes inferred edges under the current `policy_version`, and seals a
   `branch_snapshot_id`. The branch snapshot is immutable once sealed.
4. The scenario graph is read-only; scenarios cannot mutate mainline.
5. Scenarios are workspace-scoped; a scenario in workspace A cannot read workspace B.

### 23. Comparatives

`scenario_type=comparative` scenarios compare two sealed snapshots or two
scenarios and produce a `diff` (Part I §6.2) plus a determinism report (which
inferred edges differ and why). Phase 1 contracts the diff; Phase 2 implements.

### 24. Assumption discipline

Every scenario assumption becomes evidence for downstream recommendations made
under that scenario. If an assumption is unsupported, no recommendation may be
made from the scenario. Assumptions are first-class evidence candidates.

---

## Part V — Recommendations Layer

### 25. Purpose

Recommendations are **deterministic, evidence-backed proposals** for action,
derived from (graph snapshot, scenario, signals, policy version). They are
reviewed and either approved, rejected, or superseded. They never execute on the
operational world by themselves — that requires a human `DecisionRecord`.

### 26. Recommendation record (see E14)

Plus frozen enforcement:

- `explanation` is mandatory and structured:
  ```
  explanation = {
    rule_id:     string,            # e.g. "reroute_to_lower_risk@2026.01"
    policy_version:    string,
    inputs_hash: string,           # hash of deterministic inputs (graph + signals + scenario + overrides)
    evidence_refs: [uuid],          # non-empty
    assumptions_refs: [uuid]?,      # references to scenario assumptions if applicable
    derived_from_scenario?: uuid,
    reasoning:  human_readable,
    ml_candidate_ref?: uuid         # if an ML candidate was used as input evidence
  }
  ```
- `expected_impact` is signed per vector and carries a confidence; the
  combining function is named in `policy_version`.
- An ML candidate may contribute to `expected_impact` only as an evidence
  candidate with `confidence ≤ 0.5`; it never sets the recommendation's own
  confidence (always `1.0` for the deterministic policy).

### 27. Determinism

- Same (snapshot, scenario, signals, policy_version) ⇒ identical recommendation,
  identical `inputs_hash`. Replay reproduces it.
- If a recommendation's inputs change (new signal, new evidence, new policy
  version) it is `superseded` and a new recommendation is generated; the
  supersession link is preserved.

### 28. MVP scope

Phase 1 freezes types and the contract. Phase 2 ships the deterministic types
`reroute`, `buffer_stock`, `split_source`, `escalate` for the MVP signal set;
others follow in later phases.

---

## Part VI — Decision Memory Layer

### 29. Purpose

Decision memory is the **auditable closure of the intelligence loop**: every
recommendation or human action becomes a `DecisionRecord`, and later outcomes
are recorded against it. This is what makes Cortex an *operational intelligence*
platform and not a black box of recommendations.

### 30. DecisionRecord (see E15)

Plus frozen enforcement:

- Every `DecisionRecord` references an `input_snapshot_id` (the sealed snapshot
  at decision time) so the decision is reproducible.
- `decided_by_ref` is non-null; no anonymous decisions exist.
- `policy_version` and `input_hash` are non-null for `accept_recommendation`
  and `override`.
- `decision_type = no_action` records the decision to *not* act; this is the
  same shape used by `graph.readiness.determined` (§11 Part II). Decision memory
  thus captures both "we decided the system is ready" and "we decided to do
  nothing about signal X".
- A decision that follows a recommendation copies the recommendation's
  `explanation` (with provenance) into the decision record and sets
  `follows_recommendation=true`.

### 31. Outcome recording and feedback

- After a decision, downstream evidence (shipments arriving, inventory changes,
  supplier-status updates) is later ingested into canonical entities.
- A scheduled job (`outcome.evaluate`) matches each open decision to its
  expected vs actual outcomes and emits `outcome.recorded` with deltas.
- The decision lifecycle transitions: `recorded → in_effect → observed → closed`
  (or `reverted` at any time).
- Outcomes feed back into the graph as new events/claims; signals recomputed on
  the next snapshot may close or escalate the originating signal (`signal.detected`
  → supersession linkage). This closes the loop deterministically.

### 32. Replay of decisions

- Decisions are deterministic functions of their recorded inputs; replay tests
  (Phase 2) re-derive recommendations and compare against the stored
  decision's `input_hash`. Drift is a release-blocking regression.

### 33. MVP scope

Phase 1 freezes the decision memory contract and the `no_action` readiness
decision. Phase 2 implements readiness decisions and no-action recording of
signals. Accept/reject of full recommendations ships with the recommendations
phase.

---

## Part VII — Frozen scope summary (MVP vs. later vs. frozen)

| Concern | MVP (Phase 2) | Later phases | Frozen now (Phase 1) |
|---|---|---|---|
| Graph nodes/edges | all 15 entity types + 14 edge types | new types require ACR | types, invariants, evidence-required, versioning, snapshots, replay contract |
| Snapshots | on-demand + on-event | incremental maintenance | snapshot schema, seal, hash, parent chain |
| Diffs | basic diff between two snapshots | advanced inferred-impact diff | diff schema |
| Signals | 3 deterministic types | full catalog | signal contract, types enum |
| Scenarios | single-shot counterfactual from base snapshot | projected + comparative, branching | scenario contract |
| Recommendations | 4 types under the MVP signal set | full catalog | recommendation + explanation contract |
| Decisions | readiness `no_action` + signal acknowledgement | full accept/reject/override + outcomes | decision contract, replay, outcome loop |
| Event model | foundation events + signal/decision subset | full intelligence event set | event shape, immutability, linkage, checksum/chain, versioning |

---

## Part VIII — Frozen decisions summary

- Operational graph in PostgreSQL; snapshots are the read unit; no live-transaction graph.
- Evidence is required on every edge and every signal/recommendation/scenario/decision reasoning.
- Inferred edges are deterministic, policy-versioned, and acyclic in lineage.
- Append-only audit event log with hash chain; INSERT-only at the DB grant level.
- The deterministic readiness decision is the first entry in decision memory.
- ML candidates are evidence-candidates (`confidence ≤ 0.5`), never facts and never
  write canonical/audit/graph/decision state directly.
- Replay is a first-class contract: same inputs + same policy version ⇒ identical output.

Phase 1 proceeds to `05-api-standards.md` on this basis.
