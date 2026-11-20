# Cortex Nexus — Implementation log

Statuses: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `PASS`, `DEFERRED`,
`NOT RUN`. A line is `PASS` only when the behaviour was run and the evidence
exists.

## How this sprint was executed

- **One contributor.** The playbook assumes a lead and three parallel lanes.
  This build was done by one coding agent working the lanes in sequence, in
  the playbook's order, with each gate run before the next day's work
  started. The full scope was kept; nothing was moved to the solo fallback.
- **One branch.** Work was committed to a single working branch
  (`arena/6e4094b4-cortex`) with conventional commit messages, one group of
  commits per work package, instead of the `sprint/*` branches of the
  playbook. The working environment tracks one branch per session.
- **Existing repository, emptied.** The playbook's first step is a new
  repository. The work was done in the existing GitHub repository instead:
  its first commit on the branch removes every file of the earlier codebase
  (the licence file is kept), and everything after it is new. The earlier
  code remains in the Git history only.
- **"Day" means a stage of the playbook, not a calendar day.** The three
  stages were worked in one continuous effort. By the clock of the build
  machine every commit falls on 2026-11-19 (UTC); the commit tables below
  give the times. Each gate was run before the next stage started.
- **The playbook is not in the repository.** The repository is public and
  the playbook is a planning document of the project lead. What a change
  needs from it is restated in `docs/`.
- **Build machine.** No Docker, and network access limited to GitHub, PyPI
  and npm. Python 3.12.16 was compiled from the official source; PostgreSQL
  16.2 ran from binaries, as two instances shaped like the Compose services,
  on `127.0.0.2`. Details and the reason for the address are in
  `artifacts/sprint/README.md`. Whatever needs Docker is verified by CI and
  is marked so below.

## Day 1 — Greenfield foundation

### Completed

- [x] D1.1 Repository: `.gitignore`, `.editorconfig`, `.python-version`, `README.md`, `AGENTS.md`, this log
- [x] D1.2 Toolchain: `services/api/pyproject.toml`, `uv.lock`, Ruff, mypy (strict), pytest
- [x] D1.3 Contract freeze: system boundaries, domain model, World State contract, API contract, ADR-001
- [x] D1.4 Local database: `infra/docker-compose.yml`, `.env.example`, typed settings
- [x] D1.5 API spine: application factory, request ids, structured logging, error envelope, health endpoints
- [x] D1.6 Database session and migration harness: engine, sessions, transaction helpers, Alembic environment
- [x] D1.7 Harness: Makefile, CI workflow, `wait_for_db`, `export_openapi`, `smoke_test`, `verify_sprint`
- [x] D1.8 Integration gate run (below)

### Commits

| Commit | Time (UTC) | Summary |
|---|---|---|
| `eaabe49` | 09:38 | chore(repo): remove the previous implementation for the greenfield rebuild |
| `5ae40af` | 10:02 | chore(dev): bootstrap the repository, toolchain and local PostgreSQL |
| `e1f9489` | 10:02 | feat(api): application spine with health checks, request ids and the error envelope |
| `6f6f257` | 10:02 | docs(architecture): freeze the boundaries, the domain model and the contracts |

All on the branch `arena/6e4094b4-cortex`.

### Files changed

66 files added, 5,209 lines (`git diff --shortstat eaabe49 6f6f257`): the
repository files, `infra/`, `scripts/` (4), `services/api` (application
spine in `app/core`, `app/db`, `app/api`; Alembic environment; 6 test
files), `docs/architecture/` (4), `docs/engineering/` (3) and 8 evidence
files. The commit before them removes the 1,189 files of the earlier
codebase.

### Commands executed

| Command | Result | Evidence |
|---|---|---|
| `make setup` in an empty copy of the repository | Exit 0; `uv.lock` unchanged | `day1-clean-install.txt` |
| `uv run python -c "from app.main import app; print(app.title)"` | `Cortex Nexus API`; no connection opened | `day1-clean-install.txt` |
| `uv run alembic heads` / `current` / `check` | Connects; no revision yet; metadata read | `day1-alembic.txt` |
| `uv run uvicorn app.main:app --host 127.0.0.2 --port 8000` | Started | — |
| `curl /health/live` | 200 `{"status":"alive"}` | `day1-health-live.json` |
| `curl /health/ready` | 200, database ok, migrations ok | `day1-health-ready.json` |
| `curl /health/ready` with PostgreSQL stopped | 503; liveness still 200 | `day1-health-ready-db-stopped.txt` |
| `curl /openapi.json` | 200, OpenAPI 3.1.0 | `day1-openapi.json` |
| `make verify` | 11 of 11 steps pass; 72 tests | `day1-test-results.txt` |
| `docker compose -f infra/docker-compose.yml up -d` | NOT RUN on the build machine (no Docker) | CI, see "Continuous integration" |

### Found and fixed on the way

- **Readiness reported "ready" while PostgreSQL refused new connections.**
  During a shutdown PostgreSQL keeps serving connected clients and rejects
  new ones; the first version of the probe borrowed a pooled connection and
  answered 200. Readiness now opens a new connection every time. The state
  is reproduced by `test_readiness_does_not_trust_a_connection_that_is_already_open`,
  which fails against the old probe.
- **The deprecated HTTP test client.** The locked Starlette release warns
  that `httpx` is deprecated for its test client; the suite turns warnings
  into errors, so this surfaced on the first run. `httpx2` is used instead
  (ADR-001).

### Gate G1

| Check | Status |
|---|---|
| New tree with no dependency on earlier files | PASS |
| README and AGENTS.md explain setup and invariants | PASS |
| Python pinned to 3.12 | PASS |
| `pyproject.toml` and `uv.lock` committed | PASS |
| Clean `uv sync --frozen` succeeds | PASS |
| PostgreSQL starts with a healthy named volume | NOT RUN locally (needs Docker); PostgreSQL 16 itself: PASS. In CI: PASS (run 44539765258) |
| API imports and starts without circular imports | PASS |
| `/health/live` works | PASS |
| `/health/ready` verifies PostgreSQL | PASS |
| OpenAPI JSON can be retrieved | PASS |
| Error envelope and request id are wired | PASS |
| Alembic imports metadata deterministically | PASS |
| Ruff and bootstrap tests pass | PASS |
| CI workflow committed | PASS. Its first run, on the pull request, passed (run 44539765258) |
| Architecture, domain and stack decisions written | PASS |
| This log records evidence and blockers | PASS |

- Status: **PASS**, with one line carried to CI (Compose and the named
  volume). That line passed in the CI run recorded under "Continuous
  integration".
- Blockers: none.
- Deferred items: none.

### End-of-day review

1. **What works now?** A clean copy installs from the lockfile. The API
   starts, answers liveness without the database and readiness only when
   PostgreSQL is reachable and the schema is at the migration head. Every
   response carries a request id; every error uses one envelope. Alembic
   reaches the database. One command runs the whole verification chain.
2. **Which test proves it?** `tests/api/test_health.py`,
   `tests/api/test_error_envelope.py`, `tests/unit/test_config.py`,
   `tests/unit/test_clock.py`, `tests/unit/test_logging.py`,
   `tests/integration/test_database_session.py`; 72 tests. Alembic reaching
   the database is shown by `day1-alembic.txt`, not by a test yet.
3. **Which data invariants remain untested?** All of them: there is no model
   yet. Also the named volume, which needs Docker.
4. **Which contract changed and why?** None after the freeze. The test client
   library became `httpx2` (ADR-001).
5. **Is the branch runnable from a clean environment?** Yes for everything
   except Docker Compose (`day1-clean-install.txt`); Compose is left to CI.
6. **Was a file ownership or transaction boundary bypassed?** No.
7. **Highest-severity open defect?** None known. Open risk: Compose not run.
8. **What was deferred?** Nothing.
9. **Is the next stage feasible?** Yes, at full scope.
10. **What can be shown without narration?** The `day1-*` files and
    `make verify`.

## Day 2 — Canonical domain and preview

### Completed

- [x] D2.1 Models: eleven tables in ten model files, enumerations, shared field sizes
- [x] D2.2 Migration `0001`: autogenerated, reviewed by hand, upgrade / downgrade / re-upgrade verified
- [x] D2.3 Schemas: strict dates and decimals, create / update / read / list per entity, error envelope
- [x] D2.4 Repositories: workspace-scoped queries, no commit
- [x] D2.5 Services and routes: projects, suppliers, equipment, purchase orders with line items, milestones with plan versions, supplier commitments
- [x] D2.6 Readers: CSV and XLSX, bounded, formulas never evaluated
- [x] D2.7 Column mapping and normalization: fixed alias tables, ISO dates only, exact decimals
- [x] D2.8 Row validation and preview: batch and row ledger, no canonical write
- [x] D2.9 Tests and OpenAPI export

### Commits

| Commit | Time (UTC) | Summary |
|---|---|---|
| `da0f5f7` | 10:46 | feat(domain): canonical models and the initial migration |
| `104c57b` | 10:47 | feat(api): workspace-scoped services and routes for the canonical records |
| `1457ebd` | 10:47 | feat(ingestion): safe CSV/XLSX reading, deterministic mapping and import preview |
| `ca232c7` | 10:47 | docs(engineering): Day 2 record, gate G2 and evidence |

### Files changed

97 files, 19,738 lines added (`git diff --shortstat 6f6f257 ca232c7`):
`app/models` (15), `app/schemas` (9), `app/repositories` (9), `app/services`
(11), `app/ingestion` (6), `app/api` (9), the migration, 14 new test files
with their helpers, the validation example, the exported OpenAPI document and
5 evidence files.

### Commands executed

| Command | Result | Evidence |
|---|---|---|
| `uv run alembic revision --autogenerate -m "initial canonical procurement schema"` | Revision `0001`, 11 tables | `day2-migration-review.txt` |
| `uv run alembic upgrade head` / `downgrade base` / `upgrade head` / `upgrade head` | 12 tables / 1 / 12 / no-op | `day2-migration-review.txt`, `tests/integration/test_migrations.py` |
| `uv run alembic check` | No drift between models and schema | `day2-test-results.txt` |
| `curl -F file=@equipment_with_issues.csv -F entity_type=equipment …/ingestion/preview` | 201; 6 rows, 3 valid, 3 invalid, 4 warnings | `day2-preview-equipment.json` |
| Row counts of every table before and after that preview | Canonical tables unchanged; 1 batch, 6 ledger rows | `day2-canonical-counts-before-after.txt` |
| `make openapi` | 19 paths | `docs/engineering/openapi.json` |
| `make verify` | 11 of 11 steps pass; 297 unit, 142 API, 64 integration tests | `day2-test-results.txt` |

### Found and fixed on the way

- **A CHECK violation was reported as a duplicate key.** Equipment without a
  specification failed with `DUPLICATE_NATURAL_KEY`. Two causes: Python
  `None` was stored in the JSONB column as the JSON value `null` instead of
  SQL `NULL`, which the "specification is an object" constraint refuses; and
  the helper that turns a unique violation into a conflict caught every
  integrity error. The column now stores `NULL`; the helper and the generic
  handler act on unique and foreign-key violations only, and any other
  constraint failure surfaces as a logged 500, because it means invalid data
  got past validation.
- **Deprecated `DISTINCT ON` syntax.** SQLAlchemy 2.1 deprecates
  `select().distinct(column)`; warnings are errors in the suite, so the
  first request that used it failed. The repositories use
  `postgresql.distinct_on`.
- **Statement parameters in error logs.** An unhandled database error logged
  the statement with its bound values, which for an import are source rows.
  Engines are created with `hide_parameters=True`.
- **An over-large chunked body was answered 400.** The framework turns any
  failure while reading a body into its own "bad request". The body guard now
  replaces that answer with 413.
- **A trailing empty line counted as a skipped blank row.** Only blank rows
  between data rows are reported.

### Decisions recorded while implementing

All are in `docs/architecture/domain-model.md` or
`docs/engineering/api-contract.md`; the ones that go beyond the playbook text:

| Decision | Reason |
|---|---|
| Uniqueness of `(workspace, entity type, checksum)` excludes `FAILED` batches | A failed batch wrote nothing. Without this, a file that failed because of an outage could never be submitted again |
| Uploading the bytes of a `PREVIEWED` batch again re-validates that batch | A file previewed before its dependencies were committed must be able to become valid without being edited |
| `CROSS_WORKSPACE_REFERENCE` is never returned | It would disclose that a record exists in another workspace; the answer is `REFERENCE_NOT_FOUND` |
| A blank cell never clears or overwrites a stored value | "Not supplied" and "delete this" must not look the same in a file |
| Equipment may lack a required-on-site date (warning, not rejection) | Rejecting the row would hide the equipment |
| A purchase order may exist without line items | Headers and lines arrive in separate files |
| Extra routes for supplier, purchase-order and milestone operations, and for provenance | The playbook requires the service operations and the audit lookups; they need a route to be usable |
| Decimals are JSON strings; a JSON float is rejected | A float cannot carry every decimal value |

### Gate G2

| Check | Status |
|---|---|
| All canonical model tables are in the migration metadata | PASS |
| Empty database upgrades successfully | PASS |
| Foreign keys, unique and check constraints reviewed | PASS |
| Workspace and project consistency enforced (service and database) | PASS |
| Purchase order and line items created atomically | PASS |
| Quantity and money keep Decimal precision | PASS |
| Milestone and commitment version services work | PASS |
| Workspace-scoped CRUD routes return Pydantic schemas | PASS |
| CSV reader: BOM, empty file, duplicate headers, blank rows | PASS |
| XLSX reader: selects the requested sheet, rejects ambiguity | PASS |
| Upload size, row and column limits enforced | PASS |
| Unknown columns retained and surfaced as warnings | PASS |
| Ambiguous alias collisions rejected | PASS |
| Invalid dates, decimals and enums give row-level errors | PASS |
| Preview creates ledger entries and no canonical record | PASS |
| OpenAPI contains the routes and response schemas | PASS |
| Unit, API and integration tests pass | PASS |

- Status: **PASS**.
- Blockers: none.
- Deferred items: none. XLSX, which the solo fallback allows deferring, is implemented.

### End-of-day review

1. **What works now?** The eleven tables exist through a migration. Records
   are created, read and updated through workspace-scoped routes; a purchase
   order is created with its line items in one transaction; a changed planned
   date or commitment appends a version. CSV and XLSX files are read within
   bounds and previewed row by row; a preview writes the ledger and no
   canonical record.
2. **Which test proves it?** `tests/integration/test_model_constraints.py`
   and `test_migrations.py`; `tests/api/test_projects.py`,
   `test_suppliers_equipment.py`, `test_purchase_orders.py`,
   `test_ingestion_preview.py`; `tests/unit/test_readers.py`,
   `test_column_mapping.py`, `test_normalization.py`,
   `test_row_validation.py`; `tests/integration/test_workspace_isolation.py`.
   503 tests.
3. **Which data invariants remain untested?** Everything about commit:
   atomicity, replay, provenance links, two writers on one record. World
   State does not exist yet.
4. **Which contract changed and why?** Additions to the playbook tables, each
   marked in the domain model: file warnings and commit counters on the
   batch, planned action and outcome on the row, the supplier's own reference
   on a commitment. Routes beyond the inventory are marked † in the API
   contract.
5. **Is the branch runnable from a clean environment?** Yes; `make verify`
   passes 11 of 11 steps. Compose is still left to CI.
6. **Was a file ownership or transaction boundary bypassed?** No. Repositories
   do not commit; endpoints hold no SQL; `app/ingestion` has no database
   access.
7. **Highest-severity open defect?** None open. The five found that day are
   listed above, each fixed with a test.
8. **What was deferred?** Nothing.
9. **Is the next stage feasible?** Yes.
10. **What can be shown without narration?** The `day2-*` files and
    `make verify`.

## Day 3 — Commit and World State

### Completed

- [x] D3.1 Batch state machine: commit only from `PREVIEWED`, under a row lock on the batch; `COMMITTING` exists only inside the commit transaction
- [x] D3.2 Transactional commit: every valid row is checked again at commit time; the valid rows are written in one transaction or not at all; a failure is recorded in a transaction of its own
- [x] D3.3 Idempotency: one batch per file and entity type; records resolved by natural key; only source-owned fields change; a policy for duplicates inside a file
- [x] D3.4 Provenance and history: each committed row is linked to its record; each new version names the source row that introduced it; the six audit lookups of the playbook have a test each
- [x] D3.5 World State service: workspace, summary and project projections; data-quality warnings for what is not recorded
- [x] D3.6 World State endpoints: paged, scoped, with a number of SQL statements that does not grow with the data
- [x] D3.7 Demonstration dataset: 8 files and `expected.json` in `data/samples/nexus_demo/`
- [x] D3.8 Seed, smoke test over HTTP, end-to-end run with a restart of the API and of PostgreSQL
- [x] D3.9 Release record: OpenAPI document, test strategy, known limitations, evidence, CI workflow

After the first end-to-end pass the build was probed on purpose, which is not
a package of the playbook: one file and one batch sent by eight clients at
once, files of several thousand rows, extreme values in imports and in JSON,
ids and codes of a second workspace on every route. The probes were throwaway
scripts against a running API and are not in the repository. What they found
is listed under "Found and fixed" below; each defect of the application has
a test in the repository.

### Commits

| Commit | Time (UTC) | Summary |
|---|---|---|
| `7720548` | 11:56 | feat(ingestion): transactional commit with replay, provenance links and version history |
| `46cde61` | 11:56 | feat(world-state): workspace, summary and project projections read from PostgreSQL |
| `bcd26d4` | 11:56 | feat(demo): synthetic dataset, seed through the services, end-to-end verification |
| `6329e8b` | 12:13 | fix(ingestion): one new file uploaded several times at once is one batch |
| `54f9a8b` | 12:25 | fix(api): values PostgreSQL cannot hold are refused as input, not answered 500 |
| `eaaa053` | 12:28 | fix(errors): a deadlock is a conflict to send again, not an outage |
| `aaa62dd` | 12:34 | test(e2e): the demo dataset as an Excel workbook with typed cells |
| `2ffe4b8` | 12:36 | fix(api): sequence_no is a JSON whole number |
| `b19decf` | 12:44 | fix(e2e): the first import of the demonstration goes over HTTP |
| `2434cce` | 12:46 | test(api): an id of another workspace on every route that takes an id |
| `45b0671` | 12:59 | test: show that the tests fail when the behaviour is removed |
| `c830e48` | 13:02 | fix(dates): a date takes the digits 0 to 9 only, stated in the code |
| `6be089d` | 13:30 | docs,ci: README for the finished v0.1; CI reports test totals and runs defect detection |
| `dd33ca5` | 14:03 | docs(engineering): Day 3 record, gate G3 and evidence |
| the commit that holds this text | | docs(engineering): the first CI run; gate G3 decided |

**How this history was made.** The session that built Day 3 was interrupted
once, with the commit path, the World State and the dataset written and not
yet committed. That work was committed as it was found and then verified by
the full suite before anything was added. All Day 3 work was first committed
as work-in-progress commits. Before the pull request those were replaced by
the commits above, built from the same file contents: the final tree is
identical (`git diff` between the old and the new tip is empty). The first
work-in-progress commit was divided by file into the three `feat` commits.
In three of the thirteen commits the committed OpenAPI document was exported
again from the code of that commit, so that the check for a stale document
passes at every commit. The times are those of the original commits. Each
of the thirteen commits was then checked out on its own and run through
lint, format check, mypy, the OpenAPI check and the three test suites: all
pass (`day3-commit-validation.txt`).

### Files changed

60 files, 10,219 lines added and 218 removed between the end of Day 2 and
`6be089d` (`git diff --shortstat ca232c7 6be089d`):

- `app/services`: `ingestion_service.py` (commit), `world_state_service.py`, `data_quality_service.py`
- `app/repositories/world_state_repository.py`; `app/schemas/world_state.py`; `app/api/v1/endpoints/world_state.py` and `ingestion.py`
- `app/core/errors.py`, `app/core/decimals.py`, `app/models/limits.py`, `app/models/ingestion.py`, `app/ingestion/normalization.py`, `app/ingestion/column_mapping.py`, `app/schemas/common.py`, `app/schemas/milestone.py`, `app/api/deps.py` (the fixes)
- `data/samples/nexus_demo/` (9 files)
- `scripts/`: `seed_demo_data.py`, `demo_checks.py`, `defect_detection.py` (new); `smoke_test.py`, `verify_sprint.py` (extended)
- Tests: 7 files in `tests/api`, 7 in `tests/integration`, 2 in `tests/unit`, and the helper `tests/importing.py`
- `README.md`, `AGENTS.md`, `Makefile`, `.github/workflows/ci.yml`, `infra/docker-compose.yml`
- `docs/`: `known-limitations.md`, `test-strategy.md` (new); `domain-model.md`, `api-contract.md`, `openapi.json` (updated)

`dd33ca5` adds the Day 3 evidence files and this record. The commit after it
records the first CI run and changes one line of the workflow.

### Commands executed

All on the build machine, on the code identified in the header of
`day3-full-test-results.txt`.

| Command | Result | Evidence |
|---|---|---|
| `DROP DATABASE`, `CREATE DATABASE`, `uv run alembic upgrade head` | An empty development database: 12 tables, no workspace, no record | `day3-full-test-results.txt` (header) |
| `uv run python ../../scripts/verify_sprint.py --e2e …` (`make e2e` with a restart command for a machine without Docker) | Exit 0; 12 of 12 steps pass | `day3-full-test-results.txt`, `day3-verify-summary.json` |
| — unit, API and integration tests in that run | 339, 224 and 126 passed (689) | same |
| — workspace created, 8 files previewed and committed over HTTP | 8 × 201 and `COMMITTED`; 112 rows committed, none rejected | `day3-import-results.json` |
| — the whole dataset sent again over HTTP | Every file resolved to its batch, every commit a replay, counts unchanged; 53 of 53 checks | `day3-full-test-results.txt` |
| — `seed_demo_data.py` on top | Every file "already committed"; 28 of 28 dataset checks | same |
| — World State of the project with its history | 20 equipment records, 12 purchase orders, 40 milestones, 12 commitment versions | `day3-world-state.json` |
| — commitment history of `PO-1007` | Version 1 (2026-11-28) and version 2 (2026-12-06), each with its source row | `day3-commitment-history.json` |
| — API stopped, PostgreSQL restarted, API started | World State identical before and after (same SHA-256); 42 of 42 checks, twice | `day3-restart-proof.txt` |
| `psql` counts of every table next to `GET …/world-state/summary` | Equal; 8 batches and 112 source rows after the dataset was sent three times; every row linked to a record | `day3-database-counts.txt` |
| `uv run python ../../scripts/defect_detection.py` | 26 of 26 deliberate defects detected | `day3-defect-detection.txt` |
| The `curl` commands of the README against the running API | Preview 200 (file already known), commit 200 (`replayed: true`), the three World State routes 200 | — |
| Lint, format check, mypy, OpenAPI check and the three suites at each of the 13 commits | All pass | `day3-commit-validation.txt` |
| `make db-up`, `make e2e` with Docker Compose | NOT RUN on the build machine (no Docker). In CI: pass | "Continuous integration" below |

### Found and fixed on the way

Found by the probes and by reading the code against the contract. Items 1
to 10 are defects of the application. Each has a test, and the run with
deliberate defects shows a test failing when the fix is taken out
(`docs/engineering/test-strategy.md`); for item 5 that run covers the
rounding case, and the over-long text has an ordinary test. Items 11 to 13
are of another kind, and each says so.

1. **One new file sent by eight clients at once: seven were answered 409.**
   The requests raced to create the batch and the losers surfaced the unique
   violation. The index now decides the race; a request that loses waits and
   answers with the batch that won. One batch, one 201, seven 200.
2. **A NUL character in JSON text was answered 500.** PostgreSQL text cannot
   hold it. It is now a field error (422, `INVALID_VALUE`).
3. **A sequence number above 2,147,483,647 was answered 500, and an import
   previewed it as valid and then failed at commit.** It is now refused at
   the boundary: 422 in the API, `INVALID_INTEGER` on the row at preview.
4. **An offset beyond 64 bits was answered 500.** Offsets end at
   2,147,483,647 (422, `OUT_OF_RANGE`).
5. **Decimal text of thousands of digits crashed the parser, and a digit
   beyond the 28th place was rounded away and the value accepted.** The size
   of a number is now read from its digits; both cases are `INVALID_DECIMAL`.
   The second one mattered more: a value was stored that the file did not
   contain.
6. **A deadlock was answered 503 and failed the batch.** It is 409
   `CONFLICT`; nothing is written and the batch stays `PREVIEWED`, so the
   same commit can be sent again.
7. **A value the database refuses all the same** is answered 422 with the
   transaction rolled back (`COMMIT_FAILED` for an import, whose batch
   becomes `FAILED`), and logged as an error without the value.
8. **Control characters in an uploaded file name were stored.** They are
   dropped; the name is display text.
9. **`sequence_no` accepted `"1"`, `1.0` and `true`.** It is a JSON whole
   number.
10. **A test did not prove what its name said.** The test with two imports
    on one purchase order passes without the row lock, because the race
    falls the harmless way. The locks are now proven by holding the row in
    another session and waiting until PostgreSQL reports the writer as
    waiting.
11. **The end-to-end run imported through the seed first**, so the import
    over HTTP only replayed and proved less than it claimed. The first import
    now goes over HTTP. A defect of the verification script, not of the
    application; the run itself is the check.
12. **A date in the digits of another script was refused only because the
    standard library refuses it.** The rule is now stated in the patterns
    and has tests. The behaviour did not change, so those tests pass with
    or without the change.
13. **The Compose health check could report "healthy" too early.** Not
    observed: found by reading the entrypoint of the PostgreSQL image, which
    runs a temporary server on the Unix socket while it creates the data
    directory. The check now goes over TCP. No test; Compose runs in CI
    only.

### Decisions recorded while implementing

All are in `docs/architecture/domain-model.md`,
`docs/architecture/world-state-contract.md` or
`docs/engineering/api-contract.md`.

| Decision | Reason |
|---|---|
| Identical rows in one file: the first is applied, the others are skipped as `DUPLICATE_ROW`. Conflicting rows: all rejected | Row order must never decide which value is stored |
| A row that names an existing record with another project or supplier is an error (`IMMUTABLE_FIELD_CONFLICT`) | An import must not move a record |
| A failed commit answers 409 `COMMIT_CONFLICT` and the batch is `FAILED`; the file is uploaded again as a new batch | The retry policy the playbook calls the safest |
| A deadlock answers 409 `CONFLICT` and leaves the batch `PREVIEWED` | Nothing about the file is wrong; the same request succeeds when sent again |
| The same new file uploaded several times at once is one batch | The rule "one file, one batch" must hold under a race too |
| Whole numbers and offsets end at 2,147,483,647 | The size of the column; a larger value is refused, never cut |
| In numbers a digit of any script is the digit it is; dates take 0 to 9 only | A number has one meaning in any script. A date in another script may be of another calendar |
| A `COMPLETED` milestone may lack an actual date; an actual date on a milestone that is not completed is an error | A source may say "completed" without a date; the date is not invented |
| The provenance route answers an empty list for a record that is unknown or belongs to another workspace | The two cases must look the same |
| World State reports what is not recorded as warnings, and compares no dates | Facts and judgement stay apart; lateness belongs to a later layer |

### Gate G3

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Batch state machine implemented and guarded against concurrent commits | PASS | `test_two_concurrent_commits_of_one_batch_take_effect_once`, `test_a_second_commit_waits_for_the_first_and_then_reports_its_result`, `test_commit_status_codes`; defect 6 |
| 2 | Commit revalidates references and state | PASS | `test_a_reference_that_became_invalid_after_preview_fails_the_whole_batch`, `test_commit_refuses_rows_whose_stored_values_no_longer_validate` |
| 3 | The valid-row subset commits in one transaction | PASS | `test_the_valid_subset_is_committed_and_invalid_rows_stay_visible`, `test_commit_reports_counters_and_links_each_row_to_its_record` |
| 4 | Any commit-time failure rolls back the canonical writes of the batch | PASS | `test_an_unexpected_failure_mid_batch_leaves_no_partial_records`, `test_a_database_constraint_failure_mid_batch_rolls_everything_back`, `test_a_value_the_database_cannot_store_fails_the_batch_and_says_what_to_do`, `test_a_commit_ended_by_a_deadlock_writes_nothing_and_can_be_sent_again` |
| 5 | A repeated commit returns the original result without writing | PASS | `test_committing_a_committed_batch_again_writes_nothing`, `test_repeated_commit_does_not_duplicate_records`; end-to-end run: every commit of the second pass is a replay |
| 6 | The same file checksum does not create a second batch | PASS | `test_the_same_file_is_one_batch_and_one_import`, `test_the_same_new_file_uploaded_at_once_is_one_batch_for_everyone`; `day3-database-counts.txt` (8 batches after three passes) |
| 7 | Different files with the same natural keys do not duplicate records | PASS | `test_known_records_are_resolved_and_only_source_owned_fields_change`, `test_a_different_file_with_the_same_keys_updates_instead_of_duplicating` |
| 8 | Conflicting duplicate rows are rejected or handled by a documented policy | PASS | `test_conflicting_rows_in_one_file_are_rejected_whatever_their_order`, `test_identical_rows_in_one_file_are_applied_once_and_both_linked`; `domain-model.md`, "Field ownership for imports" |
| 9 | Source rows link to the committed canonical records | PASS | `test_every_source_row_is_linked_to_the_record_it_produced`; `day3-database-counts.txt` (112 of 112) |
| 10 | Commitment and plan history is append-only | PASS | `test_commitment_history_first_revised_replayed`, `test_plan_history_first_revised_replayed`, `test_versions_have_no_update_or_delete_operation`, `test_the_revised_commitment_is_appended_and_the_old_one_remains`; `day3-commitment-history.json` |
| 11 | World State is generated from PostgreSQL | PASS | `test_summary_counts_match_the_database`, `test_counts_follow_the_database_not_a_fixture`, `test_a_new_process_reads_the_same_world_state`; `day3-database-counts.txt` |
| 12 | Workspace and project World State are bounded and scoped | PASS | `test_the_project_list_is_paged_and_the_total_stays_complete`, `test_project_collections_are_paged`, `test_nested_lists_are_capped_and_the_count_stays_complete`, `test_warnings_are_bounded_and_counts_are_complete`, `test_counts_exclude_other_workspaces`, `test_world_state_of_another_workspace_or_project_is_not_disclosed`; `test_world_state_queries.py`; `test_workspace_isolation_http.py` |
| 13 | The demo dataset imports through the public application flow | PASS | End-to-end run over HTTP on an empty database: `day3-import-results.json`, `day3-full-test-results.txt` |
| 14 | All five data conditions are represented and queryable | PASS | `test_all_five_conditions_are_represented_and_queryable`; the dataset checks of the end-to-end run |
| 15 | Repeating the seed or the import changes no count and appends no version | PASS | `test_repeating_the_whole_import_changes_no_count_and_appends_no_version`, `test_no_table_is_touched_by_a_full_replay`; end-to-end run, three passes |
| 16 | Data survives a restart of the API and of the database container, volume retained | PASS in CI: the container was removed and created again, the named volume kept, the World State identical. On the build machine the same for a restarted server without a container | CI run 44539765258, "Continuous integration" below; `day3-restart-proof.txt` |
| 17 | Critical unit, API, integration and end-to-end tests pass | PASS | 339 unit, 224 API, 126 integration; 165 end-to-end checks; `day3-full-test-results.txt` |
| 18 | OpenAPI export, test report, sample World State and known-gap list are committed | PASS | `docs/engineering/openapi.json`, `day3-full-test-results.txt`, `day3-world-state.json`, `day3-known-limitations.md` |

The stop rule of the playbook: the demonstration must not work only through
direct seeding, fixed JSON, manual SQL or a mocked World State. In the
end-to-end run the first import of every file is an HTTP upload to the
preview route followed by an HTTP commit, on a database that holds nothing
but the schema and the workspace. The seed calls the same two services. No
script inserts a canonical record, and
`test_preview_then_commit_is_the_only_way_a_file_becomes_records` holds the
API to it.

- Status: **PASS.** 17 of the 18 checks are shown on the build machine;
  check 16 needs Docker and is shown by the CI run. The CI run repeats the
  tests and the end-to-end demonstration on PostgreSQL 16.16.
- Blockers: none.
- Deferred items: none.
- After the gate had been decided, defects were found in the workbook reader
  and corrected. None of the 18 checks concerns them, and the gate was not
  decided again; they are recorded under "After gate G3" below. The counts in
  this table are those of the gate.

### End-of-day review

1. **What works now?** A previewed file can be committed: the valid rows are
   written in one transaction, linked to their source rows, with history
   appended where a date changed. Sending the same file or the same commit
   again changes nothing. The World State reads the result back from
   PostgreSQL in three bounded projections. The demonstration dataset goes
   from eight files to the World State over HTTP and reads back identically
   after a restart of the API and of PostgreSQL.
2. **Which test proves it?** The tests named in the gate table; the
   end-to-end run; and, for the tests themselves, the 26 deliberate defects.
3. **Which data invariants remain untested?**
   - Nothing in the database stops an `UPDATE` or `DELETE` of a version row
     by someone with SQL access. Append-only is a property of the service,
     which has no such operation; that is what the test checks (L-34).
   - A deadlock between two imports. One deadlock is tested, between an
     import and another writer.
   - Behaviour under load: no load test was run. Timings were taken once.
   - A file produced by Excel or by a supplier system.
4. **Which contract changed and why?** The API contract gained the code
   `COMMIT_FAILED`, bounds on `offset` and `sequence_no`, and the answers to
   a simultaneous upload and to a deadlock: each closes a case that was
   answered 500, 503 or 409 before. It also lists `OUT_OF_RANGE`,
   `INVALID_VALUE` and `BAD_REQUEST`, which the API returned already and the
   document had left out. The OpenAPI document went from 19 to 23 paths
   (commit, three World State routes). The domain model gained the section
   on writers at the same time.
5. **Is the branch runnable from a clean environment?** From an empty
   database on the build machine, yes: that is the run recorded above.
   From a clean clone with Docker, yes: that is what the CI workflow does,
   and its first run passed.
6. **Was a file ownership or transaction boundary bypassed?** No. Checked
   again on the final code with `grep`: no `commit` or `rollback` in
   `app/repositories`, no query in `app/api`, no HTTP type in `app/services`,
   no database import in `app/ingestion`, no `datetime.now` outside
   `app/core/clock.py`. The seed creates the workspace through the workspace
   service and everything else through preview and commit.
7. **Highest-severity open defect?** No P0 or P1 is known. The highest open
   items are P2 limitations, first of them L-10: commit is synchronous and
   writes row by row, about 26 seconds for 8,000 milestones.
8. **What was deferred?** Nothing of the sprint scope. What the sprint does
   not build is L-01 to L-06 in `known-limitations.md`: authentication,
   intelligence, agents, frontend, deployment, integrations.
9. **Is the next scope feasible?** Not assessed here. The next phase reads
   the World State and derives findings from it; this release gives it a
   contract and a dataset to start from. Authentication (L-01) comes before
   any use beyond a developer machine.
10. **What can be shown without narration?** `make e2e` is one command and
    prints every check. The `day3-*` files hold its output. The CI run shows
    the same from a clean checkout, on its own page.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request, in two jobs:

- **Clean checkout to end-to-end proof.** Installs from the lockfile, runs
  lint, format check, mypy and the unit tests, starts both databases with
  Docker Compose, migrates, runs the API and integration tests and the
  OpenAPI check, then the end-to-end demonstration. Its database restart is
  `make db-down && make db-up`: the container is removed and created again
  and the named volume is kept.
- **Tests fail when the behaviour is removed.** Runs
  `scripts/defect_detection.py`.

Both jobs publish their results as annotations on the run and keep the
output files as artifacts for 30 days.

### The first run

Run 44539765258, on pull request 26, commit `dd33ca5`, started 2026-11-19
14:04 UTC on `ubuntu-24.04`. Both jobs passed at the first attempt. The
figures below are read from the annotations of that run.

**Clean checkout to end-to-end proof** (1 min 41 s), Python 3.12.16:

| Step | Result |
|---|---|
| Install from the lockfile | Pass; the lockfile was not changed by the install |
| Lint, format check, mypy | Pass |
| Unit tests | 339 passed |
| `make db-up` | `postgres:16.16` twice, both healthy, published on `127.0.0.1` only; named volume `cortex-nexus_nexus_pgdata`. The server reports PostgreSQL 16.16 |
| `make migrate`, `make migration-check` | Pass |
| API tests | 224 passed |
| Integration tests | 126 passed |
| OpenAPI check | Pass |
| End to end: first import | On the empty database, 8 files previewed (201) and committed over HTTP; 112 rows |
| End to end: repeat and seed | Every file resolved to its batch, every commit a replay; the seed found every file committed |
| End to end: restart | PostgreSQL restarted with `make db-down && make db-up`; its start time moved from 14:04:45 to 14:05:37 |
| End to end: compare | World State identical before and after the restart (SHA-256 `1207ec1f…16004` both times) |

**Tests fail when the behaviour is removed** (3 min 21 s): the unchanged code
passed (235 tests); 26 of 26 deliberate defects were detected; every file
was put back.

This run is the evidence for what the build machine could not show: the
Compose file, the health check, the named volume, the restart of the
container, and the pinned PostgreSQL 16.16.

One warning appeared in the run: both jobs tried to save the same dependency
cache, and one reported that it could not. Since the commit that holds this
text only the first job saves it.

### Later runs

`27597ab` changes documents and the workflow file only; the Git tree hashes
of `services/api`, `scripts` and `data` are those named in the `day3-*`
evidence files. The commits after it change the workbook reader, the tests
and the defect script ("After gate G3" below). Each commit has its own run
on the pull request page; the run of `2221f42`, the first with the changed
reader, passed both jobs. The step "Explain a failure" has never run,
because no run has failed.

## After gate G3: what no test had reached

### Why

With the gate decided and the CI run green, the Makefile targets were run
once more by hand. `make coverage` reported 97 % (3,973 statements, 71 not
run). The lines not run were read one by one. Those that a caller can reach
were tried against a running API on the test database, with requests and
files written for the purpose.

Most of them did what they should, and now have a test. The workbook reader
did not.

### Found and corrected in the workbook reader

Every item was reproduced before the code was changed.
`artifacts/sprint/review-tests-before-the-fix.txt` lists the new tests that
failed on the code of the gate, and `review-before-after.txt` holds the
figures below.

| # | Finding on the code of the gate | Now |
|---|---|---|
| 1 | **A worksheet was read only as far as the range it claims.** A worksheet that states the range `A1:B2` and holds three data rows was imported as one row, without a warning. openpyxl stops at the last row of the stated range when it streams a worksheet, and some programs state `A1` whatever the worksheet holds | The stated range is discarded before the rows are read. All three rows are read |
| 2 | **Misnumbered rows and cells were left out without a word.** With rows numbered 1, 2, 2, 3 the reader returned the first and the last data row. A row that comes late in the file was dropped; of two cells with one reference the later one won | `MALFORMED_FILE`: rows and cells must be numbered in ascending order |
| 3 | **Entities declared by a workbook were filled in.** The package that makes openpyxl refuse them, defusedxml, was not installed. An upload of 7,485 bytes made the reader build 200 MB of text: 3.7 s and 726 MB before it answered `CELL_TOO_LONG` | defusedxml is a locked dependency and the reader module does not load without it. A part that declares a document type is refused before the workbook is opened: `MALFORMED_FILE`, at once |
| 4 | **A few kilobytes of XML became hundreds of megabytes of objects.** Five megabytes of empty cell formats (an upload of 9,103 bytes) took 35.7 s and 782 MB, and the file was then read as if nothing had happened. The same size of empty elements in the workbook part: 2.4 s and 172 MB. One element with 1.2 million attributes: 4.3 s and 389 MB | Every part is read once as a stream before the workbook is opened, and counted (`app/ingestion/workbook_scan.py`). All three are refused with `FILE_TOO_LARGE` within 0.2 s |
| 5 | A worksheet was probed for data across all 16,384 columns. One hundred worksheets with a blank cell far to the right: 7.1 s | Probed within the columns that can be imported: 0.3 s |
| 6 | An error listed every worksheet name in full. Two names of 100,000 characters gave a message of 200,072 characters | At most ten names of 40 characters: 158 characters |
| 7 | A worksheet name longer than the 160 characters of the ledger column was answered by the general safety net: 422 "a value cannot be stored" and an error line in the log | `MALFORMED_FILE`, naming the limit |
| 8 | Of two worksheets with the same name the first was read, silently | `MALFORMED_FILE` |
| 9 | A worksheet whose name has spaces around it could not be requested by name | A name is matched exactly, and otherwise with the spaces ignored if that fits one worksheet only |
| 10 | Links to other workbooks were parsed when a workbook was opened | Not read |

Items 1 and 2 are losses of data: a file was accepted and a part of it was
imported. They contradict what this release is for, and they would not have
shown in any response. Items 3 and 4 let one small upload hold the service
for most of a minute and take most of a gigabyte. The playbook asks, in its
file upload safeguards, to reject malformed or suspicious workbooks safely
and not to decompress unbounded workbook contents. At the gate that was true
of the archive and not of the XML inside it.

Decisions taken with these changes:

| Decision | Why |
|---|---|
| A workbook whose rows or cells are misnumbered is refused, not repaired | Which of two rows with one number is meant cannot be known. No spreadsheet program writes such a file |
| The checks apply to every worksheet of a workbook, not only the one imported | openpyxl opens every worksheet. A worksheet that is not imported can cost as much as one that is (L-36) |
| The budget for cells is that of a full import: every row the reader scans times every column it accepts, four elements a cell | What cannot be imported is not opened. A larger neighbouring worksheet is refused with a message that says what to do |
| Formats, names and other structure: 250,000 elements a part | A spreadsheet program allows 65,490 cell formats; with their child elements that stays below the bound |
| A document type is refused even without an entity | No part of a workbook has one, and it can also give attributes default values |
| The reader module raises on import when openpyxl is not using defusedxml | openpyxl falls back to the standard parser silently. A service that cannot read workbooks safely should not start |

### Branches that did what they should, and now have a test

| Behaviour | Test |
|---|---|
| A record created while another writer holds its natural key waits, and is then a duplicate; when that writer gives up, it is created | `test_concurrency.py`, two held-lock tests |
| A constraint refused by the database: unique and foreign key are a 409, CHECK and NOT NULL a logged 500 | `test_error_envelope.py`, `test_service_support.py` |
| A commit that loses the database writes nothing and fails the batch; when even that cannot be recorded the batch stays `PREVIEWED` and can be committed afterwards | `test_import_preview_commit.py` |
| Readiness on a database without the schema, and on a schema of another revision: 503, with the database check passing | `test_migrations.py` |
| An import adds to the specification of existing equipment and keeps the rest, also when the record was changed between preview and commit | `test_ingestion_commit.py` |
| Cells beyond the header are kept with the row they invalidate | `test_ingestion_preview.py` |
| A full warning list still counts the findings it cannot show | `test_world_state.py` |
| A day that does not exist is not a date; a whole number sent as a JSON number is held to the bounds of its field | `test_purchase_orders.py` |
| The development workspace is created once; a slug cannot be taken twice | `test_workspace_isolation.py` |
| The reader branches for a damaged part, too many parts, data below blank rows, time and duration cells, files of separators only | `test_readers.py` |

### Workbooks written by real programs

Every workbook in the tests is written by openpyxl or by hand. To see
whether the stricter reader refuses what real programs write, 36 workbooks
written by Microsoft Excel and LibreOffice were read once with
`scripts/compare_workbooks.py` (`review-real-workbooks.txt`). The 27
worksheets the reader accepts were identical, cell by cell, to an
independent reading. The others were refused for their layout (a title above
the header, a column without a name, a repeated header), none for the new
checks. One of the files states a range smaller than its content: read by
openpyxl alone it gives one row of one column instead of five rows of three.

The files are the test data of the pandas project. They are not in this
repository and they are not procurement data.

### Commits

| Commit | Content |
|---|---|
| `2221f42` | The workbook reader: the ten items above, `app/ingestion/workbook_scan.py`, defusedxml, `tests/unit/test_workbook_safety.py`, `tests/workbooks.py` |
| `bb25faa` | Tests for the branches that did what they should |
| the commit that holds this text | Defects 27 to 37 of `scripts/defect_detection.py`, `scripts/compare_workbooks.py`, the documents and the `review-*` evidence |

The figures in the message of `2221f42` are from an earlier run of the same
measurements; the ones in this section are those of `review-before-after.txt`.

### Verification of the final code

| Check | Result | Evidence |
|---|---|---|
| Verification chain and end-to-end demonstration, from an empty migrated database | Exit code 0, 12 of 12 steps. 414 unit, 238 API and 134 integration tests (689 at the gate). End to end as at the gate: 53, 28 and twice 42 checks; the World State identical across the restart | `review-full-test-results.txt`, `review-verify-summary.json` |
| Deliberate defects | 37 of 37 detected; the files were put back | `review-defect-detection.txt` |
| CI | The run of `2221f42` passed both jobs. The run of the commit that holds this text cannot be recorded in it; its result is in the description of the pull request | Pull request page |

The coverage report was not read a second time.

### What this leaves

- A workbook built for the purpose can still cost about as much as the
  largest workbook that can be imported: about a minute and 300 MB on the
  build machine (L-35). There is no limit on uploads read at once.
- A workbook is refused as a whole for one worksheet that cannot be read
  (L-36).
- Reading a large workbook is slow: 41 to 59 s at both limits (L-10). It is
  read twice, once for values and once for formulas.
- The review was done by the contributor who wrote the code (V-03), on the
  workbooks that contributor could think of. It began by chance, with a
  coverage report read after the gate. The gates of the playbook did not ask
  for it.

## Work-package status board

| Task | Status | Commits | Evidence |
|---|---|---|---|
| D1.1–D1.8 Foundation | PASS | `5ae40af`, `e1f9489`, `6f6f257` | Gate G1 |
| D2.1–D2.2 Models and migration | PASS | `da0f5f7` | Gate G2 |
| D2.3–D2.5 Schemas, repositories, services, CRUD | PASS | `104c57b` | Gate G2 |
| D2.6–D2.8 Readers, mapping, validation, preview | PASS | `1457ebd` | Gate G2 |
| D2.9 Tests and OpenAPI review | PASS | `ca232c7` | Gate G2 |
| D3.1–D3.4 Commit, idempotency, provenance | PASS | `7720548`, `6329e8b`, `54f9a8b`, `eaaa053` | Gate G3, checks 1 to 10 |
| D3.5–D3.6 World State | PASS | `46cde61` | Gate G3, checks 11 and 12 |
| D3.7–D3.8 Dataset, seed, end-to-end | PASS | `bcd26d4`, `aaa62dd`, `b19decf` | Gate G3, checks 13 to 17 |
| D3.9 Release record | PASS | `45b0671`, `6be089d`, `dd33ca5`, and the commit that records the CI run | Gate G3, check 18 |
| After the gate: workbook reader and missing tests | Done | `2221f42`, `bb25faa`, and the commit that records them | "After gate G3"; `review-*` evidence |

Owner of every task: the one contributor. Blockers: none.

## Final known limitations

The full list, with what is not built at all, is
`docs/engineering/known-limitations.md`. The ones that matter most:

| ID | Limitation | Severity | Follow-up phase |
|---|---|---|---|
| L-01 | No authentication or authorisation; one configured workspace; loopback only | Blocks any use beyond a developer machine | Before any exposure |
| L-05 | No deployment: TLS, secrets, backup, monitoring, rate limits | Blocks production | A production-readiness phase |
| L-10 | Preview and commit are synchronous; commit writes row by row; a workbook at both limits takes 41 to 59 s to preview | P2 | When imports grow beyond a few thousand rows: batched writes, a job runner |
| L-35 | A workbook built for the purpose can still cost about a minute and 300 MB; uploads are not limited in number | P2 | Before the upload route faces anyone but its operator: the reader in a process of its own, with a memory and a time limit |
| L-11 | A commit locks every record its rows refer to; a deadlock is answered 409 and must be sent again by the client | P2 | With L-10 |
| L-30 | Two files that create the same new records at the same moment: one fails and must be uploaded again | P2 | With L-10 |
| L-12, L-13 | CSV must be UTF-8 and comma-separated; dates must be `YYYY-MM-DD` or a spreadsheet date cell | P2 | Per-import settings, when a real source needs them |
| L-34 | History is append-only in the service, not in the database | P2 | Before the history is relied on as an audit record |
| L-15 | Natural keys are compared exactly (`TR-001` is not `tr-001`) | P2 | When real source data shows the need |
| L-19 | Nothing can be deleted or archived | P2 | With a retention policy (L-23, L-24) |
| V-03 | One contributor; no independent review | — | Review of the pull request |
| V-05 | No file from a real source system was imported | — | First pilot data |

## XLSX resource-isolation follow-up (after PR #26)

Status: implementation is on branch `fix/xlsx-resource-admission`; automated CI and
independent review are pending. Do not treat the controls below as release-verified
until the pull-request checks pass and the resulting evidence is recorded.

### Defects investigated

- A very small workbook could declare millions of shared-string items and force
  OpenPyXL to materialise a large Python object graph. The worksheet-cell element
  budget did not bound this workbook-global table tightly enough.
- Full XML validation ran against every worksheet, even when the import named one
  worksheet. Corrupt or oversized sibling worksheets could veto otherwise valid data.
- `read_xlsx` opened the same workbook twice, once for cached values and once for
  formula metadata, multiplying parsing time and memory.
- XLSX previews had no admission control, so concurrent requests could hold several
  large workbook object graphs in the same API process.
- The selected worksheet's sparse physical row numbers were not checked against the
  configured scan ceiling before OpenPyXL iterated the source.

### Implementation changes in the hardening branch

1. `app/ingestion/workbook_scan.py` now has independent limits for shared-string
   item count (100,000) and aggregate text characters (8,000,000). It also captures
   formula-cell coordinates in the same streaming scan, applies the physical row
   ceiling to the selected worksheet, and provides a bounded 50-row worksheet probe.
2. `app/ingestion/readers.py` resolves worksheet names through the workbook
   relationships using `defusedxml`, scans workbook-global parts separately from
   worksheet XML, opens only the selected worksheet, and uses one OpenPyXL reader
   pass for cached values plus formula flags. The declared worksheet dimensions are
   not trusted; iteration is restricted to the selected worksheet's permitted columns.
3. `app/ingestion/reader_admission.py` adds a non-blocking one-slot semaphore per
   API process. `ingestion_service.py` uses it for XLSX parsing only. A busy slot is
   returned as `429 XLSX_READER_BUSY`; CSV preview behavior is unchanged.
4. The OpenAPI and API contract document the retryable 429 response.
5. Regression tests now cover the shared-string count and text budgets, malformed
   and oversized unselected worksheets, sparse row overflow, one OpenPyXL load,
   and retryable XLSX reader admission.
6. `scripts/defect_detection.py` now includes mutations for the new guards and
   retargets the old dimension workaround to the custom read-only worksheet override.

### Verification still required

- Run `make lint format-check typecheck test-unit test-api test-integration openapi-check`.
- Run `make verify` and `make e2e` against PostgreSQL 16.16 through Docker Compose.
- Run the defect detector and confirm all 43 mutations are detected, with source
  files restored after every mutation.
- Benchmark representative 1k, 5k and 10k-by-100 workbooks; compare peak RSS and
  wall time against the historical 41–59 second maximum-workbook measurement.
- Run concurrent XLSX preview tests and confirm one request succeeds while another
  receives 429, then succeeds after the slot is released.
- Review the pull request independently. The contributor who wrote the patch must
  not count self-review as the independent review.
- Run `make db-up`, migration, and restart checks on at least one developer machine.

### Boundaries not solved by this follow-up

The semaphore is process-local. Multiple API workers multiply the number of
simultaneous parses. It does not impose a hard memory or wall-clock limit on one
parse, nor does it provide a deployment-wide queue. The upload route remains local
and operator-only until a dedicated, resource-limited reader worker, authentication,
deployment-wide admission control, and independent review are in place.
