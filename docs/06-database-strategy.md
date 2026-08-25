# 06 — Database Strategy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `02-ontology.md`, `03-canonical-data-model.md`, `04-graph-and-events.md`, `05-api-standards.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and scope

This document freezes how PostgreSQL is used by Cortex: which data is
relational, which is immutable, which is append-only, which is versioned, how
workspace and tenant isolation are enforced, how lineage and snapshots are
stored, and how graph references sit in the same store. Phase 1 does not write
every SQL statement; it freezes the structure and conventions so implementation
can begin without reinterpretation.

Out of scope: object storage (`01-architecture.md` §3.1), ML artifact storage
(`08-ml-platform-strategy.md`), physical migration order (Alembic, Phase 2).

---

## 2. Engine and topology

- PostgreSQL **16+** for Phase 1.
- A single cluster per environment (dev/staging/pilot). Multi-cluster is a
  later-phase option, not Phase 1/2.
- For pilot, a managed Postgres with point-in-time-recovery (PITR) is used. The
  schema and access patterns are identical locally (`docker compose`) and in
  pilot.
- Default encoding `UTF8`, locale `C` (deterministic collation for stable
  canonicalization). Display ordering uses ICU collation explicit per query.

---

## 3. Schema organization (frozen layout)

Schemas are used as module boundaries. One schema per backend module
(`01-architecture.md` §7). This is the physical realization of the modular
monolith boundary.

| Schema | Owner module | Role grants to `app` role |
|---|---|---|
| `foundation` | foundation | SELECT |
| `iam` (auth/workspace/admin) | auth, workspace, admin | SELECT/INSERT/UPDATE (not on audit) |
| `ingest` | ingestion | SELECT/INSERT |
| `claims` | resolution | SELECT/INSERT/UPDATE (state only) |
| `conflicts` | resolution | SELECT/INSERT/UPDATE (state only) |
| `reviews` | resolution | SELECT/INSERT/UPDATE (state only) |
| `canonical` | persistence + domain | SELECT/INSERT/UPDATE (versioned appends) |
| `graph` | graph | SELECT/INSERT/UPDATE (versioned appends) |
| `intelligence` | intelligence | SELECT/INSERT/UPDATE (state only) |
| `decisions` | decisions | SELECT/INSERT/UPDATE (state only) |
| `ml` | ml | SELECT/INSERT/UPDATE only on `ml_*` tables |
| `audit` | audit | INSERT ONLY (no UPDATE/DELETE) |
| `jobs` | jobs | SELECT/INSERT/UPDATE |
| `schema_registry` | foundation | SELECT only for `app`; INSERT for `admin` at publish time |

Why schemas not separate databases: graph + canonical + audit must be
transactional together so evidence coherence is guaranteed on every write.
Cross-database transactions would forfeit that.

---

## 4. Roles and grants (frozen, security-critical)

| Role | Purpose | Grants |
|---|---|---|
| `app` | backend API + workers runtime | per-schema per §3 |
| `app_audit_writer` | used by `audit.emit()` | INSERT only on `audit.audit_events` |
| `admin_migrator` | Alembic only | DDL on all schemas; no data grants at runtime except where required for migrations |
| `retention` | retention/deletion job | DELETE on specific tables, time-bounded, audited (see §10) |
| `readonly_auditor` | audit log read | SELECT on `audit.*`, `canonical.*`, `graph.*` for replay verification |

Cross-cutting invariants:
- No role ever receives UPDATE or DELETE on `audit.audit_events`.
- No role ever receives UPDATE on `ingest.uploads`, `ingest.upload_bytes`, or
  any evidence/claim value column. UPDATE is granted only on *state* columns of
  versioned/stateful tables and only via the owning module's repository.
- A startup + CI check (`grant_check`) asserts these invariants and fails
  closed (`01-architecture.md` §11).

---

## 5. Tenant and workspace isolation

### 5.1 Model
- Tables that hold tenant or workspace data are partitioned.
- Root tables are partitioned by `tenant_id` (LIST) **and** sub-partitioned by
  `workspace_id` (HASH or LIST depending on volatility). This guarantees
  physical separation at the storage level for tenant isolation, which is
  Phase 1's security posture (`09-security.md`).
- A unique workspace belongs to exactly one tenant; `iam.workspaces.tenant_id`
  has a FK to `iam.tenants`.

### 5.2 Enforcement
- PostgreSQL Row-Level Security (RLS) policies:
  - Every table that carries `tenant_id` enforces
    `tenant_id = current_setting('app.tenant_id')::uuid`.
  - Every workspace-data table enforces
    `workspace_id = current_setting('app.workspace_id')::uuid` where set
    (`app.workspace_id` is unset for cross-workspace admin/party-directory reads).
- `app.tenant_id` is set per DB connection from the JWT at connection checkout
  and verified to match the workspace's tenant. Setting `app.tenant_id` is
  restricted to the connection acquisition code; arbitrary writes are blocked by
  not granting `SET` on those custom GUCs to the `app` runtime role beyond the
  connection-stablish code path.
- Cross-tenant tests assert that a session with tenant A cannot SELECT, INSERT,
  UPDATE, or DELETE any row whose `tenant_id = B`. Phase 2 ships these as a
  security regression suite (`09-security.md`, `10-testing-and-ci-cd.md`).

### 5.3 Per-tenant object storage prefixes
- Storage prefixes are `tenants/{tenant_id}/workspaces/{workspace_id}/...` —
  backend enforces prefix consistency with RLS-validated tenant/workspace ids
  before any signed URL is issued.

---

## 6. Table strategy by data class

This is the frozen taxonomy. Implementing tables fall into exactly one class.

### 6.1 Immutable tables
- `ingest.uploads`, `ingest.upload_bytes` (or a pointer to object storage only),
  `ingest.source_objects`, `ingest.evidence`.
- INSERT only. No UPDATE, no DELETE by `app`.
- Lifecycle deletion (retention) by `retention` role only (`§10`).

### 6.2 Append-only tables
- `audit.audit_events` (the canonical append-only event log).
- INSERT only. A separate hash-chain table (`audit.audit_event_chain`,
  minimal: `(tenant_id, workspace_id, seq, prev_event_id, prev_event_hash)`)
  backs the chain in `04-graph-and-events.md` §12.3.

### 6.3 State-only mutable tables (UPDATE on a closed `state` column set)
- `claims.claims` (state + review_id), `conflicts.conflicts`,
  `conflicts.validation_issues`, `reviews.reviews`.
- UPDATE only on `(state, review_id, resolved_by_ref, resolved_at,
  resolution_rationale, superseded_by, updated_at)`. A column-level grant
  enforces this; value columns are INSERT-only.

### 6.4 Versioned append tables (new version, close prior `valid_to`)
- `canonical.entities`, `canonical.entity_attributes`, `graph.edges`,
  `graph.edge_properties`.
- INSERT a new row per accepted change; never UPDATE `value`/`valid_from`.
  The only UPDATE allowed is `valid_to = ...` on the prior current row, done by
  the owning module's repository inside a transaction with the new insert.
- This implements the canonical attribute envelope from
  `03-canonical-data-model.md` §5.2 directly.

### 6.5 Snapshot tables
- `graph.snapshots` (sealed rows), `graph.snapshot_nodes` (materialized per
  snapshot), `graph.snapshot_edges`, `graph.snapshot_artifacts` (object
  storage pointer + content_hash).
- INSERT-only once sealed. The sealed snapshot's rows are written atomically
  when the snapshot job seals (§7).

### 6.6 Intelligence tables
- `intelligence.signals`, `intelligence.scenarios`,
  `intelligence.recommendations`.
- Versioned where determinism needs history (`recommendations` supersession,
  `signals` supersession); otherwise state-only.

### 6.7 Decision memory tables
- `decisions.decisions`, `decisions.outcomes`.
- State machine transitions recorded as state-columns updates with audit
  events; the decision body itself is immutable (the recorded decision).

### 6.8 ML tables
- `ml.datasets`, `ml.features`, `ml.models`, `ml.model_runs`,
  `ml.shadow_inferences`, `ml.candidates`.
- Phase 1 freezes structure; ML writes only here. No `ml_` table is read by the
  deterministic pipeline as a fact source — only as candidate claims reference
  into `claims.claims` via `ml.candidates.claim_id`.

### 6.9 IAM and admin tables
- `iam.tenants`, `iam.users`, `iam.memberships`, `iam.roles`,
  `iam.workspace`, `iam.api_keys` (rotatable), `iam.refresh_tokens`,
  `jobs.jobs`, `jobs.job_events`, `schema_registry.schemas`,
  `schema_registry.policy_versions`, `idempotency.idempotency_records`.

### 6.10 Cross-workspace shared tables (outside RLS workspace filter)
- `iam.party_directory` — shared Supplier/Customer directory records used by
  multi-workspace parties. Read-only via the `GET /suppliers` and
  `GET /customers` cross-workspace endpoints (`05-api-standards.md` §12.8).
- Has `tenant_id` RLS on tenant but no `workspace_id` RLS; access is gated by
  the `cross_workspace` role only.

---

## 7. Graph storage in PostgreSQL (frozen approach)

Phase 1/2 implements the operational graph with adjacency tables in PostgreSQL.

### 7.1 Tables
- `graph.nodes` — pointer rows `(node_id, workspace_id, entity_type,
  entity_ref_id, version, valid_from, valid_to, lifecycle_state)`. The
  attributes themselves live in `canonical.entity_attributes` and are joined.
  `graph.nodes` is versioned append-only (same rule as canonical entities).
- `graph.edges` — `(edge_id, workspace_id, edge_type, source_node_id,
  target_node_id, directional, version, valid_from, valid_to, confidence,
  inferred, derivation_ref)`. Versioned append-only.
- `graph.edge_properties` — `(edge_id, key, value, value_kind)` for the per-type
  properties in `02-ontology.md` §9.1. INSERT-only per edge version.
- `graph.edge_evidence` — `(edge_version_id, evidence_id, claim_ref?, role)`
  records `EVIDENCED_BY` links; non-empty per edge.
- `graph.snapshots*` — see §6.5.
- `graph.diff_records` — see `04-graph-and-events.md` §6.2.

### 7.2 Indexing and traversal (contracts, not benchmarks)
- Indexes:
  - `graph.edges(source_node_id, edge_type, valid_to)` for forward traversal.
  - `graph.edges(target_node_id, edge_type, valid_to)` for reverse traversal.
  - `graph.edges(workspace_id, edge_type)` for typed listing.
  - `graph.edge_evidence(edge_version_id)`.
- Materialized views for hot adjacency:
  - `graph.mv_current_edges` = currently-valid edges filtered to `valid_to IS NULL`.
    Refreshed on snapshot seal.
  - `graph.mv_current_nodes` likewise.
- Recursive CTEs for paths (`WITH RECURSIVE`) bounded by depth ≤4 hops by
  default (server-side guard returns `422 query_too_deep` for deeper requests
  without explicit opt-in). This bound is a frozen performance-safety default;
  it does not limit the graph model.

### 7.3 Storage of evidence refs on edges
- Edges reference evidence via `graph.edge_evidence`; the API always joins and
  returns evidence inline. There is no "graph-only" view that hides evidence.

### 7.4 Why not a graph database in Phase 1/2
- Coherence: graph mutations and canonical/audit writes must be transactional.
- Volume: pilot-scale graph fits Postgres comfortably with the indexes above
  and the depth-4 default for live traversal; impact queries that go deeper are
  served from sealed snapshots (pre-materialized) rather than live traversal.
- Portability: keep the deployment stack portable and avoid a new operational
  dependency before pilot scale justifies it.
- A future ACR may introduce a specialized store for analytics; it would not
  become the source of truth.

---

## 8. Versioning patterns (frozen SQL pattern)

All versioned tables follow the same pattern. Frozen so that all modules use one
shape and so temporal queries are uniform.

```sql
-- Versioned append-only pattern (canonical, graph)
-- New accepted attribute version:
WITH old AS (
  UPDATE canonical.entity_attributes
     SET valid_to = $now
   WHERE entity_id = $id AND attribute = $attr AND valid_to IS NULL
   RETURNING version
)
INSERT INTO canonical.entity_attributes
  (entity_id, attribute, version, value, value_kind, value_unit, confidence,
   policy_version, claim_ids, evidence_refs, valid_from, valid_to, state, conflict_ids)
VALUES
  ($id, $attr, (SELECT COALESCE(MAX(version),0)+1 FROM old), $value, ...,
   $now, NULL, 'accepted', $conflicts);
```

- Sequencing is enforced by the `(entity_id, attribute, valid_to IS NULL)`
  partial unique index guaranteeing one current version per attribute.
- Reads of "current" use the partial predicate `valid_to IS NULL`.
- Reads of "as_of T" use `valid_from <= T AND (valid_to IS NULL OR valid_to > T)`.

The same pattern applies to `graph.edges`. The repository layer is the sole
writer; raw UPDATEs would break the partial unique index.

---

## 9. Lineage storage

`DERIVED_FROM` edges are stored in `graph.edges` with `edge_type='DERIVED_FROM'`
just like any other edge. The only additional structure is:

- `graph.lineage_index` (materialized, refreshed on snapshot seal) — a
  reachability index that precomputes, for fast validation, whether a candidate
  write would create a `DERIVED_FROM` cycle. Inserts that would create a cycle
  are rejected by the graph writer after consulting this index.
- This index is derived; if stale, the writer falls back to a bounded
  recursive CTE check. Phase 2 ships both paths; Phase 1 freezes the contract.

---

## 10. Retention, immutability, and backups

- `audit.audit_events` retention is governed by tenant policy (≥7 years by
  default for enterprise). Deletion is performed only by the `retention` role,
  in time-bounded batches, and each batch is preceded by an `audit.retention`
  event signed by a separate key (`09-security.md`).
- Immutable uploads retention: same tenant policy; deletion writes a
  `upload.reclaimed` audit event referencing the original `upload_id` and
  `content_hash`.
- Backups:
  - Managed Postgres PITR with ≥35-day recovery window for pilot.
  - Logical (pg_dump) weekly snapshots retained 90 days.
  - Restore tests run monthly (`10-testing-and-ci-cd.md`).
- Object storage lifecycle and immutable-lock are described in `09-security.md`.

---

## 11. Idempotency storage

- `idempotency.idempotency_records` keyed by
  `(user_id, workspace_id, idempotency_key, idempotency_scope)` storing:
  - `request_id`, `endpoint`, `payload_hash`, `response_status`,
    `response_body_hash`, `created_at`, `expires_at`.
- A hit returns the stored response from the cache; the audit log records the
  replay with `causation_id = original_event_id` and a flag `is_replay=true`
  on the metadata (replays do not produce new domain state).
- UNIQUE constraint on the key columns makes concurrent duplicates impossible;
  the loser receives `409 conflict` with `idempotency_in_flight`.

---

## 12. Audit log storage

- `audit.audit_events` is the canonical append-only table.
- Partitioning: by `tenant_id` and by `occurred_at` month (RANGE on month) so
  retention can drop old partitions without row-level deletes.
- The hash chain in `audit.audit_event_chain` is keyed by
  `(tenant_id, workspace_id)` with a per-key sequence; the chain is maintained
  by the audit writer in the same DB transaction as the event INSERT.
- A verification job recomputes the chain nightly and on-demand; mismatches
  raise an `audit.chain_broken` alert and block the next release.

---

## 13. Constraints and integrity rules (frozen)

In addition to ontology validations (`02-ontology.md` §13):

- FK from `canonical.entities.workspace_id` → `iam.workspaces.id` (enforced).
- FK from `graph.edges.source_node_id` and `target_node_id` →
  `graph.nodes.node_id` deferred initially, validated after the snapshot is
  sealed. Phase 1 uses deferred constraints to allow in-snapshot construction;
  sealed snapshots must pass validation or the seal fails and the job is rolled
  back.
- CHECK constraints enforce closed enums at the DB level (defense in depth; the
  application is expected to validate first).
- Partial UNIQUE indexes enforce identity rules:
  - one current entity attribute per `(entity_id, attribute)` where `valid_to IS NULL`.
  - one current edge per identity key per type where `valid_to IS NULL`.
  - normalized SKU unique per workspace; normalized PO/SO/Shipment id unique
    per workspace.

---

## 14. Migrations and zero-downtime discipline

- Alembic in `backend/alembic`. Migrations are forward-only; a separate
  `undo` migration is required for every schema-changing migration so rollback
  is mechanical. Both forward and reverse are tested in CI on a clone of the
  latest production snapshot (`10-testing-and-ci-cd.md`).
- Expanding migrations (additive) ship as normal. Contractive migrations
  (column/table removal) require an ACR and run only after the consuming code is
  fully retired across at least one release.
- Backfill migrations are batched and resumable, and run inside the application
  with worker throttling to avoid pilot-scale locking.

---

## 15. Connection pooling and observability

- `asyncpg` connection pool per backend process; `app.tenant_id` and
  `app.workspace_id` set per checkout. Pool sizes and timeouts are
  configuration-driven (`11-deployment.md`).
- Per-query OpenTelemetry tracing attributes: `db.schema`, `db.operation`,
  `cortex.tenant_id`, `cortex.workspace_id`. Slow-query log threshold 200ms.
- pg_stat_statements enabled; digest of queries reviewed weekly in pilot.

---

## 16. Performance guardrails (frozen defaults)

- Default query timeout 5s; transaction timeout 10s. Long-running work runs in
  the worker, not in the API.
- Maximum rows read per request is bounded by the pagination cap (200 rows) and
  by snapshot-relative reads for graph endpoints.
- Recursive CTEs bounded to depth 4 for live traversal; deeper impact queries
  served from sealed snapshots.
- No `SELECT *` in repository code (column lists only); a linter enforces this.

---

## 17. Frozen decisions summary

- Single Postgres cluster per environment; one schema per backend module.
- Tenant isolation via partitioning + RLS; workspace isolation via RLS.
- Audit INSERT-only at the grant level with a hash chain.
- Versioned append-only pattern for canonical entities and graph edges.
- Operational graph stored in PostgreSQL adjacency tables with materialized
  current views and bounded recursive CTE traversal.
- Snapshots are sealed, hash-bound, and read units for intelligence.
- Migrations are forward/undo pairs, additive preferred; contractive changes
  gated by ACR.
- Connection pool carries tenant/workspace context; per-query tracing is
  mandatory.

Phase 1 proceeds to `07-frontend-architecture.md` on this basis.
