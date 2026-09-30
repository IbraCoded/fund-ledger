SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help demo tour test down

help: ## List the commands
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-6s %s\n", $$1, $$2}'

demo: ## Build, start, seed the demo fund and print an API key per role
	@test -f .env || cp .env.example .env
	docker compose up -d --build
	@printf 'Waiting for the API'; for _ in $$(seq 60); do \
	  curl -fsS -o /dev/null localhost:8000/healthz 2>/dev/null && break; printf .; sleep 1; done; echo
	@curl -fsS -o /dev/null localhost:8000/healthz || { echo "API didn't start: docker compose logs api"; exit 1; }
	@# Logs go to stdout too (as they should in a container), so keep only the key lines.
	@docker compose exec -T api python manage.py demo_access | grep -E '^(# |[A-Z_]+=)' > .demo-keys.env
	@cat .demo-keys.env
	@printf '\nSaved to .demo-keys.env. Next:\n  open http://localhost:8000/api/docs/  (Authorize, paste a key)\n  make tour\n'

tour: ## Walk through every security and correctness guarantee
	@scripts/tour.sh

test: ## Run the test suite (needs uv)
	docker compose up -d db
	uv run pytest

down: ## Stop everything (add -v to docker compose down to wipe the database)
	docker compose down
