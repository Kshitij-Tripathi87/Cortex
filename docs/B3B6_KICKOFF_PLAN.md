# v0.8.5-B3/B6 Kickoff Plan — Frontend Rewire to the Canonical Nexus Backend

**Date:** 2026-09-11 · **Author:** Arena Agent
**Baseline:** `main @ ca39e6a` (post-B4 merge: "v0.8.5-B4: durable outbox → live
delivery (#6)"). This is the authoritative launch baseline for this slice.
**Closes:** gap-register blockers **B3** (UI talks to `/workspace/*` demo
singleton) and **B6** (cockpit + `WorkspaceContext` demo-seeded with silent
fallbacks), i.e. structural finding **F1** ("the frontend talks to the wrong backend").

---

## 1. Why this slice is the critical path

B4 is now merged: the backend golden path (decisions/risks/signals/scenarios/
evidence/approvals/forecasts/inference) is canonical, tenant-isolated, and its
realtime delivery is live. But **the authenticated UI still does not use it.**

> The pilot question fails on the frontend, not the backend: a customer who
> creates an account and clicks into the product is still looking at
> demo-seeded data served from an in-memory singleton that the canonical backend
> doesn't know about. Realtime now delivers real `decision_created` events — to a
> cockpit that is rendering `demoRisks` and never asking `/nexus/risks`.

Per the standing dependency rule: **B10 stays blocked until this slice is green.**

---

## 2. The problem, precisely (verified on `main@ca39e6a`)

### 2.1 Three parallel HTTP layers — none unified on the canonical client

| Layer | File | Auth | Trace (X-Request-ID) | Used by |
|---|---|---|---|---|
| ✅ B2 canonical client | `lib/auth/client.ts` | `getToken()` → Bearer | **sends** `X-Request-ID` | `AuthProvider`, `/app` page (`GET /nexus/decisions`) |
| ⚠️ Legacy domain layer | `lib/api/http.ts` | `setNexusAuthToken()` — **zero callers**, so **no Authorization ever sent** | **none** | `lib/api/{data,decisions,evidence,graph,nexusClient,reasoning,scenarios,signals,world}.ts` |
| ⚠️ Legacy top-level layer | `lib/api.ts` | reads `cortex:access_token` (same key B2 writes → works) | reads response `X-Request-ID` | 8 top-level pages + `WorkspaceContext` + `ErrorState` + `features/morning-brief` |

### 2.2 Three competing workspace-id / token sources

| Source | Value | Problem |
|---|---|---|
| `lib/useWorkspace.ts` | `cortex:workspace_id`, **defaults to hardcoded `"workspace-default"`** and persists it | wrong default; not tied to `/auth/me` |
| `lib/api.ts` `getAuthToken()` | `cortex:access_token` | correct token, but legacy layer |
| `useAuth().workspace.id` | from `GET /auth/me` | **the only correct source** — should be the single one |

### 2.3 The demo is still the data source

- `frontend/src/app/nexus/cockpit/page.tsx:124` — `demoRisks: RiskItem[]`, comment
  *"the production version will pull from /api/v1/nexus/risks etc."*; `:204` `setRisks(demoRisks)`;
  `:230` `setVanessaSessionId("VSESS-demo-session")`; `:628` `demoSkus`.
- `frontend/src/lib/state/WorkspaceContext.tsx:418-444` `loadControlledDemo()` →
  `loadDemoDataset()`; `:521-522` auto-loads demo **on mount** when `!isDemoLoaded`;
  `:285`/`:288` `fetchActiveSignals().then(setSignals).catch(() => {})` — silent swallow.
- `frontend/src/lib/api/nexusClient.ts:22` `POST /workspace/demo/load`.

### 2.4 What the UI should call instead (canonical `/nexus/*`, all landed)

`GET/POST /nexus/decisions`, `.../advance|execute|outcome|memory|approvals|evidence`,
`GET/POST/PATCH /nexus/risks`, `GET /nexus/signals`, `GET/POST /nexus/scenarios` +
`.../simulate`, `POST /nexus/forecasts|observations|inference/demand|inference/risk`,
`/nexus/models/*`, `POST /nexus/vanessa/ask`, `/nexus/memory/*`,
`/nexus/realtime/events|stream|health`. (34 routes, all `require_workspace_access` +
`_authz_check`.) Backend-adjacent non-`/nexus` canonical surfaces: `/world/*`,
`/sources/*`, `/simulation/*`, `/auth/*`.

---

## 3. Scope

### In scope

1. **B3a — one client.** Route all domain data access through a single client that
   does Bearer-from-`getToken()`, sends `X-Request-ID`, normalizes errors, and
   401/403 disambiguation (403 ≠ logout). Retire `lib/api/http.ts` and `lib/api.ts`.
2. **B3b — repoint the domain clients** (`lib/api/*.ts`) to canonical `/nexus/*`
   (and `/world/*`, `/sources/*`) endpoints, threading `workspace_id` from
   `useAuth().workspace.id` (drop `useWorkspace()`'s `"workspace-default"`).
3. **B6a — remove demo state.** Cockpit pulls `GET /nexus/risks`; delete
   `demoRisks`/`demoSkus`/`VSESS-demo-session`; remove `WorkspaceContext` demo
   auto-load and every silent `.catch(() => {})` (surface errors instead).
4. **B6b — retire demo endpoints.** Delete `POST /workspace/demo/load` usage;
   gate off the `/workspace/*` demo surfaces from the authenticated journey.
5. **Trace.** Send `X-Request-ID` on every canonical call (via the unified client)
   and surface the response envelope's `request_id`/`correlation_id` on the
   cockpit + decision views so a screen element correlates to backend logs
   (backend middleware already echoes `X-Request-ID` and sets
   `request.state.request_id`, `main.py:128-136`).

### Out of scope (deliberate, carry as follow-ups)

- **B9** (kafka removal / staging / DR) and **B10** (billing / admin / email).
- IA/navigation consolidation of the duplicated `/workspace/*` vs top-level pages
  (gap register §4 "consolidate nav per plan §20") — `href` links are touched only
  where they point at data pages that move; full nav rework is a follow-up slice.
- Rebuilding demo-only *features* whose backend has no canonical equivalent (see §4
  "defer" rows) — these are documented, not silently dropped.

---

## 4. `/workspace/*` → canonical mapping (and what has no target)

Current demo-path calls are from `lib/api/*.ts` (verified on `main@ca39e6a`):

| Demo path (client) | Canonical target | Verdict |
|---|---|---|
| `/workspace/signals` (signals.ts) | `GET /nexus/signals` | ✅ rewire |
| `/workspace/decisions/evidence` (decisions.ts, evidence.ts) | `GET /nexus/decisions/{id}/evidence` | ✅ rewire |
| `/workspace/state` (data.ts, world.ts, nexusClient.ts) | `GET /world/state` (+ `/world/history`) | ✅ rewire (shape audit required) |
| `/workspace/upload`, `/workspace/ingest-raw` (data.ts) | `POST /sources/upload` | ✅ rewire |
| `/workspace/query/ask` (reasoning.ts, nexusClient.ts) | `POST /nexus/vanessa/ask` | ✅ rewire (constrained, tools-only) |
| `/workspace/append-stream`, `/workspace/stream` | `GET /nexus/realtime/stream` | ✅ rewire (B4 landed) |
| `/workspace/graph/subgraph`, `/critical-nodes`, `/delta` (graph.ts) | `GET /graph/nodes`+`/edges` (PG-backed, partial) | 🟡 map or defer |
| `/workspace/decisions/validity` (decisions.ts) | — none | 🔴 defer (demo concept) |
| `/workspace/deliberate` (nexusClient.ts, scenarios.ts) | — none | 🔴 defer |
| `/workspace/query/readiness` (reasoning.ts, nexusClient.ts) | — none (top-level `/readiness` exists) | 🔴 defer |
| `/workspace/demo/load` (nexusClient.ts) | — none | 🗑️ delete |

Top-level pages (via `lib/api.ts`) also sit on the non-canonical `/graph/*` router
(PG-backed, partial): decisions → `/graph/decisions`, scenarios → `/graph/scenarios`,
signals → `/graph/signals`. These move to `/nexus/decisions`, `/nexus/scenarios`,
`/nexus/signals` in B6b.

---

## 5. Architecture decisions (recommended; sign-off not blocking the plan)

1. **One client.** Extend the B2 `apiClient` (`lib/auth/client.ts`) into the shared
   domain client (thin `lib/api/client.ts` re-export or move), and delete
   `lib/api/http.ts` + `lib/api.ts`. One base-URL knob, one auth path, one error
   type, one 401 hook. `setNexusAuthToken` (zero callers) goes away entirely.
2. **One identity source.** `workspace_id` flows from `useAuth().workspace.id`
   (resolved server-side via `/auth/me`). `useWorkspace()`'s hardcoded
   `"workspace-default"` default is deleted. Clients take `workspace_id` as an
   explicit parameter (no implicit global) for testability.
3. **Role-aware errors.** Reads are viewer-open, recording analyst+, triage
   operator+ (B3 registrations). UI must render a **403 as "insufficient role"**
   and a **401 as "session expired"** — never clear the token on 403. The B4
   `RealtimeClient` already models this; mirror it in the HTTP client.
4. **Deferred feature surfaces** (validity, critical-nodes, deliberate, readiness)
   are removed from the customer journey and listed in a follow-up gap list rather
   than re-pointed at a non-equivalent endpoint.

---

## 6. File inventory (exact, on `main@ca39e6a`)

**Rewrite (client unification + repoint):**
`frontend/src/lib/api/{data,decisions,evidence,graph,nexusClient,reasoning,
scenarios,signals,world}.ts`; delete `frontend/src/lib/api/http.ts`,
`frontend/src/lib/api.ts`; new `frontend/src/lib/api/client.ts` (or promote
`lib/auth/client.ts`).

**Rewrite (demo removal + rewire):**
`frontend/src/app/nexus/cockpit/page.tsx` (drop `demoRisks`/`demoSkus`/
`VSESS-demo-session` → `GET /nexus/risks`),
`frontend/src/lib/state/WorkspaceContext.tsx` (drop `loadControlledDemo`,
demo auto-load, silent catches; keep B4 cursor persistence),
`frontend/src/lib/useWorkspace.ts` (delete `"workspace-default"` fallback).

**Repoint (top-level pages off `/graph/*` → `/nexus/*`):**
`frontend/src/app/{decisions,signals,scenarios,evidence,graph}.page.tsx`
(+ `propagation`, `recommendations`, `conflicts`, `audit`, `upload`, `readiness`
as audited).

**Gate/retire `/workspace/*` (17 pages):** authenticated nav stops routing into
`/workspace/*`; the tree is removed or hard-gated behind a dev-only flag (mirrors
how `/v07-legacy/*` is already gated). Follow-up nav consolidation.

**Trace:** surface `request_id`/`correlation_id` in cockpit + decision detail.

---

## 7. Commit plan (each commit individually green)

1. **`refactor(api): unify domain client (token + X-Request-ID + 401/403)`** —
   single client; delete the two legacy HTTP layers; domain clients import it.
2. **`refactor(api): repoint domain clients to canonical /nexus/* (+/world,+/sources)`**
   — with explicit `workspace_id` threading from `useAuth()`.
3. **`fix(ui): cockpit pulls /nexus/risks; remove demoRisks/demoSkus/VSESS-demo`**
   — flagship cockpit on canonical risk registry.
4. **`fix(ui): remove WorkspaceContext demo auto-load + silent catches`** — errors
   surface; no auto-seed on mount.
5. **`refactor(ui): top-level pages off /graph/* → /nexus/*`** — decisions, signals,
   scenarios, evidence, graph.
6. **`chore(ui): gate off /workspace/* demo surfaces from the auth journey`** —
   remove `useWorkspace()` default; retire demo endpoints.
7. **`feat(ui): surface request_id/correlation_id (trace) in cockpit + decisions`**.
8. **`test(e2e): canonical golden-path journey + role-gating + demo-absence`** (§9).

---

## 8. Tests

### Frontend unit (vitest, `npm test` — now CI-gated via `typecheck.yml`)

- Client: Bearer injection, `X-Request-ID` presence, 401→session-expired vs
  403→insufficient-role (no token clear), error normalization.
- Domain client mocks: each repointed client hits the canonical path with the
  right `workspace_id` (never `"workspace-default"`, never `/workspace/*`).
- `WorkspaceContext`: no demo load on mount; fetch errors surface (no silent catch).

### Playwright E2E (`tests/`)

- New `frontend/tests/golden-path-e2e.spec.ts`: signup → onboarding → cockpit
  renders **real** `GET /nexus/risks` (assert no `demoRisks` markers / no
  `VSESS-demo-session` in DOM) → create a decision via UI → it appears in the
  decisions view (canonical path, request_id surfaced) → live realtime status LIVE.
- New `frontend/tests/role-gating-e2e.spec.ts`: analyst (or viewer) sees
  recording/triage controls **disabled/403**, not a crash and not a logout.
- Regression: `auth-e2e.spec.ts` (26) + `realtime-e2e.spec.ts` (4) + `critical-path-e2e.spec.ts`
  stay green (add any new specs to `e2e.yml` run list).

### Backend

- No backend changes expected; if any `/nexus/*` endpoint shape gaps surface
  (e.g. a required field the UI needs), they're fixed **with** `test_nexus_golden_path.py`
  coverage, not by re-pointing at the demo router.

---

## 9. Acceptance gates (all on the PR)

| Gate | Requirement |
|---|---|
| `typecheck.yml` | `tsc --noEmit` + **vitest** green (incl. new client/context tests) |
| `e2e.yml` | all specs green, **0 flaky** (golden-path + role-gating + regressions) |
| `lint.yml` / `security.yml` / `build.yml` | green; no secrets in new code |
| `test.yml` / `ci.yml` | backend suite unchanged-green (no regression from any endpoint fix) |
| Manual — grep gates | **zero** `demoRisks` / `VSESS-demo` / `/workspace/demo/load` / `"workspace-default"` / `.catch(() => {})` in `frontend/src` |
| Manual — path gate | **zero** authenticated data calls to `/workspace/*`; all to `/nexus/*` (or `/world/*`, `/sources/*`, `/simulation/*`) |
| Manual — trace | cockpit + decision detail render `request_id`; every canonical request carries `X-Request-ID` (assertable in e2e via response header) |

---

## 10. Definition of Done (B3/B6)

- [ ] One HTTP client; `lib/api/http.ts` + `lib/api.ts` deleted; `setNexusAuthToken` gone.
- [ ] Domain clients + top-level pages call canonical `/nexus/*` (and `/world/*`, `/sources/*`).
- [ ] `demoRisks`, `demoSkus`, `VSESS-demo-session`, demo auto-load, and silent catches removed.
- [ ] `/workspace/*` demo surfaces gated out of the authenticated journey.
- [ ] `useWorkspace()` hardcoded default removed; workspace_id from `useAuth()`.
- [ ] `X-Request-ID` on every canonical call; `request_id` surfaced in UI.
- [ ] Deferred-feature list (validity / critical-nodes / deliberate / readiness) written up.
- [ ] Full CI green; grep/path/trace manual gates pass; PR merged to `main` (squash).
- [ ] **Then** B9 unblocks (and B10 only after this slice **and** B4 are green).

---

## 11. PR strategy

New PR from `arena/01a08ce7-cortex` against `main@ca39e6a` (or the then-current
`main`), reusing the B4 pattern: clean branch off `main`, decomposed commits (§7),
full CI. No draft; every commit green. The deferred-feature list becomes
`docs/FOLLOWUP_GAP_LIST.md` alongside this plan.
