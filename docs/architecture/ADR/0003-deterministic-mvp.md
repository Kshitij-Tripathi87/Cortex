# ADR-003: Deterministic MVP

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge answers one question: what happens when a supplier fails? This
question has a correct, computable answer given the right input data. We must
decide how much of the answer should come from deterministic computation vs
probabilistic / ML models.

## Decision

The MVP wedge is **deterministic first**. Every dollar figure, every ranking,
every confidence sub-score is a pure function of the input data. No
probabilistic models, no learned rankings, no graph embeddings in v1.

The only uncertainty in the system is reflected explicitly in the Decision
Confidence sub-scores (completeness, freshness, source agreement, conflict
density, historical accuracy). Uncertainty is shown, not hidden inside a
fudge factor in the math.

## Consequences

**Positive**:
- Every number is reproducible: same input → same output, always.
- Every number is explainable: the traceable path through the algorithm is
  the explanation.
- Backtest comparison is straightforward: predicted vs. actual with no
  model drift between runs.
- Trust is earned from deterministic correctness, not from opaque confidence.

**Negative**:
- No second-order predictions (e.g., "this supplier *might* become a
  bottleneck"). Acceptable — that's Phase 2 scope.

## ML Will Come Later

Phase 2 introduces:
- Learning-to-rank for recommendations (supervised on decision_log)
- Graph pattern detection (GNN) for "suppliers behaving like ones that failed"
- Counterfactual evaluation

These require ground-truth data the MVP wedge is designed to produce. Building
ML now would be premature.

## References

- MVP execution plan §12 (recommendation scoring)
- MVP execution plan §13 (decision confidence)
- ADR-007 (workflow engine deferred — same root principle)
