# ADR-001: Backend stack for the v0.1 sprint

- Status: accepted (2026-11-19)
- Scope: the three-day greenfield sprint and the phases that build directly on it

## Context

Cortex Nexus is rebuilt from an empty repository. The first deliverable is a
backend vertical slice: import procurement data, keep it with history and
provenance in PostgreSQL, and read it back as the World State. The sprint has
no time to compare frameworks, and it must be reproducible from a clean
checkout.

## Decision

One stack, fixed for the sprint.

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Mature ecosystem, predictable runtime |
| API | FastAPI | Typed routes and a generated OpenAPI document |
| Contracts | Pydantic 2 | Explicit request and response schemas, strict decimals and dates |
| ORM | SQLAlchemy 2.x (typed declarative, synchronous sessions) | Explicit relational model and transaction control |
| Migrations | Alembic | Versioned, reviewable schema changes |
| Database | PostgreSQL 16 | Relational integrity, composite foreign keys, JSONB for source rows, row locks |
| Driver | psycopg 3 (`psycopg[binary]`) | Maintained PostgreSQL driver |
| Uploads | python-multipart | Required by FastAPI for multipart forms |
| Spreadsheets | openpyxl | XLSX reading without executing formulas or macros |
| Server | uvicorn | Runs the ASGI application; used by every documented command |
| Packaging | uv, `uv.lock` | Reproducible resolution; `uv sync --frozen` in CI |
| Tests | pytest, httpx2 | Unit, API, integration and end-to-end tests |
| Lint and format | Ruff | One fast tool for both |
| Types | mypy (strict) | One type checker; pyright is not used |
| Local database | Docker Compose | The same PostgreSQL for every contributor and for CI |
| CI | GitHub Actions | Clean-checkout verification on every pull request |

Synchronous SQLAlchemy sessions are used on purpose. The service is
transaction-heavy and I/O-light; one session per request and one explicit
transaction per service operation are easier to reason about, and to prove
correct, than an async session shared across awaits.

### Two differences from the dependency list in the playbook

| Playbook | This repository | Reason |
|---|---|---|
| `httpx` (dev) | `httpx2` (dev) | The test client of the locked Starlette release deprecates `httpx` and asks for `httpx2`, its continuation by the same author. The test suite treats warnings as errors, so the deprecated package cannot be used silently. Same API, same role |
| (not listed) | `uvicorn` (runtime) | The playbook's own commands start the API with `uvicorn`; it has to be a declared dependency |

No other dependency was added.

## Version-lock policy

- `pyproject.toml` declares lower bounds; `uv.lock` pins every package and is
  committed. Version numbers are never copied from a document.
- `uv sync --frozen` is the only install command in CI and in the Makefile.
  It fails when the lockfile and `pyproject.toml` disagree.
- A dependency is added only for a named task, with the reason recorded in
  this file or in the implementation log, and the lockfile is updated in the
  same commit.
- PostgreSQL is pinned to an explicit minor release in
  `infra/docker-compose.yml` and moved deliberately.
- Python is pinned to 3.12 in `.python-version` and `requires-python`.

## Local infrastructure

Docker Compose runs two PostgreSQL 16 instances on loopback: `postgres`
(development, data in a named volume) and `postgres-test` (test suite, data
in memory). Nothing else: no Redis, queue, vector store or graph database.

## Rejected for this sprint

| Alternative | Why not now |
|---|---|
| A graph database for the World State | The World State is a projection of relational facts. A second store could drift from them |
| Async SQLAlchemy | No measured need; harder transaction and session reasoning |
| Native PostgreSQL enum types | Changing them needs `ALTER TYPE` and careful downgrades. Text columns with `CHECK` constraints give the same guarantee and plain migrations |
| pandas for file parsing | The standard `csv` module and openpyxl are enough, and parsing must stay strict and inspectable |
| SQLite for tests | JSONB, composite foreign keys, row locks and transaction semantics differ. Database tests run on PostgreSQL only |
| Celery, Redis, Kafka | Preview and commit are synchronous and bounded |
| An agent or LLM framework, a vector store | No agent exists in this release; facts are never produced by a language model |
| pyright in addition to mypy | One type checker |

## When to revisit

- Imports grow beyond what one request should hold open: introduce a job
  runner, and only then a queue.
- World State reads become measurably slow: add a materialised projection
  with a tested refresh, not before.
- The API must be reachable beyond loopback: authentication, membership and
  roles come first (see `docs/engineering/known-limitations.md`).
- An enumeration starts changing often: reconsider a reference table.
