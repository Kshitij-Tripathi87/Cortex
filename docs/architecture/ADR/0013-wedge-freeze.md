# ADR-0013: Wedge Freeze for the Pilot Phase

**Status**: Accepted
**Date**: 2026-08-07
**Deciders**: Founder / CTO

## Context

The MVP wedge plan v2 (DECISIONS.md, 2026-08-01) called for a narrow,
validated decision wedge — one decision type (supplier disruption), one
API endpoint (`/api/v1/briefs/supplier-failure`), one screen (Morning
Brief). The wedge shipped on 2026-08-07 with 452 backend tests passing,
a 100% reproducible backtest on the canonical `supplier_delay`
scenario, and a typed, role-switchable frontend.

The next phase ("validate, prove, sell") requires the wedge to be
frozen so that:

1. Design-partner conversations reference a stable surface.
2. Pilot backtests compare against a pinned snapshot of the math.
3. Any drift is visible as a deliberate ADR, not silent change.

## Decision

The wedge is **frozen as `v1.0.0-wedge`** as of 2026-08-07. The frozen
surface is:

| Surface | Frozen version | Reference |
| --- | --- | --- |
| API contract | `DecisionBriefResponse` v0.3.0 | `app/api/v1/briefs.py` |
| Propagation engine | BFS with `attenuated_exposure` | `app/modules/disruption/engines/propagation.py` |
| Impact engine | 6-component weighted score | `app/modules/disruption/engines/impact.py` |
| Confidence engine | 5-sub-score decomposition | `app/modules/disruption/engines/confidence.py` |
| Recommendation engine | 7-dim ranking, primary key `net_benefit` | `app/modules/disruption/engines/recommendations.py` |
| Timeline engine | 0/12/24/48/72h checkpoints | `app/modules/disruption/engines/timeline.py` |
| Backtest scenario | `supplier_delay` only | `app/modules/disruption/scenarios/supplier_delay.py` |
| Frontend Morning Brief | 7 components + RoleSwitcher | `frontend/src/features/morning-brief/` |
| Connector | CSV only, 8 files | `design_partner/INTEGRATION_GUIDE.md` |

### Allowed changes during the pilot

A change may be merged if and only if it falls into one of three
categories:

1. **Bug fix** — incorrect math, broken JSX, broken CSV column, etc.
   Must be reproducible from a failing test.
2. **Security fix** — disclosed vulnerability, secret rotation, etc.
   Must include a brief threat-model note.
3. **Out-of-scope, explicitly logged** — recorded in `DECISIONS.md`
   with: date, change, reason, decider. The change must not break any
   surface listed above.

### Disallowed changes during the pilot

- Adding a second scenario (`demand_spike`, etc.).
- Adding a second wedge (price, demand, capacity, logistics).
- Refactoring the frozen engines for "elegance."
- Adding real-time connectors (ERP, WMS, MES).
- Adding the login page unless a pilot-specific security gap forces it.
- Touching `k8s/`, `k8s/helm/`, `app/deferred/workflow_engine/`,
  `alembic/deferred/`.
- Widening the product pitch beyond supplier delay / failure.

### Unfreeze criterion

The wedge unfreezes only via a new ADR (0014 or later) that records
the pilot exit decision (Path A / B / C of the execution board).

## Consequences

**Positive**:
- Pilot conversations reference a stable artifact.
- Backtest reproducibility is enforceable.
- Scope creep requires an explicit decision record.

**Negative**:
- Legitimate improvements that don't fit the three allowed categories
  must wait. This is intentional.
- The freeze adds friction for new engineers; mitigated by clear ADR
  rules.

## Migration Plan

1. Tag `v1.0.0-wedge` on `main`.
2. Add this ADR to `docs/architecture/ADR/`.
3. Append the freeze entry to `DECISIONS.md`.
4. Create `PILOT_BOARD.md` at the repo root as the working tracker.
5. Publish `design_partner/` materials to the prospective list.

## References

- DECISIONS.md (2026-08-01 entries)
- ADR-0007 (workflow engine deferred)
- ADR-0010 (frozen API v1)
- ADR-0012 (MVP frontend refactor)
