# BeadHub Development & Docker Management
#
# Quick reference:
#   make start          - Start BeadHub (for users, port 8000)
#   make stop           - Stop BeadHub
#   make dev-backend    - Start backend (uses local postgres/redis)
#   make dev-frontend   - Start frontend dev server
#   make docker         - Start canonical docker (for contributors, port 9000)
#
# All modes can run simultaneously on different ports.

.PHONY: help start stop dev-backend dev-frontend dev-stop dev-setup dev-check docker docker-stop docker-rebuild docker-clean \
        _docker-start _docker-rebuild logs status clean-all prune bdh reset-server-schema health \
        check-python fmt-python lint-python typecheck-python \
        check-frontend check-bdh check hooks-install \
        test-instance-setup test-instance-backend test-instance-frontend test-instance-stop test-instance-clean

# Default env file (can be overridden)
ENV_FILE ?= .env.dev

# Load env file if it exists
ifneq (,$(wildcard $(ENV_FILE)))
include $(ENV_FILE)
export
endif

# Fallback defaults
BEADHUB_PORT ?= 8000
POSTGRES_HOST ?= localhost
POSTGRES_PORT ?= 5432
REDIS_PORT ?= 6379
VITE_PORT ?= 5173
POSTGRES_PASSWORD ?= dev-password
POSTGRES_DB ?= beadhub
POSTGRES_APP_USER ?= beadhub
POSTGRES_ADMIN_DB ?= postgres
POSTGRES_ADMIN_URL ?= postgresql://$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_ADMIN_DB)
BEADHUB_DATABASE_URL ?= postgresql://beadhub@localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)
BEADHUB_REDIS_URL ?= redis://localhost:$(REDIS_PORT)/0

# Test instance settings (clean slate for UI testing)
TEST_POSTGRES_DB ?= beadhub_test
TEST_BEADHUB_PORT ?= 8001
TEST_VITE_PORT ?= 5174
TEST_REDIS_DB ?= 1
TEST_DATABASE_URL ?= postgresql://beadhub@localhost:$(POSTGRES_PORT)/$(TEST_POSTGRES_DB)
TEST_REDIS_URL ?= redis://localhost:$(REDIS_PORT)/$(TEST_REDIS_DB)

help:
	@echo "BeadHub Commands:"
	@echo ""
	@echo "  Quick Start (for users):"
	@echo "    make start          - Start BeadHub server (Docker, port 8000)"
	@echo "    make stop           - Stop BeadHub server"
	@echo ""
	@echo "  Local Development (uses local postgres/redis via brew services):"
	@echo "    make dev-setup      - Set up local dev environment (postgres/redis/database)"
	@echo "    make dev-check      - Verify local dev prerequisites are met"
	@echo "    make dev-backend    - Run backend server on port 8000"
	@echo "    make dev-frontend   - Run Vite dev server on port 5173"
	@echo "    make dev-stop       - Kill local dev servers"
	@echo ""
	@echo "  Docker Canonical (for agents to connect to):"
	@echo "    make docker         - Start all services in Docker on port 9000"
	@echo "    make docker-stop    - Stop docker services"
	@echo "    make docker-rebuild - Rebuild and restart API container"
	@echo "    make docker-clean   - Stop and remove containers/volumes (reset database)"
	@echo ""
	@echo "  Test Instance (clean slate for UI testing):"
	@echo "    make test-instance-setup    - Create test database"
	@echo "    make test-instance-backend  - Run test backend on port 8001"
	@echo "    make test-instance-frontend - Run test frontend on port 5174"
	@echo "    make test-instance-stop     - Stop test servers"
	@echo "    make test-instance-clean    - Drop test database (full reset)"
	@echo ""
	@echo "  Utilities:"
	@echo "    make health         - Check API health endpoint"
	@echo "    make logs           - Follow docker logs"
	@echo "    make status         - Show service status"
	@echo "    make clean-all      - Stop and remove ALL beadhub containers"
	@echo "    make bdh            - Build the bdh Go binary"
	@echo "    make reset-server-schema - Drop server/beads schemas (fixes migration errors)"
	@echo "    make reset-dev-db   - Drop and recreate the dev database (no backwards-compat)"
	@echo "    make check-python   - Run Python format/lint/typecheck"
	@echo "    make fmt-python     - Auto-format Python (black/isort/ruff)"
	@echo "    make check-frontend - Run frontend lint/build checks"
	@echo "    make check-bdh      - Run bdh Go tests"
	@echo "    make check          - Run all checks (python + frontend + bdh)"
	@echo "    make hooks-install  - Install git hooks (pre-push checks + bd sync)"
	@echo ""
	@echo "  Port Allocation:"
	@echo "    start:  backend=8000  postgres=5432  redis=6379       (Docker, for users)"
	@echo "    dev:    backend=8000  frontend=5173  db=beadhub       (local postgres/redis)"
	@echo "    test:   backend=8001  frontend=5174  db=beadhub_test  (separate redis db)"
	@echo "    docker: backend=9000  frontend=9000  postgres=5433    redis=6380"
	@echo ""

#
# Quick Start (for users)
#

start:
	@POSTGRES_PASSWORD=beadhub docker compose up -d
	@echo ""
	@echo "BeadHub is starting..."
	@echo "  API:       http://localhost:8000"
	@echo "  Dashboard: http://localhost:8000"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Install bdh: curl -fsSL https://raw.githubusercontent.com/juanre/beadhub/main/bdh/install.sh | bash"
	@echo "  2. In your repo: bdh :init"
	@echo ""
	@$(MAKE) health BEADHUB_PORT=8000

stop:
	@docker compose down
	@echo "BeadHub stopped."

#
# Local Development (uses local postgres/redis via brew services)
#

dev-backend: dev-check
	@echo ""
	@echo "Starting backend on port 8000..."
	@echo "  API:       http://localhost:8000/v1"
	@echo "  Health:    http://localhost:8000/health"
	@echo "  Postgres:  localhost:5432/beadhub (local)"
	@echo "  Redis:     localhost:6379 (local)"
	@echo ""
	BEADHUB_DATABASE_URL="$(BEADHUB_DATABASE_URL)" \
	BEADHUB_REDIS_URL="$(BEADHUB_REDIS_URL)" \
	uv run beadhub serve --port 8000 --reload

dev-frontend: dev-check
	@echo ""
	@echo "Starting Vite dev server on port 5173..."
	@echo "  Dashboard: http://localhost:5173"
	@echo "  (proxies API calls to localhost:8000)"
	@echo ""
	@echo "Building @beadhub/dashboard package (required for local dev)..."
	cd frontend && pnpm --filter @beadhub/dashboard build
	cd frontend && VITE_BACKEND_PORT=8000 pnpm dev --port 5173

dev-stop:
	@echo "Stopping dev servers..."
	-@lsof -ti :8000 | xargs kill 2>/dev/null || true
	-@lsof -ti :5173 | xargs kill 2>/dev/null || true
	@echo "Done."

dev-check:
	@echo "Checking local dev prerequisites..."
	@FAILED=0; \
	echo ""; \
	echo "  PostgreSQL:"; \
	if pg_isready -q -h localhost -p $(POSTGRES_PORT) 2>/dev/null; then \
		echo "    [OK] Running on port $(POSTGRES_PORT)"; \
	else \
		echo "    [MISSING] Not running on port $(POSTGRES_PORT)"; \
		echo "             Fix: brew services start postgresql@14"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "  Redis:"; \
	if redis-cli -p $(REDIS_PORT) ping >/dev/null 2>&1; then \
		echo "    [OK] Running on port $(REDIS_PORT)"; \
	else \
		echo "    [MISSING] Not running on port $(REDIS_PORT)"; \
		echo "             Fix: brew services start redis"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "  PostgreSQL role '$(POSTGRES_APP_USER)':"; \
	if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$(POSTGRES_APP_USER)'" 2>/dev/null | grep -q 1; then \
		echo "    [OK] Role exists"; \
	else \
		echo "    [MISSING] Role does not exist"; \
		echo "             Fix: make dev-setup"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "  PostgreSQL database '$(POSTGRES_DB)':"; \
	if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_database WHERE datname='$(POSTGRES_DB)'" 2>/dev/null | grep -q 1; then \
		echo "    [OK] Database exists"; \
	else \
		echo "    [MISSING] Database does not exist"; \
		echo "             Fix: make dev-setup"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "  Frontend dependencies:"; \
	if [ -d "frontend/node_modules" ]; then \
		echo "    [OK] Installed"; \
	else \
		echo "    [MISSING] node_modules not found"; \
		echo "             Fix: make dev-setup"; \
		FAILED=1; \
	fi; \
	echo ""; \
	if [ "$$FAILED" = "1" ]; then \
		echo "Some prerequisites are missing. Run 'make dev-setup' to fix."; \
		exit 1; \
	else \
		echo "All prerequisites OK!"; \
	fi

dev-setup:
	@echo "Setting up local dev environment..."
	@echo ""
	@echo "1. Starting PostgreSQL..."
	@if pg_isready -q -h localhost -p $(POSTGRES_PORT) 2>/dev/null; then \
		echo "   Already running."; \
	else \
		brew services start postgresql@14 2>/dev/null || brew services start postgresql 2>/dev/null || \
			(echo "   Failed to start PostgreSQL. Please install with: brew install postgresql@14" && exit 1); \
		sleep 2; \
		if pg_isready -q -h localhost -p $(POSTGRES_PORT) 2>/dev/null; then \
			echo "   Started."; \
		else \
			echo "   Failed to start PostgreSQL."; \
			exit 1; \
		fi; \
	fi
	@echo ""
	@echo "2. Starting Redis..."
	@if redis-cli -p $(REDIS_PORT) ping >/dev/null 2>&1; then \
		echo "   Already running."; \
	else \
		brew services start redis 2>/dev/null || \
			(echo "   Failed to start Redis. Please install with: brew install redis" && exit 1); \
		sleep 1; \
		if redis-cli -p $(REDIS_PORT) ping >/dev/null 2>&1; then \
			echo "   Started."; \
		else \
			echo "   Failed to start Redis."; \
			exit 1; \
		fi; \
	fi
	@echo ""
	@echo "3. Creating PostgreSQL role '$(POSTGRES_APP_USER)'..."
	@if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$(POSTGRES_APP_USER)'" 2>/dev/null | grep -q 1; then \
		echo "   Already exists."; \
	else \
		psql "$(POSTGRES_ADMIN_URL)" -c "CREATE ROLE $(POSTGRES_APP_USER) WITH LOGIN CREATEDB;" && \
		echo "   Created."; \
	fi
	@echo ""
	@echo "4. Creating PostgreSQL database '$(POSTGRES_DB)'..."
	@if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_database WHERE datname='$(POSTGRES_DB)'" 2>/dev/null | grep -q 1; then \
		echo "   Already exists."; \
	else \
		psql "$(POSTGRES_ADMIN_URL)" -c "CREATE DATABASE $(POSTGRES_DB) OWNER $(POSTGRES_APP_USER);" && \
		echo "   Created."; \
	fi
	@echo ""
	@echo "5. Installing frontend dependencies..."
	@if [ -d "frontend/node_modules" ]; then \
		echo "   Already installed."; \
	else \
		cd frontend && pnpm install && \
		echo "   Installed."; \
	fi
	@echo ""
	@echo "Setup complete! Run 'make dev-backend' to start the server."

#
# Docker Canonical (for agents)
#

docker:
	@$(MAKE) ENV_FILE=.env.docker _docker-start

_docker-start:
	@docker compose --env-file $(ENV_FILE) -p beadhub-docker up -d
	@echo ""
	@echo "Docker services running ($(ENV_FILE)):"
	@echo "  Redis:      redis://localhost:$(REDIS_PORT)"
	@echo "  PostgreSQL: postgresql://localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)"
	@echo "  API:        http://localhost:$(BEADHUB_PORT)/v1"
	@echo "  Dashboard:  http://localhost:$(BEADHUB_PORT)"
	@$(MAKE) health BEADHUB_PORT=$(BEADHUB_PORT)

docker-stop:
	docker compose --env-file .env.docker -p beadhub-docker down

docker-rebuild:
	@$(MAKE) ENV_FILE=.env.docker _docker-rebuild

_docker-rebuild:
	docker compose --env-file $(ENV_FILE) -p beadhub-docker build api
	docker compose --env-file $(ENV_FILE) -p beadhub-docker up -d api
	@echo "API rebuilt and running on port $(BEADHUB_PORT)"
	@$(MAKE) health BEADHUB_PORT=$(BEADHUB_PORT)

#
# Utilities
#

health:
	@echo ""
	@echo "Checking health..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -sf http://localhost:$(BEADHUB_PORT)/health > /dev/null 2>&1; then \
			curl -s http://localhost:$(BEADHUB_PORT)/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Status:', d['status']); [print(f'    {k}: {v}') for k,v in d.get('checks',{}).items()]"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "  Health check failed after 10s"; \
	exit 1

logs:
	docker compose --env-file .env.docker -p beadhub-docker logs -f

status:
	@echo "=== Docker Canonical (beadhub-docker) ==="
	@docker compose --env-file .env.docker -p beadhub-docker ps 2>/dev/null || echo "  (not running)"
	@echo ""
	@echo "=== Local Services (brew) ==="
	@brew services list 2>/dev/null | grep -E 'postgresql|redis' || echo "  (check: brew services list)"

docker-clean:
	docker compose --env-file .env.docker -p beadhub-docker down -v --remove-orphans

clean-all:
	@echo "Stopping all beadhub Docker containers..."
	-docker compose --env-file .env.docker -p beadhub-docker down -v 2>/dev/null || true
	-docker ps -q --filter "name=beadhub" | xargs docker stop 2>/dev/null || true
	-docker ps -aq --filter "name=beadhub" | xargs docker rm 2>/dev/null || true
	-docker volume ls -q --filter "name=beadhub" | xargs docker volume rm 2>/dev/null || true
	@echo "Done."

prune:
	@echo "Removing dangling images and unused volumes..."
	-docker image prune -f
	-docker volume prune -f

reset-server-schema:
	@echo "Dropping server and beads schemas..."
	psql "$(BEADHUB_DATABASE_URL)" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS server CASCADE; DROP SCHEMA IF EXISTS beads CASCADE;"
	@echo "Done. Restart the server to re-apply migrations."
	@echo "If you need a full reset (drop/recreate DB), run: make reset-dev-db"

reset-dev-db:
	@echo "Dropping and recreating database '$(POSTGRES_DB)'..."
	@echo "  Admin URL: $(POSTGRES_ADMIN_URL)"
	@set -euo pipefail; \
		psql "$(POSTGRES_ADMIN_URL)" -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$(POSTGRES_DB)' AND pid <> pg_backend_pid();"; \
		psql "$(POSTGRES_ADMIN_URL)" -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS "$(POSTGRES_DB)";'; \
		psql "$(POSTGRES_ADMIN_URL)" -v ON_ERROR_STOP=1 -c 'CREATE DATABASE "$(POSTGRES_DB)" OWNER "$(POSTGRES_APP_USER)";'
	@echo "Done. Start the server to re-apply migrations."

bdh:
	@echo "Building bdh..."
	@mkdir -p "$(CURDIR)/.cache/go-build"
	@cd bdh && \
	GOCACHE="$(CURDIR)/.cache/go-build" \
	go build -ldflags "-X main.version=dev -X main.commit=$$(git rev-parse --short HEAD) -X main.date=$$(date -u +%Y-%m-%dT%H:%M:%SZ)" -o bdh ./cmd/bdh
	@echo "Built: ./bdh/bdh"

#
# Test Instance (clean slate for UI testing)
#

test-instance-setup:
	@echo "Setting up test instance database..."
	@echo ""
	@echo "  Creating PostgreSQL database '$(TEST_POSTGRES_DB)'..."
	@if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_POSTGRES_DB)'" 2>/dev/null | grep -q 1; then \
		echo "    Already exists. Run 'make test-instance-clean' first for a fresh start."; \
	else \
		psql "$(POSTGRES_ADMIN_URL)" -c "CREATE DATABASE $(TEST_POSTGRES_DB) OWNER $(POSTGRES_APP_USER);" && \
		echo "    Created."; \
	fi
	@echo ""
	@echo "  Flushing Redis db $(TEST_REDIS_DB)..."
	@redis-cli -p $(REDIS_PORT) -n $(TEST_REDIS_DB) FLUSHDB >/dev/null && echo "    Done."
	@echo ""
	@echo "Test database ready. Run 'make test-instance-backend' to start the server."

test-instance-backend:
	@echo ""
	@echo "Starting TEST backend on port $(TEST_BEADHUB_PORT)..."
	@echo "  API:       http://localhost:$(TEST_BEADHUB_PORT)/v1"
	@echo "  Health:    http://localhost:$(TEST_BEADHUB_PORT)/health"
	@echo "  Database:  $(TEST_POSTGRES_DB) (clean slate)"
	@echo "  Redis db:  $(TEST_REDIS_DB)"
	@echo ""
	@# Create DB if it doesn't exist
	@if ! psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_POSTGRES_DB)'" 2>/dev/null | grep -q 1; then \
		echo "Creating test database..."; \
		psql "$(POSTGRES_ADMIN_URL)" -c "CREATE DATABASE $(TEST_POSTGRES_DB) OWNER $(POSTGRES_APP_USER);"; \
	fi
	BEADHUB_DATABASE_URL="$(TEST_DATABASE_URL)" \
	BEADHUB_REDIS_URL="$(TEST_REDIS_URL)" \
	uv run beadhub serve --port $(TEST_BEADHUB_PORT) --reload

test-instance-frontend:
	@echo ""
	@echo "Starting TEST Vite dev server on port $(TEST_VITE_PORT)..."
	@echo "  Dashboard: http://localhost:$(TEST_VITE_PORT)"
	@echo "  (proxies API calls to localhost:$(TEST_BEADHUB_PORT))"
	@echo ""
	@echo "Building @beadhub/dashboard package..."
	cd frontend && pnpm --filter @beadhub/dashboard build
	cd frontend && VITE_BACKEND_PORT=$(TEST_BEADHUB_PORT) pnpm dev --port $(TEST_VITE_PORT)

test-instance-stop:
	@echo "Stopping test instance servers..."
	-@lsof -ti :$(TEST_BEADHUB_PORT) | xargs kill 2>/dev/null || true
	-@lsof -ti :$(TEST_VITE_PORT) | xargs kill 2>/dev/null || true
	@echo "Done."

test-instance-clean:
	@echo "Cleaning up test instance..."
	@echo ""
	@echo "  Stopping servers on ports $(TEST_BEADHUB_PORT)/$(TEST_VITE_PORT)..."
	-@lsof -ti :$(TEST_BEADHUB_PORT) | xargs kill 2>/dev/null || true
	-@lsof -ti :$(TEST_VITE_PORT) | xargs kill 2>/dev/null || true
	@echo ""
	@echo "  Dropping database '$(TEST_POSTGRES_DB)'..."
	@if psql "$(POSTGRES_ADMIN_URL)" -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_POSTGRES_DB)'" 2>/dev/null | grep -q 1; then \
		psql "$(POSTGRES_ADMIN_URL)" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$(TEST_POSTGRES_DB)' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true; \
		psql "$(POSTGRES_ADMIN_URL)" -c "DROP DATABASE $(TEST_POSTGRES_DB);" && \
		echo "    Dropped."; \
	else \
		echo "    Database does not exist."; \
	fi
	@echo ""
	@echo "  Flushing Redis db $(TEST_REDIS_DB)..."
	@redis-cli -p $(REDIS_PORT) -n $(TEST_REDIS_DB) FLUSHDB >/dev/null && echo "    Done."
	@echo ""
	@echo "Test instance cleaned. Ready for fresh 'make test-instance-backend'."

#
# Python tooling (OSS release)
#

fmt-python:
	uv run ruff format .
	uv run isort .
	uv run black .
	uv run ruff check --fix .

lint-python:
	uv run ruff check .
	uv run black --check .
	uv run isort --check-only .

typecheck-python:
	uv run mypy

check-python: lint-python typecheck-python

check-frontend:
	cd frontend && pnpm lint && pnpm build

check-bdh:
	@mkdir -p "$(CURDIR)/.cache/go-build"
	@cd bdh && \
	GOCACHE="$(CURDIR)/.cache/go-build" \
	golangci-lint run ./...

check: check-python check-frontend check-bdh

hooks-install:
	@mkdir -p .git/hooks
	@cp -f scripts/git-hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@cp -f scripts/git-hooks/pre-push .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "Installed git hooks: pre-commit, pre-push"
