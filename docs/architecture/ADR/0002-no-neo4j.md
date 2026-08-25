# ADR-002: No Neo4j or Other Graph Database

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge traverses a supply-chain graph (supplier → component → warehouse
→ factory → product → customer). Graph databases such as Neo4j are designed
for this workload. We must decide whether to introduce one for the MVP.

## Decision

The MVP wedge does **not** use a graph database. Propagation is performed via
plain Python BFS over a `String(36)` foreign-key indexed `edges` table in
PostgreSQL, with a visited-set for cycle protection.

## Consequences

**Positive**:
- Zero new operational dependencies (no Neo4j to provision, monitor, back up).
- One database to back up, one access control model.
- Deterministic and explainable traversal — every edge visited is logged for
  `decision_trace`.
- Performance is sufficient: hundreds to low thousands of nodes, single-digit
  milliseconds per query.

**Negative**:
- At higher node counts (10K+), BFS may need to be replaced with recursive CTEs
  or a graph DB. Not a problem for MVP.

## Migration Plan

If scale demands graph DB later:
1. Replicate `edges` table into Neo4j (or similar) via CDC or nightly job.
2. Keep `edges` as source of truth.
3. Add feature-flag-gated propagation path that reads from graph DB.

## Alternatives Considered

- **Neo4j**: Operational overhead, separate access model. Rejected.
- **Memgraph, TigerGraph**: Same concerns as Neo4j. Rejected.
- **NetworkX in-process**: Loses durability, doesn't share DB transactions.
  Rejected.

## References

- MVP execution plan §3.2 (propagation engine)
- ADR-003 (deterministic MVP)
