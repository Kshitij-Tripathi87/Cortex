# ADR-012: MVP Frontend Refactor (No Rebuild)

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The existing Cortex frontend at `frontend/` (Next.js + Tailwind +
TypeScript) covers many features that are out of scope for the MVP wedge.
The MVP wedge needs only one screen — the Morning Brief — rendered from
the frozen API contract (ADR-010).

## Decision

The MVP wedge frontend is **built inside the existing `frontend/`
repository**, not as a new project. The existing code remains untouched
during MVP development. New MVP code lives in:

```
frontend/src/
├── app/                         (existing Next.js app router; MVP route added here)
├── components/                  (existing shared components; MVP components added here)
├── features/
│   └── morning-brief/           (NEW — MVP-specific feature module)
└── ...
```

The Morning Brief feature module is self-contained:

```
features/morning-brief/
├── api/             (typed API client for /api/v1/mvp/*)
├── components/      (DisruptionCard, RecommendationPanel, etc.)
├── hooks/           (useMorningBrief, useTrustScore, etc.)
└── types/           (re-exports from generated OpenAPI types)
```

## Consequences

**Positive**:
- One frontend repo, one build, one deploy.
- Existing design tokens, component library, and theme are reused — visual
  consistency comes for free.
- No parallel maintenance burden of two frontend repos.

**Negative**:
- Existing frontend code is mixed with MVP code. Mitigated by the
  `features/` directory boundary; CI checks that MVP code only imports from
  `features/morning-brief/` and the generated types.
- Future cleanup (extracting the MVP into a stand-alone app if the broader
  Cortex frontend diverges) is non-trivial. Not a Phase 1 concern.

## Migration Plan

1. Build the Morning Brief page inside `frontend/src/app/mvp/`.
2. Feature module under `frontend/src/features/morning-brief/`.
3. No changes to existing frontend code paths.

## References

- MVP execution plan Part 8 (frontend scope)
- ADR-011 (generated frontend types)
