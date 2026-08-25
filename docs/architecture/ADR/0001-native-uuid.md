# ADR-001: Native PostgreSQL UUID

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The existing Cortex backend uses `String(36)` UUIDs throughout its SQLAlchemy
models. The MVP wedge calls for a focused data model in PostgreSQL. We must
decide whether to standardise on native PostgreSQL `UUID` columns (with
`UUID(as_uuid=True)` in SQLAlchemy 2.0) or to continue using `String(36)`.

## Decision

All **new** tables introduced by the MVP wedge migration (`009_*`) use native
PostgreSQL `UUID` columns. The existing tables continue to use `String(36)`
until a Phase 2 migration backfills and swaps the type.

The default for new UUID columns is `gen_random_uuid()` (PostgreSQL built-in,
no Python uuid7 dependency).

## Consequences

**Positive**:
- Native PostgreSQL optimisation (smaller indexes, faster joins).
- Standard pattern in enterprise PostgreSQL deployments.
- Easier future partitioning/sharding.
- SQLAlchemy `UUID(as_uuid=True)` is the idiomatic type.

**Negative**:
- Mixed UUID types during the MVP phase (new tables native, existing tables
  String(36)). Both compare correctly as strings, so this is non-breaking.
- Phase 2 will need a one-shot backfill-and-swap migration for the existing
  tables.

## Migration Plan

- **Phase 1 (now)**: `009_mvp_wedge_schema.py` adds new tables with native UUID.
- **Phase 2 (deferred)**: Migrate existing tables in a single Alembic revision,
  backfilling new columns from old columns, then dropping old.

## Alternatives Considered

- **`String(36)` everywhere**: Slower indexes, larger storage, inconsistent
  with PostgreSQL tooling. Rejected.
- **Migrate all tables now**: 4-5 days of risk before MVP value delivery.
  Rejected for MVP; deferred to Phase 2.

## References

- MVP execution plan §1.2 (canonical data model)
- ADR-006 (schema separation)
