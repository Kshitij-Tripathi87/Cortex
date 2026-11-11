# Cortex Nexus — Demo Audit & Engineering Backlog

**Directive:** 10-day demo specification (supplier-disruption decision journey).
**Audit baseline:** branch `rc0/workflo-core-alpha`, commit `01d4b5c`.
**Verification at audit time:** backend `pytest tests/` → **1926 passed, 136 skipped**; frontend `typecheck` ✓, 14 Vitest tests ✓.

---

## 1. Repository → specification mapping

### 1.1 Backend (strong — canonical pipeline exists)

| Spec pipeline stage | Implementation | Status |
| --- | --- | --- |
| Ingestion & validation | `backend/app/modules/ingestion/service.py`, `modules/sources/`, `api/v1/ingestion.py`, `api/v1/sources.py` | Implemented; tested |
| Entity resolution | `modules/data_intelligence/entity_resolution.py` (in-memory); spine stage 3 is 1-row-→-1-entity | **Partial** |
| Canonical World State | `modules/world/world_service.py` (sole write path, transactional, versioned) + `api/v1/world.py` | Implemented; tested |
| Dependency graph + traversal | `modules/graph/traversal.py`, `modules/graph/propagation_engine.py`, `api/v1/graph.py` | Implemented; tested |
| Disruption detection | `api/v1/nexus_persistent.py` `/nexus/signals` (computed on read), risk registry `/nexus/risks` | Implemented |
| Impact calculation | `modules/disruption/engines/impact.py` (6-component score, traceable formulas); risk records carry `revenue_exposure`, `sla_risk_pct`, `blast_radius_count`, `root_causes`, `hidden_dependencies` | Implemented |
| Recovery alternatives | `modules/nexus_spine/pipeline_stages.py` (templated, relevance-gated); scenarios engine `modules/nexus_spine/scenarios/studio.py` (deterministic twin) | Implemented; heuristics documented in code |
| Simulation | `POST /nexus/scenarios/{id}/simulate` → `ScenarioStudio.run_with_snapshot` (caller-supplied snapshot, never the singleton) | Implemented; tested (`test_nexus_golden_path.py::test_simulate_deterministic_kpis`) |
| Policy checks | `governance/lifecycle.py` + `p0_migration/authz.py` per-phase tool checks; `execution/policy_engine.py` | Implemented |
| Human approval | `p0_migration/authoritative_decisions.py::advance` — row-locked, whitelist transitions, stale-world auto-invalidation (409), `ApprovalRecordDB` trail | Implemented |
| Governed execution | `nexus_spine/governed_execution_service.py` (15+ fail-closed checks) | Implemented; **adapters simulated** |
| Outcome & audit | `/nexus/decisions/{id}/outcome`, `nexus_*` tables, hash-chained evidence (`evidence_chain.py`), `audit/service.py` | Implemented |

**Canonical decision surface:** `/api/v1/nexus/*` (`api/v1/nexus_persistent.py`) → PG-backed `Authoritative*` services. The v0.7 in-memory surface is flag-gated legacy; `/spine/run` is the one-shot batch pipeline. `workflo-cli/` + `workflo_backend/` are a **separate product** (sandboxed QA runtime) — not part of the Nexus decision loop.

**Known backend gaps (not blocking the demo, tracked in §3):** spine path synthesizes `operator_id="system_auto"` approval instead of pausing on the persistent lifecycle; execution adapters are simulated; dual outcome stores (in-memory `DecisionMemoryStore` vs `nexus_outcomes`); `multi_agent/runtime/builtin_tools.py` contains fabricated supplier data (flag-gated agent surface, must never feed canonical `/nexus/*`).

### 1.2 Frontend (the critical path)

RC0 canonical rewire left **3 live surfaces**: `/nexus/cockpit` (Command Center, ~50% of spec A), `/nexus/decision-room` (~70% of spec E), `/upload`. The rich `/workspace/*` tree is retired (redirects) and partially mocked. Orphaned-but-correct API clients exist (`lib/api/scenarios.ts` targets canonical `/nexus/scenarios`, zero importers).

| Spec screen | Route | Status |
| --- | --- | --- |
| A. Command Center | `/nexus/cockpit` | Partial — no facilities/pending-decisions/events feeds; dead sidebar links |
| B. World State Explorer | **missing** | Graph API unused beyond static SVG; no detail panel/table view |
| C. Disruption & Impact Analysis | **missing** | `root_causes`/`hidden_dependencies` fetched but never rendered |
| D. Scenario Studio | **missing** | `lib/api/scenarios.ts` orphaned; retired page was mocked |
| E. Decision Room | `/nexus/decision-room` | Working but off-token styling (hardcoded cyan hex), evidence/approvals shown as counts only |

No shared navigation shell on `/nexus/*` (each page has ad-hoc chrome; nav tree does not match spec §3).

---

## 2. Engineering executed in this change (dependency order)

**All items below are implemented and verified:** frontend `typecheck` ✓, `lint` ✓, **22/22 Vitest tests** ✓ (14 pre-existing + 8 new), production `build` ✓ (all six canonical `/nexus/*` routes compile). Backend unchanged in this slice; the full suite baseline (1926 passed) stands.

1. **Canonical navigation shell** — `frontend/src/app/nexus/layout.tsx` + `components/nexus/NexusNav.tsx`: spec §3 nav tree over `--nx-*` tokens (Inter + JetBrains Mono, dark, zero-radius).
2. **World State Explorer** — `frontend/src/app/nexus/world/page.tsx` + `components/nexus/WorldExplorer.tsx`: real `/graph/nodes` + `/graph/edges`; search, type filter, interactive graph, entity detail panel (attributes, versions, connections), tabular view, per-type data-quality counts, source/version provenance columns.
3. **Scenario Studio** — `frontend/src/app/nexus/scenarios/page.tsx`: wires the orphaned `lib/api/scenarios.ts` to canonical `POST /nexus/scenarios`, `POST /nexus/scenarios/{id}/simulate`; recovery alternatives created as real mutation-backed scenarios against a selected supplier entity; side-by-side KPI comparison (NEV, revenue-at-risk, SLA, stockout, recovery days, cost) + assumption notes + affected entities, exactly as returned by the deterministic twin.
4. **Entity snapshot bridge** — `frontend/src/lib/nexus/snapshot.ts`: deterministic graph-node → twin `Entity` mapping (UUID-5 normalization, kind mapping, attribute→state). Pure and unit-tested; shared by Scenario Studio.
5. **Impact Analysis** — `frontend/src/app/nexus/impact/page.tsx`: renders persisted risk detail (`root_causes`, `hidden_dependencies`, exposure, SLA risk, blast radius), upstream/downstream dependency paths traversed from the real graph, methodology + confidence disclosure.
6. **Decision Room normalization** — real record fields (`options`, `recommended_option_id`, `policy_id`, `recommended_nev/sla/cost`, `confidence`, `evidence_root_hash`), itemized evidence nodes, approval trail, receipt transitions; `--nx-*` tokens.
7. **Operations** — `frontend/src/app/nexus/operations/page.tsx`: model health (`/nexus/models/health`), relay health (`/nexus/realtime/health`), audit events (`/audit`).
8. **Cockpit decluttering** — inline sidebar removed (layout owns nav); links point at canonical routes only.

Every value rendered is fetched from the canonical API or explicitly labeled as unavailable — no fabricated metrics (spec invariant 4).

---

## 3. Prioritized backlog (file-level)

| # | Item | Files | Priority |
| --- | --- | --- | --- |
| B1 | Spine must stop auto-approving: route spine proposals into `nexus_decisions` + persistent lifecycle (real pause) | `modules/nexus_spine/spine_orchestrator.py`, `p0_migration/authoritative_decisions.py` | High (post-demo) |
| B2 | HTTP-level e2e: one flow, upload → world state → risk → scenario → simulate → advance → execute → receipt | `backend/tests/test_nexus_canonical_flow.py` (new) | High |
| B3 | Entity resolution persistence + cross-system dedupe | `modules/data_intelligence/entity_resolution.py` | Medium |
| B4 | Replace simulated execution adapters behind a provider interface (keep honest "simulated" labels in demo) | `nexus_spine/governed_execution_service.py`, `execution/adapters/*` | Medium |
| B5 | Retire in-memory `DecisionMemoryStore`; read Program-O from `nexus_outcomes` | `execution/decision_memory.py`, `governance/flywheel_service.py` | Medium |
| B6 | Purge fabricated fixture data from agent built-in tools | `multi_agent/runtime/builtin_tools.py` | Medium |
| B7 | Command Center: pending-decisions feed + recent events (SSE `/nexus/realtime/stream` already exists) | `components/disruption/DisruptionCockpit.tsx` | Medium |
| B8 | Decision Room: surface `policy_checks` supplied at advance time (approval-record policy checks are already displayed) | `app/nexus/decision-room/page.tsx` | Medium |
| B9 | Dedicated Data Quality / Source Provenance pages fed by `/sources/batches`, `/sources/claims`, `/conflicts` | new `app/nexus/*` pages | Low |
| B10 | Delete retired `/workspace/*` tree + orphaned components once canonical surfaces reach parity | `app/workspace/**`, `components/shell/**`, `features/morning-brief/**` | Low |

---

## 4. Acceptance-criteria traceability

| Demo criterion | Where satisfied |
| --- | --- |
| Data ingestion | `/upload` → validated contract (existing) |
| Entities resolved / World State updated | World State service (existing); visualized in `/nexus/world` |
| Dependencies explorable | `/nexus/world` (graph + table + detail panel) |
| Disruption identified | Cockpit attention queue + `/nexus/impact` |
| Impact calculated & explained | `/nexus/impact` (persisted risk fields + graph paths + methodology note) |
| ≥2 recovery alternatives | `/nexus/scenarios` creates N mutation-backed scenarios |
| Alternatives simulated & compared | `/nexus/scenarios` simulate + side-by-side KPI table |
| Policy checks enforced | Backend lifecycle/AuthZ (existing); surfaced in Decision Room fields |
| Human approval before execution | `/nexus/decision-room` advance → approved → execute (existing, tested) |
| Evidence & provenance retained | Evidence/approval/receipt rendering (this change) on existing durable stores |
| Missing/stale data surfaced | 409 stale-world errors, empty states, "not recorded" provenance labels |
| Workflow repeatable | Deterministic twin + idempotent ingestion (existing tests) |
