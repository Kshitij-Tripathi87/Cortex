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
| `docker compose -f infra/docker-compose.yml up -d` | NOT RUN on the build machine (no Docker) | CI, see Day 3 |

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
| PostgreSQL starts with a healthy named volume | NOT RUN locally (needs Docker); PostgreSQL 16 itself: PASS |
| API imports and starts without circular imports | PASS |
| `/health/live` works | PASS |
| `/health/ready` verifies PostgreSQL | PASS |
| OpenAPI JSON can be retrieved | PASS |
| Error envelope and request id are wired | PASS |
| Alembic imports metadata deterministically | PASS |
| Ruff and bootstrap tests pass | PASS |
| CI workflow committed | PASS (committed; first run happens on the pull request) |
| Architecture, domain and stack decisions written | PASS |
| This log records evidence and blockers | PASS |

- Status: **PASS**, with one line carried to CI (Compose and the named volume).
- Blockers: none.
- Deferred items: none.

## Work-package status board

| Task | Status | Evidence |
|---|---|---|
| D1.1–D1.8 | PASS | Gate G1 above |
| D2.1–D2.2 Models and migration | NOT STARTED | |
| D2.3–D2.5 Schemas, repositories, services, CRUD | NOT STARTED | |
| D2.6–D2.8 Readers, mapping, validation, preview | NOT STARTED | |
| D2.9 Tests and OpenAPI review | NOT STARTED | |
| D3.1–D3.4 Commit, idempotency, provenance | NOT STARTED | |
| D3.5–D3.6 World State | NOT STARTED | |
| D3.7–D3.8 Dataset, seed, end-to-end | NOT STARTED | |
| D3.9 Release record | NOT STARTED | |
