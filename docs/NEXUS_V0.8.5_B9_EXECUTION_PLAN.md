# Nexus v0.8.5 — B9 Deployment & Recovery Execution Plan

## Objective

Prove that Nexus can be deployed, restarted, recovered, and restored without losing or corrupting authoritative operational state.

## Preconditions

- B4 realtime is merged on `main@ca39e6a`.
- B3/B6 frontend canonical rewire must be merged before customer-facing release validation.
- PostgreSQL remains authoritative.
- Redis remains transport/cache infrastructure, never the source of truth.
- Transactional outbox remains the source for durable realtime delivery.

## B9a — Production topology

Minimum launch topology:

```text
HTTPS / load balancer
        ↓
   API instances (2+)
        ↓
 PostgreSQL (HA where available)
        ├── Redis
        ├── object storage
        └── worker / outbox relay
```

Do not introduce Kafka or a service mesh for v0.8.5.

Acceptance:

- all runtime dependencies are explicitly declared;
- no production credential fallbacks;
- secrets come from deployment configuration/secret storage;
- API and worker processes have health/readiness checks;
- graceful shutdown is verified.

## B9b — Staging deployment

Deploy the exact release candidate configuration into staging.

Validate:

1. DNS and HTTPS;
2. CORS/origin policy;
3. frontend API base URL;
4. PostgreSQL connectivity;
5. Redis connectivity;
6. object storage connectivity;
7. migration execution;
8. API readiness;
9. worker/outbox-relay readiness;
10. realtime SSE/WS connectivity.

Evidence to retain:

- deployment commit SHA;
- migration revision;
- container/image versions;
- health/readiness results;
- configuration fingerprint without secret values.

## B9c — Database migration rehearsal

Run:

```text
clean/staging database
→ alembic upgrade head
→ application smoke tests
→ downgrade rehearsal where supported
→ re-upgrade head
```

Do not perform destructive downgrade tests against the only staging database containing customer-like data.

Verify:

- schema revision;
- required indexes/constraints;
- outbox sequence authority;
- onboarding/auth tables;
- model/provenance tables.

## B9d — Backup / restore

Create a real PostgreSQL backup from a known staging snapshot.

Then restore into a clean database and verify:

```text
backup
→ clean database
→ restore
→ migrations/schema integrity
→ World State
→ signals/risks/forecasts
→ scenarios
→ decisions
→ approvals/execution/outcomes
→ evidence/NexusTrace
→ realtime replay from durable state
```

Measure:

- backup duration;
- restore duration;
- data validation duration;
- RPO;
- RTO.

Acceptance:

- no missing authoritative records;
- no orphaned decision/evidence references;
- World State versions remain consistent;
- evidence references remain valid.

## B9e — Failure / restart rehearsal

Run each scenario independently and record before/after observations.

### API restart

Expected:

- in-flight safe failure semantics;
- process returns healthy;
- persistent state unchanged;
- clients reconnect normally.

### Worker restart

Expected:

- no permanent job loss;
- durable work resumes;
- duplicate processing is idempotent where applicable.

### Outbox relay restart

Expected:

- uncommitted events do not appear;
- committed unpublished events are reclaimed;
- sequence continuity remains valid.

### Redis restart

Expected:

- Redis transport loss does not delete authoritative state;
- realtime catches up from durable replay after recovery.

### Database connection interruption

Expected:

- failed transaction rolls back;
- no partial governance state is persisted;
- service recovers after database availability returns.

### Browser/WS/SSE disconnect

Expected:

- client reconnects;
- duplicate events are ignored;
- sequence gaps trigger resync;
- stale UI is replaced by authoritative state.

## B9f — Customer rehearsal

Use a clean customer-like tenant/workspace and perform:

```text
signup
→ workspace
→ upload data
→ World State
→ signal/risk
→ forecast
→ scenario
→ decision
→ approval
→ execution
→ outcome
→ evidence
```

Restart API/worker and refresh the browser at multiple points.

Acceptance: the same authoritative trace remains recoverable and internally consistent.

## B9g — Release evidence and rollback

Produce an after-action report containing:

- exact release SHA;
- deployment timestamps;
- migration revision;
- backup artifact identifier;
- restore result;
- measured RPO/RTO;
- each failure drill result;
- known deviations;
- rollback decision;
- owner and follow-up for every failed gate.

Rollback must be rehearsed at least once in staging.

## Launch gate

B9 is green only when:

```text
[ ] staging deployment succeeds
[ ] HTTPS/DNS/secrets are correct
[ ] migrations are reproducible
[ ] backup completes
[ ] clean restore succeeds
[ ] restored World State validates
[ ] restored decisions validate
[ ] restored evidence validates
[ ] API restart passes
[ ] worker restart passes
[ ] outbox relay restart passes
[ ] Redis restart passes
[ ] DB interruption passes
[ ] realtime reconnect/gap recovery passes
[ ] rollback procedure is rehearsed
[ ] customer rehearsal passes
```

B10 and RC freeze must not begin until this checklist is green.