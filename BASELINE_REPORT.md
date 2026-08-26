# Phase 1 — Authoritative Baseline Report

**Date:** 2026-08-25
**Method:** complete measured run of the current system. No claims copied from
status docs — every row below was executed and observed today.

---

## 1. Environment

| Item | Claimed (docs) | Measured | Verdict |
|------|----------------|----------|---------|
| Backend Python | 3.12 | **3.14.6** (venv) | ⚠️ drift — validate 3.14 against deps |
| Git repository | `git tag -a v0.3.0` claimed in LAUNCH_STATUS.md | **no `.git` — not a repository** | ❌ critical gap |
| Docker daemon | `make docker-up` | Docker CLI present, **daemon not running** | ⚠️ infra baseline limited to static checks |
| backend venv | — | present | ✅ |
| frontend node_modules | — | present | ✅ |

## 2. Backend

**Command:** `.venv\Scripts\python.exe -m pytest tests/ -q --tb=no`
**Result:** 1336 passed, **1 failed**, 17 skipped, 2 deselected — 155.5s — **1,354 collected**

| Claimed | Measured |
|---------|----------|
| "348 tests passing" (COMPLETE_STATUS.md, LAUNCH_STATUS.md) | 1,354 collected, 1 failing |

### The single failure — `test_nexus_data_intelligence_platform.py::test_nexus_data_to_decision_orchestration`

This is the flagship vertical-slice test (Data → Graph → Signals → Deliberation →
Decision → Evidence). Three independent root causes:

1. **Taxonomy drift (contract bug).** `operational_graph.py` maps
   `seller_id → "SUPPLIER"` (line 186-187); `live_workspace.py` and
   `graph_delta_engine.py` emit nodes as `"SELLER"`; `signal_engine.py`
   accepts both (`("SUPPLIER", "SELLER")`, line 138). The same real-world
   entity has two type identities depending on which path ingested it.
   The test asserts `SELLER` in graph coverage; the orchestrator path
   produces `SUPPLIER`.
2. **Non-hermetic test.** Reads real data from
   `C:\Users\21330\Downloads\archive` — outside the repo. Not reproducible
   on any other machine or CI.
3. **Coverage expectation drift.** Test asserts
   `relationship_coverage_pct > 95.0`; measured **33.77%** with
   `max_orders=200` sampling over a ~99k-order dataset.

**Flag (Phase 13):** the run output contains `world_state_version=101`
and `relationship_coverage=98.5` (readiness dimension) — exactly the shape of
the "suspicious constants" the program calls out. Must verify derivation.

## 3. Frontend

**Commands:** `npx tsc --noEmit`, `npm run build`

| Gate | State found | State now |
|------|-------------|-----------|
| `tsc --noEmit` | ❌ **18 errors** | ✅ **0 errors** |
| `next build` (production) | ❌ blocked by tsc | ✅ **clean — all 45 routes compiled** |

### Defects found and fixed (`src/app/nexus/page.tsx` — the flagship console)

1. **Orphaned `</main>`** after the closing `</div>` of the root wrapper;
   `</main>` missing before `<aside>` (right rail).
2. **Missing `)}`** closing `{subgraph && subgraph.nodes.length > 0 && (` —
   caused "Adjacent JSX elements" parse failure.
3. **Missing `</div>`** — world wrapper never closed.
4. **`onKeyDown` handler** closed with `)}` instead of `}}` (syntax error).
5. **Inverted loading condition** — displayed "loading operational graph…"
   when the graph *had* nodes (`subgraph && nodes.length > 0 && !error`),
   and nothing when it didn't. Fixed to `(!subgraph || nodes.length === 0) && !error`.
6. **172-line duplicated graph canvas** inlined in the World section —
   a stale copy of the proper `GraphCanvas` component, referencing
   an undefined `overlay` variable and three nonexistent `GraphNode`
   properties (`depends_on`, `cf_simulation`, `node_type`).
   **Excised; World now renders `<GraphCanvas withToolbar showFocusedPanel />`.**
7. Duplicate local `interface GraphNode` at page top shadows
   `src/types/nexus.ts` — left in place (compiles); dedup queued for Phase 3.

### Defects found and fixed (Playwright specs, `frontend/tests/`)

8. `test.info().annotations.push({ category, description })` — `category`
   is not a valid Playwright annotation key (13 sites, 3 files).
   Converted to `{ type: 'category: <x>', description }`.
9. `test.skip('reason')` — invalid signature (3 sites in
   `realtime-e2e.spec.ts`). Corrected to `test.skip(true, 'reason')`.

### Repository hygiene (same disease class — surgery debris)

Deleted: `frontend/temp_component_only.tsx` (70 KB broken copy),
`frontend/temp_no_use_client.tsx`, `frontend/temp_main_test.tsx`,
`frontend/src/app/nexus/page.tsx.backup` (70 KB).
Root of repo still carries scratch scripts: `fix_main.py`, `fix_indent.py`,
`swap_lines.py`, `trace_jsx.py`, `bisect_parse.py`, `balance.py`,
`count_braces.py`, `analyze_world.py`, `trace_world.py`, `run.py`,
`parse_check.js`. **Recorded, not yet removed** (Phase 10 decision: move to
attic/ or delete).

## 4. Infrastructure (static only — Docker daemon down)

| Check | Result |
|-------|--------|
| docker-compose.yml | present (unstarted) |
| alembic migrations dir | present; `upgrade head` **not exercised** (needs Docker/PostgreSQL) |
| /healthz, /readyz, /metrics | defined in `app/main.py` — `/readyz` checks DB only; Redis/S3 not probed despite status docs claiming "DB/Redis/S3 checks" |
| K8s manifests | present (unchanged since sign-off) |

## 5. Security (test inventory, not re-run in isolation)

| Claim | Evidence | Verdict |
|-------|----------|---------|
| RLS enforced | `alembic/versions/002_row_level_security.py`; `test_workspace_isolation.py`, `test_workspace_scope.py` pass in full run | ✅ code present & covered |
| Tenant isolation | `test_program_p11_security_capabilities.py`, `test_production_qualification_security.py` pass | ✅ covered |
| Secrets scanner | covered by `test_modules.py` | ✅ |
| Fail-closed Redis for authZ paths | **not verified** — Phase 8 owns | ⬜ open |
| Frontend state never influences authZ | **not audited endpoint-by-endpoint** — Phase 3/12 own | ⬜ open |

---

## Baseline verdict

| Axis | State |
|------|-------|
| Backend tests | 1336/1337 passing; **1 flagship pipeline test red** |
| Frontend compile | ✅ tsc 0 errors — **was red, fixed today** |
| Frontend production build | ✅ 45 routes — **was red, fixed today** |
| Docs vs reality | "348 tests passing" vs 1,354 collected; "v0.3.0 tagged" vs no git repo; "Python 3.12" vs 3.14.6 — **systematic documentation overstatement** |
| Run-time stack (Docker/DB/Redis) | **not exercised** — daemon unavailable |

## Gap list (promoted to program phases)

| # | Gap | Phase | Status |
|---|-----|-------|--------|
| G1 | SELLER vs SUPPLIER taxonomy split across graph/delta/signal/live modules | 3 | ✅ **RESOLVED 2026-08-26** — canonical `SUPPLIER`; `SELLER` accepted only as ingest alias (delta event names, CSV conventions). Emission paths unified in entity_resolution, signal_engine, graph_delta_engine, live_workspace, query_planner, nexus_supervisor, orchestrator |
| G2 | Vertical-slice test non-hermetic (absolute path to Downloads) | 4 | ✅ **RESOLVED** — deterministic seeded fixture (`backend/tests/fixtures/olist/`, generator: `scripts/generate_olist_fixture.py`); `CORTEX_OLIST_DIR` env override for full-archive runs |
| G3 | relationship_coverage_pct 33.8% vs asserted 95% under sampling | 4/13 | ✅ **RESOLVED** — two real bugs fixed: (a) adapter now referentially filters ORDER_ITEM/PRODUCT to sampled orders instead of disjoint row caps; (b) `_detect_id_fields` mis-picked `order_id` as ORDER_ITEM's PK (cardinality-ranked detection now); coverage honestly ~100% on complete data |
| G4 | `world_state_version=101` constant smell in live path | 13 | ✅ **RESOLVED (orchestrator)** — version now a pipeline parameter recorded verbatim; dispatch-latency signal derived from actual purchase→handoff data with cross-supplier median baseline; blast radius switched from hardcoded fallbacks to real BFS traversal; evidence payloads derived. ⚠️ **G4b OPEN**: the 4 counterfactual simulations and shipment telemetry remain declared scenario inputs — wiring the real Digital Twin runtime is Phase 13 work |
| G5 | No git repository | 10 | ✅ **RESOLVED** — repo initialized; baseline commit `6588aca`; hardening changes committed separately |
| G6 | `/readyz` probes only DB (docs claim DB+Redis+S3) | 10/11 | ⬜ open |
| G7 | Python 3.14 vs documented 3.12 | 10 | ⬜ open |
| G8 | page.tsx local `GraphNode` shadows `types/nexus.ts` | 3 | ⬜ open |
| G9 | Scratch scripts in repo root | 10 hygiene | ⬜ open |
| G10 | Playwright specs not run (tsc only) — E2E against live stack pending | Phase 5 onward | ⬜ open |

## Post-fix verification (2026-08-26)

```
Backend: 1337 passed, 17 skipped, 2 deselected — 154.96s   (baseline was 1336 pass / 1 fail)
Frontend: tsc --noEmit = 0 errors; next build = clean (45 routes)
```

The flagship vertical-slice test now proves the honest chain on hermetic data:

```
CSV fixture → canonical dataset (referentially complete under sampling)
  → operational graph (SUPPLIER taxonomy) → analytics (real PageRank/SPOF/Gini)
  → signal CRITICAL SUPPLIER_DEGRADATION (8.08d actual vs 2.08d median baseline — derived)
  → blast radius via BFS ($37,466.55 across 37 orders / 159 customers / 6 regions — traversed)
  → features (real pagerank/spof flags) → context → deliberation → decision card
  → evidence graph (payloads sourced from the computed values above)
```
