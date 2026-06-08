.PHONY: bootstrap hooks db-up db-down dev-api dev-desktop dev-web lint typecheck test

bootstrap: ## one-command setup (run after cloning)
	corepack enable && pnpm install
	uv sync --all-packages
	$(MAKE) hooks
	@echo "✅ bootstrap done."
	@echo "   Terminals: 'make db-up' (once docker is set up), 'make dev-api', 'make dev-desktop'"

hooks:
	chmod +x .claude/hooks/*.sh 2>/dev/null || true

db-up:
	docker compose -f docker-compose.dev.yml up -d --wait

db-down:
	docker compose -f docker-compose.dev.yml down

dev-api:
	uv run --package solus-api uvicorn solus_api.main:app --reload --port 8000

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
