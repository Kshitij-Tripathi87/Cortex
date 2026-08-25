# Cortex — RC-1 Enterprise Evidence Platform Certification

**Status:** RC-1 hardening complete. Phase 3 — Operational Intelligence — may begin.

RC-1 is a **blocking certification milestone**: nothing from Phase 3 starts until
these gates are green. The objective is to **prove** that the evidence platform is
correct, deterministic, secure, observable, and trustworthy — not to add capabilities.

## Overview

Cortex turns messy supply-chain exports into trusted, conflict-aware, human-reviewed
operational evidence. The platform compiles raw uploads into typed, provenance-bearing
evidence claims; surfaces conflicts for human review; and computes deterministic
readiness before any downstream graph reasoning consumes the evidence.

## RC-1 Hardening Gates (all green)

| Gate | Owner |
| --- | --- |
| P0-1 Golden Dataset Regression Suite | ✅ `tests/test_golden_dataset.py` (84 cases, deterministic + convergence invariants) |
| P0-2 Domain Event Dispatch | ✅ `app/modules/events/domain_events.py` — `emit_domain_event` now async + validates + dispatches |
| P0-3 Data Quality Framework | ✅ `app/modules/quality/service.py` — real `timeliness` + `integrity` implementations |
| P0-4 Row-Level Security | ✅ `alembic/versions/002_row_level_security.py` — enforced PostgreSQL policies |
| P1-1 Request IDs | ✅ `app/main.py` — UUIDv7 generated server-side, propagated to OTel + logs |
| P1-2 Frontend Audit | ✅ all 6 pages load real data, fixed duplicate `formatDate` + missing `useMemo` import |

## Test Suite

```powershell
cd backend
pytest tests/ -v --tb=short
```

Current state: **99 tests passing**, covering:

- `test_golden_dataset.py` — full pipeline regression against 7-file golden dataset
  - Validation passes for every golden file
  - Profiling row/column counts match golden expectations
  - Profiling byte-determinism (same input → identical output)
  - Profiling order-convergence (shuffled rows → same summary stats)
  - Schema mapping correctness (supplier_name → Supplier.legal_name, etc.)
  - Quality scores in [0.0, 1.0] for every file
  - Anomaly detection: duplicate tax_id reduces integrity
  - Anomaly detection: duplicate line fingerprints in PO line file
  - Performance budget: profiling completes < 5s per file
- `test_modules.py` — RC-1 invariants for every hardened subsystem
  - `uuid7` monotonicity and format
  - Error taxonomy frozen codes + HTTP statuses + wire envelope
  - `DomainEventDispatcher` at-least-once + dedup + handler isolation
  - `emit_domain_event` validates required fields
  - Performance budgets produce ok/alert/breach correctly
  - Data quality: dimension weights sum to 1.0, recommendations fire below threshold
  - Stale business dates reduce timeliness
  - Duplicate IDs reduce integrity
  - Secrets scanner detects AWS/GitHub keys without false positives
- `test_backend.py` — pre-existing unit tests for storage, validation, profiler, mapping

## Backend (FastAPI + Python 3.12)

**Modules:**
- `app/common/` — UUIDv7 IDs, error hierarchy, enums
- `app/infrastructure/` — Database (SQLAlchemy async), S3 client, structured JSON logging, Prometheus metrics, OpenTelemetry tracing
- `app/modules/audit/` — Immutable append-only audit event writer
- `app/modules/sources/` — Storage (content-addressed), validation, profiler, service orchestration
- `app/modules/inference/` — Rules-based schema mapping (alias registry)
- `app/modules/compiler/` — Claim extraction, conflict detection, readiness calculation
- `app/modules/events/` — Domain event dispatcher + integration event outbox
- `app/modules/quality/` — Data Quality Framework (6 dimensions + trust score)
- `app/modules/ontology/expanded.py` — Tiered supplier / BOM / lot / route / carrier ontology
- `app/modules/performance/budgets.py` — CI-enforced performance budgets
- `app/modules/security/hardening.py` — Secrets scanner + RLS policy definitions
- `app/api/v1/` — REST endpoints for sources, audit, readiness

**Database:** PostgreSQL with Alembic migrations
- `001_initial` — Phase 2 tables (audit, sources, compiler)
- `002_row_level_security` — Add tenant_id, enable + force RLS, create tenant + workspace isolation policies

**Observability endpoints:** `/healthz`, `/readyz`, `/metrics`

**API Endpoints:**
- `POST /api/v1/sources/upload` — Upload file
- `GET /api/v1/sources/batches/{id}` — Batch status
- `GET /api/v1/sources/files/{id}/profile` — File profile
- `GET /api/v1/sources/batches/{id}/claims` — List claims
- `GET /api/v1/sources/batches/{id}/conflicts` — List conflicts
- `POST /api/v1/sources/conflicts/{id}/resolve` — Resolve conflict
- `POST /api/v1/sources/batches/{id}/compile` — Extract claims, detect conflicts, compute readiness
- `GET /api/v1/audit` — List audit events
- `POST /api/v1/readiness/batches/{id}` — Compute readiness
- `GET /api/v1/readiness/assessments/{id}` — Get readiness

## Frontend (Next.js 14 + TypeScript)

**Pages (all functional, real backend data, not placeholders):**
- `/` — Home dashboard with cards linking to each workflow
- `/upload` — File upload form with validation feedback + source-system selection
- `/evidence` — Evidence Explorer: filter by state/entity/field/confidence, sort, pagination, claim drawer
- `/conflicts` — Conflict Center: severity/status/blocking filters, claims comparison modal, resolution form
- `/readiness` — Readiness Center: compute readiness for a batch, view state + assumptions, audit history
- `/audit` — Audit Timeline: full event log with category/type/subject filters, date range, payload viewer

## How to Run

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Set environment variables (see backend/AGENTS.md)
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### Nexus Console

Open `http://localhost:3000/nexus` — a dark, dense operational console wired to
real backend data: the live operational graph (`/workspace/graph/subgraph`),
current situation + signals (`/workspace/state`), critical suppliers/SPOFs
(`/workspace/graph/critical-nodes`), and evidence-backed natural-language
queries (`POST /workspace/query/ask`). Every number on screen comes from the
backend; nothing is mocked.

---

# Workflo — Autonomous QA & Runtime Agent CLI

Workflo is a real CLI product (`@cortex/workflo`) with a control plane, not a
terminal mockup. It discovers test surfaces in any project, plans an auditable
execution strategy, runs commands inside an isolated sandbox, streams events,
collects artifacts, diagnoses failures, and emits a report.

## Install (release gate)

```bash
cd workflo-cli
npm pack
npm install -g ./cortex-workflo-*.tgz
workflo --version
```

Then on any project:

```bash
workflo init      # writes .workflo.json
workflo doctor    # env checks + sandbox self-test + control-plane probe
workflo run "run the regression suite and find why checkout is failing"
```

The CLI auto-selects its mode: if the Cortex control plane is reachable
(`CORTEX_URL`, default `http://localhost:8000`) it uses remote sandboxes via the
REST API + SSE event stream; otherwise it falls back to an embedded local
runtime with identical policy semantics.

## CLI command surface

```text
workflo
├── init            # initialize project config
├── doctor          # environment, connectivity, sandbox self-test
├── login           # store API token (~/.workflo/config.json)
├── config get|set  # inspect or change configuration
├── run [intent]    # discover → plan → sandbox → execute → diagnose → report
├── test            # alias of run
├── agent <intent>  # build and display an auditable execution plan
├── sandbox create|inspect|exec|files|destroy
├── artifacts list|fetch
├── report <runId>
└── version
```

## Sandbox isolation model

Each sandbox is a confined root (`workspace/`, `artifacts/`, `tmp/`):

- **filesystem scope** — all file operations resolve inside the sandbox root;
  traversal, absolute paths, UNC paths, drive letters are blocked (HTTP 403)
- **command allowlist** — only approved programs run; docker/kubectl/ssh/etc.
  are hard-blocked
- **network mode** — `none` by default; curl/wget/ping blocked at policy level
- **secret isolation** — sandbox processes inherit only an OS-variable
  allowlist; host secrets never pass through
- **resource caps** — execution timeout, output cap, artifact count/size limits
- **no reuse after destroy** — destroyed sandbox IDs are tombstoned
- **auditability** — every run is a hash-chained event stream (SSE), every
  finding has evidence + suggested fix

Backend module: `backend/app/modules/workflo/` (policy, orchestrator, agent,
runs) exposed under `app/api/v1/workflo.py`:

```text
POST   /api/v1/workflo/sandboxes
GET    /api/v1/workflo/sandboxes/{id}
DELETE /api/v1/workflo/sandboxes/{id}
POST   /api/v1/workflo/sandboxes/{id}/files
GET    /api/v1/workflo/sandboxes/{id}/files[?path=]
POST   /api/v1/workflo/sandboxes/{id}/execute
POST   /api/v1/workflo/runs
GET    /api/v1/workflo/runs/{id}
GET    /api/v1/workflo/runs/{id}/events        # SSE stream
GET    /api/v1/workflo/runs/{id}/artifacts
POST   /api/v1/workflo/agent/plan
POST   /api/v1/workflo/agent/continue
GET    /api/v1/workflo/health
```

## Acceptance gates

- Backend tests: `tests/test_workflo.py` + `tests/test_workflo_api.py`
  (lifecycle, security blocks, contract tests incl. SSE)
- CLI release gate: `.github/workflows/workflo-cli.yml` — npm pack → global
  install → version/help → doctor against a live control plane → sandbox
  create/exec/files/destroy → security blocks (host escape, secret access,
  network violation, unauthorized command, reuse-after-destroy) → run pipeline
- Full stack smoke: `scripts\smoke.bat` / `scripts/smoke.sh` (PostgreSQL,
  Redis, MinIO, APIs, frontend, CLI, real sandbox execution, contract checks)
- Standalone control plane for CI: `scripts/workflo_dev_server.py`

## Architecture Alignment

- Evidence-first: every claim has provenance
- Immutable uploads: content-addressed storage with SHA-256 dedup
- Append-only audit: INSERT-only audit events (audit / domain / integration event separation)
- Deterministic readiness: rules-based conflict detection and readiness calculation
- Human review required: conflicts flagged for review, resolution recorded
- Observability by default: Request ID, Correlation ID, Trace ID in every log line
- Tenant-scoped RLS: enforced PostgreSQL policies (not Python string documentation)

## What's Next (Phase 3+)

Revised Phase 3 sequence — the Evidence → Graph Compiler is the new prerequisite:

```
Evidence Platform (RC-1 ✅)
↓
Evidence → Graph Compiler (NEW)
↓
Operational Graph
↓
Graph Features → Signals
↓
Propagation Engine (its own subsystem)
↓
Scenario Engine → Recommendation Engine → Decision Memory
```

## Documentation

See `docs/` for the complete Phase 1 / Phase 1.5 specification package.