# Nexus Launch Build Log — v0.8.5 (Launch Candidate)

Running record of launch slices. Audit baseline: `docs/LAUNCH_GAP_REGISTER.md`
(Days 1–2). Scope freeze: P0 = B1–B10 + golden-path E2E + security/rehearsal/RC
(approved by proceeding default: open signup + trial stub, one workspace/org).

## Slice v0.8.5-B1 — Launch onboarding, backend (Day 3–4, part 1)

**Branch:** `arena/01a08657-cortex` · **Blockers:** B1 (signup/provisioning),
B7 (login/logout/me) — backend half. Frontend auth UI follows in slice B2.

### Shipped

| Area | Change |
|---|---|
| `POST /auth/signup` (201) | Open signup: creates organization + workspace + admin user in one transaction; seeds 7-day trial (`plan=trial`, `trial_ends_at`); global email uniqueness; slug uniquification; per-instance rate limit (30/hr); audit `auth.signup`. |
| `POST /auth/login` | Hardened: inactive-user rejection with uniform 401 (no enumeration oracle), per-email rate limit (20/15min), audit `auth.login`, response extended with `organization_id` (additive). |
| `GET /auth/me` | Principal + workspace + organization + trial state. Gated (`get_current_user`). |
| `POST /auth/logout` | Audit-recorded (`auth.logout`); client discards token (see limitation L1). |
| `POST /auth/change-password` | Current-password check + strength policy; audit `auth.password_changed`. |
| `POST /auth/reset/request` + `/reset/confirm` | Single-use 30-min tokens, hash-only storage, uniform responses (no oracle), token disclosed in-band ONLY in dev/test; pilot/prod delivery via admin CLI until Day-15 email. |
| Password policy | ≥10 chars, letter + digit (server-enforced on signup/change/reset). |
| Migration `015_auth_onboarding` | `core.organizations`; `workspaces.organization_id` (nullable FK); `users.full_name/is_active/password_changed_at`; `password_hash` 128→255; `core.password_resets`. Up + down verified on real PG. |
| `scripts/admin_users.py` | Operator CLI: `issue-reset`, `set-password`, `deactivate`, `activate`, `list`. |
| Tests `test_auth_onboarding.py` | 16 acceptance tests incl. real-JWT cross-workspace 403 on canonical `/nexus/decisions`. |
| Generated artifacts | `backend/openapi.json` + `frontend/src/types/openapi.json` + `api.ts` regenerated (183 paths; also picks up 10 previously-unrecorded `/nexus/models/*`, `/nexus/inference/*` routes). |
| Authz audit | `/signup`, `/reset/request`, `/reset/confirm` classified PUBLIC (note D3i) in test + `docs/architecture/ENDPOINT_AUTHZ_AUDIT.md`. |

### Incidental fixes (found by testing, required for correctness)

1. **`CORTEX_ENV` was silently ignored (critical).** Field `cortex_env` with
   `env_prefix="CORTEX_"` bound to `CORTEX_CORTEX_ENV`, so every deployment —
   including `prod` — ran dev header-identity (complete auth bypass). Fixed by
   renaming the field to `env` (per-field prefix opt-out is unsupported).
   `app/config.py`, `app/infrastructure/security.py`,
   `product/workflo_backend/infrastructure/security.py` updated; k8s
   manifests normalized `production`→`prod` (both spellings still accepted
   defensively). All CI workflows use `test` → non-strict → no CI behavior change.
2. **`AuditEvent.occurred_at` model/migration mismatch.** Model created naive
   `TIMESTAMP` while migration 001 specifies timestamptz and `emit()` passes
   tz-aware datetimes (asyncpg hard-fails). Model now matches the migration.
3. **Migration numbering.** First written as 013 against a stale tree listing;
   the real head was 014 → shipped as `015_auth_onboarding`.

### Verification (this slice)

- 16/16 new tests pass against real PostgreSQL (ephemeral `pgserver`).
- Targeted regressions pass: `test_endpoint_authz_audit`,
  `test_nexus_v082_routing_flip`, `test_dynamic_security_penetration`
  (36 + 19 green in combined runs).
- `ruff check` + `ruff format` clean; `mypy` (strict) clean on changed files.
- `alembic upgrade head` 001→015 + `downgrade -1` + re-`upgrade` verified.
- App boots; `/openapi.json` serves 183 paths incl. all 7 auth routes.
- Remaining gate: CI on the slice PR (full suite + E2E + typecheck incl.
  `openapi-types` drift check).

### Honest limitations (carried, not hidden)

- **L1 — no server-side token revocation.** Stateless HS256 (60 min). Logout
  is client-side + audit. Stolen tokens live until `exp`. Day-11 decision:
  Redis denylist vs. Baroness (documented in `auth.py` module docstring).
- **L2 — rate limits are per-process memory buckets.** Fine at launch scale;
  Redis-backed limiter if multi-instance abuse appears (Day 11).
- **L3 — reset delivery in pilot/prod is admin-assisted** until Day-15 email.
- **L4 — frontend still calls stale auth contract** (`/auth/logout`+`/auth/me`
  now exist; `LoginRequest` shape + pages pending slice B2).

### Next: slice v0.8.5-B2 — Auth UI + route guards (below)

## Slice v0.8.5-B2 — Auth UI + route guards (Day 3–4, part 2)

**Branch:** `arena/01a08657-cortex` · **Blockers:** B1 + B7, frontend half
(closes both). Follows the B2 spec: server-derived auth state, single
AuthProvider, validated `next`, no OAuth/SSO/MFA (deferred per spec).

### Shipped

| Area | Change |
|---|---|
| `lib/auth/` library | `client.ts` (central apiClient: Bearer injection, 15s timeout, X-Request-ID, normalized `ApiClientError`, single 401 hook), `errors.ts` (kind mapping + safe form messages), `token.ts` (single storage key, multi-tab logout sync, per-user onboarding ack), `next.ts` (double-decode-proof internal-path validator), `validation.ts` (zod mirrors of server policy), `types.ts` (B1 contracts). |
| `AuthProvider` | UNKNOWN→CHECKING→AUTHENTICATED/ANONYMOUS; boot resolves `/auth/me` iff a token exists; login/signup hydrate via `/auth/me`; logout best-effort + local clear; central 401 invalidation with protected-route bounce (`?next=` preserved). |
| Guards | `RequireAuth` (loader until resolved, anonymous → login?next=), `RequireAnonymous` (authed → next or /app); Suspense-safe for prerendering. |
| Pages | `/auth/login` (generic failures, email preserved, no double-submit, `?reset=1` notice), `/auth/signup` (exact B1 fields, backend creates everything), `/auth/forgot-password` (uniform message incl. on backend failure — no oracle), `/auth/reset-password` (uniform token errors), `/onboarding` (server-created org/workspace/trial verification + ack), `/app` (identity summary, live canonical `/nexus/decisions` status card distinguishing 403-stays-logged-in, change-password, logout). |
| Guards wired | `/app/*` (auth + ack gate), `/workspace/*` (auth; demo-context rewire stays B3+), root layout mounts `AuthProvider` (zero requests for anonymous visitors). |
| `lib/api/auth.ts` | Rewritten to the B1 contract (was stale: called nonexistent `/logout`, `/me`; zero importers so no fallout). |
| Base-URL config | Single knob `NEXT_PUBLIC_API_URL` for all new code; legacy `NEXT_PUBLIC_API_BASE_URL` honored as override (`http.ts` fallback added; legacy pages untouched — B3). |
| E2E | `tests/auth-e2e.spec.ts` (12 tests: full gate, guards, external-`next` rejection, generic failures, duplicate signup, expiry invalidation, 403-keeps-session, 429 UI, uniform forgot, reset round-trip, change-password). Workflow runs both specs in one invocation; `CORTEX_JWT_SECRET` added to e2e backend env (signup/login fail closed without it). |

### Backend changes in B2 (contract mismatches the slice exposed)

1. **Login without `workspace_id`** (`auth.py`, backward compatible). Users
   don't know their workspace UUID; signup's global email uniqueness makes
   email+password sufficient. Scoped lookup preserved when provided. +1 test.
2. **Dev/test verify-if-present** (`security.py`). Non-strict envs ignored
   Bearer tokens entirely, so login was unusable in dev/test/e2e. Now: a
   presented token MUST verify (shared strict-rules helper, 401 otherwise);
   anonymous + header callers byte-for-byte unchanged. Verified: no
   pre-existing test sends Bearer tokens over real HTTP. +4 tests.

### Verification (this slice)

- Backend 21/21 on real PG (17 B1 incl. login-without-workspace + 4 dev-mode token tests).
- `npm run build` clean; `tsc --noEmit` clean; `next lint` clean for new files.
- Auth logic unit-probed in Node (28 assertions: `next` attacks incl.
  double-encoding, error mapping, zod schemas) — 28/28.
- Live stack rehearsal (uvicorn + `next start` + migrated PG): all 6 routes
  200; matrix me/own-200, foreign-403, forged-401, anon-unchanged ✔.
- Playwright spec could NOT run locally (browser CDN blocked in sandbox);
  CI e2e is the gate. First CI run: 23/26 — the 3 failures were spec bugs,
  not product bugs (token-injecting tests bypassed the onboarding ack gate
  and correctly landed on `/onboarding` instead of `/app`; fixed by acking
  in the `setSession` helper; the ack-UI path itself passed in the gate
  test). Re-run: **26/26 E2E green, 0 flaky; all 15 PR checks green.**
- Remaining gate: none — B2 done; PR #4 still draft pending B3+.

### Honest limitations (carried)

- L1–L3 (revocation, per-process limits, admin-assisted reset) unchanged.
- Legacy `lib/api.ts` + top-level pages still use their own client/fetch;
  full migration rides the B3 `/workspace`→`/nexus` rewire.
- Onboarding "ack" is a per-user localStorage flag (UI progress only;
  identity always re-resolves server-side).

### Next: slice v0.8.5-B3 — Golden-path API completion (B4 + B8)

Canonical persistent signals/risks/scenarios/evidence/approval endpoints
(tables exist; endpoints don't) + ApprovalRecordDB writes in the advance
path. F3 from the register.

## Ship record

- **PR #4 MERGED to `main`** (2026-09-09, squash `50fcbfd`): slices B1
  (backend onboarding) + B2 (auth UI/guards) + B3 (golden-path APIs,
  closes B4/B8/F3). Pre-merge gate: 15/15 checks, E2E 26/26, backend
  suite 1917/1917.
- Post-merge `main` CI: 6/7 green; E2E failed at the *install* step
  (Playwright browser fetch, before any test) — proven environmental:
  `git diff 9e87677 50fcbfd` is EMPTY (merged tree == green PR HEAD
  tree). Re-validation rides the next PR's full CI (below).
- Working branch `arena/01a08657-cortex` re-synced to post-merge `main`
  (merge commit on the branch); B4+ continues from here.

## Slice v0.8.5-B3 — Golden-path API completion (Day 7–10)

**Branch:** `arena/01a08657-cortex` · **Blockers:** B4 (F3, §1 rows 6,7,9,14),
B8 (§1 row 11).

### Recon verdicts (shaped the design)

- `RiskRepository` / `ScenarioRepository` / `EvidenceRepository` exist but
  are called by NOTHING (not even tests) — pure promotion work.
- `RiskEngine.compute`, `ScenarioStudio.run`, `GetSignalTool` all read the
  in-memory `get_world_model()` singleton → canonical endpoints MUST NOT
  call them as-is (would violate the canonical "no singletons" contract).
  Promotion strategy: persist + serve registries; simulate runs the twin's
  PURE mutation/KPI core against an explicit caller-supplied snapshot
  (`run_with_snapshot` refactor; legacy `run()` delegates unchanged).
- `/graph/signals` is factorable + PG-backed → canonical `GET /nexus/signals`
  delegates to the same `SignalEngine` construction (detection-on-read,
  documented; no new table).
- §1 row 9 "BROKEN" is dead code: `fetchScenarios`/`simulateScenario` have
  zero importers (the live scenarios page uses `/graph/scenarios`). B3
  repoints + retypes the client to the honest canonical contract.
- `POST /simulation/result/{id}` is an acknowledged 501; not in B3 scope.
- Authz `check()` denies unknown tools → new tools registered explicitly.
- Cockpit `demoRisks` stays hardcoded in B3 (777-line flagship; rewire is a
  dedicated slice with e2e cover). Canonical risk responses mirror the
  `RiskItem` shape so the rewire is trivial.

### Planned endpoints (all gated + enveloped, `extra="forbid"` bodies)

Risks: `POST /nexus/risks` (upsert, `RISK_CHANGED`), `GET /nexus/risks`
(filters), `GET /nexus/risks/{id}`, `PATCH /nexus/risks/{id}` (status).
Signals: `GET /nexus/signals` (PG-backed detection-on-read).
Scenarios: `POST/GET /nexus/scenarios`, `GET /nexus/scenarios/{id}`,
`POST /nexus/scenarios/{id}/simulate` (`SCENARIO_COMPLETED`).
Evidence: `POST .../decisions/{id}/evidence/nodes|edges`
(`EVIDENCE_APPENDED`, new enum member), `GET .../evidence` (graph), plus
AUTO nodes on approval/execution/outcome transitions (same txn).
Approvals (B8): `advance()` writes `ApprovalRecordDB` for
APPROVED/REJECTED/AUTHORIZED (actor + role + decision hash);
`GET .../decisions/{id}/approvals` reads the trail.

### Explicit non-goals

RiskEngine/Studio singleton→PG-world projection (deep project, later
slice); cockpit/UI rewire (dedicated slice); GNN augmentation wiring
(`gnn_risk_score` accepted, not computed).

### Shipped

| Area | Change |
|---|---|
| `POST/GET/PATCH /nexus/risks` | Persisted risk registry (upsert on open entity risk, severity/status filters, triage); emits `RISK_CHANGED`. Response mirrors the cockpit `RiskItem` shape for the future rewire. |
| `GET /nexus/signals` | Canonical detection-on-read over PG-backed graph/operational state (same `SignalEngine` construction as `/graph/signals`); no signal table by design. |
| `POST/GET /nexus/scenarios` + `.../simulate` | Scenario records + twin simulation against caller-supplied snapshots (`run_with_snapshot`; legacy `run()` delegates unchanged); emits `SCENARIO_COMPLETED`. |
| Decision evidence DAG | Manual node/edge append + graph read (emits `EVIDENCE_APPENDED`, new enum member); lifecycle transitions self-append approval/execution/outcome nodes in-transaction. |
| B8 approval trail | `advance()` writes `ApprovalRecordDB` (actor + role + decision hash + policy checks) for APPROVED/REJECTED/AUTHORIZED; `GET .../approvals` reads it. `approver_role` NULL = programmatic advance without a principal (annotation-only; column already nullable, no migration). |
| Authz | 10 new tools registered (`nexus.risk.*`, `nexus.signal.read`, `nexus.scenario.*`, `nexus.evidence.*`, `nexus.approval.read`); reads viewer-open, recording analyst+, triage operator+. |
| Frontend | `lib/api/scenarios.ts` repointed to the canonical contract (was calling nonexistent `/scenarios`; zero importers so zero fallout). |
| Tests | `test_nexus_golden_path.py` (21 tests, real PG + real JWTs): full lifecycles, deterministic KPI assertions, outbox emission proofs, 403/404 isolation matrix, restart-persistence. Pinned `CANONICAL_NEXUS_PATHS` extended (deliberate surface change). |

### Verification

- Backend full suite **1917/1917** on real PG (incl. 21 new; the one
  routing-flip pin update is the designed-for surface-change workflow).
- `ruff check` + `ruff format` clean; `mypy` clean on touched services
  (one real catch: `uuid7()` returns `str`, not `UUID`).
- `tsc --noEmit` + `next build` + `next lint` clean.
- OpenAPI/TS regen is purely additive (+10 paths; `api.ts` reorder lines
  are diff-alignment artifacts, verified by inspection).
- Suite-ordering catch worth recording: B3 tests originally signed up
  over HTTP and exhausted the shared per-process signup bucket (429) when
  run after B1 in one process. Fixed by provisioning identities directly
  + minting real JWTs via `issue_token` (signup HTTP stays B1's covered
  territory; strict-path verification unchanged).

### CI verdict

**15/15 checks green, E2E 26/26, 0 flaky** (first run — no spec fixes
needed this time). B3 done; PR #4 still draft pending B4+.

### Next: slice v0.8.5-B4 — Outbox relay + realtime resync (B2)

Host the dormant `OutboxPublisher` sweeper (lifespan/CLI/k8s) + frontend
seq-gap detection/resync/replay. F2 from the register. (Rewire prerequisite
found in B3: `setNexusAuthToken` has zero callers — the rewire slice must
bridge AuthProvider → legacy `http.ts` client.)
