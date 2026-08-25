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
| 1 | Authoritative baseline (full stack, measured) | ✅ MEASURED | `BASELINE_REPORT.md` — 1336/1337 backend tests, 10 tracked gaps |
| 2 | Nexus frontend recovery (tsc / build / routes / states) | 🔄 COMPILE GREEN | tsc=0 ✅ build=0 ✅ (45 routes) — route/state matrix + E2E pending |
| 3 | API boundary hardening (contracts, authZ, error model) | ⬜ | contract audit table |
| 4 | Integration suite (Dataset→…→Evidence regression) | ⬜ | permanent regression test |
| 5 | Failure-behavior tests (backend + frontend) | ⬜ | failure matrix results |
| 6 | Realtime correctness (seq/version/resync protocol) | ⬜ | protocol tests |
| 7 | PostgreSQL concurrency hardening (10→1000 writers) | ⬜ | concurrency test results |
| 8 | Redis production semantics (per-use failure model) | ⬜ | failure-model table |
| 9 | API performance (P50/P95/P99, SLOs) | ⬜ | SLO doc + measurements |
| 10 | Production infra (backup/restore, probes, K8s) | ⬜ | validated runbooks |
| 11 | Observability (end-to-end trace: request→evidence) | ⬜ | trace walkthrough |
| 12 | Security hardening (RLS, isolation, scanning) | ⬜ | security audit pass |
| 13 | Real-data validation (multi-dataset, no fake constants) | ⬜ | dataset matrix |
| 14 | Chaos / resilience (kill deps, inject faults) | ⬜ | chaos test results |
| 15 | Final production gate | ⬜ | all boxes checked below |

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
