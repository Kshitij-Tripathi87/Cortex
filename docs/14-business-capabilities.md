# 14 — Business Capability Map

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Product Architect |
| Depends on | `01-architecture.md` (modules), `02-ontology.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Cortex is defined by **capabilities**, not by modules. A capability is a
durable product ability that survives technology changes. The decomposition
chain is fixed:

```
Business Capability  →  Domain  →  Module  →  Code
```

New modules are created under exactly one capability; a module that cannot be
placed in a capability either belongs in a new capability (requires an ACR) or
is over-reaching. This is the product map that Phase 2 organizes teams around
and that the frontend navigation reflects.

## 2. The frozen capability set

The closed set of eleven capabilities. Adding or merging a capability requires
an ACR plus a Constitution §1 amendment review.

| Id | Capability | One-line purpose | MVP? |
|---|---|---|---|
| C1 | Evidence Management | Ingest, validate, map, and promote audited source facts to evidence-backed claims | yes |
| C2 | Operational Modeling | Maintain the canonical versioned model of the supply chain (entities, edges, lineage) | yes |
| C3 | Graph Intelligence | Build sealed snapshots of the operational graph and answer read/traversal/impact queries | yes |
| C4 | Operational Simulation | Author and run counterfactual / projected / comparative scenarios off sealed snapshots | later |
| C5 | Decision Support | Detect signals and produce deterministic, explainable recommendations | later (signal subset MVP) |
| C6 | Decision Memory | Record human decisions, linking them to the inputs + rationale that produced them; close the feedback loop with outcomes | MVP subset |
| C7 | ML Platform | Bounded, review-gated modeling: synthetic data, features, registry, shadow inference, calibration, promotion | scaffolding only |
| C8 | Platform Administration | Tenant, user, workspace, policy, schema registry, audit, job administration | yes (subset) |
| C9 | Identity & Security | Authentication, authorization, isolation, audit integrity, sandbox, threat control ownership | yes |
| C10 | Observability | Metrics, logs, traces, audit, health, SLI/SLO, alerting — the platform visible to itself and operators | yes |
| C11 | Developer Platform | The engineering surface: repos, local dev, CI/CD, plugin SDK, contract tests, doc tooling | yes |

## 3. Capability → Domain → Module mapping (frozen)

This is the authoritative mapping. Every module from `01-architecture.md` §7
appears exactly once; cross-cutting foundation modules map to the capability
that consumes them most, with shared-component caveats noted.

| Capability (Domain) | Backend module(s) | Frontend feature | Notes |
|---|---|---|---|
| **C1 Evidence Management** | `ingestion`, `resolution` (claim/conflict/review), parts of `audit` (evidence events) | `uploads`, `evidence`, `claims`, `conflicts`, `reviews` | Foundation flow MVP. Owns claim→evidence lineage. |
| **C2 Operational Modeling** | `persistence`, `domain` | `entities` | Canonical entity + attribute envelopes; versioned appends. |
| **C3 Graph Intelligence** | `graph` | `graph`, `snapshots` | Adjacency, snapshots, diffs, traversal, impact, temporal. |
| **C4 Operational Simulation** | `intelligence.scenarios` | `scenarios` (later) | Branch snapshots + assumptions + comparatives. |
| **C5 Decision Support** | `intelligence.signals`, `intelligence.recommendations` | `signals` (later), `recommendations` (later) | Deterministic signals + recs; references operational `Event` entity. |
| **C6 Decision Memory** | `decisions` | `decisions` (later) | DecisionRecord + outcomes + revert; first entry is readiness `no_action`. |
| **C7 ML Platform** | `ml` | `models` (later) | `ml_*` writes only. No canonical/graph/audit grants. |
| **C8 Platform Administration** | `admin`, `workspace`, `jobs` | `admin` | Tenant/user/policy/audit/job admin. |
| **C9 Identity & Security** | `auth` | `auth`, read-only enforcement in all features | RBAC + RLS + MFA + sandbox + audit integrity. Functional/`api` thin layer for permission checks. |
| **C10 Observability** | `foundation` (logging/telemetry parts), `audit` (audit integrity parts) | (no dedicated feature; admin dashboards) | OTel shipper; metric/log/trace fan-out; audit verifier. |
| **C11 Developer Platform** | n/a (no runtime module; engineering surface) | n/a | Repo, CI, plugin SDK, contract tests, doc tooling. |

### Shared foundation module allocation
`foundation` (ids, time, crypto, config, errors, telemetry, logging) is a
shared component, not a single-capability module. For mapping discipline:
- **Telemetry/logging parts** belong to C10 Observability.
- **Config loading** belongs to C8 Platform Administration (config registry is the
  source of truth; runtime loaders are a shared stack accessor).
- **Crypto/ids/errors** are shared utilities with no owning capability; a module
  needing one imports it without owning it. ACRs are not needed for adding a
  utility to `foundation`; a new utility requires a unit test in `foundation.tests`
  before merge (`10` §3).

## 4. Capability definitions (detail)

### C1 — Evidence Management
The capability that turns external supply-chain data into audited, evidence-
backed claims ready for canonicalization. Outcome: a closed pipeline from
upload to human-reviewed canonical attribute. KPIs: time-to-claim, conflict
backlog, evidence integrity (chain verification pass rate). Functional
boundaries: the only writer of `ingest.*`, `claims.*`, `conflicts.*`,
`reviews.*`.

### C2 — Operational Modeling
The capability that maintains the canonical, versioned, scoped representation
of the supply chain world (entities from `02-ontology.md`). Outcome: a stable
canonical id space per workspace with full attribute history. Functional
boundaries: the only writer of `canonical.*`; never owns graph adjacency.

### C3 — Graph Intelligence
The capability that materializes the operational graph into sealed snapshots and
answers graph queries. Outcome: a tamper-evident, replayable snapshot chain per
workspace. Functional boundaries: the only writer of `graph.*`; reads
canonical via a read path, never directly writes canonical.

### C4 — Operational Simulation
The capability that branches the graph into counterfactual/projected/comparative
scenarios without touching the mainline. Outcome: sealed branch snapshots with
explicit assumptions. Functional boundaries: writes to `graph.snapshot`
metadata and `intelligence.scenarios`; mainline remains untouched.

### C5 — Decision Support
The capability that detects signals from sealed snapshots and generates
deterministic, explainable recommendations. Outcome: typed signals and
recommendations with non-empty evidence refs. Functional boundaries: writes to
`intelligence.signals`/`intelligence.recommendations`; references operational
`Event` nodes but never creates edges outside its own scope.

### C6 — Decision Memory
The capability that records human decisions and closes the loop with outcomes.
Outcome: a complete decision timeline per workspace; the readiness `no_action`
decision is the first entry. Functional boundaries: writes to
`decisions.decisions` and `decisions.outcomes`; cannot alter canonical/graph
facts beyond what the recorded decision authorizes.

### C7 — ML Platform
A bounded modeling capability producing review-gated candidates. Outcome: signed
model artifacts and candidate claims with `confidence ≤ 0.5`. Functional
boundaries: writes only `ml.*`; cannot emit decisions or canonical facts.

### C8 — Platform Administration
The capability that lets admins administer tenants, users, workspaces,
policies, the schema registry, audit log, and jobs. Outcome: correct
configuration and policy lifecycle. Functional boundaries: the only writer of
`iam.*` administration tables, `schema_registry.policy_versions`, `jobs.*`
metadata; cannot write canonical/graph/facts.

### C9 — Identity & Security
The capability that authenticates and authorizes every request and enforces
isolation and audit integrity. Outcome: zero cross-tenant/workspace leakage
and an unbroken audit hash chain. Functional boundaries: owns `auth.*` and
audit integrity; RLS policies are co-owned with the persistence module, but
policy *changes* are owned by C9 and require a security reviewer.

### C10 — Observability
The capability that makes the platform visible to itself and operators.
Outcome: SLI/SLO coverage and alert coverage for every other capability.
Functional boundaries: owns the OTel export pipeline, the audit verifier, and
the health endpoints; read-only across operational data.

### C11 — Developer Platform
The capability that engineers use to build, test, and extend Cortex. Outcome:
fast local dev, reproducible CI, and a stable plugin/contract surface. Formal
boundary: out of runtime scope; it governs tooling, plugin SDK, and the repo's
engineering surface, feeding back into all capabilities via CI gates.

## 5. Capability dependencies (frozen)

Allowed capability dependencies form a directed acyclic graph. A capability
may only depend on capabilities listed beneath it.

```
C1 Evidence Management
   depends on: C2 (canonical ids), C9 (authn/z on upload/review), C10 (log/trace)
C2 Operational Modeling
   depends on: C9, C10
C3 Graph Intelligence
   depends on: C2, C9, C10
C4 Operational Simulation
   depends on: C3, C9
C5 Decision Support
   depends on: C3, C4 (optional), C7 (optional candidates), C9, C10
C6 Decision Memory
   depends on: C3, C5, C9, C10
C7 ML Platform
   depends on: C3 (read-only snapshots), C9, C10 ; NO dependency on C5/C6 (one-way)
C8 Platform Administration
   depends on: C9, C10
C9 Identity & Security
   depends on: C10
C10 Observability
   depends on: foundation only
C11 Developer Platform
   depends on: all (tooling integrates with all capabilities)
```

Forbidden cycles: C5/C6 may not depend on C7 as a source of truth (C7 feeds
candidates only, and the dependency is optional and one-way). C4 (Simulation)
may not write to C3 mainline (it forks sealed snapshots, never mutates them).

## 6. Capability ownership model

Each capability has a single owning team in Phase 2+, named in the
`12-phase-1-acceptance.md` sign-off and refreshed each release. Cross-capability
work requires a recorded hand-off (an ACR for shared contracts). The capability
owner is accountable for the capability's negative tests
(`13-constitution.md` §6) and its SLOs (`22-observability-model.md`).

## 7. Frontend alignment

Frontend features map 1:1 to capabilities — this is already the case in
`07-frontend-architecture.md` §4 via the API-group alignment. The capability
set is therefore the navigation taxonomy at the top level; sub-navigation
inside a capability follows the entity or workflow breakdown. No frontend
feature is "homeless"; a feature without a capability is rejected at design.

## 8. Phase boundaries

The Phase boundaries in `12-phase-1-acceptance.md` §5 are inherited here. New
capabilities are added only via ACR plus Constitution review. Phase 2 ships
the MVP rows above; later-phase rows are scaffolded, not implemented.

## 9. Frozen decisions summary

- Eleven closed capabilities; every module maps to exactly one.
- Capability → Domain → Module → Code is the only decomposition chain.
- Capability dependencies form a DAG; the C7→C5/C6 path is one-way candidates only.
- Each capability has a single owning team accountable for its tests and SLOs.
- Frontend features align 1:1 to capabilities; orphan features are rejected.
