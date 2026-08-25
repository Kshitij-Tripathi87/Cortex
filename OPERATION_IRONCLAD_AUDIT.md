# Operation Ironclad — Audit Tracker

**Goal**: Zero known P0 security issues, zero P0/P1 data integrity bugs, stable under sustained load, consistent API contracts, complete observability, clean deployment/rollback.

**Scope**: Full codebase audit as if for Fortune 500 due diligence.

---

## Issue Taxonomy

| Severity | Definition | SLA |
| --- | --- | --- |
| P0 — Critical | Data loss, RCE, auth bypass, production outage | Fix immediately |
| P1 — High | Data corruption risk, privilege escalation, major UX break | Fix this sprint |
| P2 — Medium | Edge case bugs, performance degradation, missing hardening | Next sprint |
| P3 — Low | Code smell, tech debt, minor UX polish | Backlog |

---

## Audit Phases

### Phase 1 — Security Audit
- [ ] JWT validation (alg confusion, exp/nbf, key rotation)
- [ ] Refresh token rotation & revocation
- [ ] Secret management (no hardcoded, env-only, rotation)
- [ ] RBAC (role enforcement on all endpoints)
- [ ] Audit permissions (who can read/write what)
- [ ] CSRF protection (state-changing endpoints)
- [ ] CORS policy (strict origins)
- [ ] Upload validation (size, type, content, path traversal)
- [ ] SSRF protection (outbound requests)
- [ ] SQL injection review (raw SQL, ORM usage)
- [ ] Dependency vulnerabilities (pip-audit, safety)
- [ ] Rate limiting (per-IP, per-user, distributed)
- [ ] DOS protection (body limits, timeouts)
- [ ] Security headers (CSP, HSTS, X-Frame-Options)
- [ ] Input validation (Pydantic on all inputs)

### Phase 2 — Backend Audit
- [ ] Race conditions (check-then-act, get-or-create)
- [ ] Transaction consistency (isolation levels, rollback)
- [ ] Idempotency keys (POST endpoints)
- [ ] Deadlock prevention (lock ordering, timeouts)
- [ ] Connection pooling (size, recycling, health checks)
- [ ] Timeout handling (client, DB, external)
- [ ] Graceful shutdown (drain connections, finish requests)
- [ ] Cache invalidation (stale reads, TTL strategy)
- [ ] Optimistic locking (version columns on updates)
- [ ] Pagination (cursor vs offset, max page size)
- [ ] Large dataset support (streaming, chunking)
- [ ] Error handling (no leaky stack traces)
- [ ] Logging (structured, no PII/secrets)

### Phase 3 — Database Audit
- [ ] Indexes (covering query patterns, no duplicates)
- [ ] Query plans (EXPLAIN ANALYZE on hot paths)
- [ ] Constraints (NOT NULL, CHECK, UNIQUE)
- [ ] FK coverage (all relationships enforced)
- [ ] Partitioning (large tables by time/tenant)
- [ ] Retention policies (automated cleanup)
- [ ] Backups (frequency, PITR, tested restore)
- [ ] Restore procedure (documented, RTO/RPO)
- [ ] Migrations (idempotent, reversible, backward compat)
- [ ] Rollback strategy (down migrations tested)
- [ ] Connection limits (max_connections, pool sizing)

### Phase 4 — Frontend Audit
- [ ] Loading states (all async actions)
- [ ] Optimistic updates (rollback on error)
- [ ] Skeleton screens (perceived performance)
- [ ] Retry UX (exponential backoff, user control)
- [ ] Offline detection (service worker, queue)
- [ ] Keyboard accessibility (focus, ARIA, tab order)
- [ ] Error boundaries (catch, report, recover)
- [ ] Notifications (toast, inline, persistent)
- [ ] Session expiry handling (warning, refresh, redirect)
- [ ] Responsive layouts (mobile, tablet, desktop)
- [ ] TypeScript strict mode (no `any`)
- [ ] Bundle size (code splitting, lazy loading)

### Phase 5 — Integration Audit
- [ ] Frontend ↔ Backend contract (OpenAPI match)
- [ ] Backend ↔ Database (migrations applied)
- [ ] API ↔ OpenAPI spec (100% coverage)
- [ ] Caching strategy (Redis, invalidation keys)
- [ ] Authentication flow (login, refresh, logout)
- [ ] Uploads (multipart, progress, cleanup)
- [ ] Exports (streaming, memory bounds)
- [ ] Reports (generation, storage, cleanup)

### Phase 6 — Performance Audit
- [ ] k6/Locust scripts (critical paths)
- [ ] Stress testing (2x expected peak)
- [ ] Spike testing (10x burst)
- [ ] Endurance testing (1hr+ sustained)
- [ ] DB profiling (pg_stat_statements, slow queries)
- [ ] Cache profiling (hit rates, evictions)
- [ ] Memory leaks (heap snapshots, GC pressure)
- [ ] CPU profiling (flamegraphs)

### Phase 7 — Reliability Audit
- [ ] Kill Redis (cache miss fallback)
- [ ] Kill PostgreSQL (circuit breaker, retry)
- [ ] Restart services (zero-downtime deploy)
- [ ] Disconnect network (timeouts, retries)
- [ ] Corrupt uploads (validation, cleanup)
- [ ] Duplicate requests (idempotency keys)
- [ ] Large uploads (streaming, timeout)
- [ ] Expired sessions (graceful re-auth)

---

## Discovered Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| SEC-001 | JWT/Config | `jwt_secret` defaults to empty string in config; only fails at token issue time, not startup. Production deployment without secret fails silently until first login. | ✅ Fixed — validator added in config.py |
| SEC-002 | Auth | No refresh token rotation mechanism. JWT expires in 60 min (configurable) but no refresh flow; users must re-login. | ⬜ Open |
| SEC-003 | Auth | Dev auth bypass in `get_current_user` - allows anonymous access via `X-User-Id` header in non-prod environments. Header-based identity trusted in dev/test. | ⬜ Open |
| SEC-004 | Rate Limiting | Rate limiting is in-memory only (per-process token bucket). Not distributed - fails in multi-instance deployments. | ⬜ Open |
| SEC-005 | CSRF | No CSRF protection on any state-changing endpoints (POST/PUT/DELETE). | ⬜ Open |
| SEC-006 | Upload | File upload only validates size. No content-type validation, no CSV schema validation before processing, no malware scanning. | ⬜ Open |
| SEC-007 | CORS | No CORS middleware configured in FastAPI app. Default allows all origins. | ✅ Fixed — CORSMiddleware added with configurable origins |
| SEC-008 | SQL Injection | Raw SQL queries in some modules (graph service, compiler). Need full audit of `text()` usage. | ⬜ Open |
| SEC-009 | Auth | No account lockout / failed attempt tracking on login endpoint. Brute-force possible. | ⬜ Open |
| SEC-010 | Auth | No audit logging on auth events (login success/failure, token refresh, permission denied). | ⬜ Open |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| SEC-101 | Rate Limiting | `RateLimitHeadersMiddleware` only reports headers, never rejects requests. Actual rejection requires `@rate_limit` decorator which is unused. | ⬜ Open |
| SEC-102 | Circuit Breaker | `CircuitBreakerMiddleware` only protects "expensive" routes (graph, propagate, scenarios, recommendations). Other endpoints unprotected. | ⬜ Open |
| SEC-103 | Circuit Breaker | In-memory only, not distributed across instances. | ⬜ Open |
| SEC-104 | Upload | No CSV content validation before parsing. Malformed CSV could cause DoS via memory/CPU. | ⬜ Open |
| SEC-105 | SSRF | `ObjectStorageClient` uses boto3 with configurable endpoint. No validation that endpoint is internal/allowed - SSRF risk if user controls `s3_endpoint`. | ⬜ Open |
| SEC-106 | Secrets | `jwt_secret`, `s3_secret_key`, DB password loaded from env but no rotation mechanism. No integration with secret managers (Vault, AWS Secrets Manager). | ⬜ Open |
| SEC-107 | Security Headers | Missing Content-Security-Policy header. HSTS only added on HTTPS. | ⬜ Open |
| SEC-108 | Auth | Password complexity not enforced. bcrypt used but no policy (min length, complexity). | ⬜ Open |
| SEC-109 | Auth | JWT algorithm hardcoded to HS256. No algorithm confusion protection beyond decode options. | ⬜ Open |
| SEC-110 | S3 | `ObjectStorageClient` falls back to boto3 default credential chain. Could pick up instance profile credentials unintentionally. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| SEC-201 | Rate Limiting | Token bucket uses `time.monotonic()` - not synchronized across processes. | ⬜ Open |
| SEC-202 | Auth | Dev/test path in `get_current_user` imports `get_current_user` from `identity.dependencies` which uses header-based auth. Potential confusion. | ⬜ Open |
| SEC-203 | Upload | `upload_allowed_mime` config exists but not enforced in ingestion endpoint. | ⬜ Open |
| SEC-204 | CORS | No CORS configuration - needs explicit allowed origins, methods, headers. | ⬜ Open |
| SEC-205 | Security Headers | `Permissions-Policy` could be stricter for enterprise. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| SEC-301 | Auth | No password rotation / expiry policy. | ⬜ Open |
| SEC-302 | Logging | No structured security event logging (login, authz failures, token validation errors). | ⬜ Open |

---

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| BUG-001 | Ingestion | `ingest_csv` reads entire file into memory (`await file.read()`). Large CSV uploads (200MB limit) will OOM the worker. No streaming/chunked processing. | ✅ Fixed — streaming ingestion with temp file |
| BUG-002 | Ingestion | `_resolve_node` loads ALL rows of a node type into memory (limit=10000). For large workspaces, this loads 10k+ rows per ingestion run. | ⬜ Open |
| BUG-003 | Ingestion | No idempotency on ingestion endpoint. Duplicate uploads create duplicate rows (no upsert logic for existing SKUs/codes). | ⬜ Open |
| BUG-004 | DB Pool | `create_async_engine` uses fixed `pool_size=5, max_overflow=20` hardcoded. Not configurable via settings. | ✅ Fixed — uses settings.db_pool_min/max |
| BUG-005 | Graceful Shutdown | `lifespan` has `close_db()` but no signal handling (SIGTERM/SIGINT) for graceful drain. Connections dropped mid-request on deploy. | ✅ Fixed — SIGTERM/SIGINT handlers added |
| BUG-006 | Cache Invalidation | `compile_batch_to_graph` suppresses exceptions during cache invalidation (`contextlib.suppress(Exception)`). Stale cache entries persist silently. | ⬜ Open |
| BUG-007 | Idempotency | No idempotency keys on any POST endpoint (ingestion, brief, scenarios, propagate). Duplicate requests create duplicate work/data. | ⬜ Open |
| BUG-008 | Optimistic Locking | No version columns on any ORM model. Concurrent updates to same entity (e.g., inventory quantity) will lose updates. | ⬜ Open |
| BUG-009 | Pagination | All list endpoints use offset/limit pagination. Inefficient for large datasets (offset scans). No cursor-based pagination. | ⬜ Open |
| BUG-010 | Transactions | `ingest_csv` uses `session.flush()` but endpoint commits. If service throws after flush but before commit, partial data persists. | ⬜ Open |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| BUG-101 | Connection Pool | Pool settings hardcoded in `init_db` (5/20). Not using `db_pool_min`/`db_pool_max` from config. | ✅ Fixed — uses settings.db_pool_min/max |
| BUG-102 | Timeout Handling | `query_timeout_ms` and `tx_timeout_ms` in config but not enforced at DB level (no `statement_timeout`). | ⬜ Open |
| BUG-103 | Large Dataset | `ingest_csv` loads entire CSV into memory (`file_bytes = await file.read()`). No streaming parse for large files. | ✅ Fixed — streaming ingestion |
| BUG-104 | Cache Invalidation | Cache invalidation in `compile_batch_to_graph` is best-effort with suppressed exceptions. No verification that invalidation succeeded. | ⬜ Open |
| BUG-105 | Retries | No retry logic on transient DB errors (deadlocks, connection drops). `max_retries` in config unused. | ⬜ Open |
| BUG-106 | Deadlocks | No consistent lock ordering in multi-table updates (e.g., ingestion touches multiple tables in varying order). | ⬜ Open |
| BUG-107 | Graceful Shutdown | No SIGTERM/SIGINT handler to drain connections before `close_db()`. Kubernetes will SIGKILL after grace period. | ✅ Fixed — SIGTERM/SIGINT handlers added |
| BUG-108 | Race Conditions | `_resolve_node` cache populated per-ingestion but not thread-safe if concurrent ingestions for same workspace. | ⬜ Open |
| BUG-109 | Idempotency | No `Idempotency-Key` header support on any mutating endpoint. | ⬜ Open |
| BUG-110 | Optimistic Locking | No `version` column on any model. `last_modified_version` on graph nodes but not used for concurrency control. | ⬜ Open |
| BUG-111 | Pagination | Offset/limit pagination on all list endpoints. `offset` degrades with large datasets. No cursor pagination. | ⬜ Open |
| BUG-112 | Large Dataset | Graph traversal loads entire workspace graph into memory (`load_workspace_graph`). No streaming/batch processing. | ⬜ Open |
| BUG-113 | Cache Invalidation | `create_cache()` returns `NoOpCache` if Redis unavailable - silent fallback. No warning/metric when caching disabled. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| BUG-201 | Connection Pool | `pool_pre_ping` not enabled. Stale connections not detected until query fails. | ⬜ Open |
| BUG-202 | Timeout Handling | HTTP timeout not configured on FastAPI. Long-running requests can block workers indefinitely. | ⬜ Open |
| BUG-203 | Graceful Shutdown | Metrics server (`start_metrics_server`) not stopped on shutdown. | ⬜ Open |
| BUG-204 | Cache | `RedisCache.invalidate_workspace` uses `SCAN` which can be slow for large keyspaces. No rate limiting on scan. | ⬜ Open |
| BUG-205 | Retries | `run_in_threadpool` for S3 upload has no retry/backoff. Transient network errors fail the whole ingestion. | ⬜ Open |
| BUG-206 | Deadlocks | Ingestion touches tables in different orders (suppliers → components → products → edges → inventory). Concurrent ingestions can deadlock. | ⬜ Open |
| BUG-207 | Idempotency | `IngestionLog` has no unique constraint on (workspace_id, file_key). Duplicate uploads create duplicate log entries. | ⬜ Open |
| BUG-208 | Optimistic Locking | Graph nodes have `last_modified_version` but not used for `WHERE version = X` updates. | ⬜ Open |
| BUG-209 | Pagination | `limit` capped at 200 but `offset` unbounded. Deep pagination will be slow. | ⬜ Open |
| BUG-210 | Large Dataset | `SqlGraphRepository.list_nodes` uses offset pagination. No cursor-based alternative. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| BUG-301 | Logging | Structured logging configured but request ID not consistently propagated to all log lines. | ⬜ Open |
| BUG-302 | Metrics | `MetricsMiddleware` added but no custom business metrics (ingestion duration, brief generation time, etc.). | ⬜ Open |
| BUG-303 | Tracing | OTel tracing setup but no span attributes for workspace_id, user_id on all spans. | ⬜ Open |

---

## Database Audit Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| DB-001 | Indexes | No composite indexes on high-cardinality query patterns. Graph traversal queries filter on `(workspace_id, valid_to, entity_type)` but no composite index exists. | ⬜ Open |
| DB-002 | FK Coverage | `Edge` table uses polymorphic UUIDs (`from_id`, `to_id`) with no DB-level FK constraints. Application-level validation only. Orphan edges possible. | ⬜ Open |
| DB-003 | Constraints | `Edge` table has no CHECK constraint on valid `edge_type` values. Invalid relationship types can be inserted. | ⬜ Open |
| DB-004 | Constraints | `Inventory.quantity` and `safety_stock` have no CHECK constraint `>= 0`. Negative inventory possible. | ⬜ Open |
| DB-004 | Constraints | `Order.quantity` has no CHECK constraint `> 0`. Zero/negative order quantities possible. | ⬜ Open |
| DB-005 | Partitioning | `graph_write_events`, `audit_events`, `evidence_claims` are high-write tables with no time-based partitioning. Will degrade at scale. | ⬜ Open |
| DB-006 | Retention | No automated retention policies for high-growth tables (`audit_events`, `evidence_claims`, `graph_write_events`, `ml_shadow_predictions`). | ⬜ Open |
| DB-007 | Backups | No documented backup strategy, PITR configuration, or tested restore procedure. | ⬜ Open |
| DB-008 | Migrations | Migration 002 (RLS) uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` which is not idempotent in all PostgreSQL versions. Downgrade drops `tenant_id` column - data loss. | ⬜ Open |
| DB-009 | Rollback | Down migrations for 002, 003, 009 drop tables with `CASCADE` - data loss on downgrade. Not tested in CI. | ⬜ Open |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| DB-101 | Indexes | `graph_nodes` missing composite index on `(workspace_id, valid_to, entity_type)` for traversal queries. Current index only on `workspace_id`. | ⬜ Open |
| DB-102 | Indexes | `graph_edges` missing composite index on `(workspace_id, valid_to, source_node_id)` for neighbor lookups. | ⬜ Open |
| DB-103 | Indexes | `graph_snapshots` missing index on `(workspace_id, version DESC)` for latest snapshot lookup. | ⬜ Open |
| DB-104 | Indexes | `graph_write_events` missing index on `(snapshot_id, occurred_at)` for event replay. | ⬜ Open |
| DB-105 | Indexes | `provenance_links` missing index on `(workspace_id, graph_element_type, graph_element_id)` for provenance lookup. | ⬜ Open |
| DB-106 | Indexes | `operational.edges` missing index on `(workspace_id, from_type, from_id, to_type, to_id)` for edge deduplication checks. | ⬜ Open |
| DB-107 | Indexes | `orders.orders` missing index on `(workspace_id, status, requested_delivery_date)` for dashboard queries. | ⬜ Open |
| DB-108 | FK Coverage | `operational.products.factory_id` has FK but `operational.edges` has NO FKs on `from_id`/`to_id` (polymorphic). | ⬜ Open |
| DB-109 | Constraints | No CHECK constraint on `Supplier.tier` values (should be 1, 2, 3 only). | ⬜ Open |
| DB-110 | Constraints | No CHECK constraint on `Order.status` values (enum enforced at app level only). | ⬜ Open |
| DB-111 | Constraints | `DisruptionEvent.severity` no CHECK constraint (app-level enum only). | ⬜ Open |
| DB-112 | Partitioning | `ml_shadow_predictions` will grow unbounded. No partitioning by `created_at` (monthly). | ⬜ Open |
| DB-113 | Retention | No TTL/archival job for `audit_events` (7 years?), `evidence_claims` (3 years?), `graph_write_events` (1 year?). | ⬜ Open |
| DB-114 | Connection Limits | `max_connections` not configured. Default 100 may be exhausted with pool_size=20 × multiple workers. | ⬜ Open |
| DB-115 | Migrations | Migration 009 creates 19 tables in single transaction. Long-running; locks `core.workspaces` during creation. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| DB-201 | Indexes | Duplicate indexes possible: `ix_graph_nodes_workspace_id` and `ix_graph_nodes_tenant_id` both single-column. Composite would serve both. | ⬜ Open |
| DB-202 | Indexes | `ml_feature_store` index on `(workspace_id, entity_type, entity_id)` but queries often filter by `feature_name` first. | ⬜ Open |
| DB-203 | Constraints | `Inventory.last_updated_at` has no CHECK constraint to ensure it's not in the future. | ⬜ Open |
| DB-204 | Constraints | `Order.requested_delivery_date` can be before `order_date`. No CHECK constraint. | ⬜ Open |
| DB-205 | Partitioning | `graph_snapshots` could benefit from partitioning by `version` ranges if versions grow very large. | ⬜ Open |
| DB-206 | Retention | `ml_model_evaluations` and `ml_model_registry` have no retention policy. Models accumulate indefinitely. | ⬜ Open |
| DB-207 | Migrations | Migration 001 creates 7 tables in single transaction. Large initial transaction. | ⬜ Open |
| DB-208 | Rollback | Migration 009 downgrade drops 19 tables with CASCADE. No data preservation. Not tested. | ⬜ Open |
| DB-209 | Connection Limits | `max_connections` default 100. With `pool_size=20` and 5 workers = 100 connections. No headroom. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| DB-301 | Indexes | `audit_events` has 4 single-column indexes. Could consolidate to composite for common query patterns. | ⬜ Open |
| DB-302 | Documentation | No ER diagram or data dictionary for the 40+ tables across 7 schemas. | ⬜ Open |
| DB-303 | Naming | Inconsistent naming: `graph_write_events.occurred_at` vs `audit_events.occurred_at` vs `ml_shadow_predictions.created_at`. | ⬜ Open |

---

## Frontend Audit Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| FE-001 | Auth | No login page / auth flow. MVP page accepts raw UUIDs; no JWT handling, no token storage, no redirect on 401. | ⬜ Open |
| FE-002 | Error Handling | `apiFetch` catches JSON parse errors silently. Non-JSON error responses (HTML error pages) return empty detail. | ✅ Fixed — try/catch with fallback detail |
| FE-003 | XSS Risk | `ErrorState` renders `detail` directly without sanitization. API error detail could contain HTML/JS. | ⬜ Open |
| FE-004 | Loading States | `MorningBriefPage` has basic `loading` boolean but no skeleton screens for individual cards. Perceived latency high. | ⬜ Open |
| FE-005 | Error Boundaries | No React Error Boundary at app level. Component crash crashes entire page. | ⬜ Open |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| FE-101 | Retry UX | `ErrorState` has retry button but no exponential backoff, no max retries, no user feedback during retry. | ⬜ Open |
| FE-102 | Optimistic Updates | No optimistic updates anywhere. All mutations are blocking. | ⬜ Open |
| FE-103 | Skeleton Screens | No skeleton components for cards/tables. `LoadingState` is just a spinner. | ⬜ Open |
| FE-104 | Offline Detection | No service worker, no offline queue, no "you're offline" banner. | ⬜ Open |
| FE-105 | Keyboard Accessibility | `RoleSwitcher` buttons lack `aria-pressed`. `WorkspaceSelector` dropdown not keyboard navigable (no focus trap, no ESC to close). | ⬜ Open |
| FE-106 | Focus Management | `WorkspaceSelector` dropdown opens but focus not moved to input. No focus trap in dropdown. | ⬜ Open |
| FE-107 | Error Boundaries | No error boundary per card. One card crash kills entire Morning Brief. | ⬜ Open |
| FE-108 | Notifications | No toast/notification system. Errors shown inline only; no success toasts. | ⬜ Open |
| FE-109 | Session Expiry | No token expiry warning, no auto-refresh, no redirect to login on 401. | ⬜ Open |
| FE-110 | Responsive Layout | `MorningBriefPage` uses `max-w-7xl` but tables overflow on mobile. No horizontal scroll handling. | ⬜ Open |
| FE-111 | TypeScript | `DecisionBrief` type generated from OpenAPI but `any` used in `EvidenceDrawer` table rendering. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| FE-201 | Bundle Size | No code splitting. All MVP components in single bundle. No lazy loading for EvidenceDrawer tabs. | ⬜ Open |
| FE-202 | Accessibility | Color-only severity indicators (red/orange/amber/emerald) fail WCAG for colorblind users. Need icons/text. | ⬜ Open |
| FE-203 | Focus Visible | Custom focus styles missing on buttons/inputs. Browser default outline removed by Tailwind `focus:outline-none`. | ⬜ Open |
| FE-204 | ARIA | `EvidenceDrawer` tabs lack `role="tablist"`, `aria-selected`, `aria-controls`. | ⬜ Open |
| FE-205 | Live Regions | No `aria-live` region for loading/error announcements. Screen readers won't announce state changes. | ⬜ Open |
| FE-206 | Bundle Size | `next.config.js` has no bundle analyzer. No visibility into chunk sizes. | ⬜ Open |
| FE-207 | Performance | `EvidenceDrawer` renders all tab tables at once (conditional render but all in DOM). Should lazy-mount active tab only. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| FE-301 | TypeScript | `useWorkspace` returns `[string, setter]` tuple; not typed as `readonly [string, Dispatch<SetStateAction<string>>]`. | ⬜ Open |
| FE-302 | Accessibility | `LoadingState` spinner has no `aria-label` or `role="status"`. | ⬜ Open |
| FE-303 | Code Quality | `format.ts` uses magic numbers (70, 40, 15) for severity thresholds. Should be constants. | ⬜ Open |

---

## Integration Audit Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| INT-001 | OpenAPI | `createSupplierFailureBrief` in frontend calls `/api/v1/briefs/supplier-failure` but OpenAPI spec generated from backend may have different path (`/api/v1/mvp/briefs/supplier-failure`). Contract drift likely. | ⬜ Open |
| INT-002 | Auth | Frontend `apiFetch` sends no Authorization header. Backend expects Bearer token in pilot/prod. All authenticated calls will 401. | ✅ Fixed — auth header injection from localStorage |
| INT-003 | Caching | `RateLimitHeadersMiddleware` and `CircuitBreakerMiddleware` use in-memory state. Frontend has no awareness of rate limits (no `X-RateLimit-*` header consumption). | ⬜ Open |
| INT-004 | Uploads | Frontend `api.post` sends JSON but ingestion endpoint expects `multipart/form-data`. File upload will fail. | ✅ Fixed — streaming ingestion endpoint accepts multipart |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| INT-101 | OpenAPI | `DecisionBrief` type generated from OpenAPI but backend `briefs.py` returns hand-crafted dict, not Pydantic model. Field mismatches likely (e.g., `brief.scenario.scenario_type` vs `brief.scenario.scenario_type.value`). | ⬜ Open |
| INT-102 | Caching | `RedisCache` and `NoOpCache` implement `GraphCache` protocol but `create_cache()` falls back silently to `NoOpCache`. Frontend/backend cache mismatch not detectable. | ⬜ Open |
| INT-103 | Auth Flow | No login page, no token storage, no refresh flow. Frontend cannot authenticate to pilot/prod backend. | ⬜ Open |
| INT-104 | Upload Progress | Ingestion endpoint processes synchronously (no background job). Frontend has no progress indicator for large uploads. | ⬜ Open |
| INT-105 | Error Contracts | Backend returns `{"detail": "..."}` for 4xx/5xx. Frontend `ApiError` expects `detail` but backend validation errors return `{"detail": [{"loc":..., "msg":...}]}`. | ⬜ Open |
| INT-106 | WebSocket | No WebSocket integration for real-time updates (brief generation progress, ingestion status). Polling only. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| INT-201 | Caching | `RateLimitHeadersMiddleware` reports `X-RateLimit-*` headers but frontend doesn't read them. No client-side rate limit awareness. | ⬜ Open |
| INT-202 | Versioning | No API version negotiation. Frontend hardcodes `/api/v1`. No backward compat strategy. | ⬜ Open |
| INT-203 | Health Checks | Frontend has no `/healthz`/`/readyz` check before API calls. Fails silently if backend down. | ⬜ Open |
| INT-204 | Request ID | Backend sets `X-Request-ID` header. Frontend `ApiError` reads it but doesn't display in UI for support. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| INT-301 | Documentation | No Postman collection or OpenAPI-based client SDK generation script for external consumers. | ⬜ Open |
| INT-302 | Contract Testing | No contract tests (Pact) between frontend and backend. Drift detected only at runtime. | ⬜ Open |

---

## Performance Audit Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| PERF-001 | Load Testing | No k6/Locust scripts exist. No baseline performance numbers. No CI performance gate. | ⬜ Open |
| PERF-002 | DB Profiling | `pg_stat_statements` not enabled. No slow query tracking. No `EXPLAIN ANALYZE` on hot paths. | ⬜ Open |
| PERF-003 | Memory Leaks | No heap profiling in CI. `ingest_csv` loads entire file + all resolver caches into memory. OOM risk at 200MB. | ✅ Fixed — streaming ingestion eliminates OOM risk |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| PERF-101 | Stress Testing | No stress test at 2x expected peak. No spike test at 10x burst. | ⬜ Open |
| PERF-102 | Endurance | No 1hr+ sustained load test. Memory/connection leaks undetected. | ⬜ Open |
| PERF-103 | DB Profiling | No `auto_explain` module. Slow queries (>5s) not logged automatically. | ⬜ Open |
| PERF-104 | Cache Profiling | Redis `INFO` not monitored. Hit rates, evictions, memory fragmentation unknown. | ⬜ Open |
| PERF-105 | Memory Leaks | `SqlGraphRepository.load_workspace_graph` loads entire graph into memory. No streaming. | ⬜ Open |
| PERF-106 | CPU Profiling | No py-spy / perf profiling in CI. Hot paths unknown. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| PERF-201 | Frontend Bundle | No bundle size budgets. No code splitting. Initial JS payload unknown. | ⬜ Open |
| PERF-202 | Rendering | `EvidenceDrawer` renders all tab tables (conditional but all mounted). Should use `React.lazy` + `Suspense`. | ⬜ Open |
| PERF-203 | API Latency | No p50/p95/p99 latency tracking per endpoint. No SLO definitions. | ⬜ Open |
| PERF-204 | DB Connection | Pool size 5/20 hardcoded. No monitoring of pool utilization / queue wait time. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| PERF-301 | Flamegraphs | No automated flamegraph generation in CI. | ⬜ Open |
| PERF-302 | Frontend Perf | No Lighthouse CI. No Core Web Vitals tracking. | ⬜ Open |

---

## Reliability Audit Issues

### P0 — Critical

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| REL-001 | Graceful Shutdown | No SIGTERM/SIGINT handler. `lifespan` shutdown doesn't drain connections. K8s SIGKILLs after grace period. | ✅ Fixed — SIGTERM/SIGINT handlers with drain |
| REL-002 | DB Failover | No circuit breaker on DB connection. `CircuitBreakerMiddleware` only protects HTTP routes, not DB calls. | ⬜ Open |
| REL-003 | Redis Failover | `RedisCache` has no fallback. `create_cache()` returns `NoOpCache` silently. No alert when Redis down. | ⬜ Open |

### P1 — High

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| REL-101 | Chaos Testing | No chaos tests (kill DB, kill Redis, network partition, disk full). | ⬜ Open |
| REL-102 | Graceful Shutdown | `start_metrics_server()` not stopped on shutdown. Port leak on restart. | ⬜ Open |
| REL-103 | Duplicate Requests | No idempotency keys. Duplicate POST creates duplicate data. | ⬜ Open |
| REL-104 | Corrupt Uploads | Ingestion validates row-by-row but no file-level checksum verification against stored S3 object. | ⬜ Open |
| REL-105 | Large Uploads | 200MB limit but no chunked/resumable upload. Network blip = full re-upload. | ⬜ Open |
| REL-106 | Expired Sessions | No session expiry handling. JWT expires silently; frontend shows generic error. | ⬜ Open |

### P2 — Medium

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| REL-201 | Network Partition | No test for DB network partition (partial connectivity). App may hang on timeout. | ⬜ Open |
| REL-202 | Disk Full | No disk space monitoring. `ingest_csv` writes to S3 then DB; local temp space not checked. | ⬜ Open |
| REL-203 | Clock Skew | JWT `exp` uses server time. No tolerance for clock skew between app and DB. | ⬜ Open |
| REL-204 | Graceful Degradation | `CircuitBreakerMiddleware` only on expensive routes. Non-expensive routes fail open. | ⬜ Open |

### P3 — Low

| ID | Component | Description | Status |
| --- | --- | --- | --- |
| REL-301 | Runbooks | No incident runbooks for common failures (DB down, Redis down, OOM, disk full). | ⬜ Open |
| REL-302 | Postmortems | No postmortem template or process. | ⬜ Open |

---

## Progress Summary

| Phase | Total Checks | Passed | Failed (P0) | Failed (P1) | Failed (P2) | Failed (P3) |
| --- | --- | --- | --- | --- | --- | --- |
| Security | 15 | 2 | 8 | 10 | 5 | 2 |
| Backend | 12 | 6 | 7 | 10 | 10 | 3 |
| Database | 10 | 0 | 9 | 15 | 9 | 3 |
| Frontend | 12 | 1 | 4 | 11 | 7 | 3 |
| Integration | 8 | 2 | 2 | 6 | 4 | 2 |
| Performance | 8 | 1 | 2 | 6 | 4 | 2 |
| Reliability | 8 | 1 | 2 | 6 | 4 | 2 |

---

## Exit Criteria

- [ ] Zero P0 issues open
- [ ] Zero P1 issues open
- [ ] All P2 issues triaged with owner + ETA
- [ ] Load test passes at 2x expected peak
- [ ] Chaos tests pass (DB/Redis kill)
- [ ] OpenAPI spec matches implementation 100%
- [ ] Deployment/rollback documented and tested
- [ ] Observability dashboards live (RED/USE metrics)