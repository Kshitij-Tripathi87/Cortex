# ADR-010: Frozen API v1

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

API contracts that change silently break customers. The MVP wedge ships a
specific set of endpoints per `cortex-mvp-execution-plan.md Part 7`. Future
changes must not break already-shipped contracts.

## Decision

The `/api/v1/` URL prefix is **frozen** for the MVP wedge. Any breaking
change to a v1 endpoint requires either:
1. A new endpoint under `/api/v1/` (and the old one deprecated with
   `Deprecation` and `Sunset` headers), or
2. A new endpoint under `/api/v2/`.

Adding fields to responses is non-breaking (clients ignore unknown fields).
Removing fields, changing field types, or changing semantic meaning is
breaking.

## Consequences

**Positive**:
- Customers integrating against v1 are guaranteed stability.
- Deprecation path is explicit: headers, then removal, no surprise.
- The contract version (`"contract_version": "1.0"`) is included in the
  Morning Brief response, allowing clients to detect version mismatches.

**Negative**:
- Schema evolution requires care. Backward-compatible field additions only.

## Migration Plan

1. The MVP wedge endpoints live under `/api/v1/mvp/*` and
   `/api/v1/auth/*`. None are deprecated.
2. The Morning Brief response includes `"contract_version": "1.0"`.
3. OpenAPI schema is regenerated and pinned per release; CI fails if a
   PR changes a v1 endpoint shape without bumping the contract version.

## References

- MVP execution plan Part 7 (API surface)
- ADR-011 (generated frontend types — depend on stable OpenAPI)
