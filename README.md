# Cortex

## Unified Enterprise Intelligence & Action Platform

Cortex connects fragmented enterprise data, builds trusted operational context, produces evidence-backed
decisions, and coordinates policy-governed workflows and actions.

> **Understand your enterprise. Trust your decisions. Coordinate your actions.**

The initial commercial wedge is supplier-disruption and operational-impact decision intelligence for
operations-intensive manufacturers. The long-term platform spans data readiness, World State, intelligence and
simulation, evidence and decisions, orchestration, governance and execution, memory and learning, and the SaaS
control plane.

## Current implementation direction

- PostgreSQL-backed World State is the business authority.
- `/api/v1/nexus/*` is the canonical persistent decision surface.
- Evidence, permissions, approvals, durable events, and audit records are product capabilities.
- Agents, models, Redis, and orchestration never become alternative business authorities.
- The private-beta goal is one reliable supplier-disruption decision loop on fresh customer data.

## Repository map

- `backend/` — FastAPI application, domain modules, migrations, workers, and tests
- `frontend/` — Next.js application and authenticated operational workspace
- `docs/` — architecture, launch records, product charter, and roadmap
- `design_partner/` — pilot, integration, and customer-validation materials
- `k8s/`, `docker-compose*.yml` — deployment and local infrastructure

## Product planning

Read [`docs/PRODUCT_VISION_AND_ROADMAP.md`](docs/PRODUCT_VISION_AND_ROADMAP.md) for the product vision,
principles, capability map, MVP boundary, value proposition, architecture reconciliation, and phased roadmap.
The implementation charter treats the open Nexus productization work as candidate input for controlled integration;
it is not a wholesale merge target.

Release Candidate 0 is defined in [`docs/RC0_ACCEPTANCE.md`](docs/RC0_ACCEPTANCE.md). The release gate is a fresh,
authenticated supplier-disruption journey through data, World State, evidence, scenarios, decision, approval, and
trace reconstruction.

## Development

```powershell
docker compose up
```

Backend setup, lint, typecheck, tests, migrations, and environment variables are documented in
[`backend/AGENTS.md`](backend/AGENTS.md).

```powershell
cd backend
pytest tests/ -v --tb=short
ruff check .
mypy app
```

```powershell
cd frontend
npm ci
npm run typecheck
npm run test
npm run build
```

## Status

The repository is in controlled productisation. The stable supplier-disruption foundation is being graduated into
one canonical customer path. Advanced orchestration, mobile/voice, and broad agent capabilities remain staged until
their contracts, migrations, security controls, and acceptance evidence are reviewed individually.
