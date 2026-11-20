# Finding and evidence contract (task T-A-03)

Status: **PROPOSED**, to be frozen by the lead's sign-off (`policy-v1.md` §5).
Nothing here is implemented. After the freeze, a change goes the way of every
shared contract in this repository: proposed to the lead, written here, and
only then implemented (`AGENTS.md`).

The plan (`../procurement-intelligence-engine-plan.md`) gives the intent of
the Procurement Intelligence Engine v0.2. This document gives the exact
contract on the schema of v0.1: what each rule reads, when it reports, what a
finding carries, and what a run does. Where it is more specific than the
plan, or differs from it, the row of `canonical-input-mapping.md` §4 (X-nn)
and the decision of `policy-v1.md` (D-nn) are named.

## 1. Terms

| Term | Meaning |
|---|---|
| Evaluation date, `E` | The date every date rule compares with. Fixed once per run. No rule reads a clock |
| Eligible project | A project whose status is not in `excluded_project_statuses` (D-18). Records of other projects are not evaluated by any rule |
| Current commitment of a purchase order | Its commitment version with the greatest `version_no`. None when it has no version |
| Current plan of a milestone | Its plan version with the greatest `version_no` |
| Open delivery | A purchase order whose status is in `po_statuses_that_count_as_open_delivery` |
| Delivery recorded complete | The purchase order has at least one `DELIVERY` milestone that is not `CANCELLED`, and every such milestone is `COMPLETED`, with or without an actual date (D-16, D-17) |
| Acknowledgement recorded | The purchase order has a `PO_ACKNOWLEDGEMENT` milestone with status `COMPLETED`, with or without an actual date (D-16) |
| Finding | What a rule reports about one subject. A result computed from facts, never a fact |
| Diagnostic | What a rule could not decide, and why. Never a finding (D-20) |
| Occurrence | One finding as one run reported it. Immutable |

## 2. Closed vocabularies

| Vocabulary | Values |
|---|---|
| Finding code, in priority order | `OVERDUE_DELIVERY`, `MISSING_SUPPLIER_ACKNOWLEDGEMENT`, `MILESTONE_SLIPPAGE`, `COMMITMENT_THREATENS_REQUIRED_ON_SITE`, `CRITICAL_EQUIPMENT_WITHOUT_PO` |
| Subject type | `purchase_order`, `milestone`, `equipment` |
| Severity, in rank order | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`, `UNCLASSIFIED`. Policy v1 assigns `UNCLASSIFIED` to every finding |
| Finding status | `ACTIVE`, `RESOLVED`, `SUPERSEDED` |
| Run status | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED` |
| Run failure code | `SNAPSHOT_INVALID`, `EVALUATION_FAILED`, `PERSISTENCE_FAILED`, `ABANDONED` |
| Evidence type | `CANONICAL_RECORD`, `CANONICAL_VERSION`, `INGESTION_SOURCE_ROW`, `DATE_COMPARISON`, `STATUS_COMPARISON`, `POLICY_PARAMETER`, `RELATIONSHIP_EDGE`, `MISSING_DATA` |
| Evidence role | `SUBJECT`, `COMPARATOR`, `RELATIONSHIP`, `SOURCE`, `HISTORY`, `POLICY` |
| Source relation | `INTRODUCED_VERSION`, `CREATED_RECORD`, `LAST_CHANGED_RECORD` |
| Missing-data code | `SOURCE_NOT_RECORDED`, `ACTUAL_DATE_NOT_RECORDED`, `ACKNOWLEDGEMENT_MILESTONE_NOT_RECORDED`, `NO_PURCHASE_ORDER_LINE_ITEM`, `LIST_TRUNCATED` |
| Diagnostic kind and code | `NOT_EVALUABLE`: `ISSUE_DATE_NOT_RECORDED`, `PLAN_NOT_RECORDED`, `ACTUAL_DATE_NOT_RECORDED`, `REQUIRED_ON_SITE_DATE_NOT_RECORDED`. `CONTRADICTION`: `ACKNOWLEDGED_MILESTONE_ON_ISSUED_ORDER` |

A value outside these lists is a defect, in the code or in the data. Text
columns carry a `CHECK` constraint, as every enumeration of v0.1 does.

## 3. Identity

The key names the condition, not the dates that currently make it true. A
revised date changes the occurrence, not the finding.

| Code | Key | Subject |
|---|---|---|
| `OVERDUE_DELIVERY` | `OVERDUE_DELIVERY:po:<purchase order id>` | purchase order |
| `MISSING_SUPPLIER_ACKNOWLEDGEMENT` | `MISSING_SUPPLIER_ACKNOWLEDGEMENT:po:<purchase order id>` | purchase order |
| `MILESTONE_SLIPPAGE` | `MILESTONE_SLIPPAGE:milestone:<milestone id>` | milestone |
| `COMMITMENT_THREATENS_REQUIRED_ON_SITE` | `COMMITMENT_THREATENS_REQUIRED_ON_SITE:equipment:<equipment id>:po:<purchase order id>` | equipment (D-11) |
| `CRITICAL_EQUIPMENT_WITHOUT_PO` | `CRITICAL_EQUIPMENT_WITHOUT_PO:equipment:<equipment id>` | equipment |

Identifiers are lowercase UUID text. A key is unique within a workspace.
Equipment on two purchase orders gives one finding per threatening purchase
order; nothing chooses between suppliers.

## 4. The rules

Every rule is a pure function of the snapshot, the policy and `E`. The steps
are evaluated in the order written; the first that says "nothing" or
"diagnostic" ends the evaluation of that subject. "Nothing" means no finding
and no diagnostic. Rule version of each: `1`.

Dates are compared as calendar dates. `a > b` is strict: the day itself is
never late.

### 4.1 R1 `OVERDUE_DELIVERY`

For each purchase order of an eligible project:

| Step | Condition | Outcome |
|---|---|---|
| 1 | Status not in `po_statuses_that_count_as_open_delivery` | Nothing. `DRAFT`, `DELIVERED` and `CANCELLED` orders are never reported |
| 2 | No current commitment | Nothing. A missing commitment is not lateness; v0.1 reports it as `PO_WITHOUT_SUPPLIER_COMMITMENT` |
| 3 | Delivery recorded complete | Nothing, also when the status is stale |
| 4 | `E > committed_delivery_date + overdue_grace_days` | **Finding** |
| 5 | Otherwise | Nothing |

| | |
|---|---|
| Title | `Delivery is overdue` |
| Summary | `Purchase order {po_number} has a current supplier commitment of {committed_delivery_date}; the date is {overdue_days} calendar day(s) past due as of {evaluation_date}.` |
| Observed values | `committed_delivery_date`, `commitment_version_no`, `commitment_version_count`, `evaluation_date`, `overdue_grace_days`, `overdue_days` (= `E` − committed date, in days), `purchase_order_status`, `delivery_milestones` (not cancelled), `delivery_milestones_completed` |
| Evidence, in order | Purchase order with its sources · supplier · current commitment with its source · each `DELIVERY` milestone that is not cancelled, with its current plan (§7.4) · date comparison · `overdue_grace_days` · `po_statuses_that_count_as_open_delivery` |

### 4.2 R2 `MISSING_SUPPLIER_ACKNOWLEDGEMENT`

For each purchase order of an eligible project:

| Step | Condition | Outcome |
|---|---|---|
| 1 | Status not in `acknowledgement_required_statuses` | Nothing (D-02) |
| 2 | Acknowledgement recorded | No finding. **Diagnostic** `ACKNOWLEDGED_MILESTONE_ON_ISSUED_ORDER`: the milestone says acknowledged, and the status is still one that asks for an acknowledgement |
| 3 | `issue_date` is not recorded | **Diagnostic** `ISSUE_DATE_NOT_RECORDED` |
| 4 | `E > issue_date + acknowledgement_due_days_after_issue` | **Finding** |
| 5 | Otherwise | Nothing |

| | |
|---|---|
| Title | `Supplier acknowledgement is missing` |
| Summary | `Purchase order {po_number} was issued on {issue_date}; acknowledgement was due by {acknowledgement_due_date}, but no acknowledgement evidence is recorded as of {evaluation_date}.` |
| Observed values | `issue_date`, `acknowledgement_due_days_after_issue`, `acknowledgement_due_date`, `evaluation_date`, `days_past_due`, `purchase_order_status`, `acknowledgement_milestones` (not cancelled; none of them completed) |
| Evidence, in order | Purchase order with its sources · supplier · status comparison (status is in the required set) · each `PO_ACKNOWLEDGEMENT` milestone that is not cancelled (§7.4), or `ACKNOWLEDGEMENT_MILESTONE_NOT_RECORDED` · date comparison · `acknowledgement_due_days_after_issue` · `acknowledgement_required_statuses` |

### 4.3 R3 `MILESTONE_SLIPPAGE`

For each milestone whose purchase order belongs to an eligible project and
has a status in `po_statuses_that_count_as_procured` (D-18):

| Step | Condition | Outcome |
|---|---|---|
| 1 | Milestone status `CANCELLED` | Nothing |
| 2 | No plan version | **Diagnostic** `PLAN_NOT_RECORDED` |
| 3 | `PENDING` and `E > planned_date + milestone_overdue_grace_days` | **Finding**, variant `PENDING_PAST_PLAN` |
| 4 | `COMPLETED` without an actual date | **Diagnostic** `ACTUAL_DATE_NOT_RECORDED` |
| 5 | `COMPLETED` and `actual_date > planned_date + milestone_overdue_grace_days` | **Finding**, variant `COMPLETED_LATE` |
| 6 | Otherwise | Nothing |

`planned_date` is that of the current plan. A `PENDING` milestone with an
actual date cannot be stored (a `CHECK` constraint of v0.1); a snapshot that
holds one is invalid and the run fails (§9.4).

| | |
|---|---|
| Title | `Milestone is behind plan` |
| Summary, pending | `Milestone {milestone_type} #{sequence_no} of purchase order {po_number} was planned for {planned_date} and is not completed as of {evaluation_date}.` |
| Summary, completed late | `Milestone {milestone_type} #{sequence_no} of purchase order {po_number} was planned for {planned_date} and was completed on {actual_date}.` |
| Observed values | `variant`, `milestone_type`, `sequence_no`, `milestone_status`, `planned_date`, `plan_version_no`, `plan_version_count`, `actual_date`, `evaluation_date`, `milestone_overdue_grace_days`, `days_behind` (pending: `E` − planned date; completed: actual − planned), `purchase_order_status` |
| Evidence, in order | Milestone with its sources · purchase order · supplier · current plan with its source · earlier plans, oldest first, each with its source (§7.4) · date comparison · `milestone_overdue_grace_days` · `po_statuses_that_count_as_procured` |

One key covers both variants: a milestone that was pending past its plan and
is then completed late stays the same finding. A milestone completed late
stays reported for as long as it is eligible (D-27).

### 4.4 R4 `COMMITMENT_THREATENS_REQUIRED_ON_SITE`

For each line item, that is each pair of equipment and purchase order, of an
eligible project:

| Step | Condition | Outcome |
|---|---|---|
| 1 | Equipment procurement status `CANCELLED` | Nothing (D-18) |
| 2 | Purchase order status not in `po_statuses_that_count_as_open_delivery` | Nothing (D-19) |
| 3 | No current commitment | Nothing. No other date stands in for it |
| 4 | Delivery recorded complete for this purchase order | Nothing. A completed delivery of another purchase order does not count |
| 5 | `required_on_site_date` is not recorded | **Diagnostic** `REQUIRED_ON_SITE_DATE_NOT_RECORDED` |
| 6 | `committed_delivery_date > required_on_site_date` | **Finding** |
| 7 | Otherwise | Nothing |

`E` takes no part in the comparison. The status of the equipment other than
`CANCELLED` takes no part either: the plan suppresses only on the delivery of
the purchase order in question (§6.4 of the plan).

| | |
|---|---|
| Title | `Supplier commitment is later than required-on-site date` |
| Summary | `{equipment_code} is required on site by {required_on_site_date}; purchase order {po_number} currently commits delivery for {committed_delivery_date}.` |
| Observed values | `required_on_site_date`, `committed_delivery_date`, `commitment_version_no`, `commitment_version_count`, `days_after_required`, `equipment_criticality`, `equipment_procurement_status`, `purchase_order_status`, `evaluation_date` |
| Evidence, in order | Equipment with its sources · project · line item with its sources (the relationship) · purchase order with its sources · supplier · current commitment with its source · earlier commitments, oldest first, each with its source (§7.4) · date comparison · `po_statuses_that_count_as_open_delivery` |

### 4.5 R5 `CRITICAL_EQUIPMENT_WITHOUT_PO`

For each equipment record of an eligible project:

| Step | Condition | Outcome |
|---|---|---|
| 1 | Criticality is not `critical_equipment_criticality` | Nothing |
| 2 | Procurement status `CANCELLED` | Nothing |
| 3 | A line item links it to a purchase order whose status is in `po_statuses_that_count_as_procured` | Nothing |
| 4 | Otherwise | **Finding** |

A purchase order without a line item for the equipment covers nothing. A line
item on a `DRAFT` or `CANCELLED` purchase order covers nothing. One qualifying
line item is enough: v0.2 does not judge quantities. The procurement status of
the equipment, apart from `CANCELLED`, is shown and not believed: equipment
marked `ORDERED` without a qualifying line item is reported.

| | |
|---|---|
| Title | `Critical equipment has no qualifying purchase order` |
| Summary | `Critical equipment {equipment_code} is present in project {project_code} but no qualifying purchase-order line item is recorded as of {evaluation_date}.` |
| Observed values | `equipment_criticality`, `equipment_procurement_status`, `required_on_site_date`, `line_items`, `line_items_on_excluded_purchase_orders`, `evaluation_date` |
| Evidence, in order | Equipment with its sources · project · each line item on a purchase order that does not qualify, with that purchase order and a status comparison (at most 20, by PO number; then a marker with the total), or `NO_PURCHASE_ORDER_LINE_ITEM` · `critical_equipment_criticality` · `po_statuses_that_count_as_procured` |

The title says "critical" because policy v1 says `CRITICAL`. A policy with
another criticality needs another text, and that is a new rule version.

## 5. Severity

A finding takes the severity the policy maps its code to. Policy v1 maps every
code to `UNCLASSIFIED` (D-06). No rule computes a severity, and nothing about
a supplier, a country or a sum of money enters one.

## 6. Diagnostics

| Code | Kind | Rule | Subject | Says |
|---|---|---|---|---|
| `ISSUE_DATE_NOT_RECORDED` | `NOT_EVALUABLE` | R2 | purchase order | The order is `ISSUED` and has no issue date; no due date can be computed |
| `PLAN_NOT_RECORDED` | `NOT_EVALUABLE` | R3 | milestone | The milestone has no plan version |
| `ACTUAL_DATE_NOT_RECORDED` | `NOT_EVALUABLE` | R3 | milestone | The milestone is completed and has no actual date; whether it was late is unknown |
| `REQUIRED_ON_SITE_DATE_NOT_RECORDED` | `NOT_EVALUABLE` | R4 | equipment, with the purchase order | The equipment has no required date; the commitment has nothing to be compared with |
| `ACKNOWLEDGED_MILESTONE_ON_ISSUED_ORDER` | `CONTRADICTION` | R2 | purchase order | An acknowledgement milestone is completed and the status is still one that asks for an acknowledgement (`ISSUED` under policy v1) |

A diagnostic belongs to one run and is immutable. It has no lifecycle, no
severity and no evidence list: it names the rule, the subject, the field and
the code. Runs count them by rule and code. A diagnostic never resolves a
finding and never keeps one alive: a finding whose subject can no longer be
evaluated is not emitted, and is resolved like any other (§8.2).

## 7. Evidence

### 7.1 An evidence item

| Field | Meaning |
|---|---|
| `ordinal` | Position within the occurrence, from 1, without gaps. The order is that of the rule's template (§4) and never depends on the order of a query |
| `evidence_type`, `role` | §2 |
| Reference | At most one canonical target: a record (project, supplier, equipment, purchase order, line item, milestone) or a version (plan version, commitment version), by type and id. Comparison, policy and missing-data items have none |
| `ingestion_row_id` | For `INGESTION_SOURCE_ROW` only |
| `field_name` | The field the item is about, when it is about one |
| `observed_value` | A small JSON object of scalars: the values the rule used, as they were in the snapshot. Dates as `YYYY-MM-DD`. At most 12 keys; text at most 200 characters |
| `display_label` | A natural key: a code, a PO number, `{po_number} {milestone_type} #{sequence_no}`, a field or parameter name. At most 200 characters |

Natural keys are the only source-supplied text an item carries. They are
immutable in v0.1 and bounded in length. Names, locations, specifications,
`source_reference`, `recorded_by`, file contents and cell values never appear.

### 7.2 Blocks the templates are built from

| Block | Items |
|---|---|
| A record "with its sources" | One `CANONICAL_RECORD` item with the fields the rule read. Then its source rows: the row that created the record (`CREATED_RECORD`) and, if it is another row, the row that last changed it (`LAST_CHANGED_RECORD`), each an `INGESTION_SOURCE_ROW` item that says, for every field the rule read, whether the row states the value used. If no row is linked to the record: one `MISSING_DATA` item `SOURCE_NOT_RECORDED` |
| A record (project, supplier, a purchase order named for context) | One `CANONICAL_RECORD` item |
| A version "with its source" | One `CANONICAL_VERSION` item (`version_no`, the date, whether it is the current one). Then one `INGESTION_SOURCE_ROW` item (`INTRODUCED_VERSION`), or one `MISSING_DATA` item `SOURCE_NOT_RECORDED` when the version was created through the API |
| A date comparison | One `DATE_COMPARISON` item: left value, operator, right value, the grace included in the right value, the result |
| A status comparison | One `STATUS_COMPARISON` item: the status, the set it was tested against, the result |
| A policy value | One `POLICY_PARAMETER` item: name and value |
| A relationship | One `RELATIONSHIP_EDGE` item that refers to the line item and names both ends |

### 7.3 What a source row item says

By reference only: the row id. A response resolves, through the batch and
within the workspace, the file name, the format, the entity type, the row
number, the outcome and the commit time, which `GET {ws}/ingestion/sources`
returns today, and for a workbook the name of the worksheet, which the batch
carries. The ledger is never changed after a commit, so the resolved values
of an old occurrence stay the same.

"States the value used" is `true`, `false`, or `null` when the row does not
carry the field. It is computed when the snapshot is read and stored as a
boolean. `false` on the last-changing row means what it says: the value the
rule used was not set by that row, and may have been set through the API
(D-21).

### 7.4 Bounds

| Collection | Bound |
|---|---|
| Earlier versions (R3 plans, R4 commitments) | The 50 before the current one, oldest first. When there are more: the newest 50 and one `MISSING_DATA` item `LIST_TRUNCATED` with the total (D-14) |
| Milestones named by R1 and R2 | 20, by sequence number; then one `LIST_TRUNCATED` item with the total |
| Line items on purchase orders that do not qualify (R5) | 20, by PO number; then one `LIST_TRUNCATED` item with the total |
| Evidence items of one occurrence | At most 120, by the templates. A response returns all of them |

### 7.5 Validation before anything is stored

Every reference of every item is checked against the snapshot it came from:
the target exists in the snapshot, is of the stated type, belongs to the
stated parent (a version to its milestone or purchase order, a line item to
both ends, a source row to a batch of the workspace). An item that fails
fails the run. The API accepts no evidence and no reference from a caller.

## 8. A finding and its life

### 8.1 Current state and history

| | Finding | Occurrence |
|---|---|---|
| What it is | The current state of one key | The key as one run reported it |
| Changes | Yes, by complete runs only | Never |
| Carries | Key, code, subject, project, purchase order and supplier where there are any, natural-key labels for sorting, severity, status, title, summary, versions of the rule, policy and engine of the latest occurrence, first and last detection (time and run), resolution (time and run) | Run, key, code, severity, title, summary, observed values, the structured explanation (rule, variant, the comparison, the checks passed), rule, policy and engine versions, snapshot digest, evidence |

The plan's `status_at_run` is not stored: an occurrence exists only where a
run reported the finding.

### 8.2 What a complete run does

A run is complete when the snapshot was read, every enabled rule ran, and
every occurrence, evidence item and diagnostic was stored. Only then, in the
same transaction that marks the run `COMPLETED`:

| Finding | Before | After |
|---|---|---|
| Reported, key unknown | — | Created `ACTIVE`; first and last detection are this run |
| Reported, `ACTIVE` | `ACTIVE` | `ACTIVE`; last detection, severity, title, summary and versions follow this run |
| Reported, `RESOLVED` | `RESOLVED` | `ACTIVE` again; first detection kept, resolution cleared (D-12) |
| Not reported, `ACTIVE`, **its rule ran** | `ACTIVE` | `RESOLVED`; resolution time and run recorded |
| Not reported, its rule did not run | any | Unchanged |
| `RESOLVED` or `SUPERSEDED`, not reported | — | Unchanged |

All timestamps a run writes are one reading of the service clock.

A run that fails writes no occurrence, changes no finding and resolves
nothing. `SUPERSEDED` is written by no run of v0.2; it is reserved for a
documented change of identity.

A finding can be resolved because the facts changed or because the policy
did. The run that resolved it is recorded, and with it the policy and engine
versions, so the difference can be read; nothing is resolved without a run.
v0.2 has one policy id. A second one needs a decision about identity first,
because findings are keyed by workspace, not by policy.

## 9. A run

### 9.1 Request

`POST {ws}/intelligence/runs` with the header `Idempotency-Key` and a body of
at most three optional fields: `policy_id`, `policy_version`,
`evaluation_date`. Unknown fields are rejected, as everywhere in v0.1. There
is no way to send a threshold, a rule name, a subject or a workspace.

| Rule | |
|---|---|
| Key | 8 to 128 characters of letters, digits, `.`, `_`, `-` (the alphabet of `X-Request-ID`). Stored as its SHA-256, never as sent, and never logged |
| Same key, same body | The same run is returned, with `replayed: true` and status 200, whatever its status |
| Same key, other body | `409 INTELLIGENCE_RUN_CONFLICT`. The body is compared as sent: an omitted date equals an omitted date |
| Evaluation date omitted | The date, in the policy's time zone, of one reading of the service clock, taken before the run is created, and stored |
| Evaluation date supplied | Refused when later than that date, earlier than the policy's `effective_from`, or earlier than the evaluation date of the workspace's latest completed run (D-24) |
| Policy omitted | The one policy of v0.2 |
| One at a time | A workspace has at most one run in progress, by a partial unique index. Another request is answered `429 INTELLIGENCE_CAPACITY_EXCEEDED` with `Retry-After` (D-25) |

### 9.2 Stages

| Stage | Transaction | Does |
|---|---|---|
| Register | Its own | Validates the request and the policy; inserts the run as `RUNNING`. `PENDING` is not used by the synchronous run of v0.2 |
| Snapshot | One read-only `REPEATABLE READ` transaction (`read_snapshot`) | Reads the families of `canonical-input-mapping.md` §3 into immutable values, checks the invariants (§9.4), computes the digest. Ends before anything else happens |
| Evaluate | None | Pure functions over the snapshot. No database, no clock, no network |
| Publish | One | Locks the run row; if it is no longer `RUNNING`, writes nothing. Otherwise stores occurrences, evidence and diagnostics, applies §8.2, stores counts, digest and durations, and sets `COMPLETED` |
| Fail | Its own | On an error after registration: sets `FAILED` with a failure code. If the database cannot be reached, the run stays `RUNNING` and is abandoned later |

The facts may change between the snapshot and the publication. The result is
then still right for its snapshot, and the run says which: it carries the
time and the digest of the snapshot beside the time of completion. Nothing
calls it current.

A run that is still `RUNNING` after a fixed time is failed as `ABANDONED`
when the next request for the workspace arrives, under a lock on the run row,
so that a process that was only slow cannot publish afterwards. The time is
set with the run budget (task T-F-04) and is at least ten times that budget.

### 9.3 Digest

`sha256:` and the lowercase hex SHA-256 of the UTF-8 canonical JSON of: the
workspace id, the evaluation date, and the families of the snapshot in their
fixed order with their fields in a fixed order. Canonical JSON: keys sorted,
no insignificant white space, dates `YYYY-MM-DD`, UUIDs lowercase, enumerations
as their values, `null` for an absent value and never an empty string in its
place, integers as JSON numbers, no float anywhere. The policy has its own
SHA-256 over its canonical JSON. Test vectors are checked in with task T-B-02.

The same workspace state, evaluation date, policy and engine give the same
digest, the same findings in the same order, and the same evidence in the
same order, byte for byte, apart from ids and timestamps of the run.

### 9.4 Invariants of a snapshot

A snapshot that breaks one is invalid; the run fails with `SNAPSHOT_INVALID`
and reports nothing.

| Invariant |
|---|
| Every purchase order, equipment record and line item refers to a project, supplier, purchase order and equipment record that are in the snapshot |
| Every milestone refers to a purchase order in the snapshot; every version to its parent |
| Version numbers of one parent are distinct |
| A milestone with an actual date is `COMPLETED` |
| Every source row a version points to belongs to a batch of the workspace |
| Every enumeration value is one the engine knows |

## 10. Storage

Five tables, all new, none of them canonical, created by one additive
migration (task T-D-01). No canonical table is altered.

| Table | Holds | Keys and constraints |
|---|---|---|
| `intelligence_runs` | One row per run: status, hashed idempotency key, hash of the request, evaluation date and whether it was supplied, policy id, version and hash, engine version, snapshot time and digest, counts of inputs, findings and diagnostics, stage durations, failure code, request id, times | Unique `(workspace_id, idempotency key hash)`; unique `(workspace_id, id)`; partial unique on `workspace_id` where the run is in progress; failure code present exactly when `FAILED` |
| `intelligence_findings` | Current state (§8.1) | Unique `(workspace_id, finding_key)`; unique `(workspace_id, id)`; composite foreign keys to the project, and to the purchase order and supplier when present; indexes `(workspace_id, status, severity, finding_code)` and `(workspace_id, project_id, status)` |
| `intelligence_finding_occurrences` | History (§8.1) | Unique `(workspace_id, run_id, finding_key)`; composite foreign keys `(workspace_id, run_id)` and `(workspace_id, finding_id)`; index `(workspace_id, finding_id, detected_at)` |
| `intelligence_evidence_items` | §7.1 | Unique `(occurrence, ordinal)`; composite foreign key `(workspace_id, occurrence)`; a typed, nullable foreign key per kind of canonical target, at most one of them set |
| `intelligence_run_diagnostics` | §6 | Unique `(run, ordinal)`; composite foreign key `(workspace_id, run_id)` |

Every table carries `workspace_id`, and every repository function takes it as
an argument and filters on it. The subject of a finding and the target of an
evidence item cannot have a workspace-composite foreign key in every case
(`milestones`, `purchase_order_items`, the two version tables and
`ingestion_rows` offer none without a change to canonical tables), so the service validates them (§7.5)
and the foreign key guarantees only that the target exists.

Nothing is deleted. Occurrences, evidence and diagnostics are never updated;
as with the version history of v0.1 (limitation L-34), that is a rule of the
service and not of the database.

## 11. API

Every route is under `/api/v1/workspaces/{workspace_id}/intelligence`, serves
the configured development workspace only, and answers with the envelope and
the list shape of v0.1 (`limit` 1 to 200, default 50; `offset`).

| Method and path | Returns | Order |
|---|---|---|
| `POST /runs` | The run. 201 when created, 200 when replayed | — |
| `GET /runs` | A page of runs | Newest first: `created_at` descending, then id |
| `GET /runs/{run_id}` | The run with its counts | — |
| `GET /runs/{run_id}/occurrences` | A page of what that run reported | As findings |
| `GET /runs/{run_id}/diagnostics` | A page of diagnostics | Rule, then subject label, then code |
| `GET /findings` | A page of current findings. Filters: `status` (default `ACTIVE`), `severity`, `finding_code`, `project_id`, `purchase_order_id`, `supplier_id` | Severity rank, rule priority, project code, subject label, key |
| `GET /findings/{finding_id}` | The finding and its latest occurrence with all evidence | Evidence by ordinal |
| `GET /findings/{finding_id}/occurrences` | A page of occurrences, without evidence, with `evidence_count` | Newest first |
| `GET /findings/{finding_id}/occurrences/{occurrence_id}` | One occurrence with all evidence | Evidence by ordinal |

Three routes are not in the plan (§11): the diagnostics of a run (D-20), the
occurrences of a run (the plan's `run_id` filter, as a route of its own), and
one occurrence with its evidence (without it the evidence of an earlier run
could not be read).

A run in a response has: id, status, evaluation date and its origin, snapshot
time and digest, policy id and version, engine version, counts (`total`,
`by_code`, `by_severity`, `resolved`, `not_evaluable`), times, failure code,
`replayed`. No response carries a raw source row, a snapshot, an idempotency
key or a policy file path.

| Situation | Status | Code |
|---|---|---|
| `Idempotency-Key` absent or malformed; unknown field; evaluation date in the future or before `effective_from` | 422 | `VALIDATION_ERROR` with a detail on the field |
| Unknown policy id or version | 422 | `INTELLIGENCE_POLICY_NOT_FOUND` |
| The policy document does not validate | 500 | `INTELLIGENCE_POLICY_INVALID`; no run is created |
| Same key, other body; evaluation date earlier than the latest completed run | 409 | `INTELLIGENCE_RUN_CONFLICT` |
| A run of the workspace is in progress | 429 | `INTELLIGENCE_CAPACITY_EXCEEDED` |
| The snapshot is invalid | 500 | `INTELLIGENCE_SNAPSHOT_INVALID`; the run is `FAILED` |
| A rule raised | 500 | `INTELLIGENCE_EVALUATION_FAILED`; the run is `FAILED` |
| The result could not be stored | 500 | `INTELLIGENCE_RUN_FAILED`; the run is `FAILED` when that can be recorded |
| Run, finding or occurrence not found, or of another workspace | 404 | `NOT_FOUND` (D-23) |
| Another workspace | 404 | `WORKSPACE_NOT_AVAILABLE` |
| The database cannot be reached | 503 | `DATABASE_UNAVAILABLE` |

## 12. Logging

One structured event per run: request id, workspace id, run id, policy and
engine version, the count of each family, the count of findings by code, the
duration of each stage, the status and the failure code (D-22). Never a row
payload, a key, a natural key or a finding key.

Liveness and readiness do not depend on the engine. An invalid policy fails
run creation and nothing else.

## 13. Changes to v0.1 documents, made with the implementation

Not made now: until the engine exists, those documents describe the system
truthfully.

| Document | Change |
|---|---|
| `AGENTS.md` | Invariant 8 names canonical tables, canonical schemas and the World State; findings live only in the intelligence tables and schemas. Rule 10 keeps agent, LLM, vector store, queue and cache out |
| `system-boundaries.md` | The flow gains the snapshot, the rules and the intelligence tables; "outside this release" loses deterministic intelligence |
| `domain-model.md` | A section for the intelligence tables, marked as not canonical |
| `world-state-contract.md` | One sentence: findings are not part of the World State |
| `api-contract.md`, `openapi.json` | The routes and codes of §11 |
| `known-limitations.md`, `test-strategy.md`, `implementation-log.md` | As built |

## 14. Not in this contract

No agent, model, score, probability, recommendation, notification, write-back
or external call. No working-day or holiday calendar. No judgement about
quantities. No re-evaluation of the past. No rule language. No second policy.
No shadow mode. No metrics endpoint. No authentication: the routes inherit
the loopback, single-workspace boundary of v0.1 and disclose procurement
schedules to whoever can reach them.
