# SentinelAI — developer / demo shortcuts.
#
# Every target shells out to docker compose, a script in infra/scripts/, or
# a `pytest` / `npm` invocation. Nothing here is required to run the project;
# it just makes the demo loop one keystroke shorter.
#
# Run `make` or `make help` to see the menu.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Where developer scripts live, relative to this Makefile.
SCRIPTS := infra/scripts

# ---------- help ----------

.PHONY: help
help: ## Show this help.
	@printf "\nSentinelAI — make targets\n\n"
	@awk 'BEGIN {FS = ":.*##"} \
		/^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)
	@printf "\nFirst-time setup:  \033[36mmake bootstrap\033[0m\n"
	@printf "Daily loop:        \033[36mmake up\033[0m  ·  \033[36mmake logs\033[0m  ·  \033[36mmake down\033[0m\n\n"

# ---------- docker compose lifecycle ----------

.PHONY: up
up: ## Start the stack in the background (postgres + backend + frontend).
	docker compose up -d

.PHONY: down
down: ## Stop the stack (keeps the database volume).
	docker compose down

.PHONY: build
build: ## Rebuild all service images.
	docker compose build

.PHONY: ps
ps: ## Show running containers + health state.
	docker compose ps

.PHONY: logs
logs: ## Tail logs from all services (Ctrl-C to exit).
	docker compose logs -f --tail=100

.PHONY: logs-backend
logs-backend: ## Tail backend logs only.
	docker compose logs -f --tail=200 backend

.PHONY: reset
reset: ## Wipe the database volume and restart fresh (DESTRUCTIVE).
	docker compose down -v
	docker compose up -d

# ---------- backup / restore ----------

.PHONY: backup-db
backup-db: ## Dump the database to backups/sentinelai-<ts>.sql.gz.
	bash $(SCRIPTS)/backup_db.sh

.PHONY: restore-db
restore-db: ## Restore from a dump: make restore-db BACKUP=backups/<file>.sql.gz (DESTRUCTIVE).
	@[ -n "$(BACKUP)" ] || { echo "usage: make restore-db BACKUP=backups/<file>.sql.gz"; exit 2; }
	bash $(SCRIPTS)/restore_db.sh "$(BACKUP)"

# ---------- one-command demo prep ----------

.PHONY: bootstrap
bootstrap: ## First-time setup: build, wait for health, seed model, restart.
	bash $(SCRIPTS)/bootstrap.sh

.PHONY: seed
seed: ## Train a fresh detection model and restart the backend.
	bash $(SCRIPTS)/seed.sh

.PHONY: smoke
smoke: ## Run the 11-step end-to-end smoke test against the running stack.
	bash $(SCRIPTS)/smoke_demo.sh

.PHONY: e2e
e2e: ## Full E2E gate: up -> train+stage model -> smoke -> down -v (safe teardown).
	bash $(SCRIPTS)/e2e.sh

.PHONY: demo-seed
demo-seed: ## Pre-populate the dashboard with alerts, actions, and a report.
	bash $(SCRIPTS)/demo_seed.sh

.PHONY: demo
demo: bootstrap demo-seed ## Bootstrap from scratch and seed presentation data.
	@printf "\n\033[32m✓ SentinelAI is demo-ready.\033[0m Open http://localhost:5173\n"

.PHONY: single-container
single-container: ## Build and run SentinelAI as one Docker container.
	bash $(SCRIPTS)/run_single_container.sh

# ---------- quality gates ----------

.PHONY: test
test: test-backend test-frontend ## Run backend + frontend test suites.

.PHONY: test-backend
test-backend: ## Run the backend pytest suite (fast unit tests; no DB).
	cd backend && pytest

.PHONY: test-integration
test-integration: ## Run real-Postgres integration tests (needs Docker).
	cd backend && pytest -m integration

.PHONY: test-frontend
test-frontend: ## Run the frontend vitest suite.
	cd frontend && npm test --silent

.PHONY: typecheck
typecheck: ## Run the frontend TypeScript compiler in --noEmit mode.
	cd frontend && npx tsc --noEmit

.PHONY: lint
lint: ## Ruff lint + format check on the backend.
	cd backend && ruff check . && ruff format --check .

.PHONY: format
format: ## Auto-format the backend with ruff.
	cd backend && ruff check --fix . && ruff format .

# ---------- shell into a container ----------

.PHONY: shell-backend
shell-backend: ## Open a shell inside the running backend container.
	docker compose exec backend bash

.PHONY: shell-db
shell-db: ## Open a psql prompt against the dev database.
	docker compose exec postgres psql -U sentinelai -d sentinelai
