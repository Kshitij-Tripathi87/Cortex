# Cortex — Phase 1 / Phase 1.5 Specification Package

Cortex is an **evidence-first operational intelligence platform for supply chains**.

This package is the **frozen source of truth** for Phase 1 (architecture and
foundation) and Phase 1.5 (architecture validation). It is not feature
implementation. Its purpose is to make every later implementation phase
unambiguous.

The package is organized in the required build order. Each document freezes one
architectural concern. Later documents depend on earlier ones and never
contradict them.

## Reading order

### Phase 1 — Architecture and Foundation

| # | Document | Concern | Build step |
|---|----------|---------|-----------|
| 00 | `README.md` | This index | — |
| 01 | `01-architecture.md` | Enterprise blueprint, boundaries, repo structure, core principles | Step 1 |
| 02 | `02-ontology.md` | Operational ontology: entities, relationships, rules | Step 2 |
| 03 | `03-canonical-data-model.md` | Canonical data model, normalization, conflicts, lineage | Step 2 |
| 04 | `04-graph-and-events.md` | Graph model, event model, signals/scenarios/recommendations/decision memory | Steps 2 + 4 |
| 05 | `05-api-standards.md` | API conventions and endpoint catalog | Steps 3 + 5 |
| 06 | `06-database-strategy.md` | PostgreSQL strategy, immutability, audit, versioning, workspace isolation | Step 3 |
| 07 | `07-frontend-architecture.md` | Next.js enterprise workspace architecture | Step 5 |
| 08 | `08-ml-platform-strategy.md` | Bounded ML support layer | Step 5 |
| 09 | `09-security.md` | Security baseline and threat model | Step 5 |
| 10 | `10-testing-and-ci-cd.md` | Testing strategy and quality gates | Step 5 |
| 11 | `11-deployment.md` | Deployment, CI/CD, observability, rollback | Step 5 |
| 12 | `12-phase-1-acceptance.md` | Phase 1 freeze acceptance criteria | — |

### Phase 1.5 — Architecture Validation (AR-001)

Phase 1.5 is a one-day architecture review required before Phase 2 kick-off.
It closes the gaps identified in Architecture Review **AR-001**: capability and
context maps, taxonomy completeness, configuration, policy, plugin,
performance, observability, AI governance, and the philosophical foundation
that binds them. Every Phase 1.5 document depends on Phase 1 and never
contradicts it; where Phase 1 did not specify a concern, Phase 1.5 freezes it,
and a cross-reference note is added to the affected Phase 1 document.

| # | Document | Concern |
|---|----------|---------|
| 13 | `13-constitution.md` | Cortex Constitution — philosophical foundation, no engineer may violate |
| 14 | `14-business-capabilities.md` | Business Capability Map — capability → domain → module → code |
| 15 | `15-bounded-contexts.md` | DDD Bounded Context Map — ownership, I/O, anti-corruption layers |
| 16 | `16-event-taxonomy.md` | Business / System / Domain / Integration / Audit event separation |
| 17 | `17-error-taxonomy.md` | Error hierarchy and API presentation, consistent across all APIs |
| 18 | `18-configuration-strategy.md` | Runtime / Feature / Policy / Security / ML / Infra config classification |
| 19 | `19-operational-policies.md` | Operational policy framework — externalized, versioned, registered |
| 20 | `20-plugin-architecture.md` | Plugin / connector contract (SAP, Oracle, Dynamics, NetSuite, CSV, Excel, Snowflake, Kafka, S3) |
| 21 | `21-performance-budgets.md` | Per-subsystem performance budgets and enforcement |
| 22 | `22-observability-model.md` | Metrics, logs, traces, audit, health, SLIs, SLOs, alerts specification |
| 23 | `23-ai-governance.md` | AI governance rules — evidence-bound, reviewable, reproducible |

## Status legend

- **Frozen** — locked for Phase 1. Changes require a documented architecture
  change request (ACR) and re-issuing the affected document's version.
- **Open** — an explicit, tracked open question that Phase 1 must resolve before
  it can be declared frozen.

Every Phase 1 document carries a header with: version, status, owner role,
dependencies, and frozen date.

## Cross-cutting identifiers

To keep the package consistent, the following identifiers are used uniformly
across all documents and are defined once here:

- **Tenant** — the contracting organization. One Cortex deployment serves many
  tenants. Tenant isolation is physical at the database schema/object-storage
  prefix level (see `09-security.md`).
- **Workspace** — a bounded operating context inside a tenant (e.g. a region,
  business unit, or scenario sandbox). Every operational record is scoped by
  `workspace_id`. Workspaces are the unit of data isolation for users and the
  unit of graph snapshot/version isolation.
- **Canonical ID** — the system identity of an entity. A UUIDv7 (time-sortable)
  assigned at first canonicalization. Stable for the lifetime of the entity.
- **External ID** — an identity supplied by a source system, stored as
  `(source_system, external_id)` pairs on the canonical entity, never trusted as
  primary identity.
- **Version** — an entity or graph edge carries an integer `version` and a
  temporal window `(valid_from, valid_to)`. The current record has
  `valid_to IS NULL`.
- **Provenance** — the minimal tuple
  `(source_system, source_object_id, source_record_ref, extracted_at, extractor_version)`.
  Every claim, evidence record, and graph edge must carry provenance.
- **Claim** — a single normalized fact asserted by a source and evidencing a
  canonical attribute (see `03-canonical-data-model.md`).
- **Evidence** — the machine-readable support for a claim: a pointer to a
  source object plus an extractor verdict (see `04-graph-and-events.md`).
- **Audit Event** — an immutable, append-only record of a system or human
  action (see `04-graph-and-events.md`).
- **ACR** — Architecture Change Request. The only mechanism for changing a
  frozen Phase 1 artifact.

## How to change this package

1. Open an ACR describing the proposed change, rationale, and blast radius.
2. Update the affected document(s) only. Never fork a parallel definition.
3. Bump the document version, update the frozen date, and record the ACR id
   in the document's change log.
4. Re-run the Phase 1 acceptance checklist in `12-phase-1-acceptance.md`.

## Architecture change requests (ACR) log

| ACR | Date | Title | Outcome | Documents touched |
|---|---|---|---|---|
| AR-001 | Phase 1.5 | Architecture Review — capability/context maps, taxonomies, configuration, policy, plugin, performance, observability, AI governance, constitution | Applied; Phase 1.5 package (docs 13–23) frozen | `README.md`, `13-23` |
