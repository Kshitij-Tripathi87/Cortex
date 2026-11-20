# Test strategy

The suite proves behaviour, not coverage. A test passes when it shows a
specific assertion of the contracts, not when a route answers 200.

## Levels

| Level | Location | Needs | What it proves |
|---|---|---|---|
| Unit | `services/api/tests/unit` | Nothing | Pure logic: readers, column mapping, normalization, row validation against a snapshot, data-quality dimensions, World State assembly, settings, clock, log redaction |
| API | `services/api/tests/api` | Test database | The HTTP contract: status codes, the error envelope, response shapes, workspace boundary, upload checks, preview, commit, World State |
| Integration | `services/api/tests/integration` | Test database | Persistence and transactions: migrations, constraints written past the services, import lifecycle, rollback, idempotency, concurrency, history, provenance, workspace isolation, persistence across processes, the demo dataset end to end |
| End to end | `scripts/verify_sprint.py --e2e` | Development database, a free port | A real API process: import, World State, restart of the API and of PostgreSQL, World State again |

`make test-unit`, `make test-api`, `make test-integration`, `make test`,
`make e2e`.

## Rules

- **PostgreSQL only.** Database tests run on PostgreSQL 16. SQLite is never
  a substitute: JSONB, composite foreign keys, row locks and transaction
  semantics differ.
- **A dedicated test database.** `TEST_DATABASE_URL`. The suite refuses to
  run unless the database name ends in `_test`, because it empties tables.
- **The schema comes from the migrations.** The suite runs
  `alembic upgrade head` once; nothing calls `create_all`.
- **Each test owns its data.** Every table is emptied before each database
  test. Tests do not depend on the order in which they run.
- **Real paths.** Service and API tests use the real services, repositories
  and database. Factories write records only to set a scene; the behaviour
  under test goes through the service or the API.
- **No wall clock.** Dates are fixed; the reference date of the dataset is
  `NEXUS_DEMO_AS_OF=2026-11-19`. Where a timestamp matters, the service clock
  is pinned (`app.core.clock.frozen_at`).
- **Warnings are errors.** A deprecation in a dependency fails the suite
  instead of scrolling past.
- **No network.** Nothing calls a supplier system, a model provider or a
  cloud API.
- **A missing database fails, it does not skip.** A skipped database test is
  a false green.
- **Concurrency is tested with a held lock, not with luck.** A test that
  starts two writers and checks the outcome can pass without the lock it is
  meant to prove, because the race may fall the harmless way. The tests in
  `tests/integration/test_concurrency.py` therefore hold a row lock in one
  session, start the writer under test, and wait until PostgreSQL itself
  reports that writer as waiting for a lock (`pg_stat_activity`). Only then is
  the lock released. Without the lock in the code the writer never waits and
  the test fails every time.
- **A workbook is also tested as bytes, not only as a spreadsheet.** A
  spreadsheet library writes only what a spreadsheet program would write.
  The reader must also refuse what such a program never writes: XML that
  declares entities, a megabyte of empty cell formats, a worksheet that
  states a smaller range than it holds, two rows with one number.
  `tests/workbooks.py` builds such archives part by part, and
  `tests/unit/test_workbook_safety.py` reads them. Its first test reads a
  hand-written workbook that is in order, so that a refusal in the others is
  known to come from the content and not from the way the archive was made.

## Tests that were shown to fail without the behaviour

A test that cannot fail proves nothing. Each line below is a defect that is
put into the code on purpose, one at a time; the tests named are run, and the
file is restored.

`scripts/defect_detection.py` holds defects 1 to 43 and runs them in one go:

```bash
cd services/api
uv run python ../../scripts/defect_detection.py
```

It reports `DETECTED` only when the tests ran and at least one failed, and it
ends with exit code 1 when a defect leaves every test green or when the text
it replaces is no longer in the code. The pre-hardening run is recorded in
`artifacts/sprint/review-defect-detection.txt` (37 of 37 detected). This phase
adds six mutations for shared-string count, aggregate shared text, physical
row limits, unselected-sheet isolation, formula-cell provenance and import
admission. CI run #275 passed the unchanged baseline (380 selected tests),
detected all 43 of 43 mutations, and passed the file-restoration check.

This is not an automated mutation run. The defects are chosen by hand, one
per behaviour that matters most (row locks, workspace filters, bounds, the
answer to a deadlock), and behaviour outside this list has no such evidence.
The script edits source files while it runs, so it is not part of
`make verify`. CI runs it in a job of its own, beside the main job, on a
checkout that is thrown away.

| # | Broken on purpose | Detected by | Result |
|---|---|---|---|
| 1 | Readiness probe goes through the connection pool | `test_health.py::test_readiness_does_not_trust_a_connection_that_is_already_open` | Fails: 200 while PostgreSQL refuses new connections |
| 2 | Import commit reads purchase orders without a row lock | `test_concurrency.py::test_a_commitment_import_waits_for_a_writer_that_holds_the_purchase_order` | 1 failed |
| 3 | Appending a commitment through the API does not lock the purchase order | `test_concurrency.py` (the API commitment waits; a commitment that became current while waiting is not appended twice) | 2 failed |
| 4 | Import commit reads milestones without a row lock | `test_concurrency.py` (milestone import) | 1 failed |
| 5 | Appending a plan version through the API does not lock the milestone | `test_concurrency.py` (API re-plan) | 1 failed |
| 6 | Commit does not lock the batch row | `test_concurrency.py::test_a_second_commit_waits_for_the_first_and_then_reports_its_result`, `test_two_concurrent_commits_of_one_batch_take_effect_once` | 2 failed |
| 7 | Preview does not look again after losing the race for a new file | `test_concurrency.py` (both upload-race tests) | 2 failed |
| 8 | World State reads the latest commitment with one query per purchase order | `test_world_state_queries.py` | 1 failed |
| 9 | Text with a NUL character passes the request schema | `test_unstorable_values.py` | 5 failed |
| 10 | Imports do not bound whole numbers | `test_unstorable_values.py`, `test_normalization.py` | 8 failed |
| 11 | `sequence_no` has no upper bound in the API | `test_unstorable_values.py` | 3 failed |
| 12 | `offset` of the lists has no upper bound | `test_unstorable_values.py` | 6 failed |
| 13 | Offsets of the project World State have no upper bound | `test_unstorable_values.py` | 1 failed |
| 14 | The stored file name keeps control characters | `test_unstorable_values.py` | 1 failed |
| 15 | No handler for a value the database refuses | `test_unstorable_values.py` | 1 failed |
| 16 | Decimal places are counted after rounding to the arithmetic precision | `test_normalization.py::test_a_digit_far_to_the_right_is_still_seen` | 1 failed |
| 17 | Commit has no branch for a value the database refuses | `test_import_preview_commit.py::test_a_value_the_database_cannot_store_fails_the_batch_and_says_what_to_do` | 1 failed |
| 18 | A deadlock during commit is treated like an outage | `test_concurrency.py::test_a_commit_ended_by_a_deadlock_writes_nothing_and_can_be_sent_again` | 1 failed |
| 19 | A deadlock on a JSON route is answered 503 | `test_error_envelope.py::test_a_deadlock_is_a_conflict_to_retry_not_an_outage` | 1 failed |
| 20 | `sequence_no` accepts `"1"`, `1.0` and `true` | `test_unstorable_values.py` | 3 failed |
| 21 | Project lookup by id ignores the workspace | `test_workspace_isolation_http.py` | 4 failed |
| 22 | Purchase-order lock by id ignores the workspace | `test_workspace_isolation_http.py` | 1 failed |
| 23 | Milestone lookup by id ignores the workspace | `test_workspace_isolation_http.py` | 3 failed |
| 24 | Batch lock for commit ignores the workspace | `test_workspace_isolation_http.py` | 1 failed |
| 25 | Equipment list ignores the workspace | `test_workspace_isolation_http.py` | 1 failed |
| 26 | World State counts ignore the workspace | `test_workspace_isolation_http.py` | 1 failed |
| 27 | A worksheet is read only as far as the range it claims | `test_workbook_safety.py` | 5 failed; detected in CI #275 |
| 28 | Workbook-level XML is not checked before openpyxl materializes it | `test_workbook_safety.py` | 6 failed; detected in CI #275 |
| 29 | The reader loads without the hardened XML parser | `test_workbook_safety.py` | 1 failed; detected in CI #275 |
| 30 | An over-wide worksheet row is silently truncated | `test_readers.py::test_xlsx_row_and_column_limits` | 1 failed; detected in CI #275 |
| 31 | Two rows of a worksheet may carry the same number | `test_workbook_safety.py` | 4 failed; detected in CI #275 |
| 32 | Two cells of a row may carry the same reference | `test_workbook_safety.py` | 2 failed; detected in CI #275 |
| 33 | Formats and structure of a workbook are not counted | `test_workbook_safety.py` | 3 failed; detected in CI #275 |
| 34 | A single tag or text of any length is handed to the parser | `test_workbook_safety.py` | 4 failed; detected in CI #275 |
| 35 | An error message quotes every worksheet name in full | `test_workbook_safety.py` | 2 failed; detected in CI #275 |
| 36 | A worksheet name of any length is passed on to the ledger | `test_workbook_safety.py` | 1 failed; detected in CI #275 |
| 37 | Two worksheets of a workbook may share a name | `test_workbook_safety.py` | 1 failed; detected in CI #275 |
| 38 | Shared-string count is not bounded before openpyxl loads it | `test_workbook_safety.py` | 1 failed; detected in CI #275 |
| 39 | Aggregate shared-string text is not bounded before materialization | `test_workbook_safety.py` | 1 failed; detected in CI #275 |
| 40 | A selected worksheet can exceed the physical row scan limit | `test_workbook_safety.py::test_selected_sheet_row_numbers_are_bounded_before_iteration` | 1 failed; detected in CI #275 |
| 41 | Unselected worksheet XML is scanned with the selected worksheet | `test_workbook_safety.py` | 2 failed; detected in CI #275 |
| 42 | Formula locations from the bounded scan are ignored | `test_workbook_safety.py` | 2 failed; detected in CI #275 |
| 43 | The import admission limit is removed | `test_import_concurrency.py` | 1 failed; detected in CI #275 |
| by hand | Batch row lock removed, checked against the older race test | `test_import_preview_commit.py::test_two_concurrent_commits_of_one_batch_take_effect_once` | Fails in 5 of 5 runs |

One test was found **not** to prove what its name suggests.
`test_two_batches_that_touch_the_same_order_allocate_distinct_versions`
passes in 5 of 5 runs with the purchase-order lock removed: the race falls
the harmless way on this machine. It is kept as a check of the outcome; the
evidence for the lock is defect 2.

## Where each required scenario is tested

| Scenario (playbook section 19) | Test |
|---|---|
| Readiness success, failure, liveness independence | `tests/api/test_health.py` |
| OpenAPI contract | `tests/api/test_error_envelope.py`, `make openapi-check` |
| Natural keys, per-workspace uniqueness | `tests/integration/test_model_constraints.py` |
| Equipment without a purchase order | `test_model_constraints.py`, `tests/api/test_suppliers_equipment.py` |
| Line item with equipment of another project | `test_model_constraints.py` (database), `tests/api/test_purchase_orders.py` (service), `tests/unit/test_row_validation.py` (import) |
| Cross-workspace supplier | `test_model_constraints.py`, `tests/integration/test_workspace_isolation.py` |
| Zero quantity, decimal precision, duplicate line | `test_model_constraints.py`, `tests/api/test_purchase_orders.py` |
| First, revised and replayed commitment; order of history | `tests/api/test_purchase_orders.py`, `tests/integration/test_history_provenance.py` |
| First, revised and replayed milestone plan | same files |
| Provenance of a version | `tests/integration/test_history_provenance.py` |
| CSV BOM, duplicate headers, blank rows, encoding, limits | `tests/unit/test_readers.py` |
| XLSX sheet selection, ambiguity, formulas, malformed and oversized workbooks | `tests/unit/test_readers.py` |
| Aliases, unknown columns, alias collisions | `tests/unit/test_column_mapping.py` |
| Ambiguous dates, exact decimals, enum aliases | `tests/unit/test_normalization.py` |
| Required fields, references, duplicates, currency | `tests/unit/test_row_validation.py` |
| Preview writes the ledger and no canonical record | `tests/api/test_ingestion_preview.py` |
| Duplicate checksum, missing dependency | `tests/api/test_ingestion_preview.py`, `tests/integration/test_import_preview_commit.py` |
| Commit of the valid subset | `tests/integration/test_import_preview_commit.py`, `tests/api/test_ingestion_commit.py` |
| Reference drift between preview and commit | same files |
| Rollback on a failure in the middle of a batch | `tests/integration/test_import_preview_commit.py` |
| Commit replay, concurrent commit | `tests/integration/test_import_preview_commit.py`, `test_import_idempotency.py`, `test_concurrency.py` |
| Writers on the same purchase order or milestone; the same new file uploaded at once; a deadlock | `tests/integration/test_concurrency.py` |
| Values the database cannot hold (NUL in text, whole numbers and offsets beyond 32 bits, very long decimals) | `tests/api/test_unstorable_values.py`, `tests/unit/test_normalization.py` |
| A different file with the same keys; conflicting rows | `tests/integration/test_import_idempotency.py` |
| World State counts equal the database | `tests/api/test_world_state.py`, `tests/integration/test_demo_dataset_e2e.py` |
| Procurement gap, missing confirmation, commitment history | `tests/api/test_world_state.py` |
| Paging, empty workspace, deterministic order, isolation | `tests/api/test_world_state.py`, `tests/api/test_workspace_context.py` |
| An id of another workspace on every route that takes an id | `tests/api/test_workspace_isolation_http.py` (the list of routes is read from the OpenAPI document; a new route without a case fails) |
| World State cost does not grow with the data | `tests/integration/test_world_state_queries.py` (statement count) |
| The demo dataset as an Excel workbook with typed cells | `tests/integration/test_demo_dataset_e2e.py` |
| Full import, repeat import | `tests/integration/test_demo_dataset_e2e.py` |
| Restart of the API | `tests/integration/test_world_state_persistence.py` (a second instance and a new process), `make e2e` |
| Restart of the database container with its volume | `make e2e`; in CI with Docker Compose |
| Empty migration, repeated migration | `tests/integration/test_migrations.py` |

## What the suite does not cover

- Load and soak. Concurrency is tested with held locks and with races of up
  to six writers; timings of large files were measured once
  (`known-limitations.md`, L-10) and are not asserted.
- Deadlocks between two imports: the test builds one deadlock, between an
  import and another writer, and it relies on PostgreSQL's default
  `deadlock_timeout`.
- A real spreadsheet produced by Excel or a supplier portal: workbooks in the
  tests are written by openpyxl or by hand. `scripts/compare_workbooks.py`
  reads a directory of real workbooks with the service's reader and compares
  each worksheet with an independent reading; it was run once over 36
  workbooks written by Excel and LibreOffice (`known-limitations.md`, V-05)
  and is not part of the suite, because those files are not in the repository.
- The cost of reading a workbook. The tests show that a workbook asking for
  too much is refused; the new single-load implementation's latency and peak
  memory are not yet benchmarked. The pre-hardening timing is recorded in
  `known-limitations.md`, L-10.
- Authentication and authorisation, which do not exist in this release.
- Docker Compose on a developer machine other than the CI runner.


## XLSX hardening cases added after PR #26

- Shared-string item count is bounded before openpyxl materializes the table.
- Aggregate decoded shared-string text has an independent limit.
- The selected worksheet's physical row numbering is bounded before iteration.
- A large, malformed or hidden unselected worksheet is not parsed when another sheet is selected.
- A workbook with several visible sheets requires explicit selection; the reader does not probe tabs to infer intent.
- Formula coordinates are captured during the bounded XML scan while cached values are read from one `data_only=True` workbook.
- Import admission is tested at the ASGI boundary: the second simultaneous import gets a 429 before the route/parser runs.
- A separate test asserts that openpyxl is invoked exactly once per workbook preview.

The performance claim remains open until the same full-limit benchmark is rerun against this branch.
