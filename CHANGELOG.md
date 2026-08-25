# Changelog

All notable changes to Cortex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Docker Compose stack for local development (PostgreSQL, Redis, MinIO, Prometheus, Grafana)
- GitHub Actions workflows: lint, test, typecheck, security, build
- OpenAPI schema generation with TypeScript type inference
- Makefile for unified development commands
- `.env.example` for environment variable documentation

### Changed
- None

### Deprecated
- None

### Removed
- None

### Fixed
- None

### Security
- None

---

## [0.2.0] - 2026-07-19

### Added
- RC-1 Enterprise Evidence Platform certification
- Golden Dataset Regression Suite (84 test cases)
- Domain Event Dispatch with async validation
- Data Quality Framework (6 dimensions + trust score)
- Row-Level Security with PostgreSQL policies
- UUIDv7 request IDs with server-side generation
- Frontend audit pages with real backend data
- Operational Graph module
- Propagation Engine foundation
- Scenario Engine foundation
- Recommendation Engine foundation
- Decision Memory foundation

### Security
- Secrets scanner for AWS/GitHub keys
- RLS enforcement at database level
- Content-addressed storage with SHA-256 dedup

---

## [0.1.0] - 2026-06-01

### Added
- Initial Phase 2 architecture
- FastAPI backend with async SQLAlchemy
- Next.js 14 frontend with TypeScript
- PostgreSQL with Alembic migrations
- Immutable audit event logging
- Evidence claim extraction
- Conflict detection and resolution workflow
- Readiness calculation engine