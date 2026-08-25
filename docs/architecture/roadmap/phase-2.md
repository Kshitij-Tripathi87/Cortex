# Phase 2 — Pilot Hardening (Active)

**Status**: Active
**Plane**: Operational
**Governing document**: `docs/architecture/active/wedge-architecture-v1.md`

---

## Objective

Move the shipped wedge from internal proof to external validation.

## Deliverables

- Design partner onboarded (1+)
- Schema mapping for partner CSVs
- Pilot deployment (Customer-controlled)
- Two backtest runs against partner disruption history
- Operator feedback captured and filed

## Acceptance

- Real partner can use the wedge end to end.
- Backtest within tolerance (≥ 0.8).
- Operator says the brief is something they would act on.

## Out of Scope

- Memory Plane, Intelligence Plane, Agent Runtime, Execution Plane.
- Second wedge or second scenario.
- Login page (unless pilot-specific security forces it).

## Where to Look

- `PILOT_BOARD.md` — week-by-week tracker
- `design_partner/` — pilot kit
- ADR-0013 (wedge freeze), ADR-0014 (exit decision template)
