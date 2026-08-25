# 22 — Observability Model

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `11-deployment.md` (logs/metrics/traces), `16-event-taxonomy.md`, `21-performance-budgets.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

`11-deployment.md` §7 covers the *mechanics* (OTel, structured logs, retention).
Phase 1.5 freezes the **model**: which signals exist, which dimensions they
carry, what questions they answer, the SLI/SLO hierarchy, the alert
catalog, the health model, and the audit-as-observability alignment.

Cortex is enterprise software. The customer (a tenant admin or an enterprise
SRE) must be able to answer "is Cortex behaving?" in three seconds and
"why?" in three minutes — from the same surfaces Cortex itself uses. So
observability is product-facing, not just operator-facing.

## 2. The seven pillars (frozen)

| Id | Pillar | Source | Consumer | Retention |
|---|---|---|---|---|
| O1 | Metrics | Prometheus exposition (OTel-compatible) | Operator dashboards; alerts; admin UI | 30d hot, 13m cold |
| O2 | Logs | Structured JSON from every service | Operator queries; audit | 90d hot; 13m cold |
| O3 | Traces | OpenTelemetry SDK propagated through API→worker | Latency investigation; SOI | 30d |
| O4 | Audit | `audit_events` (T5) | Auditor role; BC8 admin | ≥ tenant policy (7y) |
| O5 | Health | `/healthz`, `/readyz`; readiness gates | LB; orchestrator; admin UI | live |
| O6 | SLIs/SLOs | Derived from O1, O3, O4 | Customer-visible status; release gates | 18m trend |
| O7 | Alerts | Rule registry over O1 + O4 | On-call; admin UI | 90d history |

## 3. Naming and dimensions (frozen conventions)

- **Namespaces**: `cortex.<subsystem>.<signal>` (e.g.
  `cortex.api.requests_total`). Subsystem maps to the bounded contexts
  (`15`).
- **Labels**: a frozen closed set per metric. High-cardinality labels
  (workspace_id) are quantized where allowed; no user ids, entity ids, or row
  contents are labels. Cardinality budgets enforced (a metric exceeding
  20 000 series triggers an alert).
- **Units**: baked into the name (e.g. `..._seconds`, `..._bytes`); the
  Prometheus expositor never uses raw integer "milliseconds" to mix units.
- **Resource attributes**: every OTel resource carries `service.name`,
  `service.version` (= image digest), `cortex.env`, `cortex.tenant_id`,
  `cortex.workspace_id` where applicable, `cortex.snapshot_id` where bound.

## 4. The frozen core metric catalog

Building on `11-deployment.md` §7.2; closed for Phase 1.5. Adding a metric id
is an ACR.

### 4.1 API edge
- `cortex_api_requests_total{method, status, route}` (counter)
- `cortex_api_latency_seconds{route}` (histogram, buckets per SLO tiers)
- `cortex_api_request_bytes` / `cortex_api_response_bytes` (histograms)
- `cortex_api_in_flight` (gauge)
- `cortex_api_idempotency_replays_total` (counter)

### 4.2 Evidence pipeline (BC1)
- `cortex_uploads_total{result, source_system}` (counter)
- `cortex_upload_bytes_total{source_system}` (counter)
- `cortex_evidence_extracted_total{extractor, verdict}` (counter)
- `cortex_claims_total{state, source_system}` (counter; gauge for state)
- `cortex_validation_issues_total{issue_type, severity}` (counter)
- `cortex_conflicts_open{entity_type}` (gauge)
- `cortex_reviews_open{assignee?}` (gauge)

### 4.3 Operational Graph (BC2)
- `cortex_entities_total{entity_type, lifecycle}` (gauge per workspace)
- `cortex_edges_total{edge_type, inferred}` (gauge)
- `cortex_graph_neighbors_query_seconds` (histogram)
- `cortex_graph_path_query_seconds` (histogram)
- `cortex_graph_query_rejected_total{reason}` (counter; includes `query_too_deep`)

### 4.4 Snapshots
- `cortex_snapshot_build_requested_total` (counter)
- `cortex_snapshot_sealed_total` (counter)
- `cortex_snapshot_build_duration_seconds` (histogram)
- `cortex_snapshot_seal_invalid_total` (counter)
- `cortex_snapshot_readiness_score` (gauge per workspace)

### 4.5 Decisions
- `cortex_decisions_total{decision_type, lifecycle}` (counter)
- `cortex_decisions_reverted_total` (counter)
- `cortex_decisions_open` (gauge)
- `cortex_outcomes_recorded_total` (counter)

### 4.6 ML Platform
- `cortex_ml_candidates_submitted_total{model_id}` (counter)
- `cortex_ml_candidate_confidence_overflow_total` (counter; MUST be 0)
- `cortex_ml_signature_failed_total` (counter; MUST be 0)
- `cortex_ml_shadow_inference_runs_total{model_id}` (counter)
- `cortex_ml_promotions_total` (counter)

### 4.7 Identity & Security
- `cortex_auth_token_issued_total{method}` (counter)
- `cortex_auth_step_up_required_total{action}` (counter)
- `cortex_permission_denied_total{action, role}` (counter)
- `cortex_rls_violation_total` (counter; MUST be 0; pages)
- `cortex_quota_exceeded_total{quota}` (counter)

### 4.8 Events (chains the audit category to metrics per `16` §8)
- `cortex_business_events_total{event_type, workspace_id}` (counter)
- `cortex_system_events_total{event_type}` (counter)
- `cortex_domain_events_total{event_type, target_context_id}` (counter)
- `cortex_integration_events_total{event_type, partner_id}` (counter)
- `cortex_audit_events_total{event_type, workspace_id}` (counter)
- `cortex_audit_chain_broken_total` (counter; MUST be 0; pages)
- `cortex_audit_storage_checksum_broken_total` (counter; MUST be 0; pages)

### 4.9 System / jobs
- `cortex_workers_active` (gauge)
- `cortex_worker_jobs{state, kind}` (gauge)
- `cortex_worker_job_duration_seconds{kind}` (histogram)
- `cortex_worker_job_failed_total{kind, reason}` (counter)
- `cortex_db_pool_in_use` (gauge)
- `cortex_db_query_duration_seconds` (histogram)
- `cortex_db_slow_query_total` (counter; threshold 200 ms)

### 4.10 Replay / determinism
- `cortex_replay_drift_total{step}` (counter; MUST be 0; pages)
- `cortex_policy_evaluator_runs_total{policy_id}` (counter)
- `cortex_policy_evaluator_drift_total{policy_id}` (counter; MUST be 0)

Any "MUST be 0" counter is treated as a continuous alert (anomaly), with a
hard page on first non-zero.

## 5. SLIs (per-subsystem, frozen)

A Service-Level Indicator is a metric (or derived ratio) that captures
goodness from the user's point of view. SLIs are defined percapability and
measured over the **last 28 days**.

| Capability | SLI | Definition |
|---|---|---|
| C1 Evidence Management | Validated upload success ratio | `uploads.result="ok"` / `uploads_total` |
| C2 Operational Modeling | Canonical write success ratio | canonical upserts with state `accepted` / total upserts |
| C3 Graph Intelligence | Graph read SLO-compliant latency ratio | successful `cortex_graph_*_query_seconds` ≤ budget target / total |
| C4 Operational Simulation | Scenario run success ratio | scenario `status=active` runs / total runs |
| C5 Decision Support | Recommendation determinism pass ratio | recommendation replays matching `input_hash` / total replays |
| C6 Decision Memory | Decision record completeness | decisions with non-null `decided_by_ref, policy_version, input_hash` / total |
| C7 ML Platform | Confidence ceiling compliance | ML candidates with confidence ≤0.5 / submitted |
| C8 Platform Administration | Admin action audit completeness | admin actions with emitted T5 / total admin actions |
| C9 Identity & Security | Zero RLS violations | 1 − (`rls_violation_total` / requests_total) |
| C10 Observability | Audit chain integrity | 1 − `audit_chain_broken_total` |
| C11 Developer Platform | Perf suite pass ratio | green perf runs / total perf runs |

## 6. SLOs (frozen)

Each SLI is paired with a target over the 28-day window. Crossings open an
error-budget burn investigation.

| Capability | SLO target | Error budget |
|---|---|---|
| C1 Validated upload success | ≥ 99.5% | 0.5% |
| C2 Canonical write success | ≥ 99.9% | 0.1% |
| C3 Graph read latency (within target, §3.4) | ≥ 99% | 1% |
| C4 Scenario run success | ≥ 99% (MVP: not measured) | 1% (later) |
| C5 Recommendation determinism | 100% | 0% (must be perfect; any drift blocks release) |
| C6 Decision completeness | 100% | 0% |
| C7 ML confidence compliance | 100% | 0% |
| C8 Admin audit completeness | 100% | 0% |
| C9 RLS violation rate | 0 per 30d | 0 (any ⇒ paging) |
| C10 Audit chain integrity | 100% | 0% |
| C11 Perf pass ratio | ≥ 95% | 5% |

Error-budget policy (frozen): when a capability exhausts its error budget
over 28 days, the team deprioritizes new features for that capability until
a post-mortem is completed. A zero-budget violation blocks release of any
new dependency on that capability.

## 7. Logs (O2) — frozen shape

- One JSON object per line. Each log carries: `ts`, `severity`,
  `msg`, `module`, `request_id`, `correlation_id`, `tenant_id`,
  `workspace_id`, `policy_version`, `snapshot_id`, `version` (image).
- **Severity ladder** (closed): `trace`, `debug`, `info`, `warn`, `error`,
  `critical`. `critical` logs page the on-call.
- **Redaction**: never logs PII, row contents, signals, model weights, or
  secrets. A nightly redaction test (`09` §3.3, `10` §9.1) verifies a sample
  of prod lines against known PII patterns; failure is release-blocking.
- **Audit-style**: structured logs are not a substitute for the audit log; if
  a log line is the only record of an auditable action, the system is buggy.
  Every auditable action writes a T5 row first; logs are operational.

## 8. Traces (O3) — frozen propagation

- W3C Trace Context propagation through API → service layer → worker → job
  events. Each async job inherits the parent `correlation_id` and opens a
  new span rooted at the parent.
- **Critical span attributes** (frozen, low-cardinality): `cortex.tenant_id`,
  `cortex.workspace_id`, `cortex.snapshot_id`, `cortex.policy_version`,
  `cortex.capability_id`. No entity ids are span attributes.
- **Sampling**: 100% for traces with errors or >2s duration; 10% baseline in
  pilot (production phase will tune). Failed dispatches are always traced.
- **Span coverage**: every endpoint, every worker job kind, every snapshot
  build, every policy evaluation, every audit emission, every connector run.

## 9. Audit (O4) — observability alignment

The audit log is the tamper-evident spine; metrics and logs are convenience
projections. Whenever a metric and the audit log disagree, the audit log is
authoritative (e.g. `cortex_decisions_total` must equal the count of
`decision.recorded` T5 rows; a mismatch is `audit.metric_drift` and the metric
is repaired). A nightly reconciliation job asserts parity for the "MUST equal"
metric-to-event pairs.

## 10. Health model (O5)

- `/healthz` (liveness, unauthenticated): returns `200 OK` boolean only.
- `/readyz` (readiness): returns `200 OK` only if DB pool warm, Redis
  reachable, object storage reachable, audit chain last-verified ≤1d; else
  `503 unavailable`.
- `/{workspace_id}/health` (internal admin): per-workspace readiness — last
  sealed snapshot age, readiness score, open conflict count, queue depth.
- Health surfaces must never reveal internal ids, secrets, or any audit data.

## 11. Alert catalog (frozen)

Each alert has: id, source metric, threshold, severity, route (on-call),
runbook link, auto-acknowledge window. Categories: **security**, **determinism**,
**reliability**, **degradation**, **quota**, **ops**.

| Id | Metric/condition | Sev | Route |
|---|---|---|---|
| A-S1 | `cortex_rls_violation_total > 0` | critical | security on-call |
| A-S2 | `cortex_audit_chain_broken_total > 0` | critical | security on-call |
| A-S3 | `cortex_ml_signature_failed_total > 0` | critical | security + ML on-call |
| A-S4 | `cortex_ml_candidate_confidence_overflow_total > 0` | critical | security on-call |
| A-D1 | `cortex_replay_drift_total > 0` | critical | capability on-call + release captain |
| A-D2 | `cortex_policy_evaluator_drift_total > 0` | critical | capability on-call |
| A-R1 | API p95 latency crossing `alert` (`21` §3.11) for 10m | warning | capability on-call |
| A-R2 | API 5xx rate ≥1% sustained 5m | critical | platform on-call |
| A-R3 | Snapshot build failing ≥3 consecutive | warning | capability on-call |
| A-G1 | Upload validation throughput below `alert` | warning | capability on-call |
| A-G2 | Worker job backlog growing for ≥10m | warning | platform on-call |
| A-Q1 | `cortex_quota_exceeded_total` sustained 30m | warning | tenant admin + sales ops |
| A-O1 | `audit.metric_drift_total > 0` | warning | observability on-call |
| A-O2 | Snapshot age per workspace > 24h | warning | capability on-call |
| A-O3 | Open conflicts > 10 000 per workspace | warning | tenant admin |

Anything not in this catalog cannot page; new alerts are added via an operator
PR reviewed by the on-call rotation and the security reviewer (for A-*1).

## 12. Dashboards (frozen set)

- **M**: the workspace overview (readiness, open reviews, recent snapshots, SLI
  sparklines). Customer-facing (admin role).
- **P**: platform overview (API edge, error rate, queue depth, capacity).
- **C-Pipeline**: evidence pipeline detail (uploads, claims, conflicts).
- **C-Graph**: graph + snapshot health.
- **C-Intelligence**: signals, recommendations, decisions, outcomes.
- **C-ML**: ML candidate + signature + confidence statistics (read-only).
- **C-Audit**: chain integrity, anomaly counters.
- **C-Security**: RLS, permission denied, step-up events.

Each dashboard is read-only in pilot; modifications require an admin ACR. A
"snapshot in time" export of a dashboard is auditable by the dashboard itself
emitting a `dashboard.viewed` audit event when accessed by a non-operator role.

## 13. Customer-visible status

A read-only `/status` page surfaces tenant-specific SLO status and health checks
(the M dashboard projection) to tenant admins only, scoped to their tenant. It
never crosses tenants; RLS applies. This is what "enterprise before convenience"
looks like in observability: customers do not have to ask the vendor whether
Cortex is healthy.

## 14. Frozen decisions summary

- Seven pillars (metrics, logs, traces, audit, health, SLI/SLO, alerts);
  `audit` is authoritative over metrics when they disagree.
- Closed metric catalog; closed SLI/SLO table; zero-tolerance alerts for
  security and determinism anomalies.
- High-cardinality labels quantized; no PII/entity ids as labels; redaction
  asserted nightly.
- Health endpoints reveal only status, never data; `/status` projects per-tenant
  health to the tenant admin scoped by RLS.
- Trace attributes and span coverage are frozen; w3c propagation across the
  async worker boundary is mandatory.
- Alert catalog is closed; paging outside the catalog is forbidden.
