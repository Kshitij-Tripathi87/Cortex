# Nexus Launch Readiness Matrix — v0.8.5 (single authoritative launch document)

**Date:** 2026-09-10 · **Auditor:** Arena Agent (fresh live-main audit, not a carried-forward conclusion)
**Audited tree:** `origin/main = 50fcbfda77a7105c644bd53d59f3a83617075986`
("v0.8.5 (slice B1): launch onboarding backend — signup/login/me/logout/reset (#4)", 2026-09-09)
**Method:** live `git`/`gh` inspection of the actual remote, static analysis of
`main`, CI run history, and the repo's own launch records
(`docs/LAUNCH_GAP_REGISTER.md`, `docs/LAUNCH_BUILD_LOG.md`). No product code was
changed. Test suites were not re-executed in the sandbox (no Python 3.12 runtime);
test-count claims below cite the repo's recorded verdicts plus the green CI runs,
and the skip/xfail audit is mine.

**Classification key**

| Color | Meaning |
|---|---|
| 🟢 GREEN | Production/pilot-ready — on `main`, tested, gated |
| 🟡 YELLOW | Pilot-ready with hardening/verification still required |
| 🔴 RED | Launch blocker — missing, not landed on `main`, or not verified |
| ⚪ GRAY | Intentionally deferred (out of launch scope) |

> This document **supersedes `docs/LAUNCH_GAP_REGISTER.md`** as the working launch
> document. The gap register remains a historical record of the Day 1–2 audit
> against `faa6e6e`.

---

## 0. Headline verdict

> **`main` is a strong v0.8.5 Launch Candidate, but it is NOT the state the
> hand-off narrative describes.** Specifically: the *backend* golden path and
> onboarding are real and merged; the *frontend rewire* (F1) and the *realtime
> relay/resync* (F2) are **not** on `main` — the relay code exists only on an
> unmerged, PR-less branch. Billing/email/admin remain greenfield.

One-line answer to the pilot question
(*"can an external customer create an account, bring real supply-chain data in,
trust what Nexus derives, make a governed decision, and keep using it reliably
without an engineer manually repairing the environment?"*):

**Not yet, for two concrete reasons.** (1) The authenticated frontend still reads
from the in-memory `/workspace/*` demo singleton and the partial `/graph/*`
routers, not the canonical `/nexus/*` path — so an external customer's UI-driven
data would not hit the authoritative, tenant-isolated backend. (2) The outbox
relay that delivers committed events to Redis → SSE/WS is not running on `main`,
so realtime delivery stalls. Both blockers already have code in flight (B4) or a
clear, bounded plan (B3 rewire), but neither is landed on `main`.

---

## 1. Corrections to the previous premise (verified, not assumed)

The prior hand-off made three claims. This audit verifies each against live `main`:

| # | Premise | Verified reality |
|---|---|---|
| 1 | "The old *missing canonical endpoints* findings are stale." | ✅ **Correct.** Canonical `/nexus/risks`, `/nexus/signals`, `/nexus/scenarios`, decision-evidence DAG, and `/nexus/decisions/{id}/approvals` were shipped in slice **v0.8.5-B3** and are on `main` (blocker B4 in the register). |
| 2 | "B4 (realtime relay/resync) is **complete** per current baseline." | ⚠️ **Half-true.** The code exists — commit `1fb3d66` "v0.8.5-B4: launch reliability — durable outbox to live delivery" (8,417 insertions: `outbox_relay.py` worker, migration 016, `/nexus/realtime/events` replay, WS/SSE resync, frontend `RealtimeClient`). **But it is on branch `arena/01a0894d-cortex`, has no PR, and is not merged.** On `main` the `OutboxPublisher` sweeper is still unhosted and the frontend has no seq-gap/resync. |
| 3 | "B4 and **subsequent** launch work have moved the repo forward." | ❌ **Not true.** There is no "subsequent." After B4 (the unmerged branch) there are no B5–B10 commits anywhere on the remote. B5–B10 do not exist as code. |

### The B-numbering trap (root cause of the confusion)

The register and the slices reuse the letter `B` with **different meanings**, and
this is exactly where the two narratives diverged:

| Register **blocker** ID | Meaning | Status on `main` | Closed by slice |
|---|---|---|---|
| B1 | No signup/onboarding | ✅ done | v0.8.5-B1 (merged) |
| B2 | Outbox relay never runs + no frontend seq/resync | 🔴 **code written, unmerged** | v0.8.5-B4 (branch only) |
| B3 | UI talks to `/workspace/*`, not `/nexus/*` | 🔴 open | — |
| B4 | No canonical signals/risks/scenarios/evidence/approvals endpoints | ✅ done | v0.8.5-B3 (merged) |
| B5 | Scenario UI 404 | ✅ fixed | v0.8.5-B3 |
| B6 | Cockpit demo-seeded with silent fallbacks | 🔴 open | — |
| B7 | No login/logout/me pages | ✅ done | v0.8.5-B2 (merged) |
| B8 | Approval identity trail never written | ✅ done | v0.8.5-B3 |
| B9 | Prod stack never rehearsed; kafka still in prod compose | 🔴 open | — |
| B10 | Billing/admin/email greenfield | 🔴 open | — |

> So "B4" as a **slice** (realtime relay) is *written but not landed*, while "B4"
> as a **blocker** (canonical endpoints) is *done*. The prior narrative appears to
> have read "slice B4 = realtime" as "blocker B4 = realtime is done" — which is not
> what `main` contains.

---

## 2. The 20-item evidence inventory

### 2.1 Git & GitHub state (items 1–6)

| # | Item | Finding |
|---|---|---|
| 1 | Current `main` SHA | `50fcbfda77a7105c644bd53d59f3a83617075986` — "v0.8.5 (slice B1): launch onboarding backend (#4)", 2026-09-09 |
| 2 | All branches | `main` + `arena/01a07f13-cortex` (`ade065a`, pre-closeout snapshot), `arena/01a081f6-cortex` (`4a9db3e`, v0.8.3 design), `arena/01a085c4-cortex` (`731dfaa`, v0.8.3/v0.8.4, merged), `arena/01a08657-cortex` (`fc3c0bc`, B1–B3 PR branch), `arena/01a0894d-cortex` (`1fb3d66`, **B4 unmerged**), `arena/01a08ce7-cortex` (this session) |
| 3 | Open PRs | **1** — PR #5 "v0.8.5 (slices B4+): outbox relay + realtime resync [WIP]", **DRAFT**, head `arena/01a08657-cortex`. Its own body says "Do not merge yet." |
| 4 | Closed/merged PRs | **4** — #1 (v0.8.2 routing flip + CI-green), #2 (v0.8.3 kickoff design), #3 (v0.8.3 outbox + v0.8.4 ML inference/promotion), #4 (v0.8.5 B1+B2+B3) |
| 5 | GitHub issues | **0** — none filed |
| 6 | Latest commits | B1 squash (`50fcbfd`) → PR #3 merge `faa6e6e` (v0.8.4 ML + v0.8.3 outbox) → PR #2 merge `4a9db3e` (design) → PR #1 merge `57e5a51` (routing flip) |

### 2.2 Backend & frontend surface (items 7–8)

| # | Item | Finding |
|---|---|---|
| 7 | Backend endpoint inventory | **248 `@router.<verb>` handlers** across **28 v1 router files** (up from the register's 225 at `faa6e6e`). Canonical `/nexus/*` (decisions/risks/signals/scenarios/evidence/approvals/forecasts/models/inference/vanessa), `/world/*`, `/sources/*`, `/simulation/*`, `/auth/*` (7 routes), plus `/graph/*`, `/workspace/*`, `/execution/*`, `/agent_runtime/*`, `/gnn/*`, `/rl/*`, `/multi_agent/*`, and correctly-gated `/v07-legacy/*` |
| 8 | Frontend route inventory | **57 page files.** Auth pages exist (`/auth/login|signup|forgot-password|reset-password`, `/onboarding`). `/workspace/*` (≈17), top-level domain pages, `/nexus` + `/nexus/cockpit` (still demo-hardcoded), marketing/legal |

### 2.3 Auth, realtime, and launch slices (items 9–11)

| # | Item | Finding |
|---|---|---|
| 9 | Auth flow | **Real and merged.** `POST /auth/signup` (org+workspace+admin+trial atomically), `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password`, `POST /auth/reset/request|confirm`. `AuthProvider` state machine, `RequireAuth`/`RequireAnonymous` guards, validated `next`. Carried limits: no server-side token revocation (L1), per-process rate limits (L2), reset delivery is admin-assisted until email exists (L3), JWT in `localStorage` (XSS exposure accepted) |
| 10 | Realtime implementation | **On `main`:** WS endpoint (fail-closed JWT), `RealtimeBus` + Redis fan-out, and the PG outbox **write path** are real; the `OutboxPublisher` sweeper is **imported by nothing runnable** (no lifespan task, no worker, no k8s wiring). Frontend has reconnect but **no seq-gap/resync/replay**. **On unmerged B4 branch:** `backend/app/workers/outbox_relay.py`, migration `016_outbox_claim_lease.py`, `/nexus/realtime/events` replay, WS catch-up + `resync_needed`, `frontend/src/lib/realtime/client.ts` (sequence gate + resync), k8s `workers.yaml` relay deployment |
| 11 | B5–B10 status | **B5 done (B3)**. **B6 open** (`nexus/cockpit/page.tsx:124` still `demoRisks`). **B9 open** (no staging/prod rehearsal record; kafka still in `docker-compose.prod.yml:44`). **B10 open** (no billing/admin/email). No B5–B10 commits exist anywhere |

### 2.4 CI, deployment, migrations, tests (items 12–16)

| # | Item | Finding |
|---|---|---|
| 12 | CI gates | **10 workflows** — `build`, `ci`, `e2e`, `lint`, `release`, `security`, `stress`, `test`, `typecheck`, `workflo-cli`. **All green on `main`** (15/15 on the PR #4 push; full matrix success on the merge; scheduled `stress` success). `release.yml` is not publish-gated (no release ever cut) |
| 13 | Deployment manifests | `docker-compose.prod.yml` (postgres/redis/**kafka**/minio/2×api/workers/frontend), `docker-compose.yml`, `k8s/` (`base.yaml`, `infrastructure.yaml`, `workers.yaml`, `cronjob-pg-backup.yaml`, Helm chart). **Never rehearsed live in this program** |
| 14 | Migrations | **15 live** (`001_initial` → `015_auth_onboarding`) + **1 deferred** (`alembic/deferred/008_workflow_engine`). B4 adds `016_outbox_claim_lease.py` (unmerged) |
| 15 | Test counts | **Backend: 153 test files** (B3 recorded verdict: **1917/1917** on real PG). **Frontend: 6 test files** incl. `auth-e2e.spec.ts` (12 tests) + `critical-path-e2e` (B2 recorded **26/26 E2E**, 0 flaky). B4 branch self-reports 1904 backend + 14/14 vitest (unverified by CI — no PR) |
| 16 | Known failures/skips | **All skips are environmental**, not product failures: `PostgreSQL not available`, `backup.py not on sys.path`, "no signals/proposals to exercise gate", "Ingress schemas not importable". **Concerning:** `frontend/tests/realtime-e2e.spec.ts` is hard-disabled (`test.skip(true, 'Backend not available')`) on `main` — realtime delivery is not E2E-covered on `main` |

### 2.5 Hardcoded/demo, security, billing, readiness (items 17–20)

| # | Item | Finding |
|---|---|---|
| 17 | Hardcoded/demo paths | `nexus/cockpit/page.tsx:124` `demoRisks`; `nexus/page.tsx:596` `POST /workspace/demo/load`; `lib/api/nexusClient.ts:22` `loadDemo`; `WorkspaceContext.tsx:482-483` auto-loads controlled demo on mount and `:243` swallows fetch errors `.catch(() => {})`; `workspace.py:59` still mounts `/workspace/demo/load`; openapi default `ws_default` |
| 18 | Security exceptions | Authz audit (D3): **150 routes → 148 gated, 1 legitimately public (`/workflo/health`), 0 debt**. Carried launch limits L1 (no token revocation), L2 (per-process rate limits), L3 (admin-assisted reset); JWT in `localStorage`; **Day-11 pen-test not yet done** |
| 19 | Billing/email | **Greenfield.** Only `plan="trial"` + `trial_ends_at` seed (migration 015, "seed the Day-15 billing entitlement model"). No Stripe/billing/entitlement code, no SMTP/provider email, no transactional email. Password-reset delivery is admin-CLI-assisted |
| 20 | Production deployment readiness | Manifests + CI are real and green, but **no staging environment observed, no live rehearsal record, no DR restore test record, kafka still in prod compose (P2), and the realtime relay is not hosted on `main`** |

---

## 3. Launch Readiness Matrix

### 3.1 Golden path (product correctness)

| Capability | Status | Evidence / note |
|---|---|---|
| Signup / onboarding | 🟢 GREEN | B1 merged; atomic org+workspace+admin+trial; 16 PG tests + 12 E2E |
| Login / session / me / logout / reset | 🟢 GREEN | B1+B2 merged. GA-hardening carried: L1 revocation, L3 email reset |
| Tenant/workspace isolation (server) | 🟢 GREEN | `require_workspace_access` on canonical paths; real-JWT cross-workspace 403 test |
| **Frontend → canonical `/nexus/*` rewire (F1/B3)** | 🔴 **RED** | UI still calls `/workspace/*` and `/graph/*`; demo auto-load + silent catch remain |
| CSV ingestion → World State | 🟡 YELLOW | `/sources/*` pipeline real; end-to-end projection into World State not yet E2E-proven |
| World State + graph | 🟢 GREEN | PG-backed `/world/*` (state/event/history/diff/replay/rollback/verify) |
| Signals | 🟢 GREEN | Canonical `GET /nexus/signals` merged (detection-on-read over PG) |
| Risks | 🟢 GREEN | Canonical `/nexus/risks` upsert/list/triage merged (B3) |
| Forecasts / inference / truth loop | 🟢 GREEN | Persistent, outbox-emitting; v0.8.4 ML promotion gate merged |
| Scenarios / simulation | 🟢 GREEN | Canonical `/nexus/scenarios` + `simulate` merged; B5 404 fixed |
| Decisions (governed lifecycle) | 🟢 GREEN | PG-backed phase machine + capability checks + outbox |
| Approvals (B8) | 🟢 GREEN | `advance()` now writes `ApprovalRecordDB` (actor+role+hash); read endpoint |
| Execution | 🟡 YELLOW | `/nexus/decisions/{id}/execute` real; adapters/policy reality not yet fully audited |
| Outcomes | 🟢 GREEN | Persistent `OutcomeRecordDB` |
| Evidence + lineage | 🟢 GREEN | Canonical evidence DAG endpoints merged (manual + lifecycle auto-nodes) |
| Vanessa (assistant) | 🟡 YELLOW | Persistent, tools-only; LLM render not wired (shippable as-is per plan) |
| Audit trail | 🟡 YELLOW | `DecisionTransitionDB` + `/world/history` + audit router; full-mutation coverage not verified |

### 3.2 SaaS readiness

| Capability | Status | Evidence / note |
|---|---|---|
| Realtime — outbox write path | 🟢 GREEN | In-transaction `EventRecordDB` in all four Authoritative* services |
| **Realtime — relay/resync (B2)** | 🔴 **RED** | Sweeper unhosted on `main`; frontend has no seq/resync. Code exists on unmerged B4 branch only |
| Observability | 🟢 GREEN | Prometheus + OTel + structured logging + `/healthz`/`/readyz` + Grafana manifests |
| Deployment topology | 🟡 YELLOW | Manifests real; never rehearsed live; kafka still in prod compose |
| Backups / DR | 🟡 YELLOW | Backup CronJob + restore-verify code exist; **no restore test on record** |
| **Billing / entitlements (B10)** | 🔴 **RED** | Greenfield (only `plan=trial` seed) |
| **Admin / support tooling (B10)** | 🔴 **RED** | Only `scripts/admin_users.py` CLI; no admin surface/status page |
| **Email delivery (B10)** | 🔴 **RED** | No email provider; reset delivery admin-assisted |
| Rate limiting / security headers | 🟢 GREEN | Middleware wired; Redis-backed limiter is a hardening item |
| Secrets management | 🟡 YELLOW | Pydantic + `.env.example` + k8s secrets present; unverified live |
| Security hardening (pen-test) | 🟡 YELLOW | Day-11 pass not yet executed |

### 3.3 Cross-cutting

| Capability | Status | Evidence / note |
|---|---|---|
| CI gates | 🟢 GREEN | 10 workflows, all green on `main` |
| Tests | 🟢 GREEN | 1917 backend + 26 E2E (B3); all skips environmental; realtime E2E hard-skipped |
| Migrations | 🟢 GREEN | `alembic upgrade head` clean through 015 (verified in B1) |
| **Cockpit demo-rewire (B6)** | 🔴 **RED** | `demoRisks` hardcoded in flagship cockpit; not on canonical APIs |
| GNN / RL / twin / multi-agent | ⚪ GRAY | P2 — mounted, not linked into the launch journey |
| workflo / agent-runtime / `/v07-legacy` | ⚪ GRAY | P2 — correctly gated/deferred |
| Kafka | ⚪ GRAY | P2 — removable; still present in prod compose (cleanup pending) |

### 3.4 Rollup

| Color | Count | Items |
|---|---|---|
| 🟢 GREEN | 17 | backend golden path (11), onboarding/auth (2), outbox write path, observability, rate-limit/headers, CI, tests, migrations |
| 🟡 YELLOW | 9 | ingestion E2E, execution, Vanessa, audit, deployment, DR, secrets, pen-test, + GA-hardening notes on auth |
| 🔴 RED | 6 | **frontend→nexus rewire (F1/B3), realtime relay (F2/B2), billing, admin, email, cockpit rewire (B6)** |
| ⚪ GRAY | 4 | GNN/RL/twin/multi-agent, workflo/agent-runtime/v07-legacy, kafka |

---

## 4. What is actually left (no architectural changes required)

The repository has **not** reached the "stop building, only harden" point the
narrative assumes — but it is close. The remaining work is bounded and already
scoped by the register:

1. **Land B4 (realtime relay/resync).** The code exists at `1fb3d66` on
   `arena/01a0894d-cortex`. It needs a PR off `main` (currently PR #5's head is
   stale at `fc3c0bc`, pre-B4), a full CI run (its self-reported 1904/0 and
   14/14 vitest are **unverified by any PR check**), and re-enabling
   `realtime-e2e.spec.ts`.
2. **Finish B3/B6 (frontend → canonical `/nexus/*`).** Replace the
   `/workspace/*` + `/graph/*` calls in the authenticated UI with canonical
   clients, stop the demo auto-load, remove silent catches, and rewire the
   cockpit off `demoRisks`.
3. **B9 (operations).** Remove kafka from prod compose (P2), stand up staging,
   and run one live deploy + DR restore rehearsal with RPO/RTO recorded.
4. **B10 (SaaS).** Billing/entitlements, admin/status surface, and transactional
   email — the three genuinely-greenfield slices.
5. **Day-11 security pass** and the GA-hardening items already documented
   (token revocation, Redis rate limiter, httpOnly cookie decision).

No new architecture is needed. The order is: **merge-and-verify B4 → rewire the
frontend (B3/B6) → operations rehearsal (B9) → billing/email/admin (B10) → RC.**
