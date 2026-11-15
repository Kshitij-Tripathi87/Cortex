# Cortex Nexus v0.8.5 — Product Implementation Plan

> Status: execution plan grounded in `main@ca39e6a` after B4 realtime. This document does not change the authoritative architecture or reopen completed slices.

## 1. Product outcome

Ship one trustworthy customer workflow for supply-chain decision intelligence:

```text
customer signup
→ organization/workspace
→ ingest operational data
→ versioned World State
→ signals + risk + forecast
→ scenario comparison
→ governed decision
→ human approval
→ execution record
→ outcome
→ evidence / NexusTrace
```

The product must derive customer-visible facts from authoritative persisted state. No demo singleton, fabricated metrics, client-side authority, or UI-only governance.

## 2. Non-negotiable invariants

1. World State is the single authoritative operational state.
2. Digital Twin is a derived isolated branch/snapshot and never mutates production World State.
3. Agents and UI can propose or request work; server-side governed infrastructure controls execution.
4. Every consequential object remains traceable through NexusTrace: signal → world → model/forecast/risk → scenario → decision → approval → execution → outcome → evidence.
5. Realtime is derived from committed state through the transactional outbox and is never the source of truth.
6. Tenant/workspace isolation is enforced server-side and fails closed.

## 3. Current baseline

`main@ca39e6a` contains:

- authenticated onboarding/auth flows from B1/B2;
- canonical Nexus backend golden-path endpoints from B3;
- durable outbox / Redis / SSE / WebSocket realtime from B4;
- governed model registry, inference, provenance and truth-loop capabilities from v0.8.4;
- production-oriented health, audit, migration, and CI foundations.

Open dependency: the B3/B6 frontend canonical rewire remains unmerged and must be reconciled before customer UI launch validation.

## 4. Product workstreams

### P0 — Customer-facing integrity

**B3/B6 frontend rewire**

- one authenticated API client;
- canonical `/nexus/*` data plane;
- workspace identity from trusted auth context;
- remove demo risks/SKUs/session/autoload;
- gate legacy `/workspace/*` demo surfaces;
- surface request/correlation identifiers;
- golden-path + role-gating E2E.

Exit gate: an authenticated user can complete the operational workflow without hitting legacy demo data paths.

### P0 — Ingestion and World State

Use one reliable launch ingestion path first, preferably CSV.

Supported initial dataset families:

```text
orders
products
inventory
suppliers
shipments
```

Pipeline:

```text
upload
→ schema discovery
→ validation
→ profiling
→ entity resolution
→ canonicalization
→ World State version
```

UI must expose processed rows, warnings/errors, entities resolved, dataset identifier and resulting World State version.

Exit gate: fresh customer data reaches persisted World State with a traceable dataset/version relationship.

### P0 — Decision Room / NexusTrace

The primary operational UI should answer:

- What changed?
- What is affected?
- Why does it matter?
- What options exist?
- What does simulation predict?
- What is recommended?
- What policy applies?
- Who must approve?
- What happened afterward?

Every major view consumes canonical identifiers instead of guessing relationships client-side.

Exit gate: Signal → Impact → Root Cause → Options → Simulation → Recommendation → Approval → Outcome is navigable from one trace.

### P0 — Realtime

Consume the existing durable event fabric for collaborative UI state:

```text
forecast.generated
signal.created
risk.updated
scenario.created

decision.updated
approval.recorded
execution.completed
outcome.recorded
```

Client behavior:

- normal event → apply;
- duplicate → ignore;
- gap → resync;
- reconnect → catch up;
- stale local state → reload authoritative state.

Exit gate: reconnect/gap/replay tests pass against real persisted mutations.

### P0 — Security and tenancy

Validate:

- expired/replayed session behavior;
- logout behavior;
- viewer/operator/admin role boundaries;
- cross-tenant access;
- cross-workspace access;
- decision/evidence/forecast object authorization;
- realtime tenant/workspace boundaries;
- fail-closed error handling.

Exit gate: no server-side path permits cross-tenant or unauthorized object access.

## 5. B9 — Production operations

### B9a — Production topology

Target minimum topology:

```text
HTTPS/load balancer
→ API instances
→ PostgreSQL
→ Redis
→ object storage
→ worker / outbox relay
```

Do not add Kafka or microservices solely for launch.

### B9b — Deployment

Prove:

- staging environment;
- HTTPS;
- secrets supplied externally;
- DNS/configuration validated;
- readiness/health endpoints;
- graceful shutdown;
- database migrations;
- worker startup/supervision;
- rollback procedure.

### B9c — Backup / restore

Perform an actual clean restore, not a documentation-only check:

```text
backup
→ clean database
→ restore
→ migration/integrity validation
→ verify World State
→ verify decisions
→ verify evidence
```

Record measured RPO/RTO and retention.

### B9d — Failure rehearsal

At minimum:

- API restart;
- worker restart;
- outbox-relay restart;
- Redis restart/outage;
- DB connection interruption;
- realtime disconnect/reconnect;
- sequence gap;
- stale decision;
- deployment rollback.

Exit gate: no data corruption and recoverable service behavior.

## 6. B10 — SaaS product layer

### Billing

Keep launch billing minimal:

```text
subscription
→ entitlements
→ workspace limits
→ backend enforcement
```

Do not rely on frontend-only limit checks.

### Admin

Minimum internal support surface:

- organizations;
- users/workspaces;
- ingestion jobs/failures;
- decision volume;
- model health;
- event/outbox backlog;
- service health.

### Email

Minimum transactional paths:

- password reset;
- onboarding/invitation;
- critical system notifications.

## 7. ML productization

Keep the existing governed ML architecture as the basis:

```text
approved champion model
→ versioned inference
→ prediction provenance
→ observation
→ Truth Loop
→ drift
→ human-governed promotion / rollback
```

No autonomous retraining at launch.

A prediction must carry enough provenance to identify model/version, feature fingerprint, forecast/prediction identifier and World State version.

## 8. Vanessa productization

Launch Vanessa as a grounded investigation interface, not an autonomous authority:

```text
question
→ intent/entity extraction
→ authoritative Nexus tools
→ persisted state/evidence
→ structured answer
→ traceable evidence
```

Every material answer should be explainable from authoritative Nexus data.

## 9. Observability

Critical requests and mutations should expose:

```text
request_id / correlation_id
workspace_id
entity/decision identifiers
world_state_version
event identifiers
model/version where applicable
```

Track:

- API latency and errors;
- DB health;
- Redis health;
- worker/outbox backlog;
- realtime reconnect/gap rates;
- inference latency/errors;
- decision lifecycle failures.

## 10. Validation program

### Pre-merge

- typecheck;
- lint;
- backend tests;
- frontend unit tests;
- OpenAPI/type generation checks;
- security/secrets/dependency checks.

### Release candidate

- full Golden Path E2E;
- role-gating E2E;
- realtime replay/gap/reconnect;
- fresh-data ingestion;
- decision approval/execution/outcome;
- evidence/NexusTrace integrity;
- backup/restore;
- migration up/down;
- load tests at 50/100/250 concurrent operations;
- API/worker/Redis/DB/realtime chaos drills.

## 11. Release gates

Release only when all are true:

```text
[ ] authenticated frontend uses canonical Nexus data
[ ] fresh customer data reaches World State
[ ] signal/risk/forecast are derived from persisted state
[ ] scenario simulation works on a World State snapshot
[ ] governed decision approval path works
[ ] execution/outcome are persisted
[ ] NexusTrace is complete
[ ] realtime replay/resync/reconnect passes
[ ] tenant/workspace isolation passes
[ ] production staging deployment passes
[ ] backup + clean restore passes
[ ] observability identifies failures
[ ] billing/entitlements enforce limits server-side
[ ] support/admin path exists
[ ] transactional email works
[ ] security/load/chaos gates pass
[ ] RC rehearsal succeeds on fresh customer data
```

## 12. Sequencing

```text
B3/B6 frontend rewire
        ↓
Golden Path validation
        ↓
B9 deployment + DR
        ↓
security + load + chaos hardening
        ↓
B10 billing / admin / email
        ↓
fresh-customer production rehearsal
        ↓
v0.8.5-rc1
        ↓
pilot launch
```

## 13. Intentionally deferred

Do not block v0.8.5 on:

- Kafka adoption;
- microservice decomposition;
- multi-region;
- service mesh;
- autonomous agent execution;
- autonomous retraining;
- advanced ontology expansion;
- mobile;
- broad third-party integrations;
- full SSO/SAML unless a launch customer requires it;
- major GNN/RL expansion.

## 14. Definition of product-ready

Nexus is product-ready when a real customer can:

1. sign up and enter a workspace;
2. import operational data without engineering help;
3. see a real, versioned operational state;
4. investigate a material signal with evidence;
5. compare a scenario;
6. receive a grounded recommendation;
7. approve a governed decision;
8. see the recorded outcome;
9. follow the complete NexusTrace;
10. return later and find the same authoritative state after restarts or recovery.

The objective is not feature breadth. It is a trustworthy, repeatable operational workflow.