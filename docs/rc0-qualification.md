# RC0 Qualification Record — Workflo Core R0

> Status: **staging qualification phase**. This document is the release
> gate record: what is proven, at which level (unit / application boundary
> / staging exercise), and what remains pending before the go/no-go.

## 1. Release scorecard

| Gate | Status | Evidence |
| --- | --- | --- |
| Policy-bound production receipts | **Complete** | `test_workflo_receipt_binding.py` (69 tests): resolution → policy_enforced event → signed receipt → independent verification |
| Executor/supervisor consistency | **Complete** | Both paths resolve through `ExecutionPolicyBundle.resolve`; receipt consumes the same immutable `ResolvedExecution` |
| Backend regression | **Green** | Full suite (1907+ tests) — final gate run recorded before RC0 branch |
| TypeScript regression | **Green** | `npm ci`, `typecheck`, `lint` (0 warnings), `test` (14/14), `build` |
| Receipt signing configuration | **Code-complete, staging config pending** | Fail-closed enforcement + compose `:?required` — see §3.1 |
| Registry image promotion | **CI-complete, first promotion pending** | build.yml pushes to GHCR on main, publishes digest — see §3.2 |
| CLI CI target reconciliation | **Complete** | `workflo-cli/` restored; `@cortex/workflo` owns `workflo policy validate`; CI gate target exists |
| S3 artifact-store qualification | **Test-complete, CI execution pending** | `test_evidence_store.py` (6 tests, runs against CI MinIO) |
| Deployed security qualification | **Application-boundary complete** | `test_workflo_security_qualification.py` (12 tests) — see §2 |
| DR & rollback rehearsal | **Pending (Day 5)** | Runbook in §5 |
| External pilot rehearsal | **Pending (Day 6)** | Staging acceptance workflow §4 |

## 2. Security qualification — what is proven at which level

| Control | Unit | Application boundary | Staging exercise |
| --- | --- | --- | --- |
| Tenant isolation (workspaces) | ✅ policy unit tests | ✅ cross-workspace 403 on sandbox/run/receipt/verify/events/files | ☐ Day 3 |
| Authorization (strict env) | ✅ | ✅ 401 without Bearer; workspace-scoped token cannot cross tenant | ☐ Day 3 |
| Queue/replay (destroyed sandbox reuse) | ✅ | ✅ 403 at API | ☐ Day 3 |
| Lifecycle evidence integrity | ✅ | ✅ event-chain tamper detected at `/events/verify`; receipt cross-check fails | ☐ Day 3 |
| Secrets non-leakage | ✅ env allowlist | ✅ host secret + signing key absent from all events/receipt/findings; receipt carries binding fields only | ☐ Day 3 |
| Policy integrity (digests) | ✅ | ✅ `IMAGE_IDENTITY_MISMATCH` denied at API; profile substitution detected | ☐ Day 3 |
| Receipt integrity | ✅ | ✅ stored-receipt tampering → hash mismatch; rotated key → signature mismatch | ☐ Day 3 |
| Egress policy | ✅ | ✅ profile cannot widen bundle egress | ☐ Day 3 (runtime network: container runner) |
| Runner isolation (FS/network/runtime) | ✅ command allowlist | partial (host-path/secret blocks at API) | ☐ Day 3 — requires the digest-pinned container runner |
| Object storage tenant isolation | ✅ | skip-gated (CI MinIO) | ☐ Day 2/3 |

Rule: **no staging exercise may be marked pass from unit evidence alone.**

## 3. Release blocker configuration

### 3.1 Receipt signing (fail-closed)

* `receipts.signing_required()` — enforced automatically for
  `CORTEX_ENV ∈ {staging, pilot, prod}`; explicit
  `CORTEX_REQUIRE_SIGNED_RECEIPTS=1|0` overrides.
* Without a configured `CORTEX_RECEIPT_SIGNING_KEY`, governed execution is
  **refused** (HTTP 503 `RECEIPT_SIGNING_UNAVAILABLE`) — with or without a
  policy bundle. Verification with `require_signature` fails closed.
* `docker-compose.prod.yml` declares
  `CORTEX_RECEIPT_SIGNING_KEY: ${CORTEX_RECEIPT_SIGNING_KEY:?...}` on all
  backend services → the deployment itself fails when the secret store
  hasn't provided the key.

**Staging operator action (Day 1):** inject `CORTEX_RECEIPT_SIGNING_KEY`
from the staging secret store; smoke: a governed run must produce a receipt
whose `/receipt/verify` reports `signature_ok: true`.

### 3.2 Image promotion & digest binding

* `build.yml` pushes `ghcr.io/<repo>/backend` and `/frontend` on main and
  records the **registry digest** in the job summary.
* Pin the promoted digest into the Workflo `RunnerProfile`
  (`name@sha256:…`) and inject the same value as
  `CORTEX_RUNNER_IMAGE_DIGEST`. Mismatch ⇒ resolution fails closed
  (`IMAGE_IDENTITY_MISMATCH`).

### 3.3 CLI

`workflo-cli` (npm `@cortex/workflo`) is the owner of
`workflo policy validate <file> [--json]` — exit 0 valid / exit 3 violation,
using the same stable codes as the control plane. The release-gate workflow
(`workflo-cli.yml`) has a real target again.

### 3.4 Evidence storage

`evidence_store.py` persists receipts/artifacts under
`workflo/{workspace_id}/runs/{run_id}/…` with tenant-guarded keys and
SHA-256 integrity verification. `test_evidence_store.py` runs in CI
against MinIO.

## 4. Staging acceptance workflow (Day 4 rehearsal script)

1. Deploy the **RC0 branch commit** (never `main` by accident).
2. Open a GitHub PR against a test repository.
3. Verify commit/source-tree identity in the control plane.
4. Generate + review the validation plan.
5. Resolve + enforce the execution policy (bundle + profile).
6. Run real Pytest/Playwright suites in the sandbox.
7. Inspect events, results, findings (`/runs/{id}`, `/events/verify`).
8. Generate the signed production receipt.
9. Verify independently: `/receipt/verify` → all `ok`; signature via public
   material (hash + HMAC check with the staging verification key).
10. Evidence storage: receipt/artifact present under the tenant prefix,
    integrity verified.
11. Publish the GitHub result.
12. **Negative repeats:** one policy-blocked execution (must produce NO
    receipt + auditable `policy_denied`) and one failing test run (must
    produce a receipt whose findings/verdict differ and are correctly
    represented).

## 5. DR & rollback runbook (Day 5)

**Backup/restore:** `pg_dump` staging DB → restore into isolated instance →
verify: app connects, `GET /workflo/runs/{id}` for a pre-backup run returns
the receipt + event stream intact (hash chain verifies), a new governed run
executes, recovery time and data-loss window recorded in the go/no-go report.

**Rollback:** deploy RC0 → controlled rollback to previous image/digest →
verify DB compatibility (migrations), previous version boots and serves a
governed run with receipts verifying under the same key. A successful
`helm rollback`/`docker compose up` alone is NOT the exit condition.

## 6. Freeze list (effective now)

No merges of: Autopilot expansion, advanced Tenant Shield screens, new AI
capabilities, frontend redesign, B10/billing/email — release-blocking
defects excepted.
