# ADR 0001: Controlled Cortex Platform Graduation

**Status:** Accepted for implementation planning  
**Date:** 2026-11-03

## Context

Cortex `main` contains a substantial supplier-disruption and operational-intelligence foundation. Open PR #8,
`arena/nexus-v0.8.5-productization` at `26ecacf`, adds durable task runtime, capability discovery, a Tool Gateway,
Decision Room projections, billing, mobile/voice surfaces, four migrations, and qualification tooling. GitHub currently
reports the pull request as open and non-mergeable due to conflicts. It contains 60 commits, 117 changed files, and
more than 20,000 additions.

The product charter selects Cortex as a Unified Enterprise Intelligence & Action Platform, while the private-beta
scope remains one supplier-disruption decision loop. Merging the entire PR would mix core beta work with optional
mobile/voice, billing, device mesh, and advanced orchestration before each has been reconciled with the current
schema, dependency, and customer path.

## Decision

1. Keep the current PostgreSQL-backed World State and persistent Nexus decision path as the authoritative foundation.
2. Make the customer product a focused operational workspace centred on Overview, Data, Intelligence, Decision Room,
   Activity & Evidence, and Governance & Admin.
3. Integrate PR #8 by capability slice, not by wholesale merge. Each slice requires an ADR or implementation note,
   migration review, dependency review, tenant/authz review, focused acceptance tests, and a staging rehearsal.
4. Graduate the durable task lifecycle, capability registry, Tool Gateway, Decision Room, and Decision Receipt first
   where they directly complete the supplier-disruption workflow.
5. Keep mobile/voice, broad device mesh, public agent marketplace, unrestricted writeback, and multi-vertical expansion
   outside the private-beta release gate.
6. Treat PostgreSQL/World State as the only business authority. Agents, hosted models, Redis, and orchestration are
   derived or controlled services.

## Consequences

### Positive

- The current commercial wedge remains shippable while the broader platform is built.
- The product has one authority, one evidence chain, one governed decision lifecycle, and one customer path.
- PR #8 can be mined for reusable capabilities without accepting unrelated release risk.
- Decision Receipt becomes a product projection over durable records rather than a parallel state machine.

### Costs

- Integration will take longer than merging the branch wholesale.
- Some branch tests and qualification records must be rerun against current `main`.
- New orchestration features cannot be treated as production-ready solely because they exist on the branch.

## First implementation slices

1. Restore the backend package/import contract after the root `product/` deletion.
2. Reconcile the canonical frontend/API path and remove demo data from authenticated surfaces.
3. Define and test the Decision Room and Decision Receipt contracts over existing decision, evidence, approval,
   execution, outcome, and event records.
4. Selectively integrate durable task and Tool Gateway code after its boundaries are mapped to those contracts.
5. Qualify staging, recovery, tenant isolation, policy enforcement, and fresh-data supplier-disruption journeys.
