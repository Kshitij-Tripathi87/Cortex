# ADR-006: Schema Separation by Domain

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge and existing Cortex backend both share a single PostgreSQL
database. Without organisational structure, all tables live in `public`,
which makes role-based access control, backup isolation, and future data
architecture evolution harder than they need to be.

## Decision

PostgreSQL tables are organised into **schemas by domain**:

```
core.*          — workspaces, users
operational.*   — suppliers, components, warehouses, factories, products, customers, edges
inventory.*     — inventory, bom
orders.*        — orders, disruption_events
analytics.*     — impact_reports, backtest_results
decision.*      — decision_log, decision_memory
audit.*         — ingestion_log, audit_events
```

All schema names are reserved keywords; no cross-schema shortcuts; FK
references are explicit (e.g., `inventory.warehouse_id REFERENCES
operational.warehouses.warehouse_id`).

## Consequences

**Positive**:
- Role-based access control maps naturally: grant `SELECT` on `analytics.*`
  to analyst role, `ALL` on `operational.*` to operator role.
- Backup isolation: nightly backup of `analytics.*` separately from
  `operational.*` is trivial via `pg_dump --schema=`.
- Migration is reversible at the schema level (drop `analytics.*` without
  touching operational state).
- Future data warehouse exports are clear: which schemas to replicate vs
  ignore.

**Negative**:
- Search path must be set per session (`SET search_path TO operational,
  inventory, orders, decision;`) for ergonomic queries. SQLAlchemy
  `__table_args__ = {"schema": "operational"}` plus a configured
  `MetaData.schema` makes this transparent.
- Tooling (psql, dashboards) needs to know the schema names. Documented
  centrally.

## Migration Plan

1. Migration `009_mvp_wedge_schema.py` creates the schemas and the new
   MVP tables in their respective schemas.
2. Existing tables remain in `public` for now; Phase 2 migration moves them
   to their appropriate schemas.
3. SQLAlchemy models declare `__table_args__ = {"schema": "..."}` on each
   new ORM class.

## References

- ADR-001 (native UUID)
- MVP execution plan §1.2 (canonical data model)
