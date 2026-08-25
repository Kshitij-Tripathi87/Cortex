.PHONY: help dev test lint typecheck migrate seed clean docs openapi graph

help:
	@echo "Cortex — Enterprise Evidence Platform"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  dev          Start backend and frontend dev servers"
	@echo "  dev-backend  Start backend dev server only"
	@echo "  dev-frontend Start frontend dev server only"
	@echo "  test         Run backend tests"
	@echo "  test-cov     Run tests with coverage report"
	@echo "  lint         Run Ruff linter"
	@echo "  format       Run Ruff formatter"
	@echo "  typecheck    Run MyPy type checker"
	@echo "  migrate      Apply database migrations"
	@echo "  migrate-rev  Create new migration (usage: make migrate-rev MSG=\"description\")"
	@echo "  seed         Seed database with test data"
	@echo "  openapi      Generate OpenAPI schema and TypeScript types"
	@echo "  graph        Generate operational graph from evidence"
	@echo "  clean        Remove build artifacts and caches"
	@echo "  docs         Generate API documentation"
	@echo "  docker-up    Start Docker Compose stack"
	@echo "  docker-down  Stop Docker Compose stack"
	@echo "  docker-logs  Show Docker Compose logs"

dev:
	@echo "Starting backend and frontend..."
	docker compose up

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest tests/ -v --tb=short

test-cov:
	cd backend && pytest tests/ -v --tb=short --cov=app --cov-report=html --cov-report=term

lint:
	cd backend && ruff check .

format:
	cd backend && ruff format .

typecheck:
	cd backend && mypy app

migrate:
	cd backend && alembic upgrade head

migrate-rev:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

seed:
	cd backend && python scripts/seed_data.py

openapi:
	cd backend && python scripts/generate_types.py
	cd frontend && npm run generate-types

graph:
	cd backend && python scripts/generate_graph.py

clean:
	@echo "Cleaning build artifacts..."
	rm -rf backend/__pycache__ backend/app/__pycache__ backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -rf backend/.venv backend/dist backend/*.egg-info
	rm -rf frontend/node_modules frontend/.next frontend/out
	rm -rf logs uploads data *.db *.sqlite
	@echo "Clean complete."

docs:
	cd backend && python scripts/generate_openapi.py
	@echo "OpenAPI schema generated at backend/openapi.json"

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f