# 11 — Deployment Strategy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `06-database-strategy.md`, `09-security.md`, `10-testing-and-ci-cd.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and posture

Phase 1 freezes a deployment model that is **portable and production-oriented**
without committing to a single cloud. The same images and the same
configuration shape run on a laptop, in staging, and in pilot. A production
topology is the pilot topology scaled and hardened — never a separate fork.

This document freezes environments, Docker/Compose strategy, environment
variables, CI/CD, rollback, observability, monitoring, logging, metric and trace
shape, and backups.

---

## 2. Environments (frozen set)

| Env | Purpose | Data | Tenants | SLOs |
|---|---|---|---|---|
| `dev` (local) | Per-engineer stack | Synthetic only | One seeded tenant | none |
| `staging` | Merge verification, continuous validation | Synthetic + optional anonymized | Multi-tenant seeded | none, but monitored |
| `pilot` | Real-customer pilot evaluation | Real tenant data | Per-pilot-customer | business-hours SLO |
| `prod` (later) | Production | Real tenant data | Per-customer | 99.9% target |

**Environment separation is strict** (`09-security.md` §10): no shared secrets,
no shared KMS keys, no copy-from-prod without anonymization and tenant approval
and time-boxed access. `prod` is out of Phase 1 scope but its requirements are
stated so pilot does not preclude it.

### 2.1 Local development
- One command brings the full stack up: `scripts/dev-up.ps1` (Windows) and
  `scripts/dev-up.sh` (POSIX). It uses `docker compose` with profiles:
  `core`, `workers`, `ml` (optional), `observability`.
- Hot reload for backend (uvicorn `--reload`) and frontend (`next dev`).
- A seeded synthetic tenant and a few workspaces are provisioned by a `seed`
  script so login, uploads, and graph exploration work immediately.

### 2.2 Staging
- Identical images to pilot; configuration via environment only. Reset nightly
  from synthetic fixtures plus an anonymized snapshot of pilot (per tenant
  approval, on a timer that purges after the configured window).
- Hosts the e2e suite and regression-replay on the nightly cadence.

### 2.3 Pilot
- Single region. Managed Postgres + managed object storage + a small cluster of
  backend API + N workers behind a load balancer; frontend served via CDN.
- Business-hours SLO; a maintenance window is published; no 24/7 incident
  rotation required in pilot.

### 2.4 Production (later)
- Superset of pilot: multi-AZ Postgres with replicas, multiple API/worker
  deployments Behind an LB with autoscaling, global CDN, multi-region object
  storage replication, full retention and observability, a 24/7 incident
  rotation. Phase 1 freezes the *direction* (portable IaC, no vendor-specific
  business logic) but not the concrete topology.

---

## 3. Docker and container strategy

### 3.1 Images
- One image per long-lived service: `cortex-backend`, `cortex-worker`,
  `cortex-frontend` (served by Node in the same container), `cortex-migrate`
  (an init container that runs Alembic), `cortex-mltrainsandbox` (later).
- Distroless/minimal bases, non-root users, read-only root filesystem where
  possible, writable only to per-job scratch (`08-ml-platform-strategy.md` §11,
  `09-security.md` §11 sandbox).
- Each image is signed (sigstore/cosign); deployment verifies signatures and
  refuses unsigned images.
- Builds are reproducible (`10-testing-and-ci-cd.md` §12): same commit + same
  pinned toolchain ⇒ same digest.

### 3.2 Compose
- `infra/docker/compose.yaml` is the local and staging base. It references the
  same images used in pilot via env-specific `.env.<env>` files.
- Services: `postgres`, `redis`, `minio`, `backend`, `worker`, `frontend`,
  `otel-collector`, `prometheus`, `tempo` (or cloud equivalents in pilot via
  env).
- Health checks are explicit; the `cortex-migrate` init container waits for
  Postgres and runs migrations before the backend/worker start.

### 3.3 Kubernetes (pilot onward)
- `infra/k8s/` holds portable manifests (or Helm charts). Vendor-neutral
  primitives only (Deployment, Service, Ingress, HPA, ConfigMap, Secret).
  Cloud-specific load balancer annotations are isolated in a thin overlay.
- Pods run with security contexts: `runAsNonRoot: true`, `readOnlyRootFilesystem:
  true` where possible, `allowPrivilegeEscalation: false`, dropped capabilities,
  seccomp `RuntimeDefault`.
- Workers are a single `Deployment` whose jobs are dispatched by Redis-backed
  queue; horizontal scaling driven by queue depth.

---

## 4. Environment variables (frozen)

All configuration is supplied via env vars, validated at startup by a typed
config module (`backend/app/config.py`). Missing required or invalid values fail
fast with a clear error — never silent defaults. The closed set:

### 4.1 Required everywhere
- `CORTEX_ENV` — `dev|staging|pilot|prod`.
- `CORTEX_LOG_LEVEL` — `trace|debug|info|warn|error`.
- `CORTEX_DB_DSN` — asyncpg DSN with TLS enforced in staging+.
- `CORTEX_REDIS_URL`.
- `CORTEX_OBJECT_STORE_ENDPOINT`, `CORTEX_OBJECT_STORE_BUCKET`,
  `CORTEX_OBJECT_STORE_REGION`, `CORTEX_OBJECT_STORE_ACCESS_KEY`,
  `CORTEX_OBJECT_STORE_SECRET_KEY` (or cloud-equivalent IAM role in pilot).
- `CORTEX_OTEL_EXPORTER_OTLP_ENDPOINT`.

### 4.2 Secrets (resolve from secrets manager)
- `CORTEX_JWT_SIGNING_KEY_RSA` — RSA private key (pilot/prod); dev can use a
  generated dev key.
- `CORTEX_AUDIT_SIGNATURE_KEY` — separate key for audit/retention signing.
- `CORTEX_ML_ARTIFACT_VERIFY_KEY` — public key for verifying ML signatures.
- `CORTEX_KMS_*` — provider-specific; per-tenant DEK access.

### 4.3 Tunables (defaults frozen; admin override)
- `CORTEX_DB_POOL_MIN`, `CORTEX_DB_POOL_MAX` (default 4 / 20).
- `CORTEX_WORKER_CONCURRENCY` (default 8).
- `CORTEX_QUERY_TIMEOUT_MS` (5000), `CORTEX_TX_TIMEOUT_MS` (10000).
- `CORTEX_GRAPH_MAX_LIVE_DEPTH` (4).
- `CORTEX_UPLOAD_MAX_BYTES` (per-tenant override; default 200 MB).
- `CORTEX_IDEMPOTENCY_TTL_S` (86400).
- `CORTEX_AUDIT_RETENTION_DAYS` (per-tenant policy; default 2555 = 7y).

### 4.4 Frontend (public, build-time)
- `NEXT_PUBLIC_API_BASE_URL`.
- `NEXT_PUBLIC_API_VERSION` (`v1`).
- `NEXT_PUBLIC_ENV` (for showing the environment badge).

### 4.5 Forbidden configurations
- No DB DSN in the frontend.
- No service account credentials in env files committed to the repo.
- No `CORTEX_ENV=prod` in any non-prod environment config file.

---

## 5. CI/CD (high level; full shape at `10-testing-and-ci-cd.md` §12)

- Push → lint/typecheck/import-linter/unit/security-static in parallel.
- Merge to main → integration/contract/DB-grants; build signed images with SBOM;
  publish to the artifact registry; deploy to staging; run e2e.
- Release branch → run the 11.2 release gate; require ≥3 nightly greens; promote
  to pilot after checklist sign-off.
- Rollback is one click and reversible for 7 days; rollback is also used to
  rewind migrations only via the tested `undo` migrations (`06` §14).

Deployment strategy in pilot is **rolling deploy** for API/worker with a
readiness gate: new pods must serve `200 OK` from `/healthz` and have processed
a canary job without errors before receiving production traffic. Frontend is
deployed via an atomic blue/green switch at the CDN edge.

---

## 6. Rollbacks

### 6.1 Application rollback
- The previous image digest is the rollback target; rollback deploys it through
  the same rolling/CDN path forward.
- Rollback is reversible for 7 days. Beyond that, rollback requires an explicit
  incident and a fresh forward deployment with a verified image.

### 6.2 Data rollback (cautious by design)
- PostgreSQL PITR restores to a point in time within the retention window
  (`06-database-strategy.md` §10). Restoring is admin-only, audited, and
  documented in runbooks.
- Schema migrations are forward/undo pairs (`06` §14). The `undo` must be the
  rollback path for structural changes. Data-loss migrations are not used in
  emergencies; instead, a forward fix migration is preferred.
- A data rollback is *destructive* and is recorded via the `decisions.reverted`
  workflow with rationale and steps-up auth (`09-security.md` §2.3).

### 6.3 Snapshot rollback
- The canonical graph is recoverable to a prior sealed snapshot via the
  `decisions.reverted` workflow (`04-graph-and-events.md` §30); the system then
  re-bases new uploads on top of the prior snapshot.

---

## 7. Observability

### 7.1 Logs
- Structured JSON logs, one event per line, always carrying `request_id` or
  `correlation_id`, `tenant_id`, `workspace_id`, `module`, `severity`, `msg`.
- Logs never contain PII, row contents, signals, or model weights; redaction is
  enforced at the logging helper level and asserted by a nightly redaction test
  (a sample of production log lines is checked for known PII patterns).
- Log retention follows audit retention for `audit.*` events and a 90-day
  retention for operational logs.

### 7.2 Metrics
- Prometheus exposition format; OpenTelemetry-compatible collector.
- Frozen core metrics (the closed MVP set):
  - `cortex_http_requests_total{method, status, route}`
  - `cortex_http_latency_seconds{route}` (histogram)
  - `cortex_uploads_total{result, source_system}`
  - `cortex_claims_total{state, source_system}`
  - `cortex_conflicts_open` (gauge)
  - `cortex_graph_edges_total{type, workspace_id}` (gauge)
  - `cortex_snapshot_sealed_total`, `cortex_snapshot_build_duration_seconds`
  - `cortex_audit_events_total{event_type}`
  - `cortex_replay_drift_total{step}` (any non-zero ⇒ alert)
  - `cortex_worker_jobs{state}`, `cortex_worker_job_duration_seconds{kind}`
  - `cortex_ml_candidate_confidence_overflow_total` (any non-zero ⇒ alert)
  - `cortex_rls_violation_total` (any non-zero ⇒ alert and page)
- Cardinality guardrails: no high-cardinality labels except in aggregations;
  workspace_id labels are quantized; user ids are not labels.

### 7.3 Traces
- OpenTelemetry SDK with W3C Trace Context propagated through API → service →
  worker → next-job events, so a single upload's journey is traceable across
  async boundaries. Sampling: 100% for traces with errors or >2s duration, 10%
  baseline in pilot.
- Critical spans carry `cortex.tenant_id`, `cortex.workspace_id`,
  `cortex.snapshot_id`, `cortex.policy_version`, `cortex.claim_id`.

### 7.4 Dashboards and alerting
- Dashboards (read-only): SLO, traffic, error rate, p95 latency, upload pipeline,
  conflict backlog, snapshot health, audit chain, ML candidates, worker health.
- Alerts (routed to on-call): error-rate >1% sustained 5m, p95 latency breaching
  the §10 targets for 10m, `audit.chain_broken`, `rls_violation_total > 0`,
  `replay_drift_total > 0`, `ml_candidate_confidence_overflow_total > 0`,
  model signature failure, retention/quota violation.

---

## 8. Backups

- PostgreSQL: managed PITR with ≥35-day window; weekly logical `pg_dump`;
  nightly incremental. Restore tests run monthly
  (`10-testing-and-ci-cd.md` §11.3).
- Object storage: cross-region replication for pilot/prod; immutable-lock on
  raw uploads for tenant retention
  (`09-security.md` §5); daily checksum verification of the last 7 days of
  uploads. Mismatches raise `audit.storage_checksum_broken` and block release.
- Audit table: a separate logical backup of `audit.audit_events` per tenant
  partition, encrypted with a separate key, retained per §6 ret policy.
- Backup restore drills: executed quarterly in pilot with an after-action report
  stored in the admin UI.

---

## 9. Health and readiness

- `GET /healthz` — liveness, unauthenticated, returns `200 OK` boolean; no
  internals.
- `GET /readyz` — readiness, unauthenticated but verify DB pool, Redis,
  object-storage reachable; returns `200 OK` only when all dependencies are
  reachable, otherwise `503 unavailable`.
- Workers expose the same endpoints; the orchestrator scales based on
  `/readyz`.

---

## 10. Network and ingress

- TLS terminates at the load balancer; mTLS between LB and backend.
- Single public ingress for API + frontend; static assets via CDN at a separate
  hostname. No public ingress to Postgres, Redis, object storage, or workers.
- Rate limiting at the LB (coarse-grained) and at the app (per-user/per-tenant,
  `05-api-standards.md` §14). WAF ahead of the LB for staged pilot
  (baseline ruleset).

---

## 11. Resource and capacity planning (pilot)

- MVP sizing for pilot (single region):
  - API: 2 instances, 1 vCPU / 1 GiB each (HPA target: p95 latency
    §10 thresholds).
  - Worker: 2 instances, 2 vCPU / 2 GiB each (driven by queue depth).
  - Postgres: 4 vCPU / 16 GiB / 500 GiB SSD; partitioned per
    `06` §5.
  - Redis: 1 GiB instance.
  - Object storage: usage-based, per-tenant quotas.
- Capacity is reviewed monthly; growth >20% month-over-month triggers a
  capacity-change ACR.

---

## 12. Release and change management

- Every release has a human-readable release note summarizing changes, schema
  migrations, policy versions, ML promotions, known issues, and rollback path.
- Phase 1 fixes release note template fields; full release process is implemented
  in the release phase.
- ACRs (`README.md`) are required for any change to a frozen artifact
  (architecture, ontology, canonical model, graph model, event model, API
  conventions, DB strategy, frontend architecture, ML posture, security
  baseline, testing strategy, deployment strategy). Final ACR approval and
  merge are admin-only events in the audit log.

---

## 13. Frozen decisions summary

- Four environments (`dev/staging/pilot/prod`); strict separation; prod is a
  superset of pilot.
- Single image per service, signed, reproducible builds; portable IaC with
  vendor-specifics isolated.
- Env-var-driven configuration validated at startup; no silent defaults; no
  committed secrets.
- Rolling deploy with readiness gate; one-click rollback for 7 days; data
  rollback is cautious and audit-recorded.
- Logs/Metrics/Traces are OpenTelemetry-native; frozen core metrics; redaction
  asserted nightly.
- PITR + logical backups + immutable-lock on uploads; monthly restore drills.
- Capacity reviewed monthly; ACR-driven changes for frozen artifacts.

Phase 1 proceeds to `12-phase-1-acceptance.md` on this basis.
