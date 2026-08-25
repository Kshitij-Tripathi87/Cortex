# 10 — Testing Strategy and CI/CD

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `04-graph-and-events.md`, `05-api-standards.md`, `06-database-strategy.md`, `09-security.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Philosophy

Cortex is evidence-first and deterministic at the decision layer. Testing must
prove the same thing twice: that the rules are followed *and* that the rules are
reproducible. Two principles therefore drive this strategy:

1. **Determinism is the contract.** Every replay test asserts that same inputs
   plus same policy version yield byte-identical outputs (snapshots, signals,
   recommendations, decisions, audit events).
2. **Gates are real.** A test type that is not enforced in CI is not a test type;
   it is an aspiration. This document freezes which tests block what.

This document freezes the testing taxonomy, tooling, coverage targets, quality
gates, and CI/CD pipeline shape. It is written so an implementation team can
use it directly.

---

## 2. Test taxonomy (frozen)

| Type | What it proves | Tooling | Where run |
|---|---|---|---|
| Unit | Pure functions, domain rules, normalization, state machines | pytest, Ruff, mypy | CI:every push |
| Integration | Module + persistence + workers within the monolith | pytest + testcontainers (postgres, redis, minio) | CI:every push |
| Contract | API responses match OpenAPI; frontend client matches OpenAPI; event schemas match registry | schemathesis / OpenAPI self-test; openapi-typescript diff | CI:every push |
| End-to-end | User-visible flows through backend + frontend | Playwright + a frozen fixture dataset | CI:on merge to main; nightly |
| Regression | Determinism replays (snapshots, signals, recs, decisions) | seeded fixtures + artifact fixtures | CI:nightly; release gate |
| Performance | Latency/throughput targets from `01-architecture.md` §10 | k6 + a sealed snapshot dataset | nightly; pre-pilot gate |
| Security | RLS isolation, audit immutability, threat-model controls | custom + Bandit/pip-audit, OSV | CI:every push + nightly |
| Acceptance | Phase goals from `12-phase-1-acceptance.md` | manual + automated checklist | release/pilot gate |

---

## 3. Unit tests

### 3.1 Scope and rules
- Target ≥85% line coverage on `domain`, `resolution`, `graph`, `intelligence`,
  `decisions`, `audit`, and `auth` modules; ≥70% elsewhere except `api`
  (thin orchestration, covered by integration/e2e).
- Pure functions for normalization, unit conversion, identity-rule derivation,
  and state-machine transitions are exhaustively parameter-tested.
- Factories build entities/claims/edges; **no test constructs a canonical record
  by hand** — all go through the factories so the contract is enforced.

### 3.2 Deterministic policy tests
- For every deterministic policy (readiness, signal rule, recommendation rule,
  decision), the unit test asserts:
  - same inputs ⇒ same output (replay),
  - inputs_hash equals what the implementation computes,
  - explanation.evidence_refs is non-empty.

### 3.3 State machine tests
- Every legal transition is tested; every illegal transition is tested to
  return `invalid_state_transition`.
- Concurrency: a duplicate transition under a stale `version` returns `409`.

---

## 4. Integration tests

### 4.1 Scaffolding
- A full backend stack with testcontainers (postgres + redis + minio) is
  created per test session and reset per test class. Migrations are applied by
  Alembic; no schema is hand-initialized.
- A test tenant and a set of test workspaces are provisioned once per session;
  tests use scoped fixtures to avoid cross-contamination.

### 4.2 Required integration coverage (foundation flow)
The foundation flow (`01-architecture.md` §4.1) is end-to-end within the
backend at the integration level:
- upload → validation → extraction → claims → entity resolution → conflict
  detection → human review → canonical → graph construction → readiness.
- Each step is tested for success, partial failure, and replay-equality.
- Schema-mapping overrides are tested as audited calls.
- Idempotency: a retried upload-extraction produces no duplicate claims.

### 4.3 Required integration coverage (graph + events)
- Snapshot build seals an immutable snapshot whose `content_hash` is stable.
- Replay from `parent_snapshot_id` reproduces the same content_hash.
- A `DERIVED_FROM` cycle attempt is rejected.
- Audit events are emitted in the right order with the right `causation_id` and
  hash chain.
- Workers emit the same audit events as the backend for the same operation.

---

## 5. Contract tests

- **OpenAPI conformance**: every endpoint is exercised by schemathesis against
  the published OpenAPI; response shape drift blocks the build.
- **Frontend-client drift**: the generated TypeScript client is regenerated
  during CI and the diff must be empty; the build fails otherwise.
- **Event schema conformance**: every audit event emitted in integration tests
  is validated against the schema registry; unknown fields or wrong versions
  fail.
- **Database grant checks**: a startup test asserts the grants frozen in
  `06-database-strategy.md` §4 (INSERT-only on `audit.audit_events`, no UPDATE
  on immutable tables, etc.). Failure fails the test session.

---

## 6. End-to-end tests

- Playwright tests run against a fully composed stack (`docker compose`)
  exercising:
  - login, workspace switch, step-up auth for sensitive actions;
  - upload flow through schema mapping and validation summary;
  - conflict review resolution and audit-trail inspection;
  - graph exploration with deterministic layout assertions (screenshot diffs
    within a tolerance, snapshot-bound).
- The fixture dataset for e2e is a generated synthetic dataset committed to
  the repo so e2e results are reproducible.
- e2e runs on merge to main and nightly. e2e failures block release.

---

## 7. Regression tests

### 7.1 Replay regressions (frozen)
For each sealed snapshot in the regression corpus, an automated job:
1. Loads the snapshot's recorded inputs (claims, evidence, policy_version).
2. Recomputes the snapshot; asserts identical `content_hash`.
3. Recomputes inferred edges; asserts identical sets.
4. Recomputes signals/recommendations/decisions for the policy version on
   record; asserts identical outputs and `input_hash`.

Any drift fails the regression. A new policy version introduces a new expected
output fixture (committed alongside the policy version), preserving the
replay contract.

### 7.2 Migration regressions
- Every migration has an `undo` path tested against a clone of the latest
  pilot snapshot. Forward then reverse must return to a byte-equivalent schema
  state for the schema-shape checksum (excluding data that the migration
  intentionally removes, fully enumerated in the migration test).
- Migrations run on a copy of real (anonymized) production data nightly in
  staging for forward validation.

---

## 8. Performance tests

- k6 scripts exercise the API performance targets from
  `01-architecture.md` §10:
  - graph read p95 ≤300 ms for ≤2-hop / ≤10k-edge queries,
  - canonical upsert p95 ≤150 ms,
  - upload validation ≥5 MB/s per worker.
- A single sealed snapshot dataset (the "pilot perf fixture") is committed and
  used so numbers are comparable across runs.
- Thresholds are asserted as gates: regression >10% vs prior run is an
  **advisory** result; crossing the absolute target is **failing**.
- Perf tests run nightly and as a pre-pilot gate.

---

## 9. Security tests

### 9.1 Continuous (every push)
- Static analysis: Bandit, ruff rules S*, pip-audit on dependencies; npm audit
  on frontend. SBOM generated per build.
- Secrets scan: trufflehog-equivalent on the diff and the full repo history.
- RLS regression: a focused suite that opens a session as tenant A and asserts
  it cannot SELECT/INSERT/UPDATE/DELETE any row of tenant B; repeated for
  workspace-to-workspace within the same tenant.
- Audit immutability: attempting UPDATE/DELETE on `audit.audit_events` from the
  `app` role must raise permission denied; the grant-check startup test passes.
- Idempotency key collision: a duplicate concurrent call must produce exactly
  one canonical effect.

### 9.2 Nightly
- Audit hash-chain verification job; mismatch fails.
- RLS exhaustive matrix (every tenant-scoped table × every role).
- Path-filter validation against an attack pack (polyglot naming, `..`, macros,
  decompression bombs).
- ML signature verification pass over the registry; unsigned/tampered artifacts
  must refuse to load.
- Threat-model control assertions: each threat in `09-security.md` §12 has an
  automated assertion; failures must be triaged within 24h.

### 9.3 Periodic / pre-pilot
- External penetration test before pilot launch.
- Dependency CVE triage after every scan; high/critical CVEs block pilot launch
  unless mitigated and recorded.

---

## 10. Acceptance tests

Acceptance is a checklist defined in `12-phase-1-acceptance.md`. For
implementation phases, each phase defines its acceptance checklist in its own
document; the gate is run by the release process and signed off by the
engineering owner and a security reviewer.

---

## 11. Quality gates (frozen)

### 11.1 Before merge (per push)
- Lint (ruff, eslint, prettier) clean.
- Type check (mypy strict on backend, tsc on frontend) clean.
- Import linter (`01-architecture.md` §11) passes.
- Unit + integration + contract tests green.
- Coverage thresholds honored (§3.1).
- Security continuous tests (§9.1) green.
- OpenAPI drift check green.
- Frontend-client regeneration diff empty.
- DB grant-check test green.

### 11.2 Before release (per release candidate)
- All merge gates green on the release branch.
- e2e green on a clean stack.
- Regression replay green on the full snapshot corpus.
- Migration regression (forward+reverse) green.
- Performance within targets.
- Security nightly green for ≥3 consecutive nights on the candidate.
- Acceptance checklist signed off by engineering owner and security reviewer.

### 11.3 Before pilot deployment (additional)
- Pen test report acknowledged; high/critical findings mitigated or risk-accepted.
- Backup restore test passed within the last 30 days.
- Runbook exercises for incident-handling stub executed.
- Synthetic data flows only (no production data) used to validate; if prod data
  is used in staging, it is anonymized and tenant-approved.

---

## 12. CI/CD pipeline shape

A single GitHub Actions-based pipeline (or equivalent portable CI) with
ordered, parallelizable jobs. Frozen shape:

```
on push | PR:
  - lint           (ruff, eslint, prettier)
  - typecheck      (mypy, tsc)
  - import-linter
  - unit           (pytest, vitest)
  - security-static (bandit, npm audit, pip-audit, trufflehog)
  - integration    (testcontainers)              # depends on unit
  - contract       (openapi self + client drift) # depends on integration
  - db-grants      (startup grant_check)         # depends on integration
ausible:
  - e2e                                       # depends on merge-to-main only
nightly:
  - regression-replay
  - perf
  - security-nightly
  - migrations-against-anon-prod-snapshot
release candidate:
  - merge-to-release-branch
  - run the 11.2 gate; require 3 nightly greens
  - build signed images, publish SBOM
```

- Each job runs in a pinned container; no `latest` base images.
- A single set of pinned dependencies is shared by lint/test/build via a
  lockfile.
- Builds are reproducible: same commit + same pinned environment ⇒ same image
  digest (asserted by re-build diff in CI).
- Cancel-in-progress for pushes; never for nightly/release.

---

## 13. Test data and fixtures

- Synthetic data is the default for all automated tests
  (`08-ml-platform-strategy.md` §4). Production-data fixtures are not committed.
- Fixtures live under `backend/tests/fixtures` and `frontend/tests/fixtures`,
  one subfolder per concern; committed synthetic datasets live under
  `backend/tests/datasets` and are content-hashed.
- Snapshot fixtures for replay live under the regression corpus and are
  append-only; new snapshots are added, old ones retained so historical
  replayability remains provable.

---

## 14. Observability of tests

- Test runs emit JUnit XML consumed by a test reporter with a 90-day history.
- Flaky tests are auto-detected (failure rate between 1% and 50% over 30 days)
  and quarantined; a flaky test is treated as a failing test for the daily
  gate after a 7-day fix window.
- Coverage and perf trend Web are dashboards (see `11-deployment.md`).

---

## 15. Frozen decisions summary

- Eight test types frozen (unit/integration/contract/e2e/regression/perf/security/acceptance).
- Replay-determinism is a first-class test for snapshots, signals, recs, decisions.
- Three quality gates: merge / release / pilot, each with explicit must-pass items.
- Contract tests cover OpenAPI, frontend client, event schemas, DB grants.
- Synthetic data is the default; production data is anonymized and tenant-approved.
- CI is ordered, parallel where possible, with reproducible builds and SBOM.
- Flaky tests are detected automatically and quarantined with a fix window.

Phase 1 proceeds to `11-deployment.md` on this basis.
