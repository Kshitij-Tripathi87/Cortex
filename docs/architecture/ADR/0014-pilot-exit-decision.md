# ADR-0014: Pilot Exit Decision (Path A / B / C)

**Status**: Accepted (template)
**Date**: 2026-08-07
**Deciders**: Founder / CTO

## Context

The pilot phase (W1–W4 of the execution board) ends with a single
binary-conditional decision: proceed, tighten, or reframe. The decision
must be **evidence-based**, not aspirational. This ADR provides the
template that will be filled in at W4D5.

## Decision

To be filled at W4D5. One of three paths is chosen:

### Path A — Proceed with the wedge

Chosen when **all four** W4 acceptance tests are checked:

- [ ] Backtest result is documented (≥ tolerance).
- [ ] Operator can understand the brief.
- [ ] Operator can point to at least one sub-score they trust.
- [ ] Operator can say what action they would take.

If Path A is chosen, the wedge unfreezes under ADR-0013 rules and
graduates toward a paid pilot program.

### Path B — Tighten the wedge

Chosen when 2–3 of the W4 acceptance tests are checked and one
**specific, fixable gap** remains. The Optional Week 5 (one targeted
fix set, one re-run) executes before re-evaluating against this ADR.

The fix must be on the Allowed Fixes list:

- trust explanation clarity
- Morning Brief wording
- schema mapping robustness
- data validation messages
- a genuine bug in propagation / recommendation math
- a missing evidence link

The fix must **not** convert feedback into platform work.

### Path C — Reframe the wedge

Chosen when 0–1 of the W4 acceptance tests are checked, or when the
operator's feedback indicates the **problem statement** itself is
wrong (not the solution). The wedge remains frozen; a new ADR series
is opened to reconsider the wedge scope itself.

## Consequences

Whatever path is chosen is appended to `DECISIONS.md` and
`CURRENT_STATUS.md`. The decision is not subject to re-litigation
inside the pilot phase.

## References

- PILOT_BOARD.md
- ADR-0013 (wedge freeze)
