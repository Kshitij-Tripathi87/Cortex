# ADR-005: Docker Compose for Deployment

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge needs to be deployable to a single VM for a design partner
pilot. The existing `k8s/` folder suggests Kubernetes was previously
considered.

## Decision

The MVP wedge is deployed via **Docker Compose** on a single VM. Kubernetes is
**not** used in v1.

The deployment stack:
- `backend` — FastAPI container
- `frontend` — Next.js container (production build, served via Node)
- `postgres` — PostgreSQL 15+ with native UUID
- `redis` — Redis 7+
- `minio` — S3-compatible object storage (single-node)

## Consequences

**Positive**:
- One `docker-compose.yml`, one VM, one deployable stack.
- No Kubernetes operational burden (no Helm charts, no cluster upgrades, no
  ingress controllers).
- Pilot customer can run the same stack on their own infrastructure for
  evaluation.
- Lower cognitive load on engineering during MVP development.

**Negative**:
- No horizontal scaling. Not needed for MVP (single design partner).
- No zero-downtime deploys. Acceptable for MVP — design partner tolerates a
  few minutes of downtime during a deploy.

## Migration Plan

Compose is the deployment unit for the entire MVP phase. If a customer
demands Kubernetes, Phase 2 wraps the existing containers with a Helm chart.
The container images do not change.

## Alternatives Considered

- **Kubernetes (EKS/GKE)**: Operational cost not justified by MVP scale.
  Rejected.
- **Bare-metal deploys**: Couples deployment to operator knowledge. Rejected.
- **PaaS (Fly.io, Railway)**: Lock-in concerns. Rejected for MVP portability.

## References

- MVP execution plan Part 4 (deployment)
