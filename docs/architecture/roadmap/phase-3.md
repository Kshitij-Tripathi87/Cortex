# Phase 3 — Memory Plane (Future)

**Status**: Draft
**Plane**: Memory
**Governing document**: `docs/architecture/platform/decision-memory.md`

---

## Objective

Record every decision as a complete training example.

## Deliverables

- Append-only decision log
- Outcome capture (operator-timed)
- Counterfactual records (from simulation runs)
- Lessons learned + corrections
- Replay API (`GET /decisions/{id}/replay`)
- Export pipeline (JSONL → Intelligence Plane)

## Acceptance

- Every decision can be replayed and exported.
- A held-out set of decisions can be replayed offline without touching
  live data.

## Prerequisite

- Phase 2 acceptance passed (operator trust).
- ADR explicitly graduating decision memory from draft to active.

## Out of Scope (still)

- No trained models. Memory is the substrate, not the consumer.
- No agent runtime. Memory is queried, not orchestrated.
