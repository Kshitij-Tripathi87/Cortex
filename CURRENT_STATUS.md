# Cortex — Current Status

> ⚠️ **SUPERSEDED BELOW.** The active status is now tracked by the V-series
> exit gates: latest freeze is **V2.3 Governed Execution**
> (`V2_3_EXIT_GATE.md`, 2026-08-22, PASS WITH KNOWN BASELINE DEBT); next
> milestone is **V2.4 Evidence & Outcome Integrity** (`V2_4_PLAN.md`).
> Everything below this banner describes the earlier MVP wedge phase.

**Date:** 2026-08-07
**Phase:** MVP Wedge v2 (complete)
**Version:** backend 0.2.0, frontend 0.2.0

---

## Strategic Context

On 2026-08-01 (DECISIONS.md), the project **pivoted** from the programs I-Q
roadmap to the **MVP wedge plan v2**: build one validated decision wedge
before expanding. 12 ADRs were locked (0001-0012), freezing architectural
decisions.

The wedge product is the **Supplier Disruption Decision Brief** — one
decision type, one screen, one API endpoint, with reproducible accuracy.

The wedge plan (dependency-sequenced, not strictly weekly) is now complete:

1. ✅ Backtest scenario with ground-truth labels (`supplier_delay`)
2. ✅ Morning Brief API contract (`DecisionBriefResponse` v0.3.0)
3. ✅ Polished frontend with role switch (CFO/COO/Logistics/Procurement)
4. ✅ `DEMO.md` (7-beat, 5-minute live script)
5. ✅ Design Partner Kit (`design_partner/`)

The previous 0.3.0 production-ready docs (`COMPLETE_STATUS.md`,
`LAUNCH_STATUS.md`, `SECURITY_AUDIT.md`, `RELEASE_RC_2.md`,
`LAUNCH_HARDENING.md`) are **historical** and no longer represent the
active codebase direction.

---

## Headline Numbers

```
Backend tests:        452 passed (was 450; +2 backtest determinism tests)
Ruff (app+scripts+tests): All checks passed
Frontend typecheck:   tsc --noEmit clean
Backtest (supplier_delay):
  Accuracy:           1.0000
  Precision:          1.0000
  Recall:             1.0000
  F1:                 1.0000
  TP / FP / FN:       9 / 0 / 0
```

---

## What Shipped in This Wedge

### Backend — Decision Brief pipeline (pure-functional)

| File | Purpose |
| --- | --- |
| `app/modules/disruption/engines/propagation.py` | BFS through supply chain, attenuated exposure per hop |
| `app/modules/disruption/engines/impact.py` | 6-component weighted business impact score |
| `app/modules/disruption/engines/confidence.py` | 5-sub-score confidence (completeness, freshness, agreement, conflict_density, coverage) |
| `app/modules/disruption/engines/recommendations.py` | 7-dim scoring, ranked by `net_benefit` |
| `app/modules/disruption/engines/timeline.py` | 0/12/24/48/72h inventory-depletion checkpoints |
| `app/modules/disruption/engines/backtest.py` | Replay predictions against ground-truth labels |
| `app/modules/disruption/engines/brief.py` | Morning Brief orchestrator |
| `app/modules/disruption/engines/types.py` | Shared dataclass types |

### Backend — Backtest scenario (canonical, ground truth)

| File | Purpose |
| --- | --- |
| `app/modules/disruption/scenarios/supplier_delay.py` | Acme Electronics 5-day delay: 2 suppliers, 4 components, 2 products, 1 warehouse, 5 orders, 4 at-risk orders |
| `app/modules/disruption/scenarios/__init__.py` | Scenario registry |
| `scripts/run_backtest.py` | CLI: prints markdown report, exits non-zero if accuracy < tolerance |

### Backend — API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/briefs/supplier-failure` | Generate full `DecisionBriefResponse` (contract v0.3.0) |

Implementation (`app/api/v1/briefs.py`) builds the `SupplyChainSnapshot`
and `DisruptionScenario` from the DB, calls `run_morning_brief()`,
returns all nested blocks: `business_impact`, `confidence`, `propagation`,
`recommendations`, `timeline`.

### Backend — Notable fixes during this wedge

- `tests/__init__.py` created (was silently breaking 41 golden-dataset tests).
- `pyproject.toml`: Python 3.14 baseline (`requires-python`, ruff target,
  mypy version).
- `engines/confidence.py`: `_calc_freshness` now handles naive/aware
  datetime mixing (snapshot `as_of` is made timezone-aware when needed).

### Frontend — Morning Brief

| File | Purpose |
| --- | --- |
| `src/app/mvp/page.tsx` | Main page: form, role switch, dynamic section ordering |
| `src/features/morning-brief/components/CriticalAlertCard.tsx` | Severity banner, impact score, blast radius |
| `src/features/morning-brief/components/ImpactCard.tsx` | 6 money/score rows, scoring-formula disclosure |
| `src/features/morning-brief/components/Timeline.tsx` | Color-coded depletion events at fixed hours |
| `src/features/morning-brief/components/RecommendationPanel.tsx` | Ranked actions with all 7 sub-scores |
| `src/features/morning-brief/components/EvidenceDrawer.tsx` | Tabbed trace: components / products / warehouses / orders |
| `src/features/morning-brief/components/TrustPanel.tsx` | 5 confidence sub-scores + overall + formula |
| `src/features/morning-brief/components/RoleSwitcher.tsx` | CFO / COO / Logistics / Procurement toggle |

The role switch reorders sections (no math change) per role-specific
priority. TypeScript types are generated from the OpenAPI spec at
`src/types/openapi.json`.

### Demo + Design Partner

| File | Purpose |
| --- | --- |
| `DEMO.md` | 7-beat, 5-minute live walkthrough with failure-recovery table |
| `design_partner/README.md` | Kit entry point |
| `design_partner/ONE_PAGER.md` | 90-second pitch |
| `design_partner/TECHNICAL_DEEP_DIVE.md` | Architecture, contract, math |
| `design_partner/INTEGRATION_GUIDE.md` | 8-file CSV connector spec |
| `design_partner/ROI_CALCULATOR.md` | Cost-of-disruption worksheet |
| `design_partner/PILOT_AGREEMENT.md` | 30-day pilot terms |

---

## Locked Decisions (reaffirmed)

1. Dependency-sequenced wedge (not strict weekly).
2. `supplier_delay` backtest only, fully complete.
3. One deep synthetic company dataset.
4. One-screen Morning Brief with role switch.
5. CSV-only connectors for MVP.
6. Demo script in separate `DEMO.md`.
7. Freeze (do not delete) `k8s/`, `k8s/helm/`, `app/deferred/workflow_engine/`.

---

## Test Suite

```
452 passed in 4.06s

Breakdown:
  test_mvp_engines.py            11 tests (+2 backtest determinism)
  test_mvp_enums.py              14 tests
  test_mvp_schema_migration.py   21 tests
  test_golden_dataset.py         41 tests
  test_modules.py                25 tests
  test_graph.py                  28 tests
  test_graph_features.py         34 tests
  test_graph_traversal.py        39 tests
  test_propagation.py            23 tests
  test_scenarios.py              23 tests
  test_recommendations.py        29 tests
  test_signals.py                21 tests
  test_decisions.py              15 tests
  test_context.py                19 tests
  test_ingestion_parsing.py      12 tests
  test_backend.py                10 tests
  test_supply_chain_repositories  7 tests
  test_synthetic_dataset.py       5 tests
  test_workspace_scope.py         7 tests
  test_disruption_deferred_guard  1 test
  tests/deferred/                20 tests (workflow engine, frozen)
```

---

## Lint + Typecheck

| Tool | Status |
| --- | --- |
| `ruff check app/ scripts/ tests/` | All checks passed |
| `ruff check alembic/deferred/` | Errors (frozen per locked decision) |
| `tsc --noEmit` (frontend) | Clean |

---

## Known Gaps (post-wedge)

1. **Auth not in frontend types** — `LoginRequest`/`LoginResponse` missing
   from generated OpenAPI types. Backend endpoint works; frontend has no
   login page yet. Manual type stubs required for the next milestone.
2. **mypy errors in legacy code (~140)** — pre-existing, concentrated in
   old graph modules, `compiler`, `ml/`, `recommendation_engine`. None
   affect runtime.
3. **No persistence of briefs** — every request recomputes from the
   snapshot. Intentional for MVP; revisit post-pilot.
4. **Single workspace per deployment** — no multi-tenant isolation at the
   DB layer. Acceptable for design-partner pilot.

---

## Stale Files (Historical — Do Not Use)

- `COMPLETE_STATUS.md` — 0.3.0 launch status (2026-07-21); superseded
- `LAUNCH_STATUS.md` — 0.3.0 launch approval (2026-07-20); superseded
- `LAUNCH_HARDENING.md` — 0.3.0 hardening checklist (2026-07-20); superseded
- `SECURITY_AUDIT.md` — 0.3.0 security review (2026-07-21); partially
  relevant for legacy auth patterns
- `RELEASE_RC_2.md` — 0.3.0 release notes (2026-07-20); superseded
- `README.md` — RC-1 hardening summary; predates the wedge; needs rewrite

---

## Development Commands

```powershell
cd backend
.venv\Scripts\Activate.ps1

# Tests
python -m pytest -q

# Backtest (canonical scenario)
python scripts/run_backtest.py

# Lint
python -m ruff check app/ scripts/ tests/

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Regenerate OpenAPI spec (after backend changes)
python scripts/generate_openapi.py

# Frontend typecheck
cd ..\frontend
npm run typecheck

# Frontend dev server
npm run dev
```

---

## Next Milestones (post-wedge)

1. Frontend login page + auth-token flow.
2. Regenerate `openapi.json` to capture `LoginRequest`/`LoginResponse`.
3. Add a second backtest scenario (demand_spike) for cross-validation.
4. Run a 30-day pilot with one design partner.
