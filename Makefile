.PHONY: bootstrap hooks db-up db-down dev-api dev-desktop dev-web lint typecheck test gen-openapi companion-bin seed-secrets

bootstrap: ## one-command setup (run after cloning)
	corepack enable && pnpm install
	uv sync --all-packages
	$(MAKE) hooks
	@echo "  bootstrap done."
	@echo "   Terminals: 'make db-up' (once docker is set up), 'make dev-api', 'make dev-desktop'"

hooks:
	chmod +x .claude/hooks/*.sh 2>/dev/null || true

db-up:
	docker compose -f docker-compose.dev.yml up -d --wait

db-down:
	docker compose -f docker-compose.dev.yml down

dev-api:
	cd packages/api && uv run uvicorn --factory solus_api.main:create_app --reload --port 8000

dev-desktop:
	pnpm --filter @solus/desktop dev

dev-web:
	pnpm --filter @solus/web dev

lint:
	uv run ruff check . && pnpm lint

typecheck:
	uv run mypy packages/api/src && pnpm typecheck

test:
	uv run pytest -q && pnpm test

mcp-forks: ## materialize the vendored MCP forks' private virtualenvs (hash-verified; ADR-031)
	bash scripts/install-mcp-forks.sh

companion-bin: ## build the companion binary + vendored MCP servers into dist/companion (BRG-04)
	bash scripts/build-companion.sh

seed-secrets: ## seed every env-sourced SecretStore ref from the root .env (idempotent; prints names+lengths only)
	uv run python scripts/seed-provider-keys.py

gen-openapi: ## regenerate packages/api/openapi.json + desktop TS types (run after model changes)
	cd packages/api && SOLUS_SUPABASE_JWT_SECRET=openapi-dump-dummy uv run python -c "import json, pathlib; from solus_api.main import create_app; pathlib.Path('openapi.json').write_text(json.dumps(create_app().openapi(), indent=2) + '\n')"
	pnpm --filter @solus/desktop run gen:api

onshape-budget: ## SOLUSDEV-167: print the Onshape before/after call-count table
	cd packages/api && uv run pytest tests/test_onshape_session_cost.py -q -s
