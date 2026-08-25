# Phase 4 — Intelligence Plane (Future)

**Status**: Draft
**Plane**: Intelligence
**Governing document**: `docs/architecture/platform/intelligence-plane.md`

---

## Objective

Learn from validated memory. Beat the deterministic baseline offline
before any model is shipped.

## Deliverables

- World Model as first-class (see `world-model.md`)
- Engine 1 (Prediction): GNN risk model
- Engine 4 (Simulation): Monte Carlo scenario expansion
- Engine 5 (Evaluation): benchmark gate + calibration
- Shadow inference (no display)
- Shadow with display (operator sees, not used)

## Acceptance

- Each model beats its deterministic baseline on a held-out backtest.
- Calibration < 0.05 Brier gap.
- Zero regression on the existing 452 tests.

## Prerequisite

- Phase 3 complete (decision memory populated and clean).

## Out of Scope (still)

- No autonomous actions (Phase 6 gating).
- No LLM-generated math in the brief.
- No RL policies in production.
