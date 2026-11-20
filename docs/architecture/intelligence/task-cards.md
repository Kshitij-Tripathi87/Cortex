# Task breakdown and dependencies

Status: **PROPOSED** with the contract. The cards restate plan §17 against
the layout of this repository and add what a card needs by `AGENTS.md`:
allowed and forbidden files, required tests, acceptance.

**Naming.** The plan uses `D-01` to `D-15` for decisions (§21) and `D-01` to
`D-04` for the tasks of workstream D. To keep the two apart, a task is written
with a leading `T-` here and in the other documents of this folder: the
plan's task `D-01` is `T-D-01`. A bare `D-nn` is always a decision.

**Gate.** Only `T-A-01` to `T-A-03` may be worked on before the entry gate of
the plan (§0.2) has passed, and they produce documents only. Every other card
is `BLOCKED` until then (`entry-gate.md`).

## What every card inherits

- The rules and invariants of `AGENTS.md`; the contracts of this folder; the
  plan where the contract is silent.
- No change to a canonical table, a canonical schema or the World State.
- No new dependency without the stated need and the lockfile in the same
  commit. No LLM, agent, queue, cache or second ORM.
- Tests are written against the contract, on PostgreSQL where a database is
  involved, with fixed dates and a pinned clock. No test is weakened to make
  a check pass.
- Before hand-over: `make lint format-check typecheck test-unit test-api
  test-integration openapi-check verify`, the exact results, the files
  changed, the limitations known.

## Order

```text
M1  T-A-01 ─▶ T-A-02 ─▶ T-A-03                       documents only; this pull request
                          │
          ┌───────────────┼──────────────────┐
M2        ▼               ▼                  ▼
       T-B-01          T-B-04             T-F-01      expected findings, written by hand
          │               │                  │        before a rule exists
          ▼               │                  │
       T-B-02             │                  │
          │               │                  │
          └──────┬────────┘                  │
                 ▼                           │
       T-C-01 … T-C-05  (independent of each other)
                 │                           │
                 └────────────┬──────────────┘
                              ▼
                           T-C-06                     engine; golden result of the fixture
                              │
M3        ┌───────────────────┤
          ▼                   ▼
       T-B-03              T-D-01                     snapshot queries; tables and migration
          │                   │
M4        │                   ▼
          │                T-D-02
          │                   │
          └────────┬──────────┘
                   ▼
           T-D-03 + T-D-04                            run lifecycle, reconciliation, evidence checks
                   │
M5                 ▼
       T-E-01 ─▶ T-E-02 ─▶ T-E-03
                              │
M6        ┌──────────┬────────┼─────────┐
          ▼          ▼        ▼         ▼
       T-F-02     T-F-03   T-F-04    T-E-04           proof, deliberate defects, benchmark, documents
          └──────────┴────────┴─────────┘
                              ▼
M7                         T-F-05                     independent review
                              ▼
M8                         T-F-06                     release gate
```

| Task | Depends on | Milestone | Status |
|---|---|---|---|
| T-A-01 Canonical input mapping | — | M1 | Done, awaiting sign-off (`canonical-input-mapping.md`) |
| T-A-02 Policy semantics | T-A-01 | M1 | Proposed, **not signed** (`policy-v1.md`) |
| T-A-03 Finding contract | T-A-01, T-A-02 | M1 | Proposed, **not frozen** (`finding-contract.md`) |
| T-B-01 Snapshot values | T-A-03 | M2 | BLOCKED (gate) |
| T-B-02 Snapshot digest | T-B-01 | M2 | BLOCKED |
| T-B-04 Policy loader | T-A-02 | M2 | BLOCKED |
| T-F-01 Fixture and expected findings | T-A-02, T-A-03 | M2 | BLOCKED |
| T-C-01 … T-C-05 Rules | T-A-02, T-A-03, T-B-01, T-B-04 | M2 | BLOCKED |
| T-C-06 Engine | T-C-01 … T-C-05, T-B-02, T-F-01 | M2 | BLOCKED |
| T-B-03 Snapshot repository | T-B-01, T-B-02 | M3 | BLOCKED |
| T-D-01 Tables and migration | T-A-03, T-C-06 | M3 | BLOCKED |
| T-D-02 Repositories | T-D-01 | M4 | BLOCKED |
| T-D-03 Run lifecycle | T-B-03, T-B-04, T-C-06, T-D-02 | M4 | BLOCKED |
| T-D-04 Evidence validation | T-C-06, T-D-02 | M4 | BLOCKED |
| T-E-01 API schemas | T-A-03, T-D-03 | M5 | BLOCKED |
| T-E-02 Routes | T-D-03, T-D-04, T-E-01 | M5 | BLOCKED |
| T-E-03 OpenAPI and API contract | T-E-02 | M5 | BLOCKED |
| T-E-04 Architecture documents | T-E-02 | M6 | BLOCKED |
| T-F-02 End-to-end and restart proof | T-E-02, T-F-01 | M6 | BLOCKED |
| T-F-03 Deliberate defects | T-C-06, T-D-03, T-E-02 | M6 | BLOCKED |
| T-F-04 Performance report | T-E-02 | M6 | BLOCKED |
| T-F-05 Independent review | all above | M7 | BLOCKED |
| T-F-06 Release gate | T-F-05 | M8 | BLOCKED |

## Cards

### T-A-01 Canonical input mapping

- **Objective.** Check every input of the five rules against the merged
  models, the migrated schema and the provenance columns.
- **Allowed files.** `docs/architecture/intelligence/`, the plan.
- **Forbidden.** Any code, migration, test or schema.
- **Acceptance.** Every input and every source pointer has an exact location,
  or a difference that is named and settled by a decision.
- **Output.** `canonical-input-mapping.md`.

### T-A-02 Policy semantics

- **Objective.** A value, a reason and an approver for every open decision;
  the policy document v1.
- **Allowed / forbidden.** As T-A-01.
- **Acceptance.** No threshold is left as a candidate. The sign-off block of
  `policy-v1.md` is filled in by the lead.
- **Output.** `policy-v1.md`.

### T-A-03 Finding contract

- **Objective.** Identity, subjects, rules step by step, evidence, lifecycle,
  runs, storage and API, exact enough to be tested against.
- **Allowed / forbidden.** As T-A-01.
- **Acceptance.** Rules, storage and API agree with each other and with the
  policy; the lead freezes it.
- **Output.** `finding-contract.md`.

### T-B-01 Snapshot values

- **Objective.** Immutable, typed values for the families of
  `canonical-input-mapping.md` §3, and the checks of contract §9.4.
- **Allowed files.** `services/api/app/intelligence/contracts.py`,
  `services/api/app/intelligence/__init__.py`,
  `services/api/tests/unit/intelligence/`.
- **Forbidden.** Models, migrations, repositories, services, endpoints. No
  import of SQLAlchemy, FastAPI or settings in `app/intelligence/`.
- **Required tests.** Values cannot be changed after construction; each
  invariant of §9.4 is refused; nullable fields stay `None` and are never
  defaulted; a test that fails when `app/intelligence/` imports a database or
  HTTP module.
- **Acceptance.** The package is pure, like `app/ingestion/`.

### T-B-02 Snapshot digest

- **Objective.** Canonical JSON and the digest of contract §9.3.
- **Allowed files.** `app/intelligence/canonicalization.py`, unit tests,
  checked-in test vectors.
- **Required tests.** The same snapshot built in another insertion order
  gives the same digest; a change of any field of §3 changes it; a change of
  a field that is not in §3 does not; dates, UUIDs, enumerations, `null`
  against empty text; no float is accepted.
- **Acceptance.** The vectors are in the repository and a second
  implementation could reproduce them from the contract alone.

### T-B-03 Snapshot repository

- **Objective.** Read one workspace into the snapshot values inside
  `read_snapshot`, source rows included.
- **Allowed files.** `app/repositories/intelligence_snapshot_repository.py`,
  integration tests.
- **Forbidden.** Rule logic, API, any schema change.
- **Required tests.** A commit that lands between two queries of one
  snapshot is not seen (held transaction, not timing); another workspace's
  records and source rows are never read; the number of statements does not
  grow with the number of records; current version is the greatest
  `version_no`; an empty workspace; a version whose source row belongs to
  another workspace fails the snapshot.
- **Acceptance.** Every query filters on the workspace; no query per record.

### T-B-04 Policy loader

- **Objective.** Load, validate and hash policy v1; resolve the time zone.
- **Allowed files.** `app/intelligence/policy.py`, the policy document, unit
  tests, `pyproject.toml` and `uv.lock` for `tzdata` (D-28).
- **Required tests.** Unknown key, negative days, unknown status, unknown
  time zone and a missing field are each refused; the hash is stable; a
  loaded policy cannot be changed; the evaluation date is the date in the
  policy's zone on both sides of midnight UTC.
- **Acceptance.** An invalid policy creates no run.

### T-C-01 R1 overdue delivery

- **Objective.** Contract §4.1, as a pure function.
- **Allowed files.** `app/intelligence/rules/overdue_delivery.py`,
  `app/intelligence/evidence.py`, unit tests.
- **Required tests.** Before, on and after the committed date; on and after
  the grace boundary; the latest version decides, not the first; no
  commitment; each excluded status; delivery complete with and without an
  actual date (D-16); two delivery milestones, one completed (D-17); a
  cancelled delivery milestone; evidence order; source row present and
  absent; the same input twice gives the same output.
- **Acceptance.** No clock, database or float; every test uses an explicit
  policy.

### T-C-02 R2 missing acknowledgement

- **Objective.** Contract §4.2.
- **Allowed files.** `app/intelligence/rules/missing_acknowledgement.py`,
  unit tests.
- **Required tests.** No issue date gives the diagnostic; `DRAFT`,
  `CANCELLED` and every status outside the required set give nothing; on and
  after the due date; a completed acknowledgement milestone suppresses and
  gives the contradiction diagnostic; a pending one does not suppress; a
  policy with other due days moves the boundary.
- **Acceptance.** As T-C-01. The rule is in `enabled_rules` only if D-01 is
  signed.

### T-C-03 R3 milestone slippage

- **Objective.** Contract §4.3, both variants.
- **Allowed files.** `app/intelligence/rules/milestone_slippage.py`, unit
  tests.
- **Required tests.** The latest plan decides; pending before, on and after
  the plan; completed on time, on the day and late; completed without a date
  gives the diagnostic; cancelled milestone; no plan gives the diagnostic;
  parent purchase order `DRAFT` and `CANCELLED` (D-18); earlier plans are
  evidence, oldest first; more than 50 earlier plans (D-14); one key for
  both variants.
- **Acceptance.** As T-C-01.

### T-C-04 R4 commitment threat

- **Objective.** Contract §4.4.
- **Allowed files.** `app/intelligence/rules/commitment_threat.py`, unit
  tests.
- **Required tests.** Commitment before, on and after the required date; the
  latest version decides; no required date gives the diagnostic; no line
  item; `DRAFT`, `CANCELLED` and `DELIVERED` purchase order; cancelled
  equipment; delivery complete on this purchase order suppresses, on another
  one does not; two purchase orders for one equipment give two keys; the
  line item and every commitment version are in the evidence.
- **Acceptance.** As T-C-01.

### T-C-05 R5 critical equipment without purchase order

- **Objective.** Contract §4.5.
- **Allowed files.**
  `app/intelligence/rules/critical_equipment_without_po.py`, unit tests.
- **Required tests.** `CRITICAL` without a line item; `HIGH` is not reported;
  line item on a `DRAFT` and on a `CANCELLED` purchase order; on an `ISSUED`
  and on a `DELIVERED` one; a purchase order without a line item for the
  equipment; two purchase orders, one qualifying; cancelled equipment; more
  than 20 excluded line items.
- **Acceptance.** As T-C-01.

### T-C-06 Engine

- **Objective.** Run the enabled rules over one snapshot; findings and
  diagnostics in the fixed order; the registry is a closed table in code.
- **Allowed files.** `app/intelligence/registry.py`,
  `app/intelligence/evaluation.py`, unit tests, the golden result of T-F-01.
- **Forbidden.** Database, API, dynamic import, a rule chosen by a caller.
- **Required tests.** The golden result of the fixture, byte for byte, twice;
  a rule that raises fails the evaluation and nothing is returned in part; a
  rule outside `enabled_rules` does not run.
- **Acceptance.** The result for the fixture equals the hand-written
  expectation of T-F-01.

### T-D-01 Tables and migration

- **Objective.** The five tables of contract §10 and migration `0002`.
- **Owner.** The migration owner only; reviewed by hand.
- **Allowed files.** `app/models/intelligence.py`, `app/models/__init__.py`,
  `alembic/versions/0002_*`, `tests/integration/test_migrations.py`.
- **Forbidden.** Any change to a canonical table.
- **Required tests.** Upgrade from an empty database and from revision
  `0001` with data; one head; `alembic check` clean; each unique, check and
  foreign-key constraint refuses what it should when written past the
  service; the partial unique index allows one run in progress.
- **Acceptance.** Additive only. What a downgrade loses is written in the
  migration.

### T-D-02 Repositories

- **Objective.** Scoped reads and writes of the five tables.
- **Allowed files.** `app/repositories/intelligence_repository.py`,
  integration tests.
- **Required tests.** Every function with another workspace's id finds
  nothing; list order of contract §11; pagination is stable.
- **Acceptance.** No commit, no rule, no policy in a repository.

### T-D-03 Run lifecycle

- **Objective.** Contract §8.2 and §9: register, snapshot, evaluate, publish,
  fail; idempotency; one run at a time; abandoned runs.
- **Allowed files.** `app/services/intelligence_service.py`, integration
  tests.
- **Required tests.** A failure injected after each stage leaves no
  `COMPLETED` run and no changed finding; a failed run resolves nothing; a
  complete run without findings resolves the active ones of the rules that
  ran, and only those; a finding that reappears keeps its first detection;
  earlier occurrences are byte-identical after later runs; the same key
  replays; two requests with one key at the same time give one run; a second
  run while one is in progress is refused; a slow run that was abandoned
  publishes nothing; canonical tables and the World State are identical
  before and after a run; the facts change between snapshot and publication
  and the run records the snapshot it read. Concurrency is shown with a held
  lock, as `test-strategy.md` requires.
- **Acceptance.** Publication is one transaction.

### T-D-04 Evidence validation

- **Objective.** Contract §7.5.
- **Allowed files.** `app/services/intelligence_service.py` or a module
  beside it, tests.
- **Required tests.** A reference to another workspace, of the wrong type
  and to the wrong parent each fails the run; nothing is stored in part.
- **Acceptance.** No evidence item is stored unchecked.

### T-E-01 API schemas

- **Objective.** Request and response models of contract §11.
- **Allowed files.** `app/schemas/intelligence.py`, unit tests.
- **Acceptance.** Closed enumerations, bounded text, explicit `null`; no ORM
  object reaches a response.

### T-E-02 Routes

- **Objective.** The nine routes, as thin adapters.
- **Allowed files.** `app/api/v1/endpoints/intelligence.py`,
  `app/api/v1/router.py`, `app/core/errors.py` for the new codes, API tests.
- **Required tests.** Every row of the error table of §11; filters, order
  and pagination; another workspace and an unknown id are answered alike;
  no response contains a source row, a key or a path; the header is
  required.
- **Acceptance.** No SQL and no rule in an endpoint.

### T-E-03 OpenAPI and API contract

- **Allowed files.** `docs/engineering/openapi.json`,
  `docs/engineering/api-contract.md`.
- **Acceptance.** `make openapi-check` passes and fails when stale.

### T-E-04 Architecture documents

- **Objective.** The changes of contract §13, as built.
- **Acceptance.** No sentence of a v0.1 document is left untrue.

### T-F-01 Fixture and expected findings

- **Objective.** Data that exercises all five rules and every diagnostic,
  with the expected findings, evidence order and diagnostics written by hand
  from the contract.
- **Allowed files.** `data/samples/`, a new dataset or update files beside
  `nexus_demo`; its `expected` file.
- **Forbidden.** Deriving the expectation from the engine's output.
- **Acceptance.** Reviewed by the lead. It includes a commitment threat,
  which `nexus_demo` does not have (`canonical-input-mapping.md` §5).

### T-F-02 End-to-end and restart proof

- **Objective.** Plan §15.6 over HTTP: import, World State, run, exact
  findings, resolve each by a new version or a documented update, run again,
  earlier occurrences unchanged, World State hash unchanged by the engine,
  restart of the API and of PostgreSQL, replay of the key.
- **Allowed files.** `scripts/verify_sprint.py`, `scripts/demo_checks.py`,
  `artifacts/`, `.github/workflows/ci.yml`.
- **Acceptance.** The evidence is committed and CI runs the proof.

### T-F-03 Deliberate defects

- **Objective.** The removals of plan §15.7 added to
  `scripts/defect_detection.py`, each detected by a named test.
- **Acceptance.** Every defect detected; the baseline and the restoration
  check pass. The count starts from what `main` holds then.

### T-F-04 Performance report

- **Objective.** Plan §16: the demo dataset, ten times it, a medium
  workspace agreed with the lead, and the largest supported one; time per
  stage, peak memory, statements, plans, response size.
- **Acceptance.** Figures are measured and published with the method. The
  budget and the supported size are agreed afterwards (D-10); the abandon
  time of contract §9.2 is set from them.

### T-F-05 Independent review

- **Objective.** Design, code, migration, evidence, tests, boundaries.
- **Acceptance.** The reviewer is not the author. No blocking comment open.

### T-F-06 Release gate

- **Objective.** Plan §19. Local-only stays the default; nothing is deployed.
