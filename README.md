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

## Commands

`make help` lists every target. The ones used most:

| Command | What it does |
|---|---|
| `make setup` | Install the locked dependencies |
| `make db-up` / `make db-down` | Start / stop the local databases; the development data volume is kept |
| `make migrate` | Apply the migrations |
| `make run` | Start the API on loopback |
| `make lint`, `make format-check`, `make typecheck` | Ruff and mypy |
| `make test-unit` | Tests that need no database |
| `make test-api`, `make test-integration` | Tests against the dedicated test database |
| `make test` | Everything |
| `make openapi` | Export `docs/engineering/openapi.json` |
| `make smoke` | Check a running API over HTTP |
| `make verify` | The whole verification chain; stops at the first failure |

`make db-reset` deletes the local development database. It is never run by
another target and needs an explicit confirmation phrase.

## Repository layout

```text
.github/workflows/ci.yml     clean-checkout verification
infra/docker-compose.yml     local PostgreSQL (development and test)
scripts/                     wait_for_db, export_openapi, smoke_test, verify_sprint
services/api/                the backend service
  app/core                   settings, clock, logging, errors, request context
  app/db                     declarative base, engine, sessions, readiness checks
  app/api                    dependencies, router, endpoints
  app/models                 ORM models (the registry Alembic reads)
  alembic/                   migrations
  tests/                     unit, api, integration
docs/architecture/           system boundaries, domain model, World State contract, ADRs
docs/engineering/            API contract, OpenAPI document, implementation log
artifacts/sprint/            evidence captured at each gate
```

## Documents

| Document | Content |
|---|---|
| `AGENTS.md` | Invariants and rules for contributors and coding agents |
| `docs/architecture/system-boundaries.md` | Layers and what each one owns |
| `docs/architecture/domain-model.md` | Entities, fields, constraints, history and import policy |
| `docs/architecture/world-state-contract.md` | The World State responses |
| `docs/engineering/api-contract.md` | Conventions, status codes, error codes, routes, import |
| `docs/engineering/implementation-log.md` | What was built each day, with commands and results |

## Configuration

All settings come from the environment or from `.env` (see `.env.example`).
`DATABASE_URL` is mandatory. `NEXUS_DEV_WORKSPACE_ID` names the one workspace
the API serves; the application refuses to start with it set when `APP_ENV`
is not `development` or `test`.
