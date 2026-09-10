# v0.8.5-B4 Kickoff Plan — Land & Validate Durable Realtime

**Date:** 2026-09-10 · **Author:** Arena Agent
**Baseline:** `main @ 50fcbfda77a7105c644bd53d59f3a83617075986` (authoritative launch baseline, per audit)
**Scope:** B4 only — outbox relay, Redis publication, SSE/WS catch-up, sequence-gap
detection + resync, reconnect recovery, frontend `RealtimeClient`, realtime E2E.
**Explicitly out of scope:** B3/B6 frontend rewire, B9, B10. (Dependency rule: B10 stays
blocked until B4 **and** F1/B3 are green.)

---

## 1. The situation in one paragraph

B4 is **already written**. The complete implementation exists as a single commit,
`1fb3d66` ("v0.8.5-B4: launch reliability — durable outbox to live delivery") on branch
`arena/01a0894d-cortex`, which **has no PR**. Its tree diff against `main` is clean:
**40 files, +8,446/−554, zero overlap with the already-merged B1–B3 work.** The open PR
#5 ("slices B4+ … [WIP]") is **stale** — its head `arena/01a08657-cortex` is at `fc3c0bc`
(the pre-B4 sync commit), it is a DRAFT, and its body says "Do not merge yet."

So the task is **not to write B4** — it is to (a) produce a clean PR off current `main`,
(b) close the **one gap B4 left behind** (the realtime E2E spec is still hard-skipped and
targets the pre-B4 wire protocol), and (c) drive it through the full gate set.

> **Shallow-clone note (avoid a false alarm):** `git rev-list --count main..1fb3d66`
> reports "41 commits" in this sandbox only because the local `main` is a depth-1
> boundary and its parent edge is cut. GitHub computes the PR against the real history:
> **12 commits ahead** (7 pre-squash B1–B3 titles whose *content* is already on `main`,
> + 5 B4-chain commits), and a **40-file diff**. Nothing about the branch is divergent:
> `git rev-list --count 1fb3d66..main` = **0**, and `main` is a strict ancestor.

---

## 2. What B4 changes (exact inventory, grouped)

Source of truth: `git diff --stat 50fcbfd 1fb3d66`. The spec that governs it:
`docs/NEXUS_v0.8.5_B4_LAUNCH_RELIABILITY.md` (shipped inside the commit).

### Backend — durable outbox → relay → Redis → SSE/WS (18 files)

| File | Change |
|---|---|
| `backend/alembic/versions/016_outbox_claim_lease.py` | Migration: claim/lease/retry columns on outbox rows |
| `backend/app/infrastructure/outbox_publisher.py` | +576 — `SKIP LOCKED` claim + lease, per-workspace publish exclusion, head-of-line backoff gating, poison flagging (never dropped), fast-path `commit_and_notify()` |
| `backend/app/workers/outbox_relay.py` | +69 — dedicated relay process (`python -m app.workers.outbox_relay`) |
| `backend/app/workers/__init__.py` | +5 |
| `backend/app/main.py` | Lifespan wiring: in-process sweeper, env-gated (`CORTEX_OUTBOX_PUBLISHER_ENABLED`, default `True`); API boots even if relay can't start |
| `backend/app/infrastructure/realtime_bus.py` | +184 — sequence gate, gap detection, `resync_needed`/`resync_required`, replay buffer, graceful Redis-less fallback |
| `backend/app/api/v1/realtime.py` | +191 — `/api/v1/realtime/ws` catch-up + live tail + gap/resync; `/api/v1/nexus/realtime/stream` (SSE), `/events` (durable replay), `/health` (aggregate relay truth) |
| `backend/app/api/v1/nexus_persistent.py` | +321 — realtime endpoints registration + envelope plumbing |
| `backend/app/config.py` | +52 — `CORTEX_OUTBOX_*`, `realtime_replay_limit` (500), `realtime_resync_threshold` (1000), `realtime_sse_heartbeat_s` (15) |
| `backend/app/infrastructure/metrics.py` | +96 — `cortex_outbox_*` + `cortex_realtime_*` counters |
| `backend/app/modules/nexus_spine/p0_migration/authoritative_truth.py` | +26 |
| `backend/app/modules/nexus_spine/p0_migration/authz.py` | +9 — realtime tool permissions |
| `backend/app/modules/nexus_spine/persistence/models.py` | +27 |
| `backend/app/modules/nexus_spine/persistence/repositories.py` | +26 |
| `backend/openapi.json` | +240 (regenerated; 3 new realtime paths) |

### Frontend — `RealtimeClient` + status UX (9 files + types)

| File | Change |
|---|---|
| `frontend/src/lib/realtime/client.ts` | +848 — sequence gate, dup/gap/replay/resync/reconnect, `?token=` auth, 401/403/4401 handling, cursor persistence |
| `frontend/src/lib/realtime/client.test.ts` | +712 — 14 vitest tests (FE1–FE14) |
| `frontend/src/lib/realtime/useRealtime.ts` | +98 — React hook |
| `frontend/src/lib/realtime/index.ts` | +15 |
| `frontend/src/lib/realtime.ts` | deprecated shim |
| `frontend/src/lib/realtime/nexusSocket.ts` | deprecated shim |
| `frontend/src/lib/api/realtime.ts` | deprecated shim |
| `frontend/src/lib/state/WorkspaceContext.tsx` | +137 — cursor persisted per workspace (`cortex:realtime_seq:<ws>`), live-state refresh on events |
| `frontend/src/components/shell/NexusHeader.tsx` / `components/ui/StatusDot.tsx` | LIVE / RECONNECTING / SYNCING / OFFLINE pill |
| `frontend/src/types/api.ts` + `types/openapi.json` | +232/+240 regenerated |
| `frontend/package.json` + `package-lock.json` + `vitest.config.ts` | vitest wiring |

### Deployment + docs (6 files)

| File | Change |
|---|---|
| `docker-compose.prod.yml` | +28 — `outbox-relay` service (DB+Redis deps, `CORTEX_OUTBOX_PUBLISHER_ID=outbox-relay-prod`) |
| `k8s/workers.yaml` | +46 — `cortex-outbox-relay` Deployment, **2 replicas**, pod-name publisher id |
| `.github/workflows/e2e.yml` | Playwright browser caching (CDN resilience) |
| `docs/NEXUS_v0.8.5_B4_LAUNCH_RELIABILITY.md` | +248 — the B4 spec (wire protocol, event catalog, client contract, ops) |
| `docs/B4_REALTIME_MAP.md` | +261 |
| `docs/LAUNCH_BUILD_LOG.md` | slice record |

---

## 3. PR strategy (recommended)

**Decision: create a new, clean branch off `main` and cherry-pick the single B4 commit.
Do NOT reopen/repurpose PR #5, and do NOT merge `arena/01a0894d-cortex` as-is.**

Rationale:
- `1fb3d66^` is `fc3c0bc`, whose tree equals `main` (they merged at `5f2044b`), so
  `git cherry-pick 1fb3d66` applies **only B4's own diff** — clean, no B1–B3 re-list.
- Opening a PR from `arena/01a0894d-cortex` would surface 12 commits including the 7
  pre-squash B1–B3 titles, which is noise against a squashed-merge convention.
- PR #5 is a stale DRAFT whose head predates B4; reusing it conflates "sync/re-validate"
  with the real payload.

Exact commands (to be executed when we build, not now):

```bash
# 1. Branch off the authoritative baseline
git fetch origin main
git checkout -b arena/01a08ce7-cortex-b4 origin/main

# 2. Apply only B4's own changes (its parent tree == main)
git fetch origin arena/01a0894d-cortex
git cherry-pick --no-commit 1fb3d66

# 3. ADD the net-new work (section 6): realtime E2E re-enable
#    ... rewrite frontend/tests/realtime-e2e.spec.ts, add it to e2e.yml ...

# 4. Verify the diff is exactly B4 + the E2E fix (should be ~41 files, no B1-B3 files)
git diff --stat origin/main

# 5. Push and open the PR
git push -u origin arena/01a08ce7-cortex-b4
gh pr create --base main --head arena/01a08ce7-cortex-b4 \
  --title "v0.8.5-B4: durable outbox → live delivery (realtime relay + resync + E2E)" \
  --body-file docs/B4_PR_BODY.md
```

Fallback if cherry-pick conflicts (unlikely, given parent-tree equality):
`git diff 50fcbfd 1fb3d66 | git apply --3way`, then commit as a fresh B4 commit.

---

## 4. Commit plan (within the PR)

Keep the PR small and reviewable. Recommended decomposition of `1fb3d66` into
sequential commits (each individually green):

1. **`feat(realtime): outbox claim/lease + relay worker`** — migration 016,
   `outbox_publisher.py`, `workers/outbox_relay.py`, `main.py` lifespan, `config.py`,
   `metrics.py`, `models.py`/`repositories.py`/`authoritative_truth.py`/`authz.py`.
2. **`feat(realtime): canonical stream/replay/health endpoints + WS catch-up`** —
   `realtime.py`, `nexus_persistent.py`, `realtime_bus.py`, `openapi.json`.
3. **`feat(realtime): RealtimeClient + status UX`** — `client.ts`, `useRealtime.ts`,
   `index.ts`, legacy shims, `WorkspaceContext.tsx`, header/status components,
   regenerated types.
4. **`test(realtime): A1–A20 + B4.1 + chaos + load acceptance`** — `test_nexus_v085_b4_reliability.py`,
   the three touched existing test files, `client.test.ts`.
5. **`deploy(realtime): outbox-relay service (compose + k8s)`** — `docker-compose.prod.yml`,
   `k8s/workers.yaml`.
6. **`test(realtime): re-enable realtime E2E on the B4 protocol`** — **net-new** (section 6).
7. **`docs(realtime): B4 spec + realtime map + build-log entry`** — the three docs.

(Single-commit cherry-pick is an acceptable alternative if review velocity matters more
than bisectability; the 40-file diff is coherent. Recommend the decomposition because
this is the highest-risk launch slice.)

---

## 5. Test matrix (what "validate" means)

### Backend — `backend/tests/test_nexus_v085_b4_reliability.py` (2,089 lines, 48 tests)

| Group | Guarantee | Tests |
|---|---|---|
| A1 | Commit writes state+outbox atomically; rollback writes neither | 4 |
| A2 | Contiguous, unique, per-workspace seqs under concurrency | 2 |
| A3 | At-least-once wire, exactly-once effect (idempotent consumer) | 2 |
| A4 | Graceful publisher restart: leases released, peer drains in order | 1 |
| A5 | Worker crash: leases honored until expiry, then peer reclaims | 1 |
| A6 | Expired claims move publishers, `reclaimed_total` increments | 1 |
| A7 | Redis restart: partition blocks, heal drains in order | 2 |
| A8 | Redis outage: mutations still commit; backlog visible then drains | 1 |
| A9 | Retry exponential+jitter; poison flagged once; rows never drop | 2 |
| A10 | Durable replay serves the table (not delivery state), paged | 2 |
| A11 | Live gap emits bounded `resync_needed`, never silent reorder | 1 |
| A12 | Gap over threshold refuses paging (`resync_required`) | 1 |
| A13 | SSE reconnect resumes from cursor; `?token=` selects workspace | 2 |
| A14 | WS: catch-up → live tail → gap `resync_needed` | 3 |
| A15 | Replay/stream/catch-up never cross tenants | 2 |
| A16 | Workspace 403 (never logout); subscribe boundary; 4401 | 4 |
| A17 | API restart: publisher lifecycle, subscribers survive | 1 |
| A18 | Cursor-at-head replays nothing; next live seq is `head+1` | 2 |
| A19 | Out-of-order arrival is a gap, never applied/reordered | 2 |
| A20 | Stale/duplicate frames ignored and counted | 1 |
| B4.1 | 10,000 concurrent mutations contiguous and drainable | 1 |
| C1–C5 | Chaos: redis-kill, worker-kill, restart, replay 501–550, gap→replay | 5 |
| L1–L2 | Load: commit→client P50/P95/P99 + backlog drain throughput | 2 |
| Pins | Outbox/realtime counters move; payloads never reach logs | 3 |

Command: `pytest tests/test_nexus_v085_b4_reliability.py -q` (needs `pgserver` or
`CORTEX_TEST_PG_RACE_URL`; ~60s).

### Frontend — `frontend/src/lib/realtime/client.test.ts` (14 vitest tests, FE1–FE14)

SSE: connect→live→apply once; mid-stream gap → paged replay → resume; `resync_needed`
heal; sync pacing; `resync_required` → snapshot hook; EOF reconnect from cursor;
403 terminal (≠ logout); 401 terminal; malformed-frame tolerance; `?token=`/Bearer auth;
buffer overflow → snapshot. WS: catch-up before live tail; socket gap → replay; 4401.

Command: `npm test -- src/lib/realtime/client.test.ts` (~2s) + `npx tsc --noEmit`.

### Regression — three touched suites must stay green

`test_endpoint_authz_audit.py`, `test_nexus_v082_routing_flip.py`,
`test_nexus_v083_outbox_acceptance.py` (the v0.8.3 outbox write-path acceptance — B4
must not regress it), plus the full `pytest` run (B4 self-reports **1904/0**).

---

## 6. Net-new work: re-enable realtime E2E (the gap B4 left)

B4 did **not** fix `frontend/tests/realtime-e2e.spec.ts`. On `main` it is:

- **hard-skipped** — `test.skip(true, 'Backend not available')` in the `beforeAll` and
  again per-test;
- targeting the **pre-B4** protocol — `WS_URL = ws://localhost:8000/ws/realtime` and
  `GET /v1/health` (neither is the B4 path); it hand-crafts raw `graph.delta` frames;
- **not in the E2E run list** — `e2e.yml` runs only `critical-path-e2e.spec.ts` and
  `auth-e2e.spec.ts`.

Required changes (must ship in this PR, else the "re-enable realtime E2E" acceptance is
unmet):

1. **Rewrite the spec against the B4 contract:**
   - SSE: `GET /api/v1/nexus/realtime/stream?workspace_id=…&after_seq=0&token=…`
   - replay: `GET /api/v1/nexus/realtime/events?workspace_id=…&after_seq=…`
   - WS: `/api/v1/realtime/ws?workspace_id=…&tenant_id=…&after_seq=0&token=…`
   - Drive a real mutation through the canonical API (`POST /api/v1/nexus/decisions`
     → `decision_created`), then assert the live frame arrives with the expected
     `seq`/`type` **and** that the UI mutates without refresh.
2. **Delete the hard-skips.** Replace the "backend not reachable" skip with a hard
   failure (the E2E workflow already provisions postgres+redis+minio and runs the API
   with `CORTEX_JWT_SECRET`). Reachability is a precondition, not a skip condition.
3. **Add the spec to the run list** in `.github/workflows/e2e.yml`:
   `npx playwright test tests/critical-path-e2e.spec.ts tests/auth-e2e.spec.ts tests/realtime-e2e.spec.ts`.
4. **Relay in E2E:** the API runs the sweeper in-process by default
   (`outbox_publisher_enabled=True`), so no extra worker is needed; assert the
   `/api/v1/nexus/realtime/health` endpoint reports `outbox` + worker heartbeat before
   the live assertions.

---

## 7. Acceptance gates (all must pass on the PR)

### CI matrix (auto)

| Workflow | Job(s) | Requirement |
|---|---|---|
| `test.yml` | `test` | full backend suite green incl. B4 (1904→ +48) |
| `ci.yml` | `lint-and-typecheck`, `test`, `budget-check`, `security`, `docker` | green |
| `e2e.yml` | `e2e-playwright` | **all three specs**, incl. rewritten realtime, **0 flaky** |
| `build.yml` | `docker-backend`, `docker-frontend`, `docker-compose` | green (validates `outbox-relay` service builds) |
| `lint.yml` | `lint` | ruff + eslint clean |
| `security.yml` | `secrets`, `dependencies` | green (payloads-never-in-logs pin + no secrets) |
| `typecheck.yml` | `typecheck`, `openapi-types` | mypy strict; **openapi/types drift check passes** (B4 regenerated both) |
| `stress.yml` | `stress` | nightly — advisory for this PR, required before RC |

### Manual gates (not covered by CI)

1. **Migration 016:** `alembic upgrade head` 001→016 clean, `downgrade -1` + re-`upgrade`
   verified (B1 established the 001→015 up/down ritual; B4 must extend it to 016).
2. **Relay health truth:** with the relay stopped, `/api/v1/nexus/realtime/health`
   reports `BACKLOGGING`; `/readyz` stays the K8s traffic gate (degraded, not dead).
3. **Cross-tenant/workspace isolation:** replay/stream/catch-up never leak across
   workspaces (A15/A16 cover it; spot-check manually on the compose stack).
4. **Chaos rehearsal numbers:** C1–C5 PASS verdicts and L1/L2 P50/P95/P99 are printed;
   record them in the build log (trend, not a hard budget).
5. **PR hygiene:** diff contains **no** B1–B3 files (only the 40 B4 files + the E2E
   rewrite); PR body links the spec doc and records the B4 self-reported verdicts.

---

## 8. Config & rollout checklist (for the B9 rehearsal that follows)

- `CORTEX_OUTBOX_PUBLISHER_ENABLED=true` (in-process) **or** dedicated `outbox-relay`
  worker — never both disabled. Compose uses the dedicated service; k8s runs 2 replicas.
- `CORTEX_OUTBOX_PUBLISHER_ID` = pod hostname in k8s (lease ownership).
- `CORTEX_REALTIME_RESYNC_THRESHOLD=1000`, `CORTEX_REALTIME_REPLAY_LIMIT=500`,
  `CORTEX_REALTIME_SSE_HEARTBEAT_S=15` — defaults are launch-safe.
- Redis requires auth in prod (compose sets `cortex_redis_secure_2026!`); the relay must
  fail-closed if Redis auth is wrong (A7/A8 cover the outage behavior).
- Metrics to watch post-deploy: `cortex_outbox_pending_count`,
  `cortex_outbox_oldest_pending_age_seconds`, `cortex_realtime_events_delivered_total`,
  `cortex_realtime_gap_detected_total`, `cortex_realtime_resync_total`.

---

## 9. Definition of Done (B4)

- [ ] Clean PR open off `origin/main` with **only** B4 + the realtime-E2E rewrite in its diff.
- [ ] `test_nexus_v085_b4_reliability.py` green (A1–A20, B4.1, C1–C5, L1–L2, pins).
- [ ] `client.test.ts` 14/14 + `tsc --noEmit` clean.
- [ ] `realtime-e2e.spec.ts` rewritten to the B4 protocol, **unskipped**, in the E2E run list, green.
- [ ] Full CI matrix green; openapi/types drift check passes.
- [ ] `alembic upgrade head` through 016 verified up/down.
- [ ] Chaos C1–C5 + load L1/L2 numbers recorded in `docs/LAUNCH_BUILD_LOG.md`.
- [ ] PR merged to `main` (squash). **Then**, and only then, is blocker B2 closed and
  the B3/B6 rewire unblocked.

---

## 10. What this deliberately does NOT touch

- **B3/B6 frontend rewire** — the `RealtimeClient` is wired into `WorkspaceContext`
  here, but the `/workspace/*` demo data paths, `demoRisks`, and silent auto-loaded demo
  state are a *separate* slice and stay as-is in this PR.
- **B10** — per the standing rule, billing/entitlements/admin/email stay **blocked**
  until B4 lands and F1/B3 is fixed.
- **B9** — kafka removal, staging, DR rehearsal are a later slice; this PR only *adds*
  the relay deployment units the rehearsal will exercise.
- **Ephemeral gateway events** (`world_state_updated`, `agent.deliberation.completed`) —
  still unsequenced/legacy; migrating them to the outbox is explicitly out of B4 scope.
