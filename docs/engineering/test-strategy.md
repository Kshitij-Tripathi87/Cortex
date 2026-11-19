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

## Tests that were shown to fail without the behaviour

A test that cannot fail proves nothing. These were run against a deliberately
broken build:

| Test | Broken on purpose | Result |
|---|---|---|
| `test_readiness_does_not_trust_a_connection_that_is_already_open` | Readiness probe through the connection pool | Fails: readiness answers 200 while PostgreSQL refuses new connections |
| `test_two_concurrent_commits_of_one_batch_take_effect_once` | Batch row lock removed | Fails in 3 of 3 runs |

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
| Commit replay, concurrent commit | `tests/integration/test_import_preview_commit.py`, `test_import_idempotency.py` |
| A different file with the same keys; conflicting rows | `tests/integration/test_import_idempotency.py` |
| World State counts equal the database | `tests/api/test_world_state.py`, `tests/integration/test_demo_dataset_e2e.py` |
| Procurement gap, missing confirmation, commitment history | `tests/api/test_world_state.py` |
| Paging, empty workspace, deterministic order, isolation | `tests/api/test_world_state.py`, `tests/api/test_workspace_context.py` |
| Full import, repeat import | `tests/integration/test_demo_dataset_e2e.py` |
| Restart of the API | `tests/integration/test_world_state_persistence.py` (a second instance and a new process), `make e2e` |
| Restart of the database container with its volume | `make e2e`; in CI with Docker Compose |
| Empty migration, repeated migration | `tests/integration/test_migrations.py` |

## What the suite does not cover

- Load, and concurrency beyond a handful of simultaneous commits.
- A real spreadsheet produced by Excel or a supplier portal: workbooks in the
  tests are written by openpyxl.
- Authentication and authorisation, which do not exist in this release.
- Docker Compose on a developer machine other than the CI runner.
