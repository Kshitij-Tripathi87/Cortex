# Procurement Intelligence Engine — Phase Plan and Engineering Specification

**Document status:** Proposed implementation specification  
**Target product:** Cortex Nexus  
**Target release:** Procurement Intelligence Engine v0.2 (deterministic findings only)  
**Repository baseline inspected:** PR #28 head `5e2def7c7bfc04405e2b59698eed39eee03cdf6f`  
**Base branch reported by PR:** `main` at `2bb280978d23d532eac50b753fe1cec6371810b2`  
**Implementation status:** NOT STARTED  
**Merge status dependency:** PR #28 is open and unmerged at the time this plan was authored.  
**Audience:** Lead engineer, backend contributors, independent reviewer, QA, future agent-runtime engineers.

---

## 0. Executive decision

Build the first Procurement Intelligence Engine as a **deterministic, read-only analytical layer** over the canonical PostgreSQL-backed World State. It identifies five well-defined procurement conditions, explains why each condition exists, and carries machine-verifiable evidence back to canonical source rows and version history.

The first release does **not** introduce autonomous agents, an LLM, probabilistic risk scores, recommendations, write-back, supplier communications, ERP integrations, external actions, or a separate graph database. It does not reinterpret canonical facts or mutate them. A finding is an analytical observation, not a new procurement fact.

The five initial finding types, in priority order:

1. **OVERDUE_DELIVERY** — an open delivery obligation whose current effective committed date is before the evaluation date and whose delivery has not been recorded as completed.
2. **MISSING_SUPPLIER_ACKNOWLEDGEMENT** — an issued purchase order for which the configured acknowledgement evidence is absent by the configured acknowledgement due date / policy rule.
3. **MILESTONE_SLIPPAGE** — an open milestone whose current planned date is before the evaluation date, or an actual completion date later than the plan, according to the precise rules below.
4. **COMMITMENT_THREATENS_REQUIRED_ON_SITE** — the latest effective delivery commitment is later than the equipment's required-on-site date, with the PO-to-equipment relationship and date lineage shown.
5. **CRITICAL_EQUIPMENT_WITHOUT_PO** — critical equipment with no qualifying non-cancelled purchase-order line item.

The order above is product priority, not execution order. All five evaluators should be pure, independently testable functions over a snapshot. The engine should produce the same output for the same snapshot, evaluation date, policy version, and engine version.

### 0.1 Non-negotiable design decisions

- PostgreSQL remains the source of truth for all canonical procurement facts.
- The current World State remains a projection of canonical rows, assembled from PostgreSQL.
- Intelligence is stored separately from canonical facts. Findings must never be added to project, supplier, equipment, purchase-order, milestone, commitment, or World State fact schemas.
- All queries and all writes are workspace-scoped. A workspace ID is not an authorization credential.
- Version history remains append-only. An intelligence run may be superseded by a later run; it does not update or delete procurement history.
- No LLM participates in detection, date arithmetic, policy evaluation, finding identity, evidence selection, or severity assignment in v0.2.
- Every finding has explicit evidence references and a reproducible rule explanation. Missing facts are represented as unknown / not evaluable, not inferred.
- The engine is read-only with respect to canonical procurement tables.
- No action is taken on a finding. Human approval and an execution gateway are future, separate phases.
- The repository's existing stack and layering remain in force: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, uv, pytest, Ruff, strict mypy.
- Do not weaken current tests, schema checks, workspace isolation, idempotency, or mutation testing to land this phase.

### 0.2 Phase entry gate

Implementation is blocked until all of these are true:

- PR #28 has an independent human review from someone other than its author.
- Every review finding is resolved or explicitly accepted by the lead with a documented rationale.
- PR #28 is merged into `main`, and the merged `main` CI is green.
- Its release-gate items are signed off or explicitly carried as accepted limitations. In particular, the XLSX parser must remain loopback/operator-only until OS-enforced memory and wall-clock isolation exists; v0.2 must not broaden upload exposure.
- The lead confirms the canonical baseline commit and working tree for the next implementation branch.
- The team has reviewed this document against the actual merged models and schemas. If any described field differs, update this plan before coding.

Do not merge PR #28 as part of implementing this document. Do not branch intelligence work from the unmerged PR head unless the lead explicitly chooses a dependent branch strategy.

---

## 1. Product and scope

### 1.1 Product objective

Move Cortex Nexus from a canonical procurement data foundation to a deterministic procurement observation system. The user should be able to ask:

- Which deliveries are overdue?
- Which issued purchase orders still lack a supplier acknowledgement?
- Which milestones have slipped?
- Which supplier commitments now threaten equipment required-on-site dates?
- Which critical equipment items have not been covered by a purchase order?

For each answer, Cortex must show:

- the affected project and procurement entities;
- the exact rule that fired;
- the evaluated date and policy version;
- the canonical facts used;
- the source ingestion batch and row, where recorded;
- the relevant plan or commitment version history;
- any missing information that limits confidence or prevents evaluation;
- whether the observation is active, resolved, superseded, or not evaluable.

The system must answer “why?” without asking an LLM to invent an explanation.

### 1.2 In scope for v0.2

- A versioned policy configuration with explicit thresholds and clear defaults.
- A snapshot builder that reads the canonical workspace state in a consistent database transaction.
- Five deterministic rule evaluators.
- A finding and finding-evidence persistence model, isolated from canonical data.
- An evaluation-run ledger with status, snapshot identity, engine version, policy version, evaluated-at timestamp, counts, and reproducibility metadata.
- Idempotent run creation and finding reconciliation.
- Workspace-scoped read APIs for runs, active findings, finding detail, evidence, and history.
- Stable finding codes, deterministic identity keys, severities, statuses, and sort order.
- Comprehensive unit, API, integration, concurrency, workspace isolation, and defect-detection tests.
- Synthetic fixtures and explicit expected results for the demo procurement dataset.
- Performance instrumentation and benchmark evidence for representative workspaces.
- Documentation and OpenAPI updates.

### 1.3 Explicitly out of scope

Do not implement any of the following in this phase:

- Agent orchestration, LLM inference, prompt engineering, natural-language interpretation, or tool-using agents.
- Supplier email, WhatsApp, portal, phone, or calendar integrations.
- Purchase-order amendments, commitment updates, milestone edits, or other write-back from intelligence.
- Automatic task creation or notifications.
- Predictive delivery probability, supplier reliability scores, risk scores, or opaque ranking.
- A graph database, vector database, event streaming platform, Redis, queue, or distributed scheduler.
- Multi-workspace production authentication or public deployment; those have separate security prerequisites.
- General-purpose rules DSL or user-authored executable policy.
- Data science experimentation, machine learning, or statistical inference.
- A UI redesign or frontend application.
- Arbitrary natural-language questions over raw tables.
- Backfilling intelligence into canonical World State schemas.

A follow-on phase can add these only after finding correctness, evidence completeness, and operational boundaries have been demonstrated.

---

## 2. Existing system constraints and facts

The repository baseline inspected contains the following structure and contracts. Treat these as current source-of-truth until revalidated against the merged base.

### 2.1 Canonical entities and relationships

The current domain model includes:

- `Workspace`
- `Project`
- `Supplier`
- `Equipment`
- `PurchaseOrder`
- `PurchaseOrderItem`
- `Milestone`
- `MilestonePlanVersion`
- `SupplierCommitmentVersion`
- `IngestionBatch`
- `IngestionRow`

Key relationships:

- One project has many equipment records and purchase orders.
- One supplier has many purchase orders.
- A purchase order has zero or more line items.
- A line item links one purchase order to one equipment record.
- The same equipment can appear on multiple purchase orders (split procurement), but once per purchase order.
- A purchase order has milestones.
- A milestone has append-only plan versions.
- A purchase order has append-only supplier commitment versions.
- Ingestion rows can link to the canonical record they created or changed.

Do not add a direct supplier field to equipment. Supplier identity for equipment procurement is derived through the purchase-order line item and that purchase order's supplier.

### 2.2 Relevant current canonical fields

Confirm the exact types, nullable rules, and field names from the merged source before implementation.

**Equipment**
- `id`, `workspace_id`, `project_id`
- `equipment_code`, `name`
- `criticality` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`)
- `procurement_status`
- `required_on_site_date` (nullable date)

**Purchase order**
- `id`, `workspace_id`, `project_id`, `supplier_id`
- `po_number`
- `issue_date`
- `status` (`DRAFT`, `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED`, `DELIVERED`, `CANCELLED`)

**Purchase order item**
- `id`, `workspace_id`, `project_id`, `purchase_order_id`, `equipment_id`
- `quantity`, `unit_price`

**Milestone**
- `id`, `workspace_id`, `purchase_order_id`
- `milestone_type`, `sequence_no`
- `actual_date` (nullable)
- `status` (`PENDING`, `COMPLETED`, `CANCELLED`)

**MilestonePlanVersion**
- `id`, `milestone_id`, `version_no`, `planned_date`
- `source_ingestion_row_id`
- `recorded_at`, `recorded_by`

**SupplierCommitmentVersion**
- `id`, `workspace_id`, `purchase_order_id`, `version_no`
- `committed_delivery_date`
- `source_reference`
- `source_ingestion_row_id`
- `recorded_at`, `recorded_by`

**IngestionRow**
- Confirm its canonical link columns and source metadata from the merged schema.
- Evidence should resolve a source row to its batch, original filename, entity type, row number, and import metadata without exposing uploaded file contents or secrets.

### 2.3 Existing architecture boundaries

Preserve the existing flow:

```text
Canonical PostgreSQL tables
        |
        v
Workspace-scoped repositories
        |
        v
World State / Intelligence snapshot builder
        |
        v
Pure deterministic rule evaluators
        |
        v
Finding reconciliation service
        |
        v
Intelligence run + findings + evidence tables
        |
        v
Read-only Intelligence API
```

The evaluator must not:
- parse CSV/XLSX;
- perform HTTP calls;
- issue SQL;
- access environment variables;
- read arbitrary workspace records;
- call an LLM;
- commit a database transaction;
- mutate canonical ORM entities.

The endpoint must not:
- run SQL;
- calculate procurement rules;
- assemble evidence from multiple repositories;
- reconcile finding state.

Repositories must:
- scope every query by workspace;
- return data, not policy decisions;
- never commit.

Services own transactions. The API is the adapter.

### 2.4 Existing repository contributor rules

Read and obey `AGENTS.md`, `docs/architecture/system-boundaries.md`, `docs/architecture/domain-model.md`, `docs/architecture/world-state-contract.md`, and `docs/engineering/test-strategy.md` before any code change.

The current project rules remain authoritative:
- PostgreSQL is the source of truth.
- Workspace scope is mandatory on every query.
- Preview does not mutate canonical records.
- Ingestion commit is atomic and idempotent.
- History is append-only.
- Decimal values remain `Decimal` / PostgreSQL `NUMERIC`; never float.
- Services own transactions.
- Facts and inference remain separate.
- Timestamps are UTC via `app.core.clock`.
- No secrets, SQL, stack traces, local paths, or submitted values in response/log output.
- Do not add dependencies without a stated need and a lockfile update.
- Schema/domain changes require coordinated docs, ORM, Pydantic, migrations, OpenAPI, and tests.
- No second ORM, migration tool, API framework, graph database, LLM, queue, or cache in this release.

---

## 3. Domain vocabulary

Use these terms consistently.

| Term | Definition |
|---|---|
| Canonical fact | A persisted procurement record or version supplied by an operator/source system and stored in the canonical domain tables |
| Current version | The version with the highest `version_no` for a parent record, selected by a deterministic query |
| Evaluation date | The date used for date-based rules. It is explicit in every evaluation run and is derived from the configured UTC clock, converted using the workspace policy timezone |
| Evaluation run | One immutable execution of all enabled intelligence rules against one canonical snapshot and one policy version |
| Finding | A deterministic observation emitted by a rule for an affected procurement subject |
| Finding identity | A stable key identifying the same underlying condition across evaluation runs |
| Finding occurrence | One result of a finding identity in one run |
| Evidence item | A typed reference to a canonical record, version, ingestion row, or derived comparison used by a finding |
| Evidence path | The ordered graph of canonical references and relationships that explains how source facts connect to the finding |
| Policy version | An immutable, named version of the business thresholds and rule options used for an evaluation |
| Engine version | A code-level semantic version of the rules and evidence contract |
| Snapshot digest | A cryptographic digest of the canonical inputs that participated in the evaluation |
| Not evaluable | Required facts are missing or ambiguous, so the engine cannot assert the condition |
| Resolved | A previously active finding no longer appears in a later complete evaluation |
| Superseded | A finding identity has been replaced by another identity due to an explicitly documented identity migration or rule semantic change |
| Acknowledgement evidence | A canonical fact that the supplier has acknowledged a PO (initially PO status or a configured milestone; see rule definition) |
| Required-on-site date | The canonical date by which equipment must be available at the project site |
| Delivery commitment | The latest appended supplier-committed delivery date for a purchase order |

Avoid calling a finding a “fact”. It is a result computed from facts under a specified rule.

---

## 4. Evaluation model

### 4.1 Snapshot semantics

Each run evaluates a **single, consistent, workspace-scoped snapshot**.

Preferred implementation:
- Start one database transaction at PostgreSQL `REPEATABLE READ` isolation for snapshot read and canonical digest calculation.
- Load only the canonical record families needed for the five rule types.
- Read current versions deterministically by highest `version_no`, with stable tie rejection (the database uniqueness constraint should already prevent ties).
- Capture the canonical row IDs and values into immutable typed snapshot DTOs.
- End the snapshot transaction before any potentially expensive pure evaluation or finding persistence, unless the transaction design explicitly needs the same snapshot held through reconciliation.
- Carry a snapshot watermark / digest to the persistence service.
- Do not run a series of independent READ COMMITTED queries and call the assembled result consistent.
- If repeatable read is not viable with the current session setup, document the trade-off and implement one explicit transaction strategy before coding.

A snapshot must contain:
- workspace identity;
- snapshot creation timestamp (UTC);
- evaluation date;
- stable, ordered lists of project, supplier, equipment, PO, PO item, milestone, plan version, commitment version, and ingestion source reference DTOs;
- input counts for each entity family;
- a digest over canonical, normalized input fields and all relevant version identifiers;
- policy and engine versions applied.

The digest should be computed over a canonical serialization:
- fixed field order;
- fixed entity order;
- stable sort keys;
- dates in ISO 8601 `YYYY-MM-DD`;
- timestamps in UTC ISO 8601 with explicit `Z`;
- UUIDs in lowercase canonical form;
- enums as their stable values;
- decimals as canonical decimal strings;
- null represented distinctly from empty string;
- no locale-dependent formatting;
- no Python object repr, unordered set iteration, or float serialization.

Suggested digest construction:
`SHA256(UTF8(canonical_json(snapshot_payload)))`.

Do not include raw uploaded file bytes or sensitive source cell payloads in the digest. Include source row IDs and stable canonical values; avoid source data that is not relevant to the rule.

### 4.2 Determinism contract

For a fixed tuple:

`(workspace_id, evaluation_date, policy_version, engine_version, canonical_snapshot)`

the engine must produce byte-for-byte equivalent normalized findings and evidence ordering.

Determinism includes:
- finding identity;
- code;
- severity;
- title and summary template;
- evaluated values;
- comparison operator and result;
- policy threshold;
- evidence references and ordering;
- rule explanation;
- finding sort order;
- API serialization, except fields explicitly identified as run-specific timestamps/IDs.

Do not use:
- random IDs as finding identity;
- current wall clock inside evaluators;
- non-deterministic SQL row order;
- dictionary/set iteration without sorting;
- floating-point arithmetic;
- network calls;
- heuristic fuzzy joins;
- model-generated labels or explanations.

### 4.3 Policy configuration

For v0.2, policy must be code-validated, immutable and stored/versioned as a document or a typed record. Do not create a general-purpose executable DSL.

Required policy fields:
- `policy_id`: stable identifier (example: `procurement-default`)
- `policy_version`: immutable semantic version or monotonically increasing integer
- `effective_from`: date
- `timezone`: IANA timezone identifier; initial default `Asia/Kolkata` for the local demonstration, but no hidden assumption in date calculations
- `overdue_grace_days`: non-negative integer, default 0
- `acknowledgement_due_days_after_issue`: non-negative integer; **must be explicitly selected by the lead before enabling the rule**
- `acknowledgement_required_statuses`: typed list of PO statuses for which acknowledgement is expected; initial candidate is `ISSUED`, subject to approval
- `critical_equipment_criticality`: default `CRITICAL`; do not silently include HIGH
- `po_statuses_that_count_as_procured`: explicit set, recommended `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED`, `DELIVERED`; exclude `DRAFT` and `CANCELLED`
- `po_statuses_that_count_as_open_delivery`: explicit set, recommended `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED`; exclude `DRAFT`, `DELIVERED`, `CANCELLED`
- `milestone_overdue_grace_days`: non-negative integer, default 0
- `delivery_risk_severity_policy`: deterministic mapping table, approved before release
- `finding_severity_policy_version`: explicit version.

Policy requirements:
- validate all fields on load;
- reject unknown keys;
- reject negative durations;
- reject unsupported timezone identifiers;
- do not edit an existing policy version in place;
- store the applied policy snapshot/hash on each run;
- an evaluation must fail closed if the selected policy is missing or invalid;
- tests must use explicit policy fixtures rather than ambient defaults.

**Open decision:** Product owner must approve acknowledgement timing (for example, 3, 5, or 7 calendar days after issue), expected PO statuses, and whether weekends/holidays affect the due date. Until then, the acknowledgement rule may run in shadow mode but must not label a PO as a breach.

### 4.4 Calendar arithmetic

Use calendar dates, not elapsed seconds:
- evaluate using a `date` in the explicit policy timezone;
- due date = issue date + policy calendar days;
- overdue = evaluation date > due date + grace days;
- equality means due today, not overdue;
- no working-day logic in v0.2 unless separately specified and tested;
- no Indian public-holiday calendar or supplier-country calendar in v0.2;
- missing dates remain unknown and do not default to today;
- all timestamps used for run metadata are UTC.

The evaluator receives `evaluation_date` as an argument. It never calls `date.today()` or `datetime.now()`.

---

## 5. Finding contract

### 5.1 Finding schema (logical contract)

A finding should have these logical fields. The actual SQLAlchemy and Pydantic names can follow existing naming conventions, but the semantics must be preserved.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `id` | UUID | yes | Primary key for persisted finding identity |
| `workspace_id` | UUID | yes | Workspace boundary |
| `finding_key` | text | yes | Stable deterministic identity key |
| `finding_code` | enum/text check | yes | One of five v0.2 rule codes |
| `subject_type` | enum/text check | yes | equipment, purchase_order, milestone |
| `subject_id` | UUID | yes | Canonical subject ID |
| `project_id` | UUID | yes | Project context |
| `severity` | enum | yes | INFO, LOW, MEDIUM, HIGH, CRITICAL, or UNCLASSIFIED pending approval |
| `status` | enum | yes | ACTIVE, RESOLVED, SUPERSEDED |
| `title` | bounded text | yes | Deterministic template |
| `summary` | bounded text | yes | Deterministic, value-substituted rule summary |
| `rule_version` | text | yes | Evaluator semantic version |
| `policy_version` | text | yes | Policy applied |
| `first_detected_at` | timestamptz | yes | First run that detected this identity |
| `last_detected_at` | timestamptz | yes | Latest complete run that detected it |
| `last_run_id` | UUID | yes | Latest run with active occurrence |
| `resolved_at` | timestamptz nullable | no | When a later complete run stopped detecting it |
| `created_at`, `updated_at` | timestamptz | yes | Service clock |

Do not store an unbounded evidence JSON blob as the only evidence structure. Evidence is relational and individually queryable.

### 5.2 Finding occurrence

Every run that emits a finding must create an immutable occurrence record:

- `id`
- `workspace_id`
- `run_id`
- `finding_id`
- `finding_key` (copied to make run audit robust)
- `finding_code`
- `severity`
- `status_at_run`
- `detected_at`
- `snapshot_digest`
- `rule_version`
- `policy_version`
- `observed_values` (bounded JSON object of typed scalar facts used by the rule; no raw source row payload)
- `explanation` (structured rule result, not generated prose)
- unique `(run_id, finding_key)`

The occurrence makes historical run results immutable even when the current finding later resolves.

### 5.3 Evidence item

Evidence item fields:
- `id`
- `workspace_id`
- `finding_occurrence_id`
- `evidence_type`
- `entity_type`
- `entity_id`
- `version_id` nullable
- `ingestion_row_id` nullable
- `role` (SUBJECT, COMPARATOR, RELATIONSHIP, SOURCE, HISTORY, POLICY)
- `ordinal`
- `field_name` nullable
- `observed_value` bounded JSON scalar/object
- `display_label` deterministic text
- unique `(finding_occurrence_id, ordinal)`

Evidence types should be a closed enum, at minimum:
- `CANONICAL_RECORD`
- `CANONICAL_VERSION`
- `INGESTION_SOURCE_ROW`
- `DATE_COMPARISON`
- `STATUS_COMPARISON`
- `POLICY_PARAMETER`
- `RELATIONSHIP_EDGE`
- `MISSING_DATA`

Evidence must not include:
- uploaded file bytes;
- unrestricted raw cell values;
- credentials, email addresses, secrets, or private notes;
- arbitrary SQL;
- unbounded nested JSON;
- unvalidated external URLs.

Evidence references must be validated against workspace, entity type, and parent relationships before persistence. Do not accept arbitrary IDs from callers as evidence.

### 5.4 Finding identity

The identity key must represent the stable condition, not the changing date value.

Recommended keys:
- overdue delivery: `OVERDUE_DELIVERY:po:<purchase_order_id>`
- missing acknowledgement: `MISSING_SUPPLIER_ACKNOWLEDGEMENT:po:<purchase_order_id>`
- milestone slippage: `MILESTONE_SLIPPAGE:milestone:<milestone_id>`
- commitment threatens required-on-site: `COMMITMENT_THREATENS_REQUIRED_ON_SITE:equipment:<equipment_id>:po:<purchase_order_id>`
- critical equipment without PO: `CRITICAL_EQUIPMENT_WITHOUT_PO:equipment:<equipment_id>`

Why stable:
- a revised commitment date should update the same condition, not create a duplicate finding each time;
- the finding occurrence preserves each run's exact comparison and evidence;
- a later rule semantic change increments the rule/engine version and may require an identity migration policy.

For split procurement, evaluate each equipment/PO pair for commitment threat; do not collapse multiple suppliers into one unexplained date. If an equipment item is on two POs, emit a finding per threatening PO relationship, and aggregate them in the API/UI later.

For critical equipment without a PO, the identity is equipment-only.

---

## 6. Deterministic rule specifications

Each rule must be a pure function with typed input and typed output. Use an explicit rule registry; do not use dynamic imports or a user-controlled rule name.

### 6.1 Rule R1 — Overdue delivery

**Code:** `OVERDUE_DELIVERY`  
**Subject:** Purchase order  
**Priority:** 1

#### Required inputs
- PO identity, project, supplier, status.
- Latest supplier commitment version for the PO.
- Delivery milestone state and actual date, where available.
- Evaluation date.
- Policy: open delivery statuses, grace days, severity mapping.
- Source evidence for the PO and latest commitment.

#### Eligibility
A PO is eligible only when:
- its status is in `po_statuses_that_count_as_open_delivery`;
- it has at least one latest supplier commitment version;
- its delivery is not recorded as complete under the approved delivery-completion interpretation.

Cancelled and delivered POs are not eligible. A PO with no commitment is not “overdue”; it may be reported as missing commitment only in a future rule, not inferred in R1.

#### Calculation
```text
effective_due_date = latest committed_delivery_date
overdue_boundary = effective_due_date + overdue_grace_days

if evaluation_date > overdue_boundary:
    emit OVERDUE_DELIVERY
else:
    emit nothing
```

If the delivery milestone has status COMPLETED with an actual date, suppress the overdue condition even if the PO status is stale. If the PO status says DELIVERED but the milestone is not completed, do not emit overdue; emit a data-quality/contradiction note only if a separate rule is later approved. Do not invent a delivery actual date from PO status.

#### Finding content
- Subject: PO.
- Title: `Delivery is overdue`.
- Summary template: `Purchase order {po_number} has a current supplier commitment of {committed_date}; the date is {overdue_days} calendar days past due as of {evaluation_date}.`
- Observed values: committed date, evaluation date, grace days, overdue days, PO status, completion evidence state.
- Evidence:
  1. PO canonical record.
  2. Supplier canonical record.
  3. Latest commitment version.
  4. Commitment ingestion source row, if present.
  5. Delivery milestone and plan/actual history, if present.
  6. Date comparison.
  7. Policy grace parameter.

#### Severity
Severity must be a policy-driven deterministic mapping. Initial candidate:
- 1–7 overdue calendar days: MEDIUM
- 8–21 days: HIGH
- >21 days: CRITICAL

These thresholds are **not approved**. Do not hard-code them until the lead signs off. If no severity policy is approved, use `UNCLASSIFIED` or block release. Do not invent thresholds.

#### Tests
- before due date: no finding;
- exactly due date: no finding;
- first day after boundary: finding;
- grace boundary equality: no finding;
- one day beyond grace: finding;
- latest version used, not first;
- append a later commitment that moves due date into future: finding disappears on next run and current finding resolves;
- completed delivery suppresses;
- delivered/cancelled statuses suppress;
- no commitment: no overdue finding;
- missing source row is represented without breaking finding;
- same snapshot yields same key/evidence;
- same PO in another workspace is invisible.

### 6.2 Rule R2 — Missing supplier acknowledgement

**Code:** `MISSING_SUPPLIER_ACKNOWLEDGEMENT`  
**Subject:** Purchase order  
**Priority:** 2

This rule is not ready to be enabled until the acknowledgement due-date policy is approved. It must not assume every PO should be acknowledged immediately.

#### Required inputs
- PO identity, issue date, status, supplier, project.
- Acknowledgement evidence. In current schema this may be:
  - PO status `ACKNOWLEDGED` or a later accepted lifecycle status; and/or
  - a milestone of type `PO_ACKNOWLEDGEMENT` with completed status and an actual date.
- Evaluation date.
- Policy acknowledgement statuses and allowed days after issue.
- Source row for the PO, and milestone evidence if available.

#### Acknowledgement source of truth
Use the following precedence, subject to confirmation against current domain contract:
1. An explicit `PO_ACKNOWLEDGEMENT` milestone marked COMPLETED is affirmative acknowledgement evidence.
2. PO status `ACKNOWLEDGED` or a later accepted state is affirmative state evidence.
3. PO status `DRAFT` is not an issued PO and is excluded.
4. A status `CANCELLED` is excluded.
5. If PO status is `ISSUED` but no explicit acknowledgement milestone exists, evaluate against the policy due date.
6. Contradictory evidence (e.g. explicit milestone completed but PO status ISSUED) suppresses the missing acknowledgement finding and emits an internal contradiction diagnostic; do not create a public separate finding in v0.2 unless approved.

Do not treat generic status `IN_PRODUCTION` as acknowledgement unless policy includes it explicitly.

#### Due date
`acknowledgement_due_date = issue_date + acknowledgement_due_days_after_issue`.

Emit only when:
- issue date exists;
- PO status is in `acknowledgement_required_statuses`;
- no affirmative acknowledgement evidence exists;
- evaluation date is strictly after due date plus any configured grace.

If issue date is absent, result is NOT_EVALUABLE with a missing-data diagnostic, not an active finding.

#### Finding content
- Subject: PO.
- Title: `Supplier acknowledgement is missing`.
- Summary: `Purchase order {po_number} was issued on {issue_date}; acknowledgement was due by {due_date}, but no acknowledgement evidence is recorded as of {evaluation_date}.`
- Evidence:
  1. PO record.
  2. Supplier record.
  3. Issue date value.
  4. Policy due days and calculated due date.
  5. Acknowledgement milestone(s), even when absent, represented with a MISSING_DATA evidence item.
  6. PO lifecycle status.
  7. PO source row.

#### Tests
- no issue date: not evaluable;
- DRAFT: excluded;
- CANCELLED: excluded;
- on or before due date: no finding;
- after due date: finding;
- completed acknowledgement milestone suppresses;
- accepted PO state suppresses;
- status without approved acknowledgement meaning does not suppress;
- duplicate milestone sequence is prevented by canonical constraints;
- source provenance present and absent;
- policy versions change due date only in new runs;
- all acknowledgement threshold boundary cases.

### 6.3 Rule R3 — Milestone slippage

**Code:** `MILESTONE_SLIPPAGE`  
**Subject:** Milestone  
**Priority:** 3

#### Required inputs
- Milestone identity and type.
- Latest planned-date version.
- Status and actual date.
- Parent PO, project, supplier.
- Evaluation date and grace days.
- Plan-version source references and milestone source references.

#### Eligibility
- `CANCELLED` milestone: excluded.
- No plan version: NOT_EVALUABLE; do not assume a date.
- `PENDING` milestone with a plan date in the past beyond grace: emit overdue slippage.
- `COMPLETED` milestone with an actual date later than the latest planned date plus grace: emit completed-late slippage.
- `COMPLETED` milestone with no actual date: not evaluable for actual slippage; do not invent actual.
- `PENDING` milestone with an actual date: canonical invariant violation; fail the evaluator input validation and surface an operational error, not a finding.
- If the current plan date is revised after the previous plan date, use the latest version for current status, but retain all plan versions as evidence. A separate historical-plan regression indicator is not in v0.2.

#### Calculation
For pending:
`evaluation_date > latest_planned_date + grace_days`.

For completed:
`actual_date > latest_planned_date + grace_days`.

Equality is not slippage.

#### Finding content
- Subject: milestone.
- Title: `Milestone is behind plan`.
- Summary includes milestone type, sequence, latest plan date, actual date if complete, and evaluation date.
- Evidence:
  1. Milestone record.
  2. Parent PO record and supplier.
  3. Latest milestone plan version.
  4. All prior plan versions in ascending version order (bounded to a documented maximum; if truncated, include count and deterministic truncation marker).
  5. Source ingestion row for each plan version that has one.
  6. Actual completion date if present.
  7. Date comparison and policy grace.

#### Tests
- latest plan version controls;
- pending before/on/after due boundary;
- completed on time vs late;
- completed without date is not evaluable;
- cancelled excluded;
- missing plan not evaluated;
- planned date revised later into future resolves current slippage;
- previous plan versions remain evidence;
- ordering of versions stable;
- missing provenance does not fail rule;
- workspace scope.

### 6.4 Rule R4 — Revised commitment threatens required-on-site date

**Code:** `COMMITMENT_THREATENS_REQUIRED_ON_SITE`  
**Subject:** Equipment + Purchase order relationship  
**Priority:** 4

#### Intent
Detect when the latest supplier delivery commitment for a PO that contains an equipment item is later than that equipment's required-on-site date. This is a deterministic date conflict, not a prediction that the supplier will fail.

#### Required inputs
- Equipment identity, project, criticality, required-on-site date.
- PO item relationship.
- PO identity, status, supplier.
- Latest supplier commitment version for that PO.
- Optional delivery/installation milestone completion evidence.
- Evaluation date is not needed for the basic date conflict but must be recorded for run consistency.
- Source rows for equipment, line item, PO and commitment.

#### Eligibility
- Equipment must have a required-on-site date.
- PO status must be in a policy-defined set of active / procured statuses; exclude DRAFT and CANCELLED by default.
- PO must contain the equipment via a canonical line item.
- PO must have a commitment version.
- If delivery for that equipment has already been recorded complete, suppress.
- If required-on-site date is missing, NOT_EVALUABLE and no finding.
- If no current commitment exists, no threat finding; do not substitute the PO issue date or milestone plan date.

#### Calculation
`latest_committed_delivery_date > required_on_site_date`.

Equality is not a threat because the supplier commitment is on the required date.

A commitment may be later than the required-on-site date even if it is later revised. Every occurrence records which version was current at that run. A later version that moves earlier can resolve the finding.

#### Split procurement semantics
Equipment may be included in multiple POs:
- Evaluate each `equipment_id + purchase_order_id` relationship independently.
- Do not choose the earliest, latest, or “best” supplier without a policy definition.
- A completed delivery on one PO must not suppress a threatening second PO relationship unless the equipment-level quantity/coverage model can prove the full required quantity is satisfied. The current schema does not support a reliable aggregate quantity balance; therefore suppress only when the specific PO relationship's delivery is complete.
- The result must say that this PO's commitment is later than the equipment required date, not that all procurement is late.

#### Finding content
- Subject type may be `EQUIPMENT_PURCHASE_ORDER` as a logical composite; if the existing subject enum permits only one type, use equipment as subject and include PO as a relationship evidence reference.
- Title: `Supplier commitment is later than required-on-site date`.
- Summary: `{equipment_code} is required on site by {required_date}; PO {po_number} currently commits delivery for {commitment_date}.`
- Evidence:
  1. Equipment canonical record.
  2. Project canonical record.
  3. PO item / relationship row.
  4. PO canonical record.
  5. Supplier canonical record.
  6. Latest supplier commitment version.
  7. All prior commitment versions in ascending version order, bounded and explicitly represented.
  8. Source rows for equipment, line item, and each commitment version when available.
  9. Date comparison: `committed_delivery_date > required_on_site_date`.

#### Tests
- commitment earlier than required date: no finding;
- equality: no finding;
- one day later: finding;
- latest commitment version, not earliest;
- missing required date: not evaluable;
- no PO item relationship: no finding;
- cancelled/draft PO excluded;
- delivered PO relation suppresses;
- two POs for one equipment generate pair-specific output;
- one safe PO does not erase a threatening second PO;
- revised commitment earlier resolves;
- provenance chain includes line item and version records.

### 6.5 Rule R5 — Critical equipment without a PO

**Code:** `CRITICAL_EQUIPMENT_WITHOUT_PO`  
**Subject:** Equipment  
**Priority:** 5

#### Required inputs
- Equipment identity, project, criticality, procurement status.
- All PO item relationships for the equipment.
- Parent PO statuses.
- Policy criticality and qualifying PO statuses.
- Source row for equipment and relationship source rows.

#### Eligibility
- Equipment criticality equals configured `critical_equipment_criticality` (default CRITICAL).
- Equipment is not CANCELLED or otherwise explicitly excluded by approved policy.
- No PO item links this equipment to a purchase order whose status is in `po_statuses_that_count_as_procured`.
- Do not count a DRAFT or CANCELLED purchase order as procurement coverage.
- A PO header without a line item is not coverage for a specific equipment item.
- A line item on a cancelled PO is not coverage.
- A PO with status DELIVERED is coverage.
- No equipment-specific quantity completeness judgment is made in v0.2; presence of one qualifying line item counts as “has a PO relationship”.

#### Finding content
- Title: `Critical equipment has no qualifying purchase order`.
- Summary: `Critical equipment {equipment_code} is present in project {project_code} but no qualifying purchase-order line item is recorded as of {evaluation_date}.`
- Evidence:
  1. Equipment record and criticality.
  2. Project record.
  3. All PO item relationships found (none for a true absence, but query metadata can prove absence).
  4. Any draft/cancelled PO relationships that were excluded, with the exclusion reason.
  5. Policy criticality and qualifying statuses.
  6. Equipment source row.

#### Tests
- CRITICAL with no PO: finding;
- HIGH is excluded when policy says CRITICAL only;
- CRITICAL with DRAFT PO: finding;
- CRITICAL with CANCELLED PO: finding;
- CRITICAL with ISSUED PO line: no finding;
- PO header without item line: finding;
- one equipment with two POs, one qualifying: no finding;
- equipment CANCELLED excluded;
- line items never cross workspaces or projects;
- source provenance present/absent.

---

## 7. Severity model

Severity must be explainable and policy-controlled. It must not imply a probability of supplier failure.

For v0.2:
- use a closed severity enum;
- each finding code has an explicit mapping;
- no evaluator may assign a severity from an undocumented heuristic;
- policy hash is persisted with the run;
- if product has not signed off thresholds, set the rule's severity policy to a documented fixed severity or `UNCLASSIFIED`; do not invent thresholds in code.

A future severity model can consider project criticality, number of impacted equipment items, days overdue, or contractual value. Those are not approved for this release.

Do not use monetary value as a risk score. Never use supplier name, country, historical reputation, or inferred “reliability” to set severity.

---

## 8. Persistence and database design

### 8.1 New logical tables

Use the existing SQLAlchemy / Alembic conventions and one migration owner. The following are proposed names; confirm naming and index style from current models before migration.

1. `intelligence_policies` (optional if policy remains in version-controlled config initially)
2. `intelligence_runs`
3. `intelligence_findings`
4. `intelligence_finding_occurrences`
5. `intelligence_evidence_items`

Do not create denormalized canonical procurement tables.

#### intelligence_runs

Fields:
- UUID primary key;
- workspace ID;
- run status: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`;
- started_at, completed_at;
- evaluation_date;
- policy_id, policy_version, policy_hash;
- engine_version;
- snapshot_digest;
- canonical counts (bounded JSON object or explicit columns);
- finding counts by code/severity/status;
- failure code (stable, non-sensitive);
- request / correlation ID if available;
- unique idempotency key for the run request, scoped to workspace.

Status transitions:
- PENDING -> RUNNING -> COMPLETED;
- PENDING -> FAILED;
- RUNNING -> FAILED;
- terminal states do not transition back.
No partially completed run may be treated as complete for resolution reconciliation.

#### intelligence_findings

Fields from §5.1. Add:
- `first_run_id`;
- optional `last_occurrence_id` if useful, but do not create cyclical delete constraints;
- unique `(workspace_id, finding_key)`;
- index `(workspace_id, status, severity, finding_code)`;
- index `(workspace_id, project_id, status)`.

This table represents current lifecycle state only. It is not the historical record.

#### intelligence_finding_occurrences

Fields from §5.2. Add:
- unique `(workspace_id, run_id, finding_key)`;
- FK to run and finding using workspace-safe composite keys where practical;
- index `(workspace_id, finding_id, detected_at DESC)`;
- index `(workspace_id, run_id, finding_code)`.

Occurrence data must be immutable after insert.

#### intelligence_evidence_items

Fields from §5.3. Add:
- FK to occurrence with workspace identity;
- index `(workspace_id, finding_occurrence_id, ordinal)`;
- index for evidence lookup by `entity_type, entity_id` only if query patterns require it.

Evidence item inserts are immutable. There is no general patch/delete endpoint.

### 8.2 Workspace safety

Every new model carries `workspace_id` or is reachable only through a parent with enforceable workspace identity. Prefer composite foreign keys to preserve workspace boundaries at the database layer:
- `(workspace_id, run_id)` -> intelligence_runs;
- `(workspace_id, finding_id)` -> intelligence_findings;
- `(workspace_id, occurrence_id)` -> occurrences;
- subject reference constraints where feasible.

For polymorphic evidence references, SQL cannot use one FK to several entity tables. Validate them in the service and enforce immutable evidence rows; where feasible, use separate typed nullable FK columns with a constraint that exactly one is populated. Do not accept raw polymorphic IDs from the API.

All repository functions take workspace ID as a mandatory first-class argument. Never load by UUID alone and check workspace ownership afterward.

### 8.3 Deletion and retention

No delete operation in v0.2. Do not cascade-delete finding history when canonical data changes. Canonical records themselves are not deleted in the current domain, so evidence references should remain resolvable. If retention requirements emerge, define a separate retention policy with audit approval.

### 8.4 Migration safety

- One migration owner.
- Migration reviewed by hand.
- Additive migration only.
- No destructive changes to canonical tables.
- Constraints and indexes tested against PostgreSQL 16.
- Migration must run from an empty database and upgrade from the current main migration head.
- Downgrade behavior documented. If dropping history tables would lose audit evidence, downgrade may be intentionally unsupported and must be called out; follow project migration convention.
- Alembic single-head check must pass.

---

## 9. Reconciliation and lifecycle semantics

### 9.1 Complete-run-only reconciliation

A run is authoritative for resolving current findings only when:
- snapshot build completed;
- all enabled rules completed successfully;
- every occurrence and evidence row is persisted;
- counts and digest are finalized;
- run status transitions to COMPLETED in the same transaction as lifecycle reconciliation.

If a run fails midway:
- mark FAILED;
- do not resolve any existing finding;
- do not publish partial findings as active;
- retain diagnostic metadata only (no sensitive payload).

### 9.2 Reconciliation algorithm

Within one transaction, lock the workspace's relevant finding set (or use a safe advisory lock keyed by workspace + engine/policy scope), then:

1. Upsert current finding identities by `(workspace_id, finding_key)`.
2. Insert immutable occurrence rows for every finding emitted by this run.
3. Insert evidence rows in deterministic ordinal order.
4. Mark findings detected in this run as ACTIVE, update last-detected/run metadata.
5. For findings previously ACTIVE but not emitted in this **complete** run, mark RESOLVED with resolved_at from the service clock.
6. Do not change RESOLVED findings unless the same identity reappears; if it reappears, set ACTIVE, preserve first_detected_at, clear resolved_at, and append a new occurrence.
7. Commit run completion, occurrences, evidence, and reconciliation atomically.

A run that changes policy or rule semantics can create a new identity namespace if required. Do not silently resolve all findings when a policy file is edited.

### 9.3 Repeat-run idempotency

Define run idempotency at API contract level:
- same workspace + client idempotency key returns the same run record and no duplicate occurrences;
- same snapshot digest + evaluation date + policy version + engine version may be deduplicated only if the product owner wants “reuse identical run”; otherwise create a new run but guarantee no duplicate occurrence within that run;
- record which semantics are chosen in docs and tests.

Recommended v0.2 behavior:
- require an idempotency key for client-triggered run creation;
- one key maps to exactly one run;
- repeated request returns that run's current status/result;
- unique DB constraint prevents duplicate key races.

---

## 10. Service and module architecture

### 10.1 Proposed application structure

Adapt to existing module naming conventions; do not blindly create directories before inspecting actual patterns.

```text
services/api/app/
  intelligence/
    __init__.py
    contracts.py             # immutable snapshot DTOs, rule results, enums
    snapshot.py              # canonical snapshot construction contract (or keep DB adapter in services)
    canonicalization.py      # canonical JSON + snapshot digest
    policy.py                # validated immutable policy model/loader
    registry.py              # explicit rule registry and engine version
    rules/
      __init__.py
      overdue_delivery.py
      missing_acknowledgement.py
      milestone_slippage.py
      commitment_threat.py
      critical_equipment_without_po.py
    evaluation.py            # pure orchestration; no DB
    evidence.py              # deterministic evidence construction helpers
  models/
    intelligence.py          # new tables, if current model grouping allows
  schemas/
    intelligence.py          # Pydantic API contracts
  repositories/
    intelligence_repository.py
    intelligence_snapshot_repository.py
  services/
    intelligence_service.py  # transaction + run lifecycle/reconciliation
  api/v1/endpoints/
    intelligence.py          # thin API adapter
```

Potential simplification: keep pure rule code under `app/services/intelligence/` if that better fits existing repository conventions. The essential property is that pure evaluators have no SQLAlchemy/FastAPI imports.

### 10.2 Dependency direction

```text
API endpoint
    -> request/response schema
    -> IntelligenceService (transaction orchestration)
         -> snapshot repository (workspace-scoped SQL)
         -> policy loader (validated immutable policy)
         -> pure EvaluationEngine
         -> intelligence repository (persist findings and evidence)
    -> response schema
```

The pure engine imports only:
- standard library types and deterministic helpers;
- typed DTOs;
- policy models;
- rule implementations.

It must not import:
- FastAPI;
- SQLAlchemy;
- HTTP clients;
- file readers;
- database sessions;
- logging configuration;
- environment settings;
- LLM clients.

### 10.3 Transaction strategy

Do not hold a long-running DB transaction while doing CPU-heavy work if snapshot data can safely be captured and materialized first.

Recommended two-transaction strategy:
1. Snapshot transaction at REPEATABLE READ: select canonical facts and source pointers, build the immutable DTO payload, calculate digest, close transaction.
2. Pure evaluation: calculate result only from DTOs.
3. Persistence/reconciliation transaction: acquire workspace run lock; verify snapshot digest and run idempotency; persist run + findings + evidence + reconciliation atomically.

Important concurrency question: canonical facts may change between snapshot capture and result persistence. This does not make the result incorrect: it is explicitly a finding against snapshot digest X. It does mean a run may finish after newer facts are committed. Expose snapshot timestamp/digest and provide a later run. Do not relabel it “current” without a newer evaluation.

If strict “latest facts at publish” semantics are later required, implement an optimistic verification:
- recalculate the relevant canonical digest before publish;
- if it differs, mark run STALE or retry evaluation;
- never merge facts from two snapshots.

For v0.2, accept snapshot-based results and clearly expose `snapshot_created_at`, `snapshot_digest`, and `completed_at`. A complete run is complete for its snapshot, not necessarily the newest database state at read time.

### 10.4 API request execution

The first release can remain synchronous only if benchmarks show the full supported workspace fits the defined request budget. Otherwise return an accepted run with an explicit pending status and require a worker. Do not add an in-process background task as a substitute for a durable worker.

Since the architecture explicitly defers queues, avoid adding a queue. Establish measured bounds first. The API can initially perform one bounded run synchronously and protect admission with the existing one-process model, but this must not be represented as horizontally scalable. If it requires durable async execution, pause and propose a worker/job architecture as a separate design decision.

---

## 11. API contract proposal

All routes remain under `/api/v1/workspaces/{workspace_id}`. Keep the existing error envelope and request conventions.

### 11.1 Create evaluation run

`POST {ws}/intelligence/runs`

Headers:
- `Idempotency-Key: <opaque client-generated value>`

Request:
```json
{
  "policy_id": "procurement-default",
  "policy_version": "1",
  "evaluation_date": "2026-11-20"
}
```

Rules:
- If `evaluation_date` is omitted, derive it exactly once from the configured clock and policy timezone before creating the run, then persist it.
- For v0.2, require complete rule-set execution. Selective rule execution must not resolve findings from rules not executed.
- Policy version must be an immutable known version.
- Reject unsupported policy/version/rule codes.
- Idempotency key required, bounded length, no secrets in logs.
- Do not accept a workspace ID in body.
- Do not accept custom severity thresholds in the request.

Response (synchronous target):
```json
{
  "run_id": "uuid",
  "status": "COMPLETED",
  "evaluation_date": "2026-11-20",
  "snapshot_created_at": "2026-11-20T08:00:00Z",
  "snapshot_digest": "sha256:...",
  "engine_version": "0.2.0",
  "policy_id": "procurement-default",
  "policy_version": "1",
  "counts": {
    "total": 7,
    "by_code": {
      "OVERDUE_DELIVERY": 1,
      "MISSING_SUPPLIER_ACKNOWLEDGEMENT": 1,
      "MILESTONE_SLIPPAGE": 2,
      "COMMITMENT_THREATENS_REQUIRED_ON_SITE": 1,
      "CRITICAL_EQUIPMENT_WITHOUT_PO": 2
    },
    "by_severity": {"UNCLASSIFIED": 7}
  },
  "created_at": "2026-11-20T08:00:00Z",
  "completed_at": "2026-11-20T08:00:01Z",
  "replayed": false
}
```

The example counts are illustrative only and must not be used as fixtures or hard-coded outputs.

### 11.2 List runs

`GET {ws}/intelligence/runs?limit=50&offset=0`

- workspace-scoped;
- newest first by `started_at DESC, id DESC`;
- stable pagination;
- include status, evaluation date, policy/engine version, digest, counts, times;
- do not include source values.

### 11.3 Get run

`GET {ws}/intelligence/runs/{run_id}`

Return run metadata and counts. Do not make this a second route for raw snapshot payloads.

### 11.4 List findings

`GET {ws}/intelligence/findings`

Optional filters:
- `status` (default ACTIVE);
- `severity`;
- `finding_code`;
- `project_id`;
- `supplier_id` only if resolved through relationships in a scoped query;
- `run_id` for historical occurrences, not current findings;
- `limit`, `offset`.

Ordering:
1. severity rank from explicit closed mapping;
2. finding code;
3. project code;
4. subject natural key;
5. finding key.

No SQL/database default order is relied upon.

### 11.5 Get finding detail

`GET {ws}/intelligence/findings/{finding_id}`

Return:
- current finding state;
- summary and deterministic rule explanation;
- first/last detected timestamps;
- last run;
- current latest occurrence summary;
- evidence list with stable ordinal;
- canonical entity links/IDs suitable for existing detail endpoints;
- provenance metadata;
- policy and engine version.

Do not return unrestricted raw source row contents.

### 11.6 Finding history

`GET {ws}/intelligence/findings/{finding_id}/occurrences?limit=50&offset=0`

Return immutable historical occurrences newest first with run, digest, policy, engine, detected values, and evidence count.

### 11.7 API error cases

Use current error envelope and stable codes. Proposed additions:
- `INTELLIGENCE_POLICY_NOT_FOUND`
- `INTELLIGENCE_POLICY_INVALID`
- `INTELLIGENCE_RUN_CONFLICT`
- `INTELLIGENCE_RUN_NOT_FOUND`
- `INTELLIGENCE_RUN_FAILED`
- `INTELLIGENCE_CAPACITY_EXCEEDED`
- `INTELLIGENCE_SNAPSHOT_INVALID`
- `INTELLIGENCE_EVALUATION_FAILED`

Do not expose a traceback, table name, SQL statement, policy file path, raw snapshot data, or submitted idempotency key.

### 11.8 OpenAPI

Every route and schema change must update generated `docs/engineering/openapi.json` using the project's existing export/check process. The snapshot check must fail when stale.

---

## 12. Evidence lineage and explainability

This is the most important product quality attribute after correctness.

### 12.1 Every finding must answer five questions

1. **What was detected?** Finding code and deterministic summary.
2. **Which entity is affected?** Canonical project, PO, equipment, milestone, supplier.
3. **Which facts caused it?** Exact canonical values and version IDs.
4. **Where did those facts come from?** Ingestion batch, source filename, source row, or manual API operation metadata where available.
5. **What rule made the comparison?** Rule version, policy version, operator, threshold, evaluation date.

### 12.2 Evidence graph example — commitment threat

```text
Equipment E-104
  | required_on_site_date = 2026-12-10
  | criticality = CRITICAL
  | source -> equipment.csv row 8
  |
  +-- PurchaseOrderItem (relationship)
  |     | purchase_order_id = PO-301
  |     | equipment_id = E-104
  |     | source -> po_lines.csv row 14
  |
  +-- PurchaseOrder PO-301
        | status = IN_PRODUCTION
        | supplier = Supplier S-08
        |
        +-- SupplierCommitmentVersion v1
        |     | committed_delivery_date = 2026-12-01
        |
        +-- SupplierCommitmentVersion v2 (current)
              | committed_delivery_date = 2026-12-18
              | source -> commitments.xlsx / Commitments / row 6

Rule comparison:
  2026-12-18 > 2026-12-10
  RESULT = TRUE
  POLICY = procurement-default@1
  ENGINE = 0.2.0
```

The dates and IDs above are illustrative, not repository data.

### 12.3 Provenance gaps

A canonical row may have no ingestion row (manual API write or legacy/demo seed). Do not fabricate a source file/row. Evidence must say `SOURCE_NOT_RECORDED` or omit source evidence with an explicit provenance status. This does not invalidate the finding.

### 12.4 Evidence display limits

- Evidence ordinal is stable and intentional.
- Each finding type has a documented evidence template.
- Limit version history returned per request via pagination or a deterministic cap.
- The occurrence stores complete rule-relevant evidence references, not necessarily every unrelated historical row.
- If evidence is truncated in a response, expose `evidence_truncated=true`, total count, and pagination cursor/offset.
- Evidence values are typed and bounded.
- Do not store the full canonical snapshot in every evidence item.

---

## 13. Observability and operational behavior

### 13.1 Structured logs

Log:
- request ID / correlation ID;
- workspace ID (or a non-reversible operational token if policy requires);
- run ID;
- rule code;
- counts;
- elapsed time per stage;
- snapshot entity counts;
- policy and engine version;
- result status and stable error code.

Never log:
- uploaded row payloads;
- source file bytes;
- supplier private notes;
- credentials;
- full policy secrets (policy should not contain secrets);
- SQL parameters;
- raw idempotency keys.

### 13.2 Metrics

Minimum metrics:
- `intelligence_run_total{status}`
- `intelligence_run_duration_seconds`
- `intelligence_snapshot_duration_seconds`
- `intelligence_evaluation_duration_seconds`
- `intelligence_persistence_duration_seconds`
- `intelligence_findings_total{finding_code,severity}`
- `intelligence_active_findings`
- `intelligence_run_failures_total{failure_code}`
- `intelligence_snapshot_entity_count{entity_type}`

Keep metric labels bounded. Do not put workspace ID, PO number, equipment code, supplier name, or finding key into labels.

### 13.3 Health and readiness

Do not make `/health/live` depend on intelligence. Readiness may verify migration head and required configuration, but must not perform a full evaluation. An invalid policy configuration should make intelligence run creation fail closed with a stable error; it need not crash the entire canonical-data API unless the policy is required at startup by product decision.

### 13.4 Capacity

Benchmark before enabling. Establish:
- maximum supported equipment count;
- maximum PO count;
- maximum PO item count;
- maximum milestone count;
- maximum version-history count;
- peak memory;
- total run time;
- snapshot query count;
- query plans and index behavior.

If run duration or memory exceeds the agreed synchronous budget, do not simply increase API timeout. Revisit a durable worker design as a separate architecture proposal.

---

## 14. Security and trust boundaries

The current repository is explicitly a loopback local prototype with no authentication. Intelligence APIs inherit that restriction.

Requirements:
- No public exposure.
- No change to workspace security assumptions.
- Mandatory workspace-scoped read and write queries.
- No caller-controlled subject/evidence references.
- No arbitrary rule execution.
- No dynamic expression evaluation.
- No SQL generated from caller input.
- No external outbound network calls.
- No untrusted source values rendered as HTML.
- Strict output length bounds.
- Stable error envelope with no sensitive internals.
- Append-only findings evidence and run history.
- Avoid leaking cross-workspace entity existence. A foreign workspace ID must appear not found, not forbidden.
- If the system later becomes multi-user, authorization must be enforced before any read of run/finding/evidence data.
- Do not claim audit-grade tamper-proofing solely because rows are append-only; PostgreSQL administrators can still alter data. Cryptographic audit chains are a separate future design.

---

## 15. Testing strategy

Testing must prove both that correct findings appear and that they disappear, remain stable, and carry the right evidence when inputs change.

### 15.1 Unit tests — pure rules

One test module per rule plus shared evaluator contract tests:
- deterministic output;
- exact boundary arithmetic;
- missing-field outcomes;
- excluded states;
- latest-version selection;
- evidence ordinal;
- stable finding key;
- same snapshot same outputs;
- no hidden clock calls;
- no floating point;
- policy validation and immutability.

Rule tests use typed DTO fixtures, not ORM objects or DB sessions.

### 15.2 Snapshot tests

- repeatable-read snapshot consistency under concurrent canonical updates;
- latest-version query determinism;
- all source rows are workspace-scoped;
- stable snapshot serialization/digest across insertion order changes;
- digest changes when any relevant fact/version changes;
- irrelevant fields do not change digest unless deliberately included;
- Decimal/date/UTC/null serialization canonicalization;
- empty workspace;
- very large but supported workspace pagination;
- query count bounded and no N+1 regressions.

### 15.3 Repository/database tests

Against PostgreSQL 16:
- composite workspace constraints;
- unique finding identity per workspace;
- occurrence uniqueness per run/key;
- evidence ordinal uniqueness;
- terminal run status transitions enforced by service;
- immutable occurrence/evidence behavior enforced by service and optionally DB trigger only if project convention allows;
- migration from empty DB and current migration head;
- indexes support list/detail queries.

### 15.4 Service integration tests

- successful run persists run, findings, occurrences, evidence atomically;
- injected failure after each persistence stage leaves no COMPLETED run;
- failed run does not resolve prior findings;
- complete empty result resolves prior active finding;
- partial rules cannot resolve rules they did not run (prefer disallowing partial runs);
- reappearing finding becomes ACTIVE and preserves first_detected_at;
- new commitment resolves old overdue/threat finding where appropriate;
- historical occurrences remain unchanged;
- same idempotency key replays;
- concurrent same key produces one run;
- concurrent distinct runs serialize reconciliation safely;
- run against snapshot A can complete after canonical state changes to B and accurately records A's digest;
- snapshot stale semantics are exposed correctly.

### 15.5 API tests

- route response schemas;
- pagination and stable ordering;
- filters;
- error envelope;
- idempotency header;
- missing/invalid policy;
- not found across workspace boundary;
- no raw source row payload;
- OpenAPI examples;
- read-only behavior (no canonical row count/value changes after evaluation).

### 15.6 End-to-end tests

Extend the synthetic demo dataset or a dedicated intelligence fixture with controlled facts for all five rule types. The expected findings must be hand-authored and reviewed.

E2E proof:
1. Start PostgreSQL and migrate.
2. Import canonical synthetic data through existing ingestion services/API.
3. Verify World State counts and hash.
4. Run intelligence.
5. Assert exact finding keys/codes/severity/status/counts.
6. Resolve each finding by changing canonical input through documented domain operations/new appended versions; rerun.
7. Verify old occurrences and evidence remain unchanged.
8. Verify canonical World State hash is unchanged by intelligence writes.
9. Restart API and PostgreSQL.
10. Re-read findings and occurrences; verify persistence and stable ordering.
11. Repeat the same idempotency key; verify replay with no duplicate rows.

### 15.7 Defect detection / mutation testing

Add targeted mutations for:
- using earliest instead of latest commitment version;
- using earliest instead of latest milestone plan version;
- changing strict `>` to `>=`;
- changing `<` to `<=`;
- ignoring grace days;
- treating missing dates as today;
- treating DRAFT PO as coverage;
- counting CANCELLED PO as coverage;
- counting a PO header without a line item;
- ignoring split procurement identity;
- treating one safe PO as clearing a second threatening PO;
- using an unapproved PO status as acknowledgement;
- suppressing finding on incomplete run;
- resolving findings on failed run;
- cross-workspace evidence lookup;
- omitting source line item in evidence;
- omitting commitment version ID;
- non-deterministic evidence ordering;
- resolving findings not evaluated in a partial run;
- using mutable policy in historical occurrence;
- allowing duplicate run idempotency keys;
- persisting occurrence without evidence;
- marking run complete before reconciliation commits.

Every mutation must be detected by its targeted test. Add baseline consistency checks and source restoration verification, following the existing 43-case defect harness conventions.

### 15.8 Required verification commands

At minimum, run and report:

```bash
make lint
make format-check
make typecheck
make test-unit
make test-api
make test-integration
make openapi-check
make verify
make e2e
```

Run defect detection on a clean working tree. If an additional command is introduced, document it in `make help` and CI as appropriate.

---

## 16. Performance acceptance

No performance claim is allowed before measurement.

Benchmark at least:
- current demo dataset;
- 10x demo scale;
- a representative medium workspace agreed by the lead;
- a maximum-supported synthetic dataset based on explicit count limits.

Record:
- DB version and hardware;
- entity counts by family;
- history version counts;
- snapshot build time;
- each rule's evaluation time;
- persistence/reconciliation time;
- total wall-clock time;
- peak RSS;
- SQL query count;
- slowest query plans;
- index use;
- API response bytes.

Acceptance targets must be agreed after first measurements. A useful starting objective is:
- demo dataset p95 under 1 second end-to-end on developer hardware;
- representative workspace p95 under 5 seconds;
- no N+1 queries;
- memory growth approximately linear with input size;
- query count bounded by entity families rather than entity count.

These are proposed targets, not claims about current performance. If the first benchmark shows these are unrealistic, update the targets with measured evidence before release, not by hiding benchmark cases.

---

## 17. Implementation workstreams and task cards

Do not delegate an unbounded task such as “build intelligence”. Split work into narrow, reviewable task cards. The lead owns shared contracts and migrations.

### Workstream A — Contract and domain review

**A-01: Verify canonical input contract**
- Objective: Compare this spec to merged ORM models, World State DTOs, and current provenance schema.
- Allowed: docs and inspection only.
- Forbidden: production code/migration.
- Output: field mapping table, discrepancies, updated spec.
- Acceptance: every required field and source pointer has a precise existing location or an approved gap.

**A-02: Approve policy semantics**
- Objective: Decide acknowledgement due days, expected statuses, timezone, severity mapping, grace periods.
- Output: signed policy v1 document.
- Acceptance: all rule thresholds have explicit values, no unresolved “candidate” behavior.

**A-03: Approve finding contract**
- Objective: Finalize finding identity, subject model, evidence enum, lifecycle, run semantics.
- Output: contract section frozen.
- Acceptance: API, DB, and evaluator contracts agree.

### Workstream B — Snapshot and deterministic core

**B-01: Snapshot DTO contracts**
- Objective: Define immutable pure DTOs for canonical facts and source pointers.
- Context: domain model, World State contract.
- Allowed: `services/api/app/intelligence/contracts.py`, unit tests.
- Forbidden: ORM models, migrations, endpoints.
- Required tests: validation, immutability, workspace identity, required/nullable field semantics.
- Acceptance: rule layer imports no DB or API module.

**B-02: Snapshot digest**
- Objective: Implement canonical serializer and SHA-256 digest.
- Allowed: canonicalization module and unit tests.
- Required tests: stable across insertion order, changed on input mutation, canonical date/UUID/Decimal/UTC/null handling.
- Acceptance: test vectors checked into repository.

**B-03: Snapshot repository**
- Objective: Read required canonical entities and history in one consistent workspace snapshot.
- Allowed: snapshot repository + repository tests.
- Forbidden: evaluator logic, API, schema changes.
- Acceptance: repeatable-read proof, scoped queries, bounded query count, no N+1.

**B-04: Policy loader**
- Objective: Load and validate immutable policy versions.
- Allowed: policy module and fixtures.
- Acceptance: unknown keys and invalid threshold fail closed; version hash stable.

### Workstream C — Rules

**C-01: Overdue delivery**
- Implement R1 exactly.
- Required: unit tests, evidence, mutation case.
- Depends on A-02/A-03/B-01/B-04.

**C-02: Missing acknowledgement**
- Implement R2, but remain disabled until policy approval.
- Required: all boundary tests and ambiguity tests.
- Depends on A-02/A-03/B-01/B-04.

**C-03: Milestone slippage**
- Implement R3.
- Required: plan-version and actual-date cases.
- Depends on A-03/B-01/B-04.

**C-04: Commitment threat**
- Implement R4.
- Required: split procurement pair identity and evidence lineage.
- Depends on A-03/B-01/B-04.

**C-05: Critical equipment without PO**
- Implement R5.
- Required: PO header vs item line, status exclusions.
- Depends on A-02/A-03/B-01/B-04.

**C-06: Rule engine composition**
- Objective: Run enabled pure rules over one snapshot and produce deterministically ordered results.
- Forbidden: DB persistence, API.
- Acceptance: output golden files for demo scenario, no clock/SQL/HTTP imports.

### Workstream D — Persistence and service orchestration

**D-01: Database model and migration**
- Owner: designated migration owner only.
- Tables: runs, current findings, occurrences, evidence, policy if approved.
- Acceptance: composite workspace constraints, unique constraints, indexes, empty DB upgrade, current-head upgrade, hand-reviewed migration.

**D-02: Intelligence repositories**
- Objective: scoped persistence and retrieval only.
- Acceptance: no commits, no policy logic, all queries workspace-scoped.

**D-03: Run lifecycle and reconciliation**
- Objective: orchestrate snapshot, pure engine, persistence, idempotency, lifecycle.
- Acceptance: atomic complete run; failed run cannot resolve findings; repeated key replays.

**D-04: Evidence validation**
- Objective: validate each evidence reference belongs to the same workspace and relationship chain.
- Acceptance: foreign-workspace / mismatched-type / mismatched-parent evidence rejected.

### Workstream E — API and documentation

**E-01: Pydantic contracts**
- Typed request/response schema, no ORM leakage.
- Acceptance: bounded output, strict enum, explicit nullable behavior.

**E-02: Intelligence routes**
- Thin endpoint adapters following current router and dependency pattern.
- Acceptance: endpoints perform no SQL or business calculation.

**E-03: OpenAPI and API docs**
- Export OpenAPI and document routes, errors, pagination, idempotency.
- Acceptance: `make openapi-check` passes.

**E-04: Architecture docs**
- Update system boundaries, domain model (intelligence tables only), World State boundaries, known limitations, test strategy, implementation log.
- Acceptance: no contradictions with frozen v0.1 contracts.

### Workstream F — Verification and release

**F-01: Synthetic intelligence fixture**
- Add controlled fixtures to exercise all rule codes and edge cases.
- Acceptance: expected findings reviewed and hand-authored.

**F-02: E2E and restart proof**
- Run import -> World State -> intelligence -> resolution -> restart -> replay.
- Acceptance: evidence and artifact report committed.

**F-03: Mutation suite**
- Add required deliberate defect cases and restoration checks.
- Acceptance: every mutation detected.

**F-04: Performance report**
- Benchmark representative workspaces.
- Acceptance: measured results, explicit supported size envelope.

**F-05: Independent review**
- Review design, code, migration, evidence, test quality, and security boundaries.
- Reviewer must not be the primary author of the implementation.
- Acceptance: review comments resolved/accepted.

**F-06: Release gate**
- All gates in §19 signed off.
- No automatic deploy.

---

## 18. Suggested milestone sequence

This is a dependency sequence, not a promise of calendar duration.

| Milestone | Deliverable | Exit condition |
|---|---|---|
| M0 — Entry gate | PR #28 reviewed, merged, CI green | Baseline accepted |
| M1 — Domain freeze | Field mapping, policy decisions, finding/evidence contracts | No unresolved semantic ambiguity |
| M2 — Pure core | DTOs, digest, policy, five rules, engine | Unit + mutation tests pass |
| M3 — Snapshot persistence | Snapshot repository + DB models/migration | PostgreSQL integration tests pass |
| M4 — Run lifecycle | Idempotent runs, occurrences, evidence, reconciliation | Atomicity/concurrency tests pass |
| M5 — API surface | Run/list/detail/history routes + OpenAPI | API contract and workspace tests pass |
| M6 — System proof | E2E, restart, benchmark, defect report | Full evidence packet complete |
| M7 — Independent review | Independent review + remediation | No open blocking comments |
| M8 — Release gate | Operational decision | Lead sign-off; local-only remains default |

Recommended implementation order:
1. Freeze semantic contracts before code.
2. Build pure DTO and rules before persistence.
3. Validate results with a golden fixture before creating DB tables.
4. Add the migration and storage only after rule output is stable.
5. Add API only after service integration tests pass.
6. Benchmark and review before enabling scheduled or public use.

---

## 19. Release gates and operational decision

### 19.1 Must-pass release gates

- [ ] PR #28 merged after independent review.
- [ ] Main baseline revalidated.
- [ ] Domain and policy decisions frozen.
- [ ] All five rule contracts implemented exactly.
- [ ] All five rule suites pass.
- [ ] Snapshot consistency and digest tests pass.
- [ ] Workspace isolation tests pass for every new query.
- [ ] Persistence/reconciliation is atomic.
- [ ] Failed/partial run cannot resolve prior findings.
- [ ] Idempotency under concurrent requests verified.
- [ ] Evidence chain verified end to end.
- [ ] Canonical World State unchanged by intelligence evaluation.
- [ ] All new database migrations verified.
- [ ] OpenAPI snapshot current.
- [ ] Ruff, format, strict mypy pass.
- [ ] Unit/API/integration/E2E tests pass.
- [ ] Mutation cases all detected.
- [ ] Performance benchmark report published.
- [ ] Independent code/security review complete.
- [ ] Known limitations updated.
- [ ] No public upload or public deployment introduced by this phase.

### 19.2 Operational boundaries

Until authentication, workspace authorization, and upload isolation are separately approved:
- remain loopback-only;
- do not deploy to a public host;
- do not accept untrusted workbook uploads;
- do not enable multiple API workers relying on process-local import admission;
- do not claim distributed capacity;
- do not run scheduled evaluations from an untrusted network entry point.

Intelligence is read-only, but read-only does not mean risk-free: it can disclose procurement schedules, supplier relationships, delivery dates, and project equipment requirements. Treat it as sensitive operational data.

### 19.3 Release artifacts

The release PR should include:
- implementation summary;
- architecture and contract changes;
- migration review note;
- exact verification commands and outputs;
- e2e evidence;
- mutation report;
- performance benchmark report;
- reviewer identity and review outcome;
- known limitations;
- explicit statement that no agents or external actions were introduced.

---

## 20. Future phase boundary: agent reasoning and controlled action

Only after v0.2 findings are proven correct should a future phase consider agents.

Proposed future interaction:

```text
Canonical World State
       |
       v
Deterministic Procurement Intelligence
       |
       v
Evidence-backed Findings
       |
       v
Agent Interpretation (read-only)
       |
       v
Proposed Options + Rationale
       |
       v
Deterministic Policy / Safety Check
       |
       v
Human Approval
       |
       v
Execution Adapter (future)
       |
       v
Outcome Observation + Audit
```

Future agents may:
- summarize a set of findings;
- explain evidence in natural language;
- compare possible responses;
- draft a supplier follow-up for a human to review;
- identify what additional data is needed.

Future agents may not:
- originate dates, thresholds, statuses, or provenance;
- change the finding code or severity;
- overwrite canonical values;
- resolve findings based on conversational claims;
- send a supplier message;
- modify a PO, commitment, milestone, or equipment record;
- bypass policy or human approval.

Any later agent must consume a typed, immutable `FindingContext` generated by this engine, not free-form raw database dumps.

---

## 21. Open decisions requiring explicit lead approval

The following are intentionally unresolved; implementation must not silently choose values.

| ID | Decision | Recommended default | Required approver |
|---|---|---|---|
| D-01 | Acknowledgement due days after issue | 5 calendar days as initial proposal | Product lead |
| D-02 | Which PO statuses prove acknowledgement | Explicit milestone completion or PO status ACKNOWLEDGED; consider later states only by policy | Product lead |
| D-03 | Weekends/holidays in acknowledgement deadline | Calendar days, no holiday calendar in v0.2 | Product lead |
| D-04 | Delivery overdue grace | 0 days initially, policy-controlled | Product lead |
| D-05 | Milestone slippage grace | 0 days initially, policy-controlled | Product lead |
| D-06 | Severity thresholds for overdue days | Keep UNCLASSIFIED until approved | Product lead |
| D-07 | Is “delivery completed” established by milestone actual only, PO DELIVERED status, or either? | Milestone completion is strongest evidence; status suppresses only if explicitly policy-approved | Product lead |
| D-08 | Whether a PO in PARTIALLY_DELIVERED counts as open delivery | Yes, for remaining delivery obligation, but schema may not model residual quantity | Product lead |
| D-09 | Policy storage | Version-controlled typed config for v0.2; DB policy registry later if needed | Lead engineer |
| D-10 | Run sync vs durable async | Synchronous only after benchmarks fit budget | Lead engineer |
| D-11 | Finding subject for commitment threat | Equipment subject + PO relationship evidence | Lead engineer |
| D-12 | Reappearing resolved finding lifecycle | Reactivate same finding key, preserve first detected time | Product lead |
| D-13 | Same snapshot duplicate run behavior | Require idempotency key; allow separate explicit runs | Lead engineer |
| D-14 | Evidence version history cap | Store rule-relevant versions; paginate API history | Lead engineer |
| D-15 | Severity enum includes UNCLASSIFIED | Yes until rule thresholds approved | Product lead |

---

## 22. Definition of done

Procurement Intelligence Engine v0.2 is complete only when:

1. It evaluates one consistent canonical workspace snapshot.
2. All five rule codes are deterministic and policy-versioned.
3. Each emitted finding is backed by typed evidence and source-row lineage wherever available.
4. Missing or ambiguous facts do not become invented facts.
5. Findings are persisted separately from canonical procurement records.
6. Current finding state and immutable run occurrences are both available.
7. Complete-run-only reconciliation is atomic and idempotent.
8. Failed runs cannot resolve findings.
9. Historical occurrences remain reproducible and immutable.
10. Every endpoint is workspace-scoped and returns bounded, typed data.
11. Existing World State responses and hashes remain unaffected by intelligence writes.
12. Tests detect deliberate removals and incorrect comparison operators.
13. Performance is measured with declared input limits.
14. Independent review is complete.
15. All release gates are signed off.
16. The system remains local/operator-only under current security constraints.

---

## 23. First implementation task

When the entry gate is satisfied, start with **A-01: Verify canonical input contract**, not with implementing rule code.

The first engineering PR after PR #28 should contain only:
- this plan reconciled against the merged source;
- a field/source mapping appendix;
- the signed policy decisions;
- a frozen finding/evidence contract;
- task breakdown and dependency links.

It should not include rules, migrations, endpoints, or agent code. This keeps the semantic contract reviewable before the code creates irreversible compatibility commitments.

**Final engineering instruction:** build a trustworthy deterministic observation layer first. Do not optimize for the appearance of intelligence. Correctness, reproducibility, provenance, workspace isolation, and explicit uncertainty are the product.
