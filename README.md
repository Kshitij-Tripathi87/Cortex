# Cortex Nexus

Cortex Nexus is being built as a decision-intelligence platform for supply
chains. The first wedge is **critical-equipment procurement for data-centre
projects**, and the first release, v0.1, is the data foundation under it: a
backend that takes procurement records in, validates them, keeps them in
PostgreSQL with their history and their source, and reads them back as one
projection, the World State.

**This is a local prototype.** It has no authentication, serves one configured
development workspace and binds to loopback. It contains no agent, no
language model and no risk scoring: it stores facts, and nothing in it judges
them. `docs/engineering/known-limitations.md` lists what is missing before
any other use.

The repository is a greenfield build. Nothing in it comes from, or depends
on, an earlier Cortex Nexus codebase.

## What v0.1 does

- **Canonical records** in PostgreSQL: projects, suppliers, equipment,
  purchase orders with line items, milestones, supplier commitments. Every
  record belongs to a workspace and every query is scoped to it.
- **History that is never rewritten.** A changed planned date or a changed
  supplier commitment is a new version; the earlier ones stay.
- **Imports in two steps.** `preview` reads a CSV or XLSX file, validates
  every row and writes only a ledger of the source rows. `commit` writes the
  valid rows in one transaction, or nothing. Sending the same file or the same
  commit again changes nothing.
- **Provenance.** Each source row is linked to the record it produced, and
  each version names the source row that introduced it.
- **The World State**: counts, records, current and earlier versions, and
  what is not recorded, read from PostgreSQL on every request.

It does not say whether anything is late or at risk. Those judgements belong
to a later layer.

## Stack

Python 3.12 · FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · PostgreSQL 16 ·
psycopg 3 · uv · pytest · Ruff · mypy · Docker Compose · GitHub Actions.
The reasons are in `docs/architecture/decisions/ADR-001-backend-stack.md`.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed)
- Docker with Compose v2
- GNU Make

## Setup from a clean clone

```bash
git clone <repository-url> cortex-nexus
cd cortex-nexus
cp .env.example .env     # local placeholders only
make setup               # uv sync --frozen
make db-up               # PostgreSQL 16: development on :5432, test on :5433 (loopback)
make migrate             # apply the schema to the development database
make test-unit
```

Start the API:

```bash
make run                 # uvicorn on http://127.0.0.1:8000
```

Check it from another terminal:

```bash
curl -f http://127.0.0.1:8000/health/live     # the process answers
curl -f http://127.0.0.1:8000/health/ready    # PostgreSQL reachable, schema migrated
curl -f http://127.0.0.1:8000/openapi.json    # the API contract
```

Interactive API documentation is at <http://127.0.0.1:8000/docs> while
`APP_ENV` is `development`.

## The demonstration dataset

`data/samples/nexus_demo/` holds a synthetic data-centre project: 8
suppliers, 20 pieces of equipment, 12 purchase orders, 40 milestones, 11
supplier commitments and one revised commitment. `expected.json` beside the
files states what the World State must show after the import.

Import it and check it:

```bash
make seed                # preview and commit every file through the services, then check the result
make run                 # terminal 1
make smoke               # terminal 2: health, API contract, workspace
```

`make seed` writes nothing to a table directly. It calls the same preview and
commit services as the API, and it is safe to run twice.

The same import over HTTP only, with the API running:

```bash
cd services/api
uv run python ../../scripts/seed_demo_data.py --workspace-only   # the API has no route that creates a workspace
uv run python ../../scripts/smoke_test.py --import-demo          # upload, preview, commit, send again, check
```

Or one file by hand:

```bash
WS=http://127.0.0.1:8000/api/v1/workspaces/00000000-0000-4000-8000-000000000001

# Preview: validates every row and stores the source rows. No project is created yet.
curl -s -F entity_type=project -F file=@data/samples/nexus_demo/projects.csv "$WS/ingestion/preview"

# Commit the batch whose id the preview returned.
curl -s -X POST "$WS/ingestion/<batch_id>/commit"

# Read it back. The project id is in the list of projects.
curl -s "$WS/world-state/summary"
curl -s "$WS/world-state"
curl -s "$WS/projects"
curl -s "$WS/world-state/projects/<project_id>?include_history=true"
```

A new file is answered 201 by the preview. A file that was imported before
is answered 200 with its existing batch (`duplicate_file: true`), and its
commit returns the recorded result (`replayed: true`). Nothing is written
twice.

Files are imported in the order of their references: projects, suppliers,
equipment, purchase orders, line items, milestones, supplier commitments.

## Verification

```bash
make verify              # configuration, lockfile, databases, migrations, Ruff, mypy, all tests, OpenAPI
make e2e                 # the same, then the end-to-end demonstration
```

`make e2e` starts the API as its own process, imports the dataset over HTTP,
sends it again, runs the seed on top, restarts the API and PostgreSQL, and
checks that the World State is identical each time. It writes to the
development database and restarts the database containers.

`scripts/defect_detection.py` answers a different question: do the tests fail
when the behaviour they guard is removed? It breaks the code in 26 chosen
ways, one at a time, and expects a failing test each time
(`docs/engineering/test-strategy.md`). It edits source files while it runs
and puts each one back; run it on a clean working tree.

## Commands

`make help` lists every target.

| Command | What it does |
|---|---|
| `make setup` | Install the locked dependencies |
| `make db-up` / `make db-down` | Start / stop the local databases; the development data volume is kept |
| `make migrate` | Apply the migrations |
| `make migration-check` | One migration head, applied, and equal to the models |
| `make run` | Start the API on loopback |
| `make lint`, `make format-check`, `make typecheck` | Ruff and mypy (strict) |
| `make test-unit` | Tests that need no database |
| `make test-api`, `make test-integration` | Tests against the dedicated test database |
| `make test` | Everything |
| `make coverage` | Everything, with a coverage report |
| `make seed` | Import the demonstration dataset through the services |
| `make smoke` | Check a running API over HTTP |
| `make openapi` / `make openapi-check` | Export `docs/engineering/openapi.json` / fail if it is stale |
| `make verify` | The whole verification chain; stops at the first failure |
| `make e2e` | The chain plus the end-to-end demonstration with restarts |

`make db-reset` deletes the local development database. It is never run by
another target and needs an explicit confirmation phrase.

## Repository layout

```text
.github/workflows/ci.yml     clean-checkout verification, end to end; defect detection
infra/docker-compose.yml     local PostgreSQL (development and test)
data/samples/                the demonstration dataset and validation examples
scripts/                     wait_for_db, export_openapi, seed_demo_data, demo_checks,
                             smoke_test, verify_sprint, defect_detection
services/api/                the backend service
  app/core                   settings, clock, logging, errors, request context
  app/db                     declarative base, engine, sessions, readiness checks
  app/models                 ORM models (the registry Alembic reads)
  app/schemas                request and response shapes
  app/repositories           workspace-scoped queries; they never commit
  app/services               business rules and transactions
  app/ingestion              reading, column mapping, normalization, row validation (no database)
  app/api                    dependencies, router, endpoints
  alembic/                   migrations
  tests/                     unit, api, integration
docs/architecture/           system boundaries, domain model, World State contract, ADRs
docs/engineering/            API contract, OpenAPI document, test strategy, limitations, log
artifacts/sprint/            evidence captured at each gate
```

## Documents

| Document | Content |
|---|---|
| `AGENTS.md` | Invariants and rules for contributors and coding agents |
| `docs/architecture/system-boundaries.md` | Layers and what each one owns |
| `docs/architecture/domain-model.md` | Entities, fields, constraints, history, import policy, concurrent writers |
| `docs/architecture/world-state-contract.md` | The World State responses |
| `docs/engineering/api-contract.md` | Conventions, status codes, error codes, routes, import |
| `docs/engineering/openapi.json` | The machine-readable contract, exported from the code |
| `docs/engineering/test-strategy.md` | Test levels, rules, where each scenario is tested, what is not covered |
| `docs/engineering/known-limitations.md` | What is not built, the limits of what is, the limits of the verification |
| `docs/engineering/implementation-log.md` | What was built each day, with commands, results and gate decisions |
| `artifacts/sprint/README.md` | The evidence files and where each was produced |

## Configuration

All settings come from the environment or from `.env` (see `.env.example`).
`DATABASE_URL` is mandatory. `NEXUS_DEV_WORKSPACE_ID` names the one workspace
the API serves; the application refuses to start with it set when `APP_ENV`
is not `development` or `test`.
