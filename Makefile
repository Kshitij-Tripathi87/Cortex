# Cortex Nexus developer commands. One interface for every contributor and for CI.
# Run `make help` for the list.

SHELL := /bin/bash
API_DIR := services/api
COMPOSE := docker compose -f infra/docker-compose.yml
UV_RUN := cd $(API_DIR) && uv run
HOST ?= 127.0.0.1
PORT ?= 8000
RESET_PHRASE := destroy-local-nexus-data

.DEFAULT_GOAL := help
.PHONY: help setup db-up db-down db-reset db-wait migrate migration-check lint format-check \
	format typecheck test-unit test-api test-integration test coverage run seed smoke \
	openapi openapi-check verify e2e

help: ## List the supported targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install the locked dependencies (fails if uv.lock is out of date)
	cd $(API_DIR) && uv sync --frozen

db-up: ## Start the local development and test PostgreSQL and wait until both are healthy
	$(COMPOSE) up -d --wait postgres postgres-test

db-down: ## Stop the local databases; the development data volume is kept
	$(COMPOSE) down

db-reset: ## DESTRUCTIVE: delete the local development database volume (needs CONFIRM=...)
	@if [ "$(CONFIRM)" != "$(RESET_PHRASE)" ]; then \
		echo "db-reset deletes every record in the local development database."; \
		echo "It is never run by any other target. To proceed, run:"; \
		echo "    make db-reset CONFIRM=$(RESET_PHRASE)"; \
		exit 1; \
	fi
	$(COMPOSE) down -v

db-wait: ## Wait until the development database accepts connections
	$(UV_RUN) python ../../scripts/wait_for_db.py

migrate: ## Apply the Alembic migrations to the development database
	$(UV_RUN) alembic upgrade head

migration-check: ## Verify a single migration head, the applied revision and that models match it
	$(UV_RUN) alembic heads
	$(UV_RUN) alembic current
	$(UV_RUN) alembic check

lint: ## Ruff lint for the service and the scripts
	$(UV_RUN) ruff check ../..

format-check: ## Verify formatting without changing files
	$(UV_RUN) ruff format --check ../..

format: ## Apply formatting and safe lint fixes
	$(UV_RUN) ruff format ../..
	$(UV_RUN) ruff check --fix ../..

typecheck: ## mypy (strict) over the service package
	$(UV_RUN) mypy app

test-unit: ## Unit tests; no database needed
	$(UV_RUN) pytest tests/unit -q

test-api: ## HTTP contract tests against the test database
	$(UV_RUN) pytest tests/api -q

test-integration: ## Persistence and transaction tests against the test database
	$(UV_RUN) pytest tests/integration -q

test: ## The full test suite
	$(UV_RUN) pytest -q

coverage: ## The full test suite with a coverage report
	$(UV_RUN) pytest -q --cov=app --cov-report=term-missing

run: ## Start the API on loopback (HOST and PORT can be overridden)
	@case "$(HOST)" in \
		127.*|localhost|::1) ;; \
		*) echo "HOST=$(HOST) is reachable from outside this machine, and this API has"; \
			echo "no authentication and no authorisation (L-01). Anyone who can reach it"; \
			echo "can read and change every record. Continue only on a network you own."; \
			;; \
	esac
	$(UV_RUN) uvicorn app.main:app --host $(HOST) --port $(PORT)

seed: ## Import the synthetic demo dataset through the preview and commit services
	$(UV_RUN) python ../../scripts/seed_demo_data.py

smoke: ## Exercise a running API over HTTP: health, contract, workspace
	$(UV_RUN) python ../../scripts/smoke_test.py --base-url http://$(HOST):$(PORT)

openapi: ## Export the OpenAPI document to docs/engineering/openapi.json
	$(UV_RUN) python ../../scripts/export_openapi.py

openapi-check: ## Fail if the committed OpenAPI document differs from the code
	$(UV_RUN) python ../../scripts/export_openapi.py --check

verify: ## The sprint verification chain; stops at the first failure
	$(UV_RUN) python ../../scripts/verify_sprint.py

e2e: ## The chain plus the end-to-end demo: import, World State, restart of API and database
	$(UV_RUN) python ../../scripts/verify_sprint.py --e2e
