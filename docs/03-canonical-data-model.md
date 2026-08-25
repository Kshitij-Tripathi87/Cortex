# 03 — Canonical Data Model

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `02-ontology.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and scope

This document freezes the **internal model Cortex uses after ingestion** — the
shape of records once raw ERP/WMS/TMS exports have been parsed, mapped, and
normalized, but before entity resolution and conflict review produce final
canonical entities.

It must be precise enough that claim extraction, conflict detection, entity
resolution, graph construction, and downstream reasoning can be implemented
directly from it without reinterpretation.

In scope: claim structure, normalization rules, conflict representation,
provenance, confidence, lineage, and the readiness contract that gates whether
canonical entities are usable for downstream intelligence.

Out of scope: graph storage layout (`06-database-strategy.md`), event schemas
(`04-graph-and-events.md`), API payloads (`05-api-standards.md`).

---

## 2. Three layers of data in Cortex

Cortex separates three layers explicitly. They never merge.

```
Layer A — Raw layer     immutable uploads + extracted tables + evidence artifacts
Layer B — Claim layer   normalized, provenance-attached candidate facts
Layer C — Canonical     accepted, versioned entities + edges (the graph)
```

- **Layer A** is write-once. It is the universe of evidence. A Layer-A object
  may only be added (and later lifecycle-deleted at the storage level), never
  modified.
- **Layer B** is append-only by ingestion. A claim asserts one attribute of one
  candidate entity. Multiple claims on the same attribute exist by design; that
  is the substrate of conflict detection.
- **Layer C** is the versioned outcome. A canonical attribute is the
  conflict-resolved, human-review-gated projection of Layer B claims, plus a
  pointer to the claims and evidence that justify it. Layer C is what the graph,
  signals, scenarios, recommendations, and decisions consume.

A single thing lives in exactly one layer at a time. No "canonical" record is
allowed to bypass Layer B. This is the structural enforcement of
*evidence first*.

---

## 3. The Claim object (Layer B)

The claim is the unit of asserted fact. Every canonical entity attribute and
every graph edge is, in essence, backed by one or more claims.

### 3.1 Claim record fields

| Field | Type | Notes |
|---|---|---|
| `claim_id` | UUIDv7 | Stable forever. |
| `workspace_id` | UUIDv7 | Scoped. |
| `upload_id` | UUIDv7 | The Layer-A upload that produced it. |
| `source_object_id` | UUIDv7 | The exact extracted-table row id (Layer A). |
| `source_system` | enum (§§ below) | `erp`, `wms`, `tms`, `oms`, `mes`, `scm_planning`, `spreadsheet`, `manual`, `external_feed`, `ml_candidate`. |
| `source_record_ref` | string | The row pointer inside the source (e.g. CSV row id, JSON path, sheet+cell). |
| `entity_candidate_key` | obj | The identity key computed per `02-ontology.md` identity rules; used by entity resolution. |
| `entity_type` | enum | One of the entity types in `02-ontology.md`. |
| `attribute` | string | The canonical attribute name (e.g. `legal_name`, `quantity`, `lead_time_days`). |
| `value` | typed value | The normalized value (see §4). |
| `value_unit` | enum?, | Unit if `value` is a quantity. |
| `value_kind` | enum | `scalar`, `ref`, `enum`, `timestamp`, `quantity`, `monetary`, `geo`, `string`. |
| `normalized_at` | timestamp | When normalization ran. |
| `normalizer_version` | string | The version of the schema-mapping/normalizer. |
| `provenance` | tuple | The provenance tuple (`01-architecture.md`). |
| `evidence_id` | UUIDv7 | The evidence record backing this claim (see §7). |
| `confidence` | decimal `[0,1]` | Per `02-ontology.md` §12. |
| `claim_state` | enum | `pending_review`, `accepted`, `rejected`, `superseded`, `conflicted`. |
| `review_id` | UUIDv7? | If reviewed. |
| `extracted_at` | timestamp | When evidence was extracted. |
| `valid_from` | timestamp | The asserted "as-of" of the claim (e.g. InventoryItem snapshot time). |
| `valid_to` | timestamp?, | Closed if superseded. |
| `lineage` | obj | `parent_claim_id?`, `derivation_method?`. |

### 3.2 Invariants

- A claim references exactly one `evidence_id`. A claim without evidence is
  forbidden and cannot be written.
- `entity_candidate_key` is computed deterministically from identity rules; it
  is how two claims become "the same entity attribute" candidates.
- `claim_state` transitions only through the centralized state machine in
  `resolution`. No UPDATE bypasses the state machine.
- `ml_candidate` claims are `pending_review` at creation and capped at
  `confidence ≤ 0.5`; they cannot be `accepted` without human review.
- Claims are append-only: a corrected source issues a *new* claim, never an
  UPDATE of an existing claim. The earlier claim is set to `superseded` via a
  review/state-machine transition that records why.

### 3.3 Claim states

- `pending_review` — default. Awaiting validation/resolution/review.
- `conflicted` — participates in a detected conflict (see §6).
- `accepted` — promoted to Layer C as the canonical attribute value.
- `rejected` — invalid or human-rejected; retained for audit; never promoted.
- `superseded` — replaced by a later claim; retained for audit.

---

## 4. Normalization rules (frozen)

Raw source rows become claims through deterministic normalization. Every rule is
implemented once in `domain.normalization` and used uniformly.

### 4.1 Column-name normalization
- Lowercase, trim, collapse inner whitespace, replace runs of `[^a-z0-9_]+`
  with `_`. Remove prefixes like `col_`. Strip surrounding quotes.
- Map the resulting token through the alias registry (`02-ontology.md` §10) to
  the canonical attribute. Unmapped columns become `unknown_<original>` claims
  with `confidence 1.0` and `claim_state pending_review`; they are surfaced for
  schema-mapping review, never silently dropped.

### 4.2 String normalization
- Trim leading/trailing whitespace; collapse internal runs of whitespace.
- Unicode NFC normalization for text fields.
- Phone numbers, tax ids, postcodes are NOT reformatted — they are stored as
  given, because over-normalization destroys identity matching. Identity rules
  operate on trimmed, case-folded (where the entity rule says so) versions.

### 4.3 Date and timestamp normalization
- Always parse to UTC ISO-8601 with a `Z` suffix.
- If source has a timezone offset, convert to UTC and store the original
  timezone in `provenance.metadata.tz_offset` so it can be undone for display.
- If source has no timezone, the source's declared workspace timezone is applied
  and conversion to UTC is recorded with `assumed_tz` in provenance metadata.
- Date-only fields become midnight UTC of that date; the time component is
  recorded as `date_only: true` in provenance metadata.

### 4.4 Unit normalization
- A quantity is stored as `(value, unit)`. The unit MUST be one of the unit
  registry (`02-ontology.md` §3.1).
- If the source uses a non-registry unit, `normalize_unit()` converts to the
  canonical unit for that dimension when an unambiguous mapping exists; the
  original unit and original value are kept in provenance metadata.
- If the unit is absent, the claim is `pending_review` with a `missing_unit`
  validation issue (see §8). It is never silently defaulted.

### 4.5 Numeric normalization
- Strip thousands separators per the source's locale (configured per upload;
  default `,` thousands and `.` decimal).
- Quantities and monetary values are stored as Decimal with 4 dp; monetary
  values always carry the currency code from §3.1.

### 4.6 Missing-value representation
- An empty cell becomes the canonical `MISSING` sentinel at Layer B. `MISSING`
- is preserved into Layer C if (and only if) the attribute is optional; required
- attributes with `MISSING` keep the candidate `pending_review`.
- Booleans: explicit empty ⇒ `MISSING`; otherwise accept a closed set of tokens
  `{true, y, yes, 1}` / `{false, n, no, 0}`; unrecognized ⇒ `pending_review`.
- Absence is never converted to `null` over the API.

### 4.7 Reference normalization
- A ref value is resolved to a canonical id at entity resolution time. Until
  then it is stored as `{source_system, external_id}` per the identity rules and
  its `value_kind = ref`. A claim with an unresolved ref is `pending_review`
  with `unresolved_ref`; it cannot promote until resolved (or marked optional).

### 4.8 Provenance attachment
- Every claim's `provenance` includes
  `(source_system, source_object_id, source_record_ref, extracted_at, extractor_version)`
  plus `metadata` (e.g. `tz_offset`, `assumed_tz`, `original_unit`,
  `original_value`, `date_only`). Provenance is immutable after the claim is
  written.

---

## 5. The Canonical entity (Layer C)

Layer-C entities are the projection of accepted claims into the versioned
ontology defined in `02-ontology.md`.

### 5.1 Canonical.cpp record fields (per entity)

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv7 | Canonical id, stable. |
| `workspace_id` | UUIDv7 | Scoped. |
| `entity_type` | enum | From `02-ontology.md`. |
| `version` | integer ≥1 | Incremented on each accepted attribute change. |
| `valid_from` | timestamp | When this version became the truth. |
| `valid_to` | timestamp?, | NULL = current. |
| `external_ids` | array | All `(source_system, external_id)` matched. |
| `attributes` | obj | One entry per attribute, see §5.2. |
| `lifecycle_state` | enum | Per `02-ontology.md`. |
| `provenance` | tuple | Entity-level provenance. |
| `confidence` | decimal | Per `02-ontology.md` §12; equals the min confidence of accepted attribute claims (worst-link) under the default policy; combining function recorded in `policy_version`. |
| `lineage` | obj | `resolved_from` (claim ids), `merged_into?`, `merged_from?`. |
| `created_at`, `updated_at` | timestamps | |
| `first_evidence_id`, `latest_evidence_id` | UUIDv7 | Hot path for evidence previews. |

### 5.2 Canonical attribute envelope

Every entry in `attributes` is itself an envelope, never a bare value:

```jsonc
{
  "legal_name": {
    "value": "Acme Logistics Co.",
    "value_kind": "string",
    "value_unit": null,
    "confidence": 1.0,
    "policy_version": "2026.01",
    "claim_ids": ["…", "…"],
    "evidence_refs": ["…", "…"],
    "valid_from": "2026-01-10T09:00:00Z",
    "valid_to": null,
    "state": "accepted",
    "conflict_ids": []
  }
}
```

- `claim_ids` and `evidence_refs` are non-empty for `state=accepted`.
- `valid_to` closes the attribute's prior version when a new accepted claim
  supersedes it; this enables temporal queries without a separate store.
- The same envelope shape holds for refs, enums, quantities, etc.; `value_unit`
  carries the unit when applicable.

### 5.3 Canonicalization rules

- To promote a claim to a canonical attribute: the candidate's
  `entity_candidate_key` must match the entity's id (existing) or pass
  identity/uniqueness rules (new entity); the claim must be `accepted`. The
  promotion appends a new entity version (or a new attribute envelope version),
  it never overwrites.
- Promoting a claim is itself an audited event (`claim.accepted`) carrying the
  reviewer and policy version.
- Required attributes must be `accepted` before the entity can leave `draft` /
  `pending_review` and become visible to downstream intelligence (see §11,
  readiness contract).

---

## 6. Conflicts

A conflict exists when two or more accepted-or-acceptable claims disagree on the
same canonical attribute of the same candidate entity. Conflicts are first-class
objects, never an enum flag.

### 6.1 Conflict record

| Field | Notes |
|---|---|
| `conflict_id` | UUIDv7 |
| `workspace_id` | scoped |
| `entity_candidate_key` | the disputed entity |
| `entity_id?` | resolved entity id once entity resolution completes |
| `attribute` | disputed attribute name |
| `claim_ids` | ≥2 |
| `conflict_type` | enum (below) |
| `severity` | `info`, `warning`, `major`, `critical` |
| `detected_at` | timestamp |
| `detection_rule_version` | string |
| `resolution` | `open`, `resolved_merge`, `resolved_supersede`, `resolved_suppress`, `escalated`, `auto_triaged` |
| `resolved_by_ref?` | user id |
| `resolved_at?` | timestamp |
| `resolution_rationale?` | string |
| `chosen_claim_id?` | UUIDv7 |

### 6.2 Conflict types (closed)

- `value_mismatch` — same `value_kind`, different `value`.
- `unit_mismatch` — quantitatively different after unit normalization. Usually
  surfaced for review because it implies wrong units or wrong conversion.
- `ref_mismatch` — a ref resolves to two different canonical entities.
- `identity_mismatch` — two candidate keys assert the same entity with
  inconsistent identity anchors (e.g. same `tax_id` different `name`).
- `missing_unit`, `unresolved_ref`, `invalid_enum`, `invalid_format` —
  validation-time conflicts (see §8).
- `temporal_mismatch` — claims with overlapping `valid_from/valid_to` and
  different values for the same window.
- `derivation_mismatch` — a derived attribute conflicts with an asserted one.
- `ml_assertion` — an `ml_candidate` claim disagrees with an `accepted` claim;
  the ML claim must be reviewed and capped ≤ `0.5`.
- `duplicate_identity` — same external id resolves to multiple canonical ids
  (entity resolution failure).

### 6.3 Detection

Conflict detection is deterministic and rule-versioned. Rules run:
- after extraction (per upload), and
- after any entity resolution or review state transition that could expose new
  overlaps.

A `detection_rule_version` is recorded so that replay yields identical results.

### 6.4 Resolution

- Only `open` conflicts block promotion; `auto_triaged` may proceed with the
  claim marked `conflicted` and exposed in review.
- Resolutions set `claim_state` on the losers to `superseded` or `rejected`, the
  winner to `accepted`, and emit `claim.conflict.resolved` events. The
  non-chosen claims are retained for audit.

---

## 7. Evidence (Layer A → Layer B link)

Evidence is the immutable support for a claim.

### 7.1 Evidence record

| Field | Notes |
|---|---|
| `evidence_id` | UUIDv7 |
| `workspace_id` | scoped |
| `upload_id` | the immutable upload |
| `source_object_id` | the extracted-table row |
| `source_system` | enum |
| `source_record_ref` | row/path pointer |
| `extractor` | string (e.g. `csv-extractor@1.2`) |
| `extractor_verdict` | `ok`, `row_warning`, `row_error`, `parse_skipped` |
| `extracted_at` | timestamp |
| `file_ref` | object-storage ref (bucket, key, version) |
| `byte_range` | `[start,end]` of the source location, when available |
| `content_hash` | sha256 of the supporting bytes/JSON |
| `metadata` | key/value (e.g. sheet name, locale, tz_offset) |

- `content_hash` makes evidence tamper-evident without re-reading the file.
- An `extractor_verdict != ok` claim is created with `claim_state=pending_review`
  and a `validation_issue_type` matching the verdict.
- Evidence is immutable: no UPDATE path; corrections arrive as new evidence +
  new claims, producing a `DERIVED_FROM` edge.

---

## 8. Validation issues

Validation issues are recorded on claims that fail checks. They are
surfaces-for-review, parallel to conflicts but concerned with structural
validity vs. semantic disagreement.

### 8.1 Issue record

| Field | Notes |
|---|---|
| `issue_id` | UUIDv7 |
| `claim_id` | affected claim |
| `workspace_id` | scoped |
| `issue_type` | enum (below) |
| `constraint` | the rule that failed (e.g. `value.kind.enum`, `unit.registry`, `ref.resolves`) |
| `severity` | `info`, `warning`, `major`, `critical` |
| `detected_at` | timestamp |
| `detection_rule_version` | string |
| `issue_state` | `open`, `resolved`, `wontfix` |
| `resolved_by_ref?` | user |
| `resolved_at?` | timestamp |

### 8.2 Issue types (closed)

`missing_required`, `missing_unit`, `invalid_enum`, `invalid_format`,
`out_of_range`, `negative_quantity`, `future_timestamp`, `invalid_ref`,
`unresolved_ref`, `invalid_country`, `invalid_currency`, `self_loop`,
`derived_cycle`, `ml_confidence_overflow` (an ml_candidate claim with declared
confidence >0.5), `duplicate_external_id`.

### 8.3 Effect on promotion

- A claim with an open `critical` or `major` issue cannot be promoted to
  `accepted`.
- `minor` (`info`, `warning`) issues can be promoted but stay flagged in the
  attribute envelope for human review visibility.

---

## 9. Entity resolution

Entity resolution turns candidate keys into canonical ids. It is deterministic
and versioned.

### 9.1 Inputs
- All `pending_review` claims with structurally valid candidate keys.
- The identity rules per entity (`02-ontology.md`).
- The existing canonical entities and their external ids.

### 9.2 Algorithm shape (frozen contract, not implementation)

1. Compute `entity_candidate_key` for each claim.
2. Within-source deduplication: collapse duplicates whose `entity_candidate_key`
   is identical into one candidate; emit `DEDUP_FROM` lineage links (a
   refinement of `DERIVED_FROM`).
3. Across-source matching: for each candidate, fetch canonical ids with matching
   external ids or matching identity rules.
4. Three outcomes:
   - **single match** — assign existing canonical id.
   - **no match** — create new canonical id (in `draft` state).
   - **multi-match** — create `duplicate_identity` conflict; candidate held
     `pending_review`.
5. For every match, append the matched `external_id` to the entity's
   `external_ids` and emit `entity.resolved` event(s).
6. Trigger conflict detection on the resolved attribute set.

### 9.3 Merges
- A human-approved merge sets `lifecycle_state=merged` on the loser, points
  `merged_into` on it, copies `external_ids` to the survivor, and rewrites
  currently-resolved refs through the versioned attribute envelope (no raw
  UPDATEs across the graph).
- Merge is reversible only by an explicit `split` operation, itself audited.

### 9.4 Confidence and lineage after resolution
- Resolved entities carry `lineage.resolved_from` = the winning claim ids.
- The canonical id chosen follows the rule: the lowest UUIDv7 among matching
  candidates becomes the survivor's id. Deterministic and stable.

---

## 10. Provenance and lineage model

Provenance is the per-claim/evidence/edge tuple. Lineage is the DAG of
derivations across layers.

### 10.1 Provenance (immutable, frozen shape)

```
provenance = {
  source_system: enum,
  source_object_id: UUIDv7,
  source_record_ref: string,
  extracted_at: timestamp,
  extractor_version: string,
  metadata: { ... }   # tz_offset, assumed_tz, original_unit, original_value, date_only, ...
}
```

### 10.2 Lineage edges
- Claim → evidence: `EVIDENCED_BY` (Layer B → evidence).
- Canonical attribute → claim: stored as `claim_ids` in the attribute envelope.
- Entity → claim: `DERIVED_FROM` (`resolved_from`).
- Snapshot → previous snapshot: `DERIVED_FROM` (edges + versions).
- Scenario → base snapshot: `DERIVED_FROM`.
- Recommendation → scenario + evidence: `DERIVED_FROM` + evidence refs in the
  recommendation's `explanation`.
- Decision → recommendation/input snapshot: `DERIVED_FROM` + input snapshot id.
- ML candidate claim → model artifact: `DERIVED_FROM` to the registered model
  version + the input dataset record.

Lineage DAG invariants: acyclic, typed, must reach an evidence record from any
canonical fact within ≤3 hops (claim/entity/snapshot/edge → claim → evidence).
A depth-greater lineage path is treated as a data-quality alert and surfaced as
an `issue`, not silently accepted.

---

## 11. The readiness contract (gate to downstream intelligence)

Layer-C entities are **not** automatically consumable by the operational
intelligence layer (signals/scenarios/recommendations). A workspace's graph is
"ready" only when it satisfies the readiness contract. This is the contract
Phase 2 implements; Phase 1 fixes its form.

### 11.1 Per-entity readiness
- All required attributes are `accepted` (no `pending_review` required field).
- No open `critical`/`major` conflict or validation issue on a required
  attribute.
- `lifecycle_state` is not `draft`, `deprecated`, or `merged`.

### 11.2 Per-edge readiness
- All edges' `evidence_refs` resolve to existing evidence records.
- `ROTATES`/`SHIPS` chain endpoints resolve (no orphan refs).
- No open `derived_cycle` issue in lineage.

### 11.3 Workspace readiness
- The latest graph snapshot exists, is sealed (`sealed: true`), and its
  `readiness_score` ≥ the workspace's configured threshold (`pilot_default: 0.8`
  by min accepted claim confidence and ≥ 1 evidence per edge).
- The readiness gate emits a `graph.readiness.determined` event recording the
  decision (`ready` | `blocked`) and the blocking object ids.

### 11.4 Deterministic readiness decision

Readiness is a **deterministic decision**, not an ML judgment. The `readiness`
module:
1. Reads the current snapshot.
2. Runs the per-entity and per-edge contracts above (policy-versioned).
3. Computes `readiness_score` and emits the `graph.readiness.determined` event.
4. Stores a `DecisionRecord` of `decision_type=no_action` (the system "decided"
   the graph is usable) only when `ready` — this is the first decision in the
   decision memory, and it is the deterministic readiness decision referenced in
   the platform foundation flow (`01-architecture.md` §4.1).

This is the seam between the MVP foundation flow and the later intelligence
flow: intelligence never operates on a non-ready graph.

---

## 12. Cross-attribute and reference integrity

- Ref attributes (`*_ref`) must resolve to a canonical id of the correct
  entity type before promotion (`issue: unresolved_ref` otherwise).
- When a referenced entity is later merged or deprecated, the ref-target is
  rewritten via an audited `entity.rewritten` event that updates attribute
  envelopes in-place at the versioning level (closes old envelope, opens new).
  Raw bulk-UPDATE is forbidden.

---

## 13. Summary of immutability rules

| Layer | Mutable? | How it changes |
|---|---|---|
| Raw upload (Layer A) | No | New upload only |
| Extracted source object | No | New extraction only |
| Evidence record | No | New evidence only |
| Claim | state only | state-machine transitions; never value changes |
| Conflict/Issue | state only | audited resolution transitions |
| Canonical entity/attribute | versioned via append | new version + `valid_to` on prior |
| Edge | versioned via append | new version + `valid_to` on prior |
| Snapshot | sealed only | new snapshot |
| Decision/Recommendation/Scenario | state only | lifecycle transitions, audited |
| Audit event | no | append-only |

---

## 14. Frozen decisions summary

- Three layers (Raw / Claim / Canonical) — never merged.
- Every canonical fact backs to a claim backed to evidence within ≤3 hops.
- The canonical envelope (value + confidence + claim/evidence refs + valid
  window) is the single shape of a fact at Layer C.
- Conflicts and validation issues are first-class, type-versioned, and
  deterministically detected.
- Entity resolution is deterministic, versioned, stable-on-merge.
- The readiness contract gates downstream intelligence deterministically and
  emits the first `DecisionRecord`.

Phase 1 proceeds to `04-graph-and-events.md` on this basis.
