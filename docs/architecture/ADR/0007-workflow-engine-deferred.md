# ADR-007: Workflow Engine Deferred

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The Workflow & Orchestration Core (Program I in the prior roadmap) was
implemented and tested (12 files, 20 passing tests) but is not part of the MVP
wedge scope per `cortex-mvp-execution-plan.md §7.2`.

## Decision

The workflow engine code remains in the repository but is moved to
`app/deferred/workflow_engine/` (and `tests/deferred/` for tests) and marked
with `DEFERRED` docstrings. It is **not** imported by any production code
path in the MVP wedge. A CI guard prevents future regressions on this rule.

The Alembic migration `008_workflow_engine.py` is moved to
`alembic/deferred/` and excluded from the default `alembic upgrade head`
chain.

## Consequences

**Positive**:
- Code is preserved (no deletion of investment).
- Future re-enablement is one directory move + one migration application.
- CI enforces the boundary — any accidental import fails the build.

**Negative**:
- Dead code in the repository. Mitigated by the `DEFERRED` docstring at the
  top of every file.
- The deferred tests still run (CI runs `pytest tests/deferred/` on a slower
  schedule) so they don't bitrot.

## Migration Plan

1. Move `app/modules/workflow/*` to `app/deferred/workflow_engine/*`.
2. Move `app/api/v1/workflows.py` to `app/deferred/workflow_engine_api.py`.
3. Move `tests/test_workflow_*` to `tests/deferred/test_workflow_*`.
4. Move `alembic/versions/008_workflow_engine.py` to
   `alembic/deferred/008_workflow_engine.py`.
5. Remove the `workflows.router` include from `app/api/v1/router.py`.
6. Add `DEFERRED` docstring to every moved Python file.
7. Add CI guard: `grep -r "from app.deferred" app/ tests/ alembic/versions/`
   must return zero results.

## Re-Enable Path (Phase 2+)

1. Move directories back to their original locations.
2. Re-add router include.
3. Apply `alembic upgrade +1 deferred/008_workflow_engine`.
4. Remove CI guard or scope it to the active paths.

## References

- `cortex-mvp-execution-plan.md §7.2` (out of scope for MVP)
- ADR-003 (deterministic MVP — same root principle of avoiding premature
  capability)
