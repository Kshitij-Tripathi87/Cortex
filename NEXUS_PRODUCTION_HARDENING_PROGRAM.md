# Nexus Production Hardening Program

**Created:** 2026-08-25
**Owner:** Engineering
**Status:** IN PROGRESS — Phase 1 (Baseline)

```
REAL DATA → WORLD STATE → INTELLIGENCE → DECISION → GOVERNANCE
          → EXECUTION → OUTCOME → EVIDENCE → TRACEABLE BACK TO SOURCE
```

The central acceptance criterion. Frontend and backend participate in the
**same chain** — not parallel systems displaying separate results.

## Governing Rules

1. **Never declare a component production-ready based on isolated unit tests.**
   Production-readiness requires the complete running stack.
2. **No silent fallback.** No implicit "latest" resolution, no plausible-looking
   fake data on failure, no `world_state_version = 101` style constants.
3. **Fail closed.** Security decisions deny on dependency failure. Never
   turn a Redis outage into an authorization success.
4. **Contract identity.** `GET .../evidence?decision_id=X` must return
   `evidence.decision_id == X`. Anything else is a contract violation.
5. **The server decides authorization.** Frontend state can never influence
   `CAN EXECUTE?`. The frontend only requests `EXECUTE`.

## Phase Ledger

| # | Phase | Status | Evidence |
|---|-------|--------|----------|
| 1 | Authoritative baseline (full stack, measured) | ✅ MEASURED | `BASELINE_REPORT.md` — 10 gaps tracked |
| 2 | Nexus frontend recovery (tsc / build / routes / states) | 🔄 COMPILE GREEN | tsc=0 ✅ build=0 ✅ (45 routes) — route/state matrix + E2E pending |
| 3 | API boundary hardening (contracts, authZ, error model) | 🔄 STARTED | G1 taxonomy contract unified; G8 type-shadow dedup open |
| 4 | Integration suite (Dataset→…→Evidence regression) | ✅ CORE DONE | Hermetic vertical-slice regression green (fixture + `CORTEX_OLIST_DIR` override); realtime/contract suites pending |
| 5 | Failure-behavior tests (backend + frontend) | ⬜ | failure matrix results |
| 6 | Realtime correctness (seq/version/resync protocol) | 🟡 PARTIAL | E1 seq/resync handshake done (`workspace.py`, `graph_delta_engine.py`); `test_realtime_seq_resync` green. WS-handshake auth (D3d) fixed 2026-08-28 — `verify_token` signature verification, fail-closed in prod, header-identity mirror in dev. D3f (realtime stats operator role) deferred to Step 7. |
| 7 | PostgreSQL concurrency hardening (10→1000 writers) | ⬜ | concurrency test results |
| 8 | Redis production semantics (per-use failure model) | 🟡 PARTIAL | **Step 2 (2026-08-28):** Redis client now has `socket_connect_timeout=0.2` + `socket_timeout=0.5`; `cache_manager` caches Redis health (30 s up / 5 s down); `_set` is fire-and-forget so a dead Redis cannot block the real-time pipeline; `is_redis_available` is bounded by `asyncio.wait_for`. `test_redis_fail_closed` (11/11) and the two pipeline latency tests (`test_realtime_state_pipeline_end_to_end` <50 ms, `test_load_state_pipeline_throughput` <100 ms avg) all green. **Redis-recovery scenarios + the failure-model table remain Step 9 work.** |
| 9 | API performance (P50/P95/P99, SLOs) | 🟡 PARTIAL | **Step 3 (2026-08-28):** `prometheus_client>=0.21.0` is now a declared dependency in `pyproject.toml` and installed. `metrics.py` exposes a real Prometheus `Histogram` / `Counter` / `Gauge`; `_DummyMetric` fallback only triggers if the package is missing (CI must guarantee it). SLO catalog (`slo.py` + `docs/architecture/F1_SLO_CATALOG.md`) and the bucket-schema regression (`test_slo_catalog.py::TestHistogramBucketSchema`) green. **Live P95/P99 measurements on real load + alert rules remain Step 9.** |
| 10 | Production infra (backup/restore, probes, K8s) | 🟡 PARTIAL | G5 git done; **F2 readyz composition** wired (`main.py` → `app.infrastructure.health` checks DB / Redis / object-storage / audit-chain marker); `k8s/base.yaml` gained a startupProbe. **Backups (`k8s/cronjob-pg-backup.yaml`, `scripts/backup.py`) not yet exercised in CI.** |
| 11 | Observability (end-to-end trace: request→evidence) | 🟡 PARTIAL | **F3** `app/infrastructure/trace_context.py` provides OTel trace-id propagation across the queue hop (`build_envelope` / `restore_from_envelope` / `traced_section`). **`MetricsMiddleware` now records into a real Prometheus histogram (post-Step 3).** End-to-end trace walkthrough (request → DB → audit emission under one trace) is the F3 acceptance gate, still pending an integration run. |
| 12 | Security hardening (RLS, isolation, scanning) | 🟡 PARTIAL | `app/infrastructure/tenant.py` (RLS `SET LOCAL` helpers), `app/infrastructure/security_scan.py` (pip-audit wrapper) landed. **D3a–D3f authz debt** (40 ungated routes; see `ENDPOINT_AUTHZ_AUDIT.md`) and CSRF/SEC-002/004/005/009 (security audit) remain open. |
| 13 | Real-data validation (multi-dataset, no fake constants) | 🔄 STARTED | Orchestrator de-fabricated (G4); **G4b open**: counterfactual simulations + shipment telemetry are declared scenario inputs — wire real Digital Twin runtime |
| 14 | Chaos / resilience (kill deps, inject faults) | ⬜ | chaos test results |
| 15 | Final production gate | ⬜ | all boxes checked below |

## Hardening-track execution log (2026-08-25 → 2026-08-28)

| Step | Commit / change | Result |
|---|---|---|
| Step 1 | `acdd197` — checkpoint commit: preserve the full hardening-track working tree (modified files + untracked infra modules + new hardening tests + new architecture docs + scratch-script archive) | working tree clean; verifiable baseline before code changes |
| Step 2 | Redis latency regression fix: bounded timeouts in `redis_client.py`; cached health + fire-and-forget `_set` + bounded `is_redis_available` in `cache_manager.py`; fixed latent double-decode in `_get` | `test_realtime_state_pipeline_end_to_end` <50 ms; `test_load_state_pipeline_throughput` <100 ms avg (was hanging >180 s); `test_redis_fail_closed` 11/11 |
| Step 3 | Add `prometheus-client>=0.21.0` to `pyproject.toml` and install | `metrics.py` real Prometheus; `test_slo_catalog.py::TestHistogramBucketSchema` green (was `_DummyMetric` no-`_upper_bounds`) |
| Step 4 | `RedisClient.publish` added; `realtime_gateway.broadcast` cluster fanout moved to fire-and-forget `_cluster_fanout` (bounded, failure-counted); `realtime.py` WS handshake now uses `verify_token` (signature-verified) and fails closed (4401) on missing/invalid tokens, mirroring header-identity in dev | 26 realtime/authz tests green; WS handshake is no longer `verify_signature: False` |

## Phase 15 — Final Production Gate (checklist of record)

```text
Backend:      [ ] unit  [ ] integration  [ ] pg concurrency  [ ] governance  [ ] evidence
Frontend:     [ ] tsc   [ ] prod build   [ ] all routes      [ ] error states [ ] stale-state
API:          [ ] OpenAPI contracts      [ ] contract tests  [ ] auth tests   [ ] pagination  [ ] timeout/retry
Integration:  [ ] real-data vertical slice  [ ] Signal→Evidence trace  [ ] exact decision_id
              [ ] no implicit/latest fallback  [ ] realtime correctness
Security:     [ ] RLS  [ ] tenant isolation  [ ] authorization  [ ] secret isolation  [ ] dep/container scan
Infra:        [ ] health/readiness  [ ] backups  [ ] restore  [ ] migrations  [ ] limits  [ ] scaling  [ ] rollback
Observability:[ ] logs  [ ] metrics  [ ] traces  [ ] alerts  [ ] SLOs
Resilience:   [ ] dep failure  [ ] restart recovery  [ ] network failure  [ ] stale state  [ ] dup events  [ ] concurrency
Performance:  [ ] baseline  [ ] P95/P99  [ ] queries optimized  [ ] load test
```

## Baseline Snapshot (Phase 1 output)

See `BASELINE_REPORT.md` for measured results. Key structural findings
are promoted into the phase ledger above as they are resolved.
