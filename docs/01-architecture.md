# 01 — System Architecture (Enterprise Blueprint)

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | — |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose of this document

This document freezes the high-level system architecture and product boundaries
for Cortex. Every later Phase 1 document refines a concern defined here and must
be consistent with it. If any later document appears to conflict, this document
is authoritative and the later document must be corrected via an ACR.

---

## 2. What Cortex is

Cortex is an **evidence-first operational intelligence platform for supply
chains**. It helps an organization answer, with auditable evidence:

- What is happening.
- Why it is happening and what evidence supports it.
- What is connected to it and how risk propagates.
- What scenarios may occur next and what options exist.
- What assumptions drive a recommendation.
- What decision was made and what happened after it.

Cortex maintains the operational graph of a supply chain as its reasoning
substrate and treats every asserted fact as a claim that must be backed by
evidence. The decision layer is deterministic and human-reviewed; machine
learning is a bounded, optional support layer that never overrides evidence or
human judgment.

### 2.1 What Cortex is not

- Not an ERP. Cortex consumes ERP/WMS/TMS exports; it does not replace
  transactional systems of record.
- Not a dashboard product. Cortex is an operational workspace with review
  workflows, not a read-only reporting tool.
- Not a forecasting company. Forecasts may be an input; Cortex reasons about
  evidence, not predictions as truth.
- Not an autonomous agent system. Cortex never acts on the operational world
  without a human decision.
- Not a generic chatbot or an LLM product. Natural-language interfaces, if
  present, are read-only commentary over the evidence layer.
- Not a black-box ML platform. ML outputs are evidence candidates, never facts.

### 2.2 What Cortex must remain

- Evidence-first.
- Graph-first.
- Deterministic at the decision layer.
- Human-reviewed where a material claim or decision is involved.
- Auditable.
- Secure.
- Versioned.
- Enterprise-ready (multi-tenant, isolated, portable).

---

## 3. System style

Cortex is a **modular monolith** by default. A single deployable backend service
contains strictly separated modules with enforced boundaries. A service is split
out only when there is a concrete, measurable reason (independent scale,
independent failure mode, or a security isolation requirement). No split is
performed in Phase 1 or Phase 2.

### 3.1 Runtime components

| Component | Technology | Role | Phase 1 status |
|---|---|---|---|
| Backend API | FastAPI (Python 3.12) | Synchronous request handling, orchestration, all business logic | Specified |
| Background worker | Python worker (same codebase, separate process) | Long-running jobs: parsing, validation, entity resolution, graph rebuild, signal evaluation | Specified |
| Authoritative store | PostgreSQL 16 | Canonical entities, claims, evidence, conflicts, graph refs, versions, audit, decisions | Specified |
| Object storage | S3-compatible (MinIO locally) | Immutable raw uploads, evidence artifacts, snapshots, model artifacts, synthetic datasets | Specified |
| Frontend | Next.js 14 (App Router, TypeScript) | Operational workspace UI | Specified |
| Graph abstraction | SQL-backed adjacency in PostgreSQL + in-process graph library | Operational graph read/write and traversal | Specified |
| ML platform | Bounded Python services + model registry in PG + artifacts in S3 | Synthetic data, feature store, registry, shadow inference | Specified (bounded) |
| Cache / queue | Redis 7 | Job queue (RQ/arq), caching, idempotency keys, rate limiting | Specified |
| Observability | OpenTelemetry → structured logs + Prometheus metrics + Tempo traces | Logs, metrics, traces | Specified |

### 3.2 Why modular monolith

- Phase 1–2 scope does not justify distributed-systems overhead.
- A single codebase keeps the evidence, graph, event, and audit models coherent
  and transactional — critical when every write must be auditable together.
- Module boundaries are enforced by linters (import rules), internal API
  contracts, and layered package structure so that a future split is mechanical.

### 3.3 Module split triggers (for later, not Phase 2)

A module may be extracted into a separate service only if ALL of these are true:
- It has an independent scale profile measured in production.
- It has a distinct failure mode that should not take down ingestion/review.
- It has a clear contract that can be served over a versioned internal API.
- Audit/evidence coherence can still be guaranteed (events are emitted before
  the external effect, with the same event schema as the monolith).

No Phase 1 or Phase 2 module qualifies. The triggers are documented so future
architects do not invent splits.

---

## 4. Conceptual data flow

### 4.1 Platform foundation flow (MVP)

```
Upload (raw file, immutable)
  → Validation (format, signature, size, path)
  → Schema mapping (source columns → canonical fields)
  → Evidence extraction (claims + evidence records)
  → Entity resolution (external ids → canonical ids)
  → Conflict detection (overlapping claims → conflicts)
  → Human review (conflicts, suspect claims)
  → Canonical entities (versioned, valid_from/valid_to)
  → Graph construction (versioned edges + snapshot)
  → Deterministic readiness decision (graph is usable for intelligence?)
```

Each arrow emits audit events; each box is a module boundary. Phase 2 implements
this flow. Phase 1 only specifies it.

### 4.2 Operational intelligence flow (later phases)

```
Canonical graph (MVP output)
  → Signal detection (deterministic rules over the graph)
  → Scenario creation (counterfactual / projected graph variants)
  → Recommendation generation (deterministic policies + bounded ML candidates)
  → Decision approval (human review, recorded)
  → Outcome recording (later evidence updates the graph; loop closes)
```

Signals, scenarios, recommendations, and decision memory are deterministic
contracts. Bounded ML may propose candidate signal scores or scenario parameters
as **evidence candidates** but never as facts.

---

## 5. Core principles (frozen, enforced)

Each principle has a concrete enforcement rule so it cannot degrade into a
vague guideline.

### 5.1 Evidence first
- Every canonical attribute is backed by at least one claim.
- Every claim is backed by at least one evidence record pointing to an immutable
  source object.
- No API may return a canonical fact without exposing its evidence.
- Enforcement: repository layer rejects writes of canonical attributes that
  carry no evidence id; a linter rule forbids serializers that drop evidence
  fields.

### 5.2 Graph first
- Relationships are first-class. The operational graph is the source of truth
  for connectedness. Relational tables are a materialization/in-memory-cache
  source for the graph, not the reasoning surface.
- No business rule reasons directly over raw tables when a graph edge exists
  for the same relationship.
- Enforcement: the graph access module is the only allowed reader/writer of
  adjacency; other modules import only the graph facade.

### 5.3 Human review required
- Material claims and every decision require an explicit human approval record.
- An unreviewed material claim cannot be promoted to canonical "accepted"
  state; the system must hold it in `pending_review`.
- Enforcement: state machine transitions are centralized; the
  `decisions` and `reviews` tables have NOT NULL `approved_by` plus
  `approved_at` for any accepted/decided state.

### 5.4 Immutable inputs
- Raw uploads are write-once. After ingest validation, an upload object becomes
  immutable: its bytes and its declared schema mapping cannot be changed. New
  corrections arrive as new uploads or as review records.
- Enforcement: object storage lifecycle + database `uploads` row marked
  `immutable_since`; no UPDATE path exists on raw bytes or schema mapping.

### 5.5 Append-only audit
- Audit events are append-only. There is no UPDATE or DELETE on audit tables.
- Enforcement: database role grants INSERT-only on audit tables to the
  application; migrations never create UPDATE/DELETE grants; a startup check
  verifies grants and fails closed otherwise.

### 5.6 Version everything
- Canonical entities, graph edges, graph snapshots, events, schemas, model
  artifacts, and API contracts are all versioned.
- Enforcement: schema registry with versions; every record carries
  `(version, valid_from, valid_to)` or an equivalent contract version.

### 5.7 Explainability required
- Every recommendation, signal, and scenario carries a human-readable and
  machine-readable explanation composed only of evidence references and the
  deterministic rule that fired.
- Enforcement: recommendation/sign/scenario serializers require a non-empty
  `explanation` with >=1 evidence id; tests assert it.

### 5.8 Deterministic decision contract
- Decisions and recommendations are produced by deterministic functions of
  (graph state, policy version, evidence). Same inputs ⇒ identical outputs.
- Enforcement: a decision/recommendation record stores the
  `policy_version` and a content hash of its inputs; replay tests must
  reproduce the exact output.

### 5.9 Bounded ML only
- ML may only produce candidates: candidate signal scores, candidate scenario
  parameters, candidate synthetic datasets. It may never write canonical facts,
  graph edges, decisions, or audit records directly.
- Enforcement: the ML module has no DB write grants to canonical/audit tables;
  it writes only to `ml_*` tables and submits candidates to a review queue.

---

## 6. Backend / frontend / storage / worker / graph / ML / decision logic boundaries

### 6.1 Backend owns
- All ingestion, validation, schema mapping, evidence extraction, entity
  resolution, conflict detection, canonical persistence, graph construction,
  signal/scenario/recommendation computation, decision recording, audit
  emission, authn/z enforcement, and API surface.
- The backend is the only writer to PostgreSQL canonical/audit tables and the
  only reader of raw object storage for parsing.

### 6.2 Frontend owns
- Workspace UI, navigation, flow orchestration, evidence/conflict/decision
  review surfaces, graph exploration, model center (read-only), admin.
- The frontend NEVER calls models, raw storage, or the database directly. It
- consumes only documented backend APIs. It holds no business rules; all rules
  live in the backend. Frontend state is presentation/orchestration only.

### 6.3 Object storage owns
- Immutable raw uploads, evidence artifacts (extracted tables, page images),
- graph snapshots, model artifacts, synthetic datasets, exports. All writes are
- append-only or lifecycle-managed. The backend is the sole writer; the frontend
- reaches storage only through short-lived signed URLs issued by the backend.

### 6.4 Background workers own
- Long-running jobs dispatched by the backend: parsing, validation,
- entity-resolution graph rebuilds, signal evaluation sweeps, snapshot
- generation, synthetic data generation, model training (sandboxed), exports.
- Workers run the same module code as the backend (shared service layer) but
- never serve the public API. Workers emit the same audit events.

### 6.5 Graph logic owns
- Adjacency read/write, traversal, path queries, impact propagation
- (deterministic), snapshot diffing, temporal queries. The graph is stored in
- PostgreSQL (adjacency tables + materialized views), not in a separate graph
- DB in Phase 1/2. The graph module is the only reader/writer of adjacency.

### 6.6 ML logic owns
- Synthetic data generation, feature computation, model training (sandboxed),
- model registry, shadow inference, calibration. It writes only to `ml_*`
- tables and submits candidates as evidence candidates. It cannot emit
- decisions or write canonical/audit tables.

### 6.7 Deterministic decision logic owns
- The policies that turn (graph state, evidence, signals, scenarios) into
- recommendations and decisions. These are pure functions of inputs and
- `policy_version`. They live in the backend `decision` module and are
- independently tested. ML candidates are inputs to this layer, not outputs
- of it.

---

## 7. Logical backend modules (modular monolith)

Modules live under `backend/app/<module>`. Import rules are enforced by an
import linter (see §11). Dependencies are strictly layered: lower layers may not
import higher layers.

```
foundation        # ids, time, crypto, errors, config, logging, telemetry
domain            # ontology definitions, canonical value objects, enums
persistence       # db models, repositories, migrations, object storage client
ingestion         # upload, validation, schema mapping, evidence extraction
resolution        # entity resolution, conflict detection, review state machine
graph             # adjacency, traversal, snapshots, diffs, temporal queries
intelligence      # signals, scenarios, recommendations (deterministic policies)
decisions         # decision records, approval, outcome recording, replay
audit             # event model, event bus, append-only writers
auth              # users, tenants, workspaces, roles, permissions
workspace         # workspace lifecycle, scoping, isolation helpers
api               # FastAPI routers that orchestrate the above (thin layer)
ml                # synthetic data, feature store, registry, shadow inference
admin             # tenant/workspace/user admin, model promotion
jobs              # worker definitions, dispatch, retry, idempotency
```

### 7.1 Allowed dependency direction

```
foundation ← domain ← persistence ← (ingestion|resolution|graph|intelligence|decisions|ml)
          ← audit ← (everything except foundation)
api → may import any non-frontend module but must stay thin
auth/workspace → may be imported by any module for scoping
```

Forbidden:
- `persistence` importing `api`.
- `domain` importing `persistence` or `api`.
- Any module importing `api` except the application entrypoint.
- `ml` importing `intelligence`/`decisions` (one-way: intelligence may read ml
  candidates; ml never reads policies).

### 7.2 Module contract

Every module exposes:
- a `service.py` (use-case functions),
- a `repository.py` (persistence) where stateful,
- a `schemas.py` (Pydantic DTOs) where it has an API,
- a `tests/` folder.

Modules communicate via explicit service function calls, never by reaching into
another module's repository directly. Cross-module data exchange uses DTOs from
`domain` or the owning module's `schemas`.

---

## 8. Repository structure

A single monorepo. Phase 1 fixes the top-level layout; Phase 2 fills it.

```
cortex/
  docs/                      # this Phase 1 specification package
  backend/
    app/<module>/            # logical modules (see §7)
    app/main.py              # FastAPI app factory
    app/config.py            # typed config from env
    app/infrastructure/      # cross-cutting infra wiring (db pool, redis, s3, otel)
    alembic/                 # migrations
    tests/                   # unit + integration + contract
    pyproject.toml
    ruff.toml
    mypy.ini
  frontend/
    src/app/                 # Next.js App Router
    src/components/
    src/features/            # one folder per feature flow
    src/lib/                 # api client, hooks, auth, state
    src/stores/
    package.json
    tsconfig.json
  infra/
    docker/                  # Dockerfiles, compose
    terraform/               # portable IaC (provider-agnostic modules)
    k8s/                     # manifests (pilot+)
  scripts/                   # local dev bootstrap, seed, lint
  .github/workflows/         # CI pipelines
  opencode.json              # opencode config
  AGENTS.md                  # agent instructions incl. lint/typecheck/test commands
  README.md
```

### 8.1 Monorepo discipline

- Backend and frontend share only authored contracts: the OpenAPI spec generated
  by the backend is the single source of truth; the frontend client is generated
  from it. No hand-maintained duplicate types.
- No module is duplicated. One concern lives in exactly one module.
- Scripts that touch the DB go through Alembic or the backend service layer,
  never raw ad-hoc SQL outside migrations/tests.

---

## 9. Deployment topology (Phase 1 reference)

Local: `docker compose` runs postgres, redis, minio, backend, worker, frontend,
otel collector. Staging/pilot: same images, real Postgres (managed), S3-compatible
object storage, single backend + N workers behind a load balancer. Production
topology is deferred but must remain a superset of pilot (no architectural
fork). See `11-deployment.md`.

---

## 10. Non-functional requirements (frozen targets)

| Attribute | Target |
|---|---|
| API p95 read latency (graph explore, L≤2 hops, ≤10k edges) | ≤ 300 ms |
| API p95 write latency (single canonical upsert) | ≤ 150 ms |
| Upload validation throughput | ≥ 5 MB/s per worker |
| Worker job idempotency | 100% (duplicate dispatch never creates duplicate canonical records) |
| Audit durability | append-only, zero UPDATE/DELETE grants, daily backup + PITR |
| Tenant isolation | zero cross-tenant DB/schema or object-prefix access; verified by tests |
| Availability (pilot) | single region, business-hours SLO, graceful degradation on worker failure |
| API backward compatibility within a major version | guaranteed |

These are targets the architecture is built to satisfy; they are exported to
`10-testing-and-ci-cd.md` and `11-deployment.md` as concrete gates.

---

## 11. Architectural enforcement mechanisms

Because principles degrade without enforcement, Phase 1 fixes these mechanisms:

- **Import linter (`import-linter` or equivalent).** Contracts in §7.1 are encoded
  and run in CI. Failure blocks merge.
- **OpenAPI contract tests.** The frontend client is generated; the backend
  self-tests against the published OpenAPI schema. Drift blocks release.
- **DB grant checks.** A startup + CI check asserts INSERT-only grants on audit
  tables and no UPDATE on `uploads`/raw evidence records.
- **Serializer lints.** Evidence fields cannot be dropped; decisions cannot be
  serialized without `policy_version` and input hash.
- **Module service-layer-only rule.** Routers may not call repositories directly.
- **No-DB-for-frontend rule.** No frontend package imports a DB driver.
- **Frozen contract versions.** API, event, and schema versions are integers in
  a registry; changing a frozen contract requires an ACR.

---

## 12. Explicit assumptions (Phase 1)

1. A single PostgreSQL 16 cluster is sufficient for pilot scale. Graph traversal
   uses SQL adjacency + materialized views; no separate graph DB in Phase 1/2.
2. S3-compatible object storage is available in every environment (MinIO locally).
3. Python 3.12 and Node 20 LTS are the runtimes for Phase 2 onward.
4. One backend deployment serves all tenants; isolation is via per-tenant schema
   and per-tenant object-storage prefixes (see `06-database-strategy.md`,
   `09-security.md`). A future dedicated-cluster-per-tenant option is not
   precluded but not required in Phase 1.
5. The browser is never trusted for canonical facts; signed URLs and server-side
   auth are required for all object access.
6. ML is optional and may be disabled per tenant/workspace without degrading the
   deterministic pipeline.

---

## 13. Frozen decisions summary

- Modular monolith; no service split in Phase 1 or Phase 2.
- FastAPI + Next.js + PostgreSQL + S3-compatible + Redis + workers.
- Graph in PostgreSQL for Phase 1/2.
- Append-only audit; immutable uploads; versioned everything.
- Deterministic decision layer; bounded, review-gated ML.
- OpenAPI as the single contract; generated frontend client.
- Monorepo with enforced module import boundaries.

Phase 1 proceeds to Step 2 (Operational Domain) on this basis.
