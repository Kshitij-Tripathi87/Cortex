# Wedge Architecture v1 (Active)

**Status**: Active — Authoritative for current engineering
**Scope**: MVP Wedge only (Supplier Disruption Decision Brief)
**Last Updated**: 2026-08-07

---

## 1. Purpose

This document is the **single source of truth** for the shipped MVP wedge. Every
engineer, tester, and pilot integrator treats this as the governing contract.

The future Cortex platform is documented separately under
`docs/architecture/platform/`. Those documents are **drafts** and do not govern
current implementation. If a `platform/` document conflicts with this one,
**this one wins** until a new ADR explicitly graduates a platform component
into active scope.

---

## 2. Wedge Definition

**One decision type**: Supplier disruption (delay / failure).
**One screen**: The Morning Brief.
**One API endpoint**: `POST /api/v1/briefs/supplier-failure`.
**One connector**: CSV (8 files).
**One scenario**: `supplier_delay` (Acme Electronics 5-day delay).

The wedge is frozen as `v1.0.0-wedge` per ADR-0013. The freeze rules
apply: only bug fixes, security fixes, and explicitly-logged out-of-scope
changes may merge during the pilot.

---

## 3. Active Modules

```
backend/app/modules/disruption/
  engines/
    brief.py          — orchestrator
    propagation.py    — BFS, attenuated exposure per hop
    impact.py         — 6-component weighted score
    confidence.py     — 5-sub-score decomposition
    recommendations.py — 7-dim ranking, primary key net_benefit
    timeline.py       — 0/12/24/48/72h checkpoints
    backtest.py       — replay vs ground-truth labels
    types.py          — shared dataclasses
  scenarios/
    supplier_delay.py — canonical backtest scenario
    __init__.py       — scenario registry
```

```
backend/app/api/v1/briefs.py  — the one endpoint
backend/app/modules/supply_chain/  — models, repos
backend/app/modules/ingestion/     — CSV parse, validate, load
```

```
frontend/src/app/mvp/page.tsx       — main page
frontend/src/features/morning-brief/
  components/  — 7 components + RoleSwitcher
  api/client.ts
  roles.ts
  format.ts
```

---

## 4. Active API Surface

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/briefs/supplier-failure` | Generate `DecisionBriefResponse` v0.3.0 |

That is the entire wedge API surface for the pilot. No other endpoints are
in active scope.

---

## 5. Active Data Model

Eight CSV files (see `design_partner/INTEGRATION_GUIDE.md`):
`suppliers`, `components`, `products`, `boms`, `warehouses`,
`inventory`, `orders`, `supplier_components`.

Rules: native UUIDs, `workspace_id` on every row, provenance preserved,
idempotent loader.

---

## 6. Active Acceptance

- 452 backend tests pass.
- `ruff check app/ scripts/ tests/` clean.
- `tsc --noEmit` clean.
- `supplier_delay` backtest: Accuracy/Precision/Recall/F1 = 1.0000,
  TP=9 FP=0 FN=0.
- The Morning Brief renders with seeded UUIDs, role switch reorders
  sections, all 7 components paint without console errors.

---

## 7. Out of Scope (Active Wedge)

The following are **not** active, regardless of what `platform/` documents
describe:

- Memory Plane (decision logging, outcomes, lessons)
- Intelligence Plane (GNNs, RL, learned ranking)
- Multi-Agent Runtime (supervisor, workers)
- Execution Plane (writebacks, ERP connectors)
- World Model (high-velocity state)
- A second scenario or second wedge
- Login page or authz flow on the frontend
- Real-time connectors

Each of these lives in `docs/architecture/platform/` as a draft. None
govern current PRs.

---

## 8. How to Change This Document

1. Propose the change in `DECISIONS.md`.
2. If accepted, open an ADR (0013+) that records the graduated scope.
3. Update this document to reflect the new active surface.
4. Tag a new wedge version (`v1.1.0-wedge` or similar).

No silent edits. This doc is the contract.
