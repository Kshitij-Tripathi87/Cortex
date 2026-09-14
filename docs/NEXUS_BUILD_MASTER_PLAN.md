# Cortex Nexus — Production Build Master Plan

## Mission

Build Cortex Nexus as a production-grade, multi-tenant operational decision platform for supply-chain teams. The first launchable wedge is inventory and supply-chain decision intelligence; the underlying platform remains capable of expanding into procurement, supplier, shipment, and planning workflows.

The product is autonomous in investigation, analysis, simulation, and proposal generation. Consequential actions remain governed by policy and human authorization unless an explicit customer policy later permits bounded automation.

## 1. Product contract

The first customer-visible loop is:

```text
customer
  -> workspace
  -> CSV data import
  -> schema discovery / validation / profiling
  -> canonical entities
  -> versioned World State
  -> operational graph
  -> signal detection
  -> impact + root cause
  -> probabilistic forecast + risk
  -> multi-agent analysis
  -> scenario alternatives
  -> simulation
  -> recommendation
  -> policy check
  -> human approval
  -> execution / execution record
  -> outcome
  -> evidence / NexusTrace
```

Success means this loop works on fresh customer data without demo state, hardcoded facts, or hidden client-side authority.

## 2. System architecture

```text
                           Browser
                              |
                         HTTPS / CDN
                              |
                       Load Balancer
                              |
                 +------------+-------------+
                 |                          |
              Next.js                  FastAPI x N
                                            |
                  +-------------------------+----------------------+
                  |                         |                      |
             PostgreSQL                  Redis              Object Storage
          authoritative state          transport/cache       datasets/artifacts
                  |                         |
                  +-------------+-----------+
                                |
                   Workers / Outbox Relay
                                |
                  +-------------+-------------+
                  |                           |
            ML / inference              Multi-agent runtime
            simulation jobs             investigation/proposals
```

### Authority model

- PostgreSQL is the only authoritative state store.
- Redis is never an authority.
- Object storage contains immutable or large artifacts referenced from PostgreSQL.
- Realtime events are derived after commit through the outbox.
- Digital Twin is a derived snapshot/branch and cannot mutate World State.

## 3. Multi-agent architecture

Specialists should remain domain-focused and produce structured proposals rather than directly mutating production state.

```text
                         Nexus Supervisor
                                |
              +-----------------+-----------------+
              |                 |                 |
         Procurement        Optimization       Compliance
              |                 |                 |
          Booking /        Risk / scenario     Back-office
          negotiation         analysis            evidence
              \                 |                 /
               +----------------+----------------+
                                |
                         Consensus / Critique
                                |
                         Scenario evaluation
                                |
                         Governed Proposal
                                |
                  Policy -> Human Approval -> Execute
```

Every agent turn must have:

- workspace and tenant context;
- World State version;
- bounded tool permissions;
- trace/request identifier;
- input evidence references;
- structured output schema;
- safety budget / iteration bounds;
- no direct database authority;
- no unapproved consequential side effect.

## 4. Engineering phases

### Phase 1 — Canonical customer UI

- Merge/reconcile B3/B6 frontend work.
- Remove remaining legacy demo paths from canonical flows.
- Establish authenticated workspace context.
- Make cockpit, signals, decisions, scenarios, and evidence use canonical APIs.

Exit: authenticated user can navigate the real Nexus application without demo state.

### Phase 2 — Ingestion to World State

Implement one high-quality launch ingestion flow for CSV.

Required behavior:

- upload to object storage;
- create immutable dataset record;
- schema detection;
- validation with row-level errors;
- profiling statistics;
- entity resolution;
- canonicalization;
- atomic World State version creation;
- dataset -> world-state provenance.

Exit: fresh customer dataset creates a verifiable World State version.

### Phase 3 — Operational intelligence

Connect persisted World State to:

- operational graph;
- signals;
- impact propagation;
- probabilistic forecasts;
- risk scoring;
- forecast provenance;
- Truth Loop observations.

Exit: each customer-visible metric can be traced to persisted state and model provenance.

### Phase 4 — Multi-agent decisioning

Use the existing multi-agent subsystem as a governed analysis layer.

The supervisor coordinates specialists; consensus and critique produce a structured proposal; scenarios test alternatives; policy gates consequences.

Exit: one real supply-chain problem produces a grounded multi-agent recommendation with evidence.

### Phase 5 — Decision Room

Build one operational workflow rather than many dashboards:

```text
Detect
 -> Impact
 -> Root Cause
 -> Options
 -> Simulation
 -> Recommendation
 -> Policy
 -> Approval
 -> Outcome
```

Exit: a user can understand why Nexus recommends an action and can approve or reject it from one trace.

### Phase 6 — Realtime

Consume the existing outbox/replay fabric.

Client contract:

- normal event -> apply;
- duplicate -> ignore;
- gap -> resync;
- reconnect -> catch up;
- invalidated local state -> reload authority.

Exit: replay, reconnect, gap, and duplicate tests pass against persisted mutations.

### Phase 7 — Cloud staging

Reference deployment:

- Next.js web service;
- two or more API replicas;
- dedicated worker processes;
- dedicated outbox relay;
- managed PostgreSQL;
- managed Redis;
- managed object storage;
- HTTPS load balancing;
- external secret management;
- centralized logs/metrics;
- isolated staging database and buckets.

No Kafka dependency is required for this release.

Exit: the entire golden path runs in staging on fresh data.

### Phase 8 — Reliability and security

Test:

- API restart;
- worker restart;
- relay restart;
- Redis loss;
- DB interruption;
- realtime reconnect;
- duplicate/out-of-order event delivery;
- event gap/resync;
- stale decisions;
- expired/replayed sessions;
- cross-tenant authorization;
- cross-workspace authorization;
- object-level authorization.

Exit: no silent corruption, no governance bypass, no isolation failure.

### Phase 9 — DR and RC

- real PostgreSQL backup;
- clean restore into an empty environment;
- migration rehearsal;
- World State integrity verification;
- decision/evidence verification;
- measured RPO/RTO;
- rollback procedure;
- load at 50/100/250 concurrent operations;
- fresh customer rehearsal.

Exit: release candidate is repeatable, recoverable, and auditable.

### Phase 10 — SaaS controls

Add only after the workflow is stable:

- organization/workspace administration;
- usage metering;
- backend-enforced entitlements;
- minimal billing;
- password reset/invitation/critical email;
- internal support/admin surface.

## 5. Production-grade quality bar

### Data

- idempotent ingestion;
- immutable dataset/version identifiers;
- transactional World State updates;
- no partial canonical state;
- explicit validation failures;
- durable provenance.

### API

- request IDs;
- structured errors;
- consistent 401/403/404/409 behavior;
- optimistic concurrency where needed;
- bounded timeouts;
- retry-safe mutations;
- authorization on every object boundary.

### Agents

- bounded context;
- bounded tool set;
- bounded iterations;
- deterministic policy checks;
- approval required for consequential execution;
- traceable reasoning outputs;
- no hidden side effects.

### ML

- immutable model versions;
- explicit promotion gates;
- provenance on every prediction;
- champion/rollback state;
- Truth Loop monitoring;
- no autonomous production retraining at launch.

### Realtime

- transactional outbox;
- ordered per-workspace sequence;
- durable replay;
- idempotent consumption;
- gap detection and resync;
- reconnect catch-up.

## 6. Repository delivery model

Work from feature branches off the current `main` baseline. Each phase gets:

1. implementation;
2. targeted tests;
3. integration tests;
4. CI validation;
5. mergeable PR;
6. staging verification;
7. release evidence.

Never merge deployment configuration that references a non-existent application entrypoint or provides working secret defaults.

## 7. Definition of done for v0.8.5

```text
[ ] canonical frontend is live
[ ] fresh CSV ingestion works
[ ] World State version is persisted
[ ] signal and impact are grounded in World State
[ ] forecast/risk carry provenance
[ ] multi-agent proposal is grounded and bounded
[ ] scenario simulation is isolated
[ ] governed decision lifecycle works
[ ] human approval is enforced
[ ] execution/outcome are persisted
[ ] NexusTrace is complete
[ ] realtime replay/resync/reconnect works
[ ] tenant/workspace isolation passes
[ ] staging is cloud deployed
[ ] backup/restore is proven
[ ] failure drills pass
[ ] load tests pass
[ ] observability and alerts work
[ ] entitlements enforce server-side limits
[ ] transactional auth/support email works
[ ] fresh customer rehearsal passes
```
