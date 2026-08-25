# Contributing to Cortex

Thank you for your interest in contributing to Cortex! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Architecture](#architecture)

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Prioritize user safety and data integrity

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/cortex.git`
3. Set up the development environment (see README.md)
4. Create a branch: `git checkout -b feature/your-feature-name`

## Development Workflow

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker and Docker Compose
- PostgreSQL 16+ (or use Docker Compose)

### Setup

```bash
# Start all services with Docker Compose
make docker-up

# Or set up manually
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
pip install -e ".[dev]"

cd ../frontend
npm install
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/test_golden_dataset.py -v
```

### Linting and Type Checking

```bash
make lint
make format
make typecheck
```

## Coding Standards

### Python

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use type hints for all function signatures
- Write docstrings for public APIs
- Keep functions focused (< 50 lines preferred)
- Use descriptive variable names

```python
# Good
async def emit_domain_event(
    event: DomainEvent,
    correlation_id: str,
) -> None:
    """Emit a domain event with validation and dispatch."""
    ...

# Bad
def emit(e, corr):
    ...
```

### TypeScript / React

- Use TypeScript for all new code
- Follow [React best practices](https://react.dev/learn)
- Use functional components with hooks
- Implement proper error boundaries
- Add loading states for async operations

### File Organization

```
backend/
  app/
    common/      # Shared utilities (UUIDv7, errors, enums)
    infrastructure/  # DB, S3, logging, telemetry
    modules/     # Business logic modules
    api/         # REST endpoints

frontend/
  src/
    app/         # Next.js app router pages
    components/  # Reusable UI components
    lib/         # Utilities and API clients
    types/       # TypeScript types (auto-generated)
```

## Testing

### Writing Tests

- Use `pytest` for backend tests
- Use `jest` and `React Testing Library` for frontend tests
- Write tests before fixing bugs (regression tests)
- Aim for meaningful coverage, not 100% for its own sake

### Test Categories

- **Unit tests**: Test individual functions/classes in isolation
- **Integration tests**: Test module interactions
- **End-to-end tests**: Test full user workflows

### Running Tests

```bash
# Backend
pytest tests/ -v --tb=short

# Frontend
npm run test
```

## Submitting Changes

### Pull Request Process

1. Ensure all tests pass: `make test`
2. Run linting: `make lint && make typecheck`
3. Update documentation if needed
4. Add a changelog entry
5. Submit PR with a clear description

### PR Title Format

```
<type>(<scope>): <description>

Examples:
- feat(compiler): add conflict resolution workflow
- fix(quality): correct timeliness calculation edge case
- docs: update architecture diagrams
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add readiness computation endpoint

- Implement POST /api/v1/readiness/batches/{id}
- Add ReadinessAssessment database model
- Include audit event logging
```

## Architecture

### Key Principles

1. **Evidence-first**: Every claim has provenance
2. **Immutable uploads**: Content-addressed storage with SHA-256
3. **Append-only audit**: INSERT-only audit events
4. **Deterministic readiness**: Rules-based conflict detection
5. **Human review required**: Conflicts flagged for review
6. **Observability by default**: Request/Correlation/Trace IDs in all logs

### Module Dependencies

```
API Layer
    ↓
Services (Modules)
    ↓
Infrastructure (DB, S3, External)
```

**Dependency Rules:**
- API layer cannot import infrastructure directly
- Services cannot import API routers
- Infrastructure cannot import business logic

### Data Flow

```
Upload → Validate → Profile → Map → Extract Claims → Detect Conflicts → Compute Readiness
   ↓         ↓          ↓        ↓         ↓              ↓              ↓
Audit    Storage   Metrics   Schema   Evidence      Flags         Assessment
```

## Questions?

- Check existing [documentation](docs/)
- Search [closed issues](https://github.com/cortex/cortex/issues?q=is%3Aissue+is%3Aclosed)
- Open a new issue for discussion