# ADR-008: Feature Flags

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge explicitly excludes several capabilities (live ERP connectors,
simulation studio, etc.) per `cortex-mvp-execution-plan.md §7.2`. Code paths
that reference these capabilities must be guarded so they cannot be reached
in production even if a developer forgets to delete the relevant code.

## Decision

Introduce a **settings-based feature flag system** in MVP. Each flag is a
boolean in `Settings.feature_flags` (a `dict[str, bool]`). Code paths read
flags via `get_settings().feature_flags["FLAG_NAME"]`.

Initial flags and defaults:

| Flag | Default | Purpose |
|------|---------|---------|
| `FEATURE_BACKTEST` | `True` | Enable backtest runner |
| `FEATURE_SIMULATION` | `False` | Enable simulation studio (Phase 2) |
| `FEATURE_CONNECTORS` | `False` | Enable live ERP connectors (Phase 2) |
| `FEATURE_DECISION_MEMORY` | `True` | Enable decision log writes |

The flag is checked at the boundary of the capability (e.g., the endpoint
handler or the service method entrypoint) and a `501 Not Implemented` is
returned when disabled.

## Consequences

**Positive**:
- Zero new infrastructure (no LaunchDarkly, no remote config service).
- Compile-time control via env vars; trivially testable.
- Phase 2 enablement is a config change, not a code change.
- Surfaces out-of-scope capabilities in the codebase without enabling them.

**Negative**:
- Runtime toggling per workspace is not supported (would need a DB or remote
  service). Acceptable for MVP.
- Flag sprawl risk if not pruned. Mitigated by removing flags when the
  capability ships or is permanently dropped.

## Migration Plan

1. Add `feature_flags: dict[str, bool]` to `app/config.py:Settings`.
2. Add a small helper `is_feature_enabled(name: str) -> bool` in
   `app/common/feature_flags.py`.
3. Pattern: at the top of any Phase 2 capability handler, call
   `if not is_feature_enabled("FEATURE_X"): raise HTTPException(501)`.

## References

- `cortex-mvp-execution-plan.md §7.2`
- ADR-007 (workflow engine deferred — same boundary-enforcement principle)
