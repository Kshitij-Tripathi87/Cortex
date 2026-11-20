# Canonical input mapping (task T-A-01)

Status: **PROPOSED**, for the lead's sign-off together with
`finding-contract.md`. Nothing here is implemented.

The plan (`../procurement-intelligence-engine-plan.md`) describes the inputs
of the five rules as they were understood when it was written, and asks for
each of them to be checked against the merged source before any code. This
document is that check: where every input lives, what the database guarantees
about it, how it gets there, and where the plan and the source disagree.

## What was inspected

| Item | Value |
|---|---|
| Baseline | `main` at `3fe1d1c53daaeb487a492b7037c43dc1bc305c86` (the v0.1 merge `2bb2809` plus the plan) |
| Sources read | `services/api/app/models/`, `alembic/versions/0001`, `app/services/`, `app/repositories/`, `app/schemas/world_state.py`, `app/db/session.py`, `docs/architecture/`, `docs/engineering/api-contract.md` |
| Schema checked | `information_schema.columns` of a database migrated to revision `0001` (PostgreSQL 16.2); every column, type and nullability below was read from it and agrees with the ORM models |
| PR #28 | Changes none of the inputs: `git diff 2bb2809 5e2def7` is empty for `app/models`, `alembic`, `app/schemas`, `app/repositories`, `app/db`, `app/services/world_state_service.py` and `data/`. The mapping holds on `main` and on the head of PR #28 alike |

## 1. Inputs of the rules

`NOT NULL` and `NULL` are what PostgreSQL enforces. "Written by" names the
import field (the key in `ingestion_rows.normalized_data`) and the API
operation.

### Project (`projects`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id` | uuid | NOT NULL; unique `(workspace_id, id)` | Service |
| Code | `code` | varchar(64) | NOT NULL; unique per workspace; immutable | `code`; `POST projects` |
| Status | `status` | text + CHECK | NOT NULL: `PLANNING`, `ACTIVE`, `ON_HOLD`, `COMPLETED`, `CANCELLED`; any value may follow any other | `status`; `PATCH projects` |

### Supplier (`suppliers`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id` | uuid | NOT NULL; unique `(workspace_id, id)` | Service |
| Code | `supplier_code` | varchar(64) | NOT NULL; unique per workspace; immutable | `supplier_code` |

A supplier enters the rules only as the party of a purchase order. Its name,
country, city and status are not inputs: the plan forbids them for severity,
and no rule compares them.

### Equipment (`equipment`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id`, `project_id` | uuid | NOT NULL; composite FK `(workspace_id, project_id)` → projects; the project is not changed after creation | Service |
| Code | `equipment_code` | varchar(64) | NOT NULL; unique per workspace; immutable | `equipment_code` |
| Criticality | `criticality` | text + CHECK | NOT NULL: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` | `criticality`; `PATCH equipment` |
| Procurement status | `procurement_status` | text + CHECK | NOT NULL, default `NOT_STARTED`: `NOT_STARTED`, `RFQ`, `QUOTED`, `ORDERED`, `IN_PRODUCTION`, `DISPATCHED`, `DELIVERED`, `INSTALLED`, `CANCELLED` | `procurement_status`; `PATCH equipment` |
| Required-on-site date | `required_on_site_date` | date | **NULL allowed** | `required_on_site_date`; `PATCH equipment` |

`specification` (JSONB with free text, `notes` included) is never read by the
engine and never appears in evidence.

### Purchase order (`purchase_orders`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id`, `project_id`, `supplier_id` | uuid | NOT NULL; composite FKs to projects and suppliers of the same workspace; project and supplier immutable | Service |
| Number | `po_number` | varchar(80) | NOT NULL; unique per workspace; immutable | `po_number` |
| Status | `status` | text + CHECK | NOT NULL, default `DRAFT`: `DRAFT`, `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED`, `DELIVERED`, `CANCELLED`. **No transition rule**: the service accepts any value after any other | `status`; `PATCH purchase-orders` |
| Issue date | `issue_date` | date | **NULL allowed** | `issue_date`; `PATCH purchase-orders` |

`total_value` and `currency` are not inputs (the plan: no monetary value in a
rule or a severity).

### Line item (`purchase_order_items`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id`, `project_id` | uuid | NOT NULL | Service |
| Relationship | `purchase_order_id`, `equipment_id` | uuid | NOT NULL; unique `(purchase_order_id, equipment_id)`; composite FKs `(workspace_id, project_id, purchase_order_id)` and `(workspace_id, project_id, equipment_id)`: PostgreSQL itself keeps a line item, its purchase order and its equipment in one workspace and one project | `po_number` + `equipment_code`; `POST purchase-orders` |

`quantity` and `unit_price` are not inputs: v0.2 makes no judgement about
quantities (plan §6.5).

### Milestone (`milestones`)

| Input | Column | Type | Guarantee | Written by |
|---|---|---|---|---|
| Identity | `id`, `workspace_id`, `purchase_order_id` | uuid | NOT NULL; composite FK `(workspace_id, purchase_order_id)` | Service |
| Type | `milestone_type` | text + CHECK | NOT NULL: `PO_ACKNOWLEDGEMENT`, `DRAWING_SUBMISSION`, `DRAWING_APPROVAL`, `MANUFACTURING_START`, `FACTORY_ACCEPTANCE_TEST`, `DISPATCH`, `DELIVERY`, `INSTALLATION` | `milestone_type` |
| Sequence | `sequence_no` | integer | NOT NULL, > 0; unique `(purchase_order_id, milestone_type, sequence_no)`. **A purchase order can have several milestones of one type** | `sequence_no` |
| Status | `status` | text + CHECK | NOT NULL, default `PENDING`: `PENDING`, `COMPLETED`, `CANCELLED` | `status`; `PATCH milestones` |
| Actual date | `actual_date` | date | NULL allowed; CHECK `actual_date IS NULL OR status = 'COMPLETED'`. **`COMPLETED` without an actual date is a valid, documented state** (domain model: the source said "completed" and gave no date) | `actual_date`; `PATCH milestones` |

A milestone has no project column; its project is that of its purchase order.

### Plan version (`milestone_plan_versions`, append-only)

| Input | Column | Type | Guarantee |
|---|---|---|---|
| Identity | `id`, `milestone_id` | uuid | NOT NULL; FK → `milestones.id`. **No `workspace_id` column**: the workspace is that of the milestone, so every query joins `milestones` |
| Version | `version_no` | integer | NOT NULL, > 0; unique `(milestone_id, version_no)`: a tie for "current" cannot exist |
| Planned date | `planned_date` | date | NOT NULL |
| Source row | `source_ingestion_row_id` | uuid | NULL allowed; FK → `ingestion_rows.id`. NULL for a version created through the API |
| Recorded | `recorded_at`, `recorded_by` | timestamptz, varchar(120) | NOT NULL. `recorded_by` is `import:<file name>` for an import, the caller's label or `api` for the API |

Both write paths (import and API) create version 1 together with the
milestone, and `planned_date` is required in both. A milestone without a plan
version can therefore exist only after a write that went past the service.
The database does not forbid it.

### Commitment version (`supplier_commitment_versions`, append-only)

| Input | Column | Type | Guarantee |
|---|---|---|---|
| Identity | `id`, `workspace_id`, `purchase_order_id` | uuid | NOT NULL; composite FK `(workspace_id, purchase_order_id)` |
| Version | `version_no` | integer | NOT NULL, > 0; unique `(purchase_order_id, version_no)` |
| Committed date | `committed_delivery_date` | date | NOT NULL |
| Source row | `source_ingestion_row_id` | uuid | NULL allowed; FK → `ingestion_rows.id` |
| Recorded | `recorded_at`, `recorded_by` | timestamptz, varchar(120) | NOT NULL. For an import: the "Recorded By" cell when the file has one, otherwise `import:<file name>` |

`source_reference` (the supplier's own reference, free text) is not an input
and does not appear in evidence.

## 2. Where a fact came from

The plan speaks of "the source row" of a record. v0.1 records two different
things, and they are not equally exact.

### 2.1 Versions: exact

A plan version and a commitment version each carry
`source_ingestion_row_id`: the one source row that introduced that version.
Versions are never changed, so the pointer stays true. It is NULL when the
version was created through the API.

The foreign key is to `ingestion_rows.id` alone. It does not prove that the
row belongs to a batch of the same workspace. The service never writes such a
link, but the database would accept it, so the snapshot query joins
`ingestion_batches` and requires `workspace_id` to match. A pointer that does
not resolve inside the workspace fails the run (`SNAPSHOT_INVALID`); it is
never cited and never skipped silently.

### 2.2 Records: by record, not by field

A project, supplier, equipment record, purchase order, line item or milestone
has **no** source column. The link runs the other way: a source row names the
record it resulted in.

| Column of `ingestion_rows` | Meaning |
|---|---|
| `canonical_entity_type`, `canonical_entity_id` | The record the row resulted in. Not a foreign key (seven target tables); index `ix_ingestion_rows_canonical_entity` |
| `outcome` | `CREATED`, `UPDATED`, `UNCHANGED`, `DUPLICATE_ROW` for rows of a committed batch |
| `status` | `COMMITTED` (created or updated) or `SKIPPED` (unchanged, duplicate) |
| `normalized_data` | The canonical values the row stated, keyed by canonical field name (`required_on_site_date`, `issue_date`, `status`, `criticality`, …), dates as `YYYY-MM-DD` |
| `batch_id` → `ingestion_batches` | `workspace_id`, `entity_type`, `original_filename`, `sheet_name`, `source_format`, `committed_at`. **A row has no `workspace_id`**: it is scoped through its batch |

Consequences the evidence contract has to respect:

1. **A record has zero, one or many source rows.** One row created it; later
   rows may have updated it or restated it unchanged. Rows of a `FAILED`
   batch carry no link (the link is written in the transaction that was
   rolled back).
2. **The ledger does not say which row set which field.** A row that updated
   a record may have changed only its name.
3. **An API write leaves no ledger row.** A value set by `PATCH` has no source
   row at all, and there is no change log of API writes in v0.1 (only
   `updated_at`).

What can be stated truthfully, and is deterministic:

- which row **created** the record and which row **last changed** it
  (`outcome` `CREATED` or `UPDATED`, ordered by the batch's `committed_at`,
  then batch id, then `row_number`);
- for a cited row, whether it **states the value the rule used**
  (`normalized_data[field]` equals the canonical value). This is a comparison,
  not a copy: the evidence stores `true`, `false` or "field not in the row",
  never the cell;
- when no linked row states the value used: `SOURCE_NOT_RECORDED` for that
  value.

This is decision D-21 in `policy-v1.md`: field-level lineage of mutable
fields is a gap of v0.1, carried into v0.2 as a stated limitation. Closing it
needs a change log of canonical writes, which is a change to the canonical
model and outside this phase.

### 2.3 What evidence may show of a source row

By reference: the row id, its `row_number` and `outcome`, and through the
batch the file name, format, entity type and commit time, all of which
`GET {ws}/ingestion/sources` already returns, and the worksheet name of a
workbook. Never `raw_data`, never `normalized_data`, never
`validation_errors`.

## 3. The snapshot

One read-only `REPEATABLE READ` transaction, as the World State uses already
(`app.db.session.read_snapshot`). The families and the fields that enter the
snapshot and its digest:

| Family | Fields | Order |
|---|---|---|
| Project | `id`, `code`, `status` | `code` |
| Supplier | `id`, `supplier_code` | `supplier_code` |
| Equipment | `id`, `project_id`, `equipment_code`, `criticality`, `procurement_status`, `required_on_site_date` | `equipment_code` |
| Purchase order | `id`, `project_id`, `supplier_id`, `po_number`, `status`, `issue_date` | `po_number` |
| Line item | `id`, `purchase_order_id`, `equipment_id` | PO number, equipment code |
| Milestone | `id`, `purchase_order_id`, `milestone_type`, `sequence_no`, `status`, `actual_date` | PO number, lifecycle order of the type, `sequence_no` |
| Plan version | `id`, `milestone_id`, `version_no`, `planned_date`, `source_ingestion_row_id` | milestone, `version_no` |
| Commitment version | `id`, `purchase_order_id`, `version_no`, `committed_delivery_date`, `source_ingestion_row_id` | PO number, `version_no` |
| Source reference | For every version: the row it points to. For every equipment record, purchase order, line item and milestone: the row that created it and the row that last changed it. Of each: `ingestion_row_id`, `batch_id`, `row_number`, `outcome`, the record it is linked to, and per field the rules read whether the row states the canonical value. Rows that restated a record unchanged are not read | batch `committed_at`, batch id, `row_number` |

Not in the snapshot, so a change to them does not change the digest: names,
locations, countries, specifications, money, quantities, `source_reference`,
`recorded_by`, `created_at`, `updated_at`.

Every family is read with one query, or a fixed number of them, never one per
record. All versions are read, not only the current one: previous versions
are evidence. The numbers are bounded by the size of the workspace; the
supported size is the outcome of task T-F-04, not an assumption.

## 4. Where the plan and the source differ

Each row is a point where the plan had to be made exact. "Decision" refers to
`policy-v1.md`; "contract" to `finding-contract.md`.

| # | Plan | Source | Settled by |
|---|---|---|---|
| X-01 | §6.1 speaks of "the delivery milestone" | A purchase order can have several `DELIVERY` milestones (`sequence_no`), or none | D-17: delivery is recorded complete when at least one `DELIVERY` milestone is not `CANCELLED` and every such milestone is `COMPLETED` |
| X-02 | §6.1: completion needs "status COMPLETED with an actual date". §6.2 says both "completed status and an actual date" and "marked COMPLETED" | `COMPLETED` without an actual date is a valid state | D-16: the status is the fact; a missing date is shown as missing and does not turn a completed delivery into an overdue one |
| X-03 | §6.4: the purchase order must be in "a policy-defined set of active / procured statuses" | Two policy sets exist; "procured" includes `DELIVERED` | D-19: R4 uses the open-delivery set, like R1 |
| X-04 | §6.3 excludes only `CANCELLED` milestones | Milestones of a `CANCELLED` or `DRAFT` purchase order would be reported for ever | D-18 |
| X-05 | No rule looks at the project | A project can be `CANCELLED` while its records are not | D-18 |
| X-06 | §1.1 and §22 require not-evaluable outcomes to be shown; §5.1 has no such finding status and §8.1 no table | — | D-20: stored per run, counted, and readable |
| X-07 | §2.2, §6: "the source row" of a record | Section 2.2 above | D-21; contract §7 |
| X-08 | §8.2 asks for composite workspace keys "where practical" | `milestone_plan_versions` and `ingestion_rows` have no `workspace_id` | Contract §9.4 and §7.5: the snapshot joins the parent; a reference that does not resolve in the workspace fails the run |
| X-09 | §11.7 proposes `INTELLIGENCE_RUN_NOT_FOUND` | Every v0.1 route answers a missing record and a record of another workspace alike: `404 NOT_FOUND` | D-23 |
| X-10 | §13.2 lists metrics in the style of a metrics exporter | The stack has none, and a dependency needs a stated need (`AGENTS.md`) | D-22 |
| X-11 | §4.3: policy timezone by IANA name | Python reads the zone database of the system; a machine without one cannot resolve `Asia/Kolkata` | D-28 |
| X-12 | §11.1: `evaluation_date` may be supplied | A run for an earlier date, or for a date in the future, would move the current findings backwards or block later runs | D-24 |
| X-13 | §9.2, §15.4: concurrent runs "serialize safely" | Two runs that finish in the other order than they read would let the older snapshot decide the current state | D-25: one run at a time per workspace, enforced by the database |
| X-14 | §15.7: "the existing 43-case defect harness" | `main` has 37 cases; 43 exist only in PR #28, which is not merged | Task T-F-03 extends whatever `main` holds when it starts |
| X-15 | §2.4: "Facts and inference remain separate" | `AGENTS.md` invariant 8 says "no … lateness … in a table" without the word canonical; `system-boundaries.md` says "canonical table" | Contract §13: the wording of `AGENTS.md` is amended with the implementation, not before |
| X-16 | The plan's example of a run (§11.1) shows one commitment threat | The demo dataset has no such case (section 5) | Task T-F-01 |
| X-17 | The overdue purchase order and its own late `DELIVERY` milestone | Both rules fire for the same lateness | D-26: both are reported; they compare different dates |
| X-18 | §6.3 emits a finding for a milestone completed late | Nothing ever resolves it, short of a re-plan | D-27 |

## 5. The demo dataset under policy v1

Derived by hand from `data/samples/nexus_demo/` (with the revision file) as of
`2026-11-19`, the reference date of the dataset, under the values proposed in
`policy-v1.md`. It is an illustration for review. It becomes a fixture only
when task T-F-01 has reviewed it, and no test may be written from this table
alone.

| Rule | Reported | Why |
|---|---|---|
| R1 overdue delivery | `PO-1006` | `IN_PRODUCTION`; current commitment `2026-11-10`; its `DELIVERY` milestone is `PENDING`; 9 days |
| R2 missing acknowledgement | `PO-1005` | `ISSUED` on `2026-08-17`; no `PO_ACKNOWLEDGEMENT` milestone; due `2026-08-22` |
| R3 milestone slippage | `PO-1003` factory acceptance test #1 | Completed `2026-11-14`, planned `2026-11-10` |
| | `PO-1006` dispatch #1 | `PENDING`, planned `2026-11-03` |
| | `PO-1006` delivery #1 | `PENDING`, planned `2026-11-10` |
| R4 commitment threat | none | The revised commitment of `PO-1007` (`2026-12-06`) is before the required date of `UPS-001` and `UPS-002` (`2026-12-15`); no other commitment is later than a required date |
| R5 critical equipment without PO | `DG-003` | `CRITICAL`, status `RFQ`, no line item |

Six findings. Not evaluable: none (every milestone has a plan, every
completed milestone a date, every equipment record a required date, and the
one `ISSUED` purchase order an issue date).

Two things the lead should see before the fixture is written:

- **R3 reports three milestones, the dataset names one.** `expected.json`
  lists the factory acceptance test of `PO-1003` as "the" slippage. Under the
  rule as the plan states it, the two pending milestones of the overdue
  `PO-1006` are behind plan as well (X-17).
- **R4 has no case.** The "changed commitment" of `PO-1007` is a change, not
  a threat. A fixture for R4 needs one more appended commitment or a
  dedicated dataset (task T-F-01).
