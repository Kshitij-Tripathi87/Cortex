# Cortex Nexus — Staging Architecture

Status: implementation baseline for v0.8.5 staging

## Objective

Create a production-shaped staging environment that exercises the same application boundaries intended for customer production without introducing unnecessary distributed-system complexity.

## Architecture

```text
                         HTTPS / DNS
                              |
                    Cloud Load Balancer
                              |
                +-------------+-------------+
                |                           |
          Next.js Web                    API x2+
                                            |
                    +-----------------------+------------------+
                    |                       |                  |
              PostgreSQL                Redis          Object Storage
             (authoritative)         (cache/events)      (datasets/artifacts)
                    |                       |
                    +-----------+-----------+
                                |
                      Worker / Outbox Relay
                                |
                     Simulation / ML Jobs
```

## Service roles

### Web

- Serves the authenticated Nexus application.
- Uses only the canonical Nexus API surface.
- No client-side authority for workspace, decisions, forecasts, risk, approval, or execution.

### API

- Horizontally scalable and stateless at the process level.
- Reads and writes authoritative state through PostgreSQL.
- Enforces authentication, tenant/workspace authorization, policy, decision lifecycle, and request correlation.
- Emits durable outbox records in the same transaction as consequential state changes.
- May run an in-process outbox fast path, but staging includes a dedicated relay to exercise the deployment boundary.

### PostgreSQL

- System of record for World State and consequential product state.
- No staging database is shared with local development.
- Backups and restore are exercised before RC.

### Redis

- Low-latency transport/cache/coordination only.
- Never authoritative for World State or decision state.
- Loss of Redis must not corrupt committed PostgreSQL state.

### Object storage

- Stores uploaded datasets, derived artifacts, model artifacts, and large evidence payloads where appropriate.
- Objects are referenced by durable identifiers from PostgreSQL.

### Worker

- Processes asynchronous application jobs.
- Must be restart-safe and idempotent.
- Never performs an unapproved consequential action.

### Outbox relay

- Reads committed outbox records from PostgreSQL.
- Publishes to Redis.
- Uses existing lease/claim/retry semantics.
- Safe to restart and safe to scale within the existing outbox invariants.

### Simulation / ML jobs

- Operate on versioned World State snapshots.
- Digital Twin mutations never write production World State.
- Model inference carries model/version/feature/world-state provenance.

## Staging invariants

1. World State is authoritative in PostgreSQL.
2. Realtime is derived from committed state.
3. Redis loss cannot become data loss.
4. API instances are interchangeable.
5. Worker restart is safe.
6. Duplicate events are harmless to consumers.
7. Cross-tenant and cross-workspace requests fail closed.
8. Every consequential decision can be traced through NexusTrace.
9. Digital Twin operations remain isolated from production state.
10. Secrets are supplied by the deployment platform; repository files contain no working credentials.

## Initial staging data path

```text
CSV upload
  -> object storage
  -> ingestion job
  -> schema discovery / validation / profiling
  -> entity resolution / canonicalization
  -> World State transaction
  -> durable dataset + world-state version
  -> signal/risk/forecast generation
  -> operational UI
```

Initial dataset families:

- orders
- products
- inventory
- suppliers
- shipments

## Golden Path staging test

A fresh staging workspace must be able to complete:

```text
create workspace
-> upload fresh dataset
-> inspect validation result
-> create World State version
-> observe signal
-> inspect impact/root cause
-> generate/view forecast + risk
-> create scenario
-> compare options
-> create governed decision
-> policy check
-> approve
-> record/execute governed action
-> record outcome
-> inspect NexusTrace/evidence
-> reconnect client
-> verify authoritative state remains intact
```

## Failure tests

Staging must explicitly rehearse:

- API instance restart
- worker restart
- outbox relay restart
- Redis interruption
- PostgreSQL connection interruption
- WebSocket/SSE reconnect
- duplicate event delivery
- event gap/resync
- stale decision submission
- authorization failure
- rollback

Expected outcome: no silent state loss, no cross-tenant leakage, no bypass of governance, and eventual recovery from transient infrastructure failure.

## Environment separation

| Concern | Local | Staging | Production |
|---|---|---|---|
| PostgreSQL | container | managed dedicated | managed dedicated |
| Redis | container | managed dedicated | managed dedicated |
| Object store | MinIO | dedicated bucket/account | dedicated bucket/account |
| API | local | 2+ replicas | 2+ replicas |
| Worker | local | dedicated service | dedicated service |
| Outbox relay | local/in-process | dedicated service | dedicated service |
| TLS | optional | required | required |
| Secrets | local env | secret manager | secret manager |
| Backups | optional | mandatory | mandatory |
| Monitoring | local logs | metrics + logs + alerts | full observability |

## Cloud-provider mapping

The architecture is provider-neutral. A reference AWS deployment is:

- ECS/Fargate or equivalent for web/API/worker/relay containers
- RDS PostgreSQL
- ElastiCache Redis
- S3 object storage
- Application Load Balancer
- Secrets Manager / Parameter Store
- CloudWatch plus application metrics

Equivalent managed services on Azure or GCP are acceptable without changing the application architecture.

## Explicitly excluded from staging launch

- Kafka
- service mesh
- multi-region databases
- microservice decomposition
- autonomous production execution
- autonomous model retraining

Staging exists to prove the Nexus product loop and operational resilience, not to maximize infrastructure complexity.
