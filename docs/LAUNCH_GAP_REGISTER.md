# Nexus Launch Gap Register — Days 1–2 Production Audit

**Date:** 2026-09-09 · **Auditor:** Arena Agent (Day 1–2 slice of the 21-day launch plan)
**Audited tree:** `origin/main = faa6e6e` ("Merge pull request #3", v0.8.2 closeout)
**Working branch:** `arena/01a08657-cortex` (reset to `faa6e6e`; see §0)
**Method:** static analysis of all 225 backend endpoints, 50 frontend routes, 159 backend
test files, CI status, and infra manifests. No code was executed (sandbox has no
Python 3.12 deps installed); every verdict below cites file + line evidence.
**CI state:** green on `main` (Test, E2E, Build, Lint, Security, Typecheck, CI all
`success` on the PR #3 push).

**Classification key:** `REAL` · `PARTIAL` · `STUB` · `DEMO` · `HARDCODED` · `BROKEN` ·
`UNTESTED` · `MISSING`

---

## 0. Corrected shipping status (supersedes the pre-audit handoff note)

The handoff note claiming *"v0.8.3 is recovered but not present on the remote;
`ca8bc3a` must be supplied by another runtime"* is **stale and superseded**.
Verified live state:

| Item | Handoff claim | Verified live state |
|---|---|---|
| `main` | `4a9db3e` | **`faa6e6e`** (PR #3 squash-merge, 2026-09-09, CI green) |
| `arena/01a081f6-cortex` | `4a9db3e` | `4a9db3e` ✔ (design-only branch, unchanged) |
| `ca8bc3a` / `6090d80` | "required, on another runtime" | **Do not exist on the remote in any ref.** Nothing to recover. |
| v0.8.3 outbox | "design only" | **Write path IMPLEMENTED on `main`** (`outbox_publisher.py` + in-transaction `allocate_outbox_seq` wired into all four Authoritative* services + `test_nexus_v083_outbox_acceptance.py`). **Relay/sweeper NOT started anywhere** — see blocker B2. |
| v0.8.4 ML promotion | design | Design doc + persistent `/nexus/models/*` endpoints implemented (register/list/health/drift/evaluate/promote/rollback). |
| Session branch base | `ade065a` (broken `router.py`, 24 undefined names) | **Reset to `faa6e6e`**. `ade065a` was a pre-closeout snapshot on an unrelated history; the only files dropped by the reset are 4 scratch scripts (`backend/debug_test.py`, `fix.py`, `fix_docstring.py`, `fix_test.py`). |

**No action needed** on `ca8bc3a`: there is no missing commit. The v0.8.3 relay gap
(B2) is ordinary new work, not a recovery operation.

---

## 1. Golden-path verdict (the only table that matters for launch)

Golden path: Workspace → Dataset → World State → Signal → Risk → Forecast →
Scenario → Decision → Approval → Execution → Outcome → Evidence, with realtime
updates and an immutable audit trail.

| # | Capability | Verdict | Evidence |
|---|---|---|---|
| 1 | **Signup / onboarding** | `MISSING` | Only `POST /auth/login` exists (`backend/app/api/v1/auth.py:35`). No signup, no org/workspace provisioning endpoint, no login page in frontend (only `lib/api/auth.ts` client). |
| 2 | **Login / session** | `PARTIAL` | `POST /auth/login` is REAL (DB user lookup, bcrypt-equivalent verify, HS256 JWT with `workspace_id` claim). But: no `GET /auth/me`, no logout/invalidation, no password reset, no session expiry UX. Frontend `auth.ts` calls `/auth/logout` + `/auth/me` → **404** (`BROKEN` contract). |
| 3 | **Tenant/workspace isolation** | `PARTIAL` | Canonical `/nexus/*` handlers call `require_workspace_access(workspace_id, auth)` (REAL server-side scoping). BUT the frontend's Nexus clients talk to `/workspace/*` (Program S singleton, **zero auth**, hardcoded `ws_default`/`org_default`, `workspace.py:30`). Isolation holds only on paths the UI doesn't use. |
| 4 | **CSV ingestion** | `PARTIAL` | `POST /sources/upload` → DB-backed batch pipeline with profile/claims/conflicts/compile endpoints (`sources.py:145-344`, REAL). Upload page exists with fetch. Gap: no evidence it projects into World State end-to-end (compile target unclear); needs E2E proof on Day 5–6. |
| 5 | **World State** | `REAL` | `/world/*` router is PG-backed via `WorldStateService(StateRepository(db))` (`world.py:363-380`): state/event/history/diff/replay/rollback/validate/verify. 12 alembic migrations incl. `008_world_state.py`. |
| 6 | **Signals** | `PARTIAL` | `GET /graph/signals` computes signals (DB-backed router, 27 session refs) but detection-on-read, not persisted signal rows; canonical `/nexus/signals` does NOT exist (only `/v07-legacy`). Frontend signals pages render from WorkspaceContext (demo-seeded). |
| 7 | **Risk** | `PARTIAL` | `RiskRecordDB` table exists; canonical `/nexus/risks/*` does NOT exist (only legacy). Cockpit risk list is `HARDCODED` demo array (`nexus/cockpit/page.tsx:124-205`). |
| 8 | **Forecast / inference** | `REAL` | `POST /nexus/forecasts`, `/observations`, `/calibration`, `/bias`, `/inference/demand`, `/inference/risk` — all persistent, outbox-emitting. Truth loop persisted (`ForecastRecordDB`, `ObservationRecordDB`). |
| 9 | **Scenarios** | `BROKEN` | `ScenarioRecordDB` table exists; `/simulation/*` router is DB-backed (REAL engine). BUT frontend `fetchScenarios()` → `GET /scenarios` and `simulateScenario()` → `POST /scenarios/{id}/simulate` — **neither route exists** (backend has only `POST /graph/scenarios` + `/simulation/*`). Scenario UI 404s. |
| 10 | **Decisions (governed lifecycle)** | `REAL` | `POST/GET /nexus/decisions`, `.../advance`, `.../execute`, `.../outcome`, `.../memory` — persistent, phase machine + capability checks (`nexus.decision.*`), outbox-emitting. `DecisionRecordDB` + `DecisionTransitionDB`. |
| 11 | **Approvals** | `PARTIAL` | `advance` enforces role-gated phases (`APPROVED/REJECTED/AUTHORIZED` via `nexus.decision.approve`). BUT `ApprovalRecordDB` rows are **never written** by any service (0 references in `p0_migration/*` + `repositories.py`). No approver identity trail. |
| 12 | **Execution** | `PARTIAL` | `POST /nexus/decisions/{id}/execute` + `ExecutionRecordDB` REAL; `execution.py` router (7 endpoints) covers supervised execution. Adapters/policy-engine reality not yet audited line-by-line → verify on Day 9–10. |
| 13 | **Outcome** | `REAL` | `POST .../outcome` persistent (`OutcomeRecordDB`), feeds memory/analogous. |
| 14 | **Evidence** | `PARTIAL` | `EvidenceNodeDB`/`EvidenceEdgeDB` tables exist, but **zero API endpoints** read/write them. Explanations live only in legacy (`POST /explanations/risk` under `/v07-legacy`). No decision-scoped evidence API on the canonical path. |
| 15 | **Realtime (WS/SSE)** | `PARTIAL` | WS endpoint REAL with fail-closed JWT handshake (`realtime.py`); `RealtimeBus` + Redis fanout + PG outbox write path REAL. **Gaps:** (a) `OutboxPublisher` sweeper is never started (no lifespan task, no CLI worker, no k8s wiring) → committed events sit unpublished; (b) frontend `NexusRealtimeClient` has reconnect but **no seq-gap detection / resync / replay**; (c) `/nexus/realtime/events` is legacy-only (in-memory log). |
| 16 | **Vanessa (assistant)** | `PARTIAL` | `POST /nexus/vanessa/ask` persistent (sessions/messages tables), grounded tools-only pipeline — LLM is render-only and **not wired** (`orchestrator.py:253` "If an LLM is wired in, this is where it would be invoked"). Matches the launch plan's "constrained Vanessa" — shippable as-is. |
| 17 | **Audit trail** | `PARTIAL` | `audit.py` router (1 endpoint) + `DecisionTransitionDB` + `/world/history`. Immutable operational audit across ALL mutations — not verified; needs Day 11 check. |
| 18 | **Observability** | `REAL` | Prometheus metrics + middleware, OTel tracing, structured logging, `/healthz` + dependency-composing `/readyz`, Grafana/Prometheus manifests. Alert rules reference needs Day 14 verification. |
| 19 | **Deployment topology** | `PARTIAL` | `docker-compose.prod.yml` (postgres/redis/kafka/minio/2×api/workers/frontend) + k8s base/helm/workers + backup CronJob manifests exist. **Never verified live** in this program; kafka is P2-removable per plan. No staging env observed. |
| 20 | **Backups / DR** | `PARTIAL` | PG backup CronJob + `scripts/backup.py` with restore-verify + retention policy exist as code. **No record of an actual restore test.** RPO/RTO undocumented. |
| 21 | **Billing / entitlements** | `MISSING` | Zero billing/subscription/entitlement code (only pub/sub "subscription" matches). Greenfield Day-15 work. |
| 22 | **Admin / support tooling** | `MISSING` | No admin surface, no `/status` page. Greenfield Day-16 work. |
| 23 | **Rate limiting / security headers** | `REAL` | `RateLimitHeadersMiddleware`, `SecurityHeadersMiddleware`, `CircuitBreakerMiddleware` wired in `main.py`. Day-11 pen-test still required. |
| 24 | **Secrets management** | `PARTIAL` | Pydantic settings + `.env.example`; prod secret injection (k8s secrets/ESO) present in manifests but unverified live. |

**Net: 5 REAL · 13 PARTIAL · 1 BROKEN · 1 HARDCODED-in-UI · 3 MISSING (signup, billing, admin).**

---

## 2. The three structural findings behind the table

### F1. The frontend talks to the wrong backend (biggest single gap)
The v0.8.2 closeout flipped the **backend** to canonical persistent `/nexus/*`,
but the **frontend** was never re-wired. All Nexus domain clients
(`frontend/src/lib/api/*.ts`) call `/workspace/*` — the Program S **in-memory
singleton**: no auth, hardcoded `ws_default`/`org_default`, volatile state,
`/demo/load` as a first-class endpoint. Consequences:
- Tenant isolation (row 3) is defeated on every UI-driven path.
- Restart wipes everything the UI created (fails Gate 3).
- `WorkspaceContext` **auto-loads the controlled demo dataset on mount**
  (`WorkspaceContext.tsx:482-483`) and swallows fetch errors (`.catch(() => {})`).
- `nexus/cockpit/page.tsx` (the flagship cockpit, 777 lines) renders
  **hardcoded `demoRisks`** with the comment *"the production version will pull
  from /api/v1/nexus/risks etc."* (`:123-124`), plus `VSESS-demo-session`.

### F2. v0.8.3 is write-path-only; the relay is dormant
`allocate_outbox_seq` + `EventRecordDB` inserts run **in-transaction** in all four
Authoritative* services (decisions/truth/inference/models) — genuinely good.
But `OutboxPublisher` (the SKIP LOCKED sweeper that moves rows to Redis/WS) is
**imported by nothing runnable**: not in `main.py` lifespan, not a CLI worker,
not in k8s/compose. Committed events accumulate unpublished. The v0.8.3 A1–A15
acceptance criteria therefore cannot pass until the sweeper is hosted + the
frontend speaks seq/reconnect/resync.

### F3. Half the golden path has tables but no canonical endpoints
`RiskRecordDB`, `ScenarioRecordDB`, `EvidenceNodeDB/EdgeDB`, `ApprovalRecordDB`
exist with migrations, yet `/nexus/*` exposes **no** signals/risks/scenarios/
evidence/approval endpoints — those live only under `/v07-legacy/*`
(in-memory, flag-gated, correctly excluded from prod). The persistent services
for these entities were never promoted. Frontend scenario calls 404 (§1 row 9).

---

## 3. Endpoint inventory (225 total: 101 GET · 120 POST · 2 PATCH · 1 PUT · 1 DELETE)

| Router | Endpoints | Golden-path relevance | Verdict |
|---|---|---|---|
| `nexus_persistent` (`/nexus/*`) | 24 | decisions/memory/forecasts/models/inference/vanessa | `REAL` (canonical) |
| `world` (`/world/*`) | 10 | world state/event/history/replay | `REAL` |
| `sources` (`/sources/*`) | 7 | CSV upload pipeline | `REAL` (needs E2E proof) |
| `simulation` (`/simulation/*`) | 4 | scenario engine | `REAL` engine, `BROKEN` UI contract |
| `auth` (`/auth/*`) | 1 | login only | `PARTIAL` |
| `graph` (`/graph/*`, 28) · `twin` (13) · `knowledge` (8) | 49 | signals detect, twin compare, knowledge | `PARTIAL` (mixed; audit Day 9–10) |
| `execution` (7) · `governance` (1) · `audit` (1) | 9 | execution/governance/audit | `PARTIAL` |
| `realtime` (WS) · `agent_runtime` (7) · `intelligence_gateway` (5) | 13+WS | streaming/gateway | `PARTIAL` |
| `workspace` (`/workspace/*`, 15) | 15 | **UI's current backend** | `DEMO` singleton — rewire target, then retire or gate |
| `nexus` v1 (28) + `nexus_v07` (22) | 50 | legacy in-memory | Correctly gated behind `CORTEX_NEXUS_V07_LEGACY_ROUTES` → `/v07-legacy/*`. **Do not use.** |
| `gnn` (6) · `rl` (3) · `multi_agent` (2) · `agents_router` (10) · `spine` (1) · `readiness` (2) · `ingestion` (2) · `briefs` (1) · `validation` (8) · `workflo` | ~45 | P1/P2 surface | Out of launch scope; leave mounted but unlinked from UI |

---

## 4. Frontend inventory (50 routes)

| Route group | Routes | Verdict |
|---|---|---|
| Marketing/legal (`/`, `/products`, `/platform`, `/company`, `/contact`, `/enterprise`, `/legal/*`, `/security`) | ~13 | `REAL` static content — fine, keep |
| `/demo` (lead form) | 1 | `REAL` form (verify submit target Day 3) |
| `/nexus`, `/nexus/cockpit` | 2 | `HARDCODED` demo data — **rebuild on canonical APIs (Day 7–8)** |
| `/workspace/*` (cockpit, signals, decisions, scenarios, evidence, world, risk, analysis, graph, agents/*) | ~17 | `PARTIAL` shell + context, `DEMO`-driven data layer — **rewire to `/nexus/*` (Day 7–8)** |
| Top-level `/decisions`, `/signals`, `/scenarios`, `/evidence`, `/graph`, `/upload`, `/recommendations`, `/readiness`, `/propagation`, `/conflicts`, `/audit`, `/agents`, `/mvp`, `/intelligence` | ~16 | Mixed `PARTIAL`: several fetch real APIs (`decisions`, `evidence`, `upload`, `readiness`, `conflicts`, `audit`); `scenarios` 404s (`BROKEN`); duplicate IA vs `/workspace/*` — **consolidate nav per plan §20** |
| Login/signup/onboarding | 0 | `MISSING` — **build Day 3–4** |

Cross-cutting UI gaps: two API clients with two env vars (`NEXT_PUBLIC_API_URL`
vs `NEXT_PUBLIC_API_BASE_URL`); auth token in `localStorage` (XSS exposure —
move to httpOnly cookie or accept + document on Day 11); no global error
boundary/auth-guard; silent `.catch(() => {})` in `WorkspaceContext`.

---

## 5. Launch blockers, ordered (P0 must-fix before RC)

| ID | Blocker | Maps to | Proposed slice |
|---|---|---|---|
| **B1** | No signup/org/workspace provisioning (API + UI). Nobody can onboard. | §1 rows 1–2 | v0.8.5-B (Day 3–4) |
| **B2** | Outbox relay never runs; frontend has no seq/resync. Realtime fabric is half-shipped. | §1 row 15, F2 | v0.8.5-B/C (Day 6, 11) |
| **B3** | UI talks to `/workspace/*` demo singleton, not canonical `/nexus/*`. | F1, §1 rows 3,6,7 | v0.8.5-B (Day 7–8) |
| **B4** | No canonical signals/risks/scenarios/evidence/approval endpoints (tables exist). | F3, §1 rows 6,7,9,11,14 | v0.8.5-B (Day 7–10) |
| **B5** | Scenario UI contract 404s (`GET /scenarios`). | §1 row 9 | v0.8.5-B (Day 9–10) |
| **B6** | Cockpit + WorkspaceContext demo-seeded with silent fallbacks. | F1 | v0.8.5-B (Day 5–8) |
| **B7** | No login/logout/me pages + stale auth client contract. | §1 row 2 | v0.8.5-B (Day 3–4) |
| **B8** | Approval identity trail never recorded. | §1 row 11 | v0.8.5-B (Day 9–10) |
| **B9** | Prod stack never verified live; no staging env; kafka in prod compose (P2). | §1 rows 19–20 | v0.8.5-C (Day 13–14) |
| **B10** | Billing/entitlements + admin/status = greenfield. | §1 rows 21–22 | v0.8.5-D (Day 15–16) |

---

## 6. Proposed scope freeze (for sign-off)

**Ship (P0):** B1–B10 + golden-path E2E (§1 rows 1–18 at `REAL`) + security pass
(Day 11–12) + rehearsal/chaos/RC (Day 17–20).
**Ship iff stable (P1):** CSV bulk-import polish, saved investigations, email
notifications, richer Vanessa rendering (LLM wire-up), extra dashboard views.
**Explicitly deferred (P2):** kafka, multi-region, service mesh, autonomous
execution/retraining, SSO/SAML (unless a launch customer requires it), ontology
expansion, mobile, RBAC hierarchy, design-system rewrite, GNN/RL/multi-agent
surfaces, workflo/agent-runtime expansion. The `/v07-legacy/*` and
`/workspace/*` demo paths stay out of the customer journey (retire or hard-gate
before RC).

## 7. Recommended milestone rename (per plan §25)

`v0.8.5 — Nexus Launch Candidate`, sliced A–F. This register is slice A
(Productization audit) output. Next slice: **v0.8.5-B Golden Operational Path,
starting Day 3–4 onboarding (B1+B7)** — needs two product decisions (§8).

## 8. Decisions needed before Day-3 build starts

1. **Onboarding model:** open signup (anyone creates org+workspace) vs
   invite-only (admin seeds users, login-only UI)? Recommends open signup with
   trial entitlement stub, since login already exists and billing (Day 15)
   assumes self-serve trials.
2. **Workspace scoping rule:** one workspace per org at launch (simple) vs
   multi-workspace? Recommends one-workspace-per-org for launch; the JWT
   already carries `workspace_id`, so the data model supports later expansion.
