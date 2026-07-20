# solus-api container. Requires BuildKit (default since Docker 23; CI uses
# docker:27) for the COPY <<'EOF' heredoc below.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv

# Third-party deps first (cached layer) — only re-runs if manifests change.
# --no-install-workspace is load-bearing: without it, uv builds solus-api
# itself at this layer, when src/ is not yet in the build context, and ships
# an EMPTY wheel — the app then fails at boot with ModuleNotFoundError.
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml ./packages/api/
RUN uv sync --frozen --no-dev --no-install-workspace --package solus-api

# Code second — changes here don't bust the deps layer. alembic.ini +
# migrations/ ship in the image because the entrypoint owns schema migration
# (SOLUS_AUTO_CREATE_TABLES stays false everywhere shared — core/config.py).
COPY packages/api/src ./packages/api/src
COPY packages/api/alembic.ini ./packages/api/alembic.ini
COPY packages/api/migrations ./packages/api/migrations

# Now install the workspace package itself from the real sources.
RUN uv sync --frozen --no-dev --package solus-api

# Boot sequence: migrate (bounded, fail-fast, logged) → serve.
# - `alembic upgrade head` is idempotent; a fresh RDS database gets its schema
#   here (nothing else in the deploy path creates tables).
# - `timeout` bounds a hung migration (exit 124) and `set -eu` makes any
#   failure abort the container before uvicorn starts, so ECS keeps the old
#   task serving instead of registering a half-migrated one.
# - `--no-sync` runs in the already-synced env: no resolver/network at boot,
#   and no accidental dev-group install (`uv run` would otherwise sync it).
# - `solus_api.main` is factory-only; uvicorn must be given --factory.
COPY <<'EOF' /app/entrypoint.sh
#!/bin/sh
set -eu
MIGRATE_TIMEOUT="${SOLUS_MIGRATE_TIMEOUT_SECONDS:-120}"
echo "[solus-api] applying migrations (alembic upgrade head, timeout ${MIGRATE_TIMEOUT}s)"
cd /app/packages/api
timeout "$MIGRATE_TIMEOUT" uv run --no-sync --package solus-api alembic upgrade head
echo "[solus-api] migrations at head — starting uvicorn"
cd /app
exec uv run --no-sync --package solus-api uvicorn --factory solus_api.main:create_app \
    --host 0.0.0.0 --port 8000
EOF
RUN chmod +x /app/entrypoint.sh

# Least privilege: nothing in the boot sequence needs root (uvicorn binds 8000,
# migrations only talk to the DB). uv needs a writable cache dir as non-root.
RUN useradd --create-home --uid 10001 solus && chown -R solus:solus /app
USER solus
ENV UV_CACHE_DIR=/tmp/uv-cache

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
