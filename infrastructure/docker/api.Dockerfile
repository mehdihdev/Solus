# solus-api container. Requires BuildKit (default since Docker 23; CI uses
# docker:27) for the COPY <<'EOF' heredoc below.
# Node 22 for the vendored MCP forks that are Node servers (today: the Brave
# search fork, launched cloud-side by this API — integrations/mcp/brave). Taken
# from the official image rather than a distro/NodeSource repo so the version is
# PINNED and reproducible, and because node:22-bookworm-slim shares glibc with
# python:3.12-slim (both bookworm). `bin/launch` looks for /usr/local/bin/node,
# one of its fixed candidates, so nothing is PATH-resolved at spawn.
FROM node:22.22.3-bookworm-slim AS node

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# Third-party deps first (cached layer) — only re-runs if manifests change.
# --no-install-workspace is load-bearing: without it, uv builds solus-api
# itself at this layer, when src/ is not yet in the build context, and ships
# an EMPTY wheel — the app then fails at boot with ModuleNotFoundError.
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml ./packages/api/
COPY packages/contracts/python/pyproject.toml ./packages/contracts/python/
RUN uv sync --frozen --no-dev --no-install-workspace --package solus-api

# Code second — changes here don't bust the deps layer. alembic.ini +
# migrations/ ship in the image because the entrypoint owns schema migration
# (SOLUS_AUTO_CREATE_TABLES stays false everywhere shared — core/config.py).
COPY packages/api/src ./packages/api/src
COPY packages/contracts/python/solus_contracts ./packages/contracts/python/solus_contracts
COPY packages/api/alembic.ini ./packages/api/alembic.ini
COPY packages/api/migrations ./packages/api/migrations

# Now install the API and its runtime contracts package from the real sources.
RUN uv sync --frozen --no-dev --package solus-api

# The bridge allowlists (~250K). Without these the image has no
# `integrations/` at all, `load_allowlist` finds nothing, and every tool a
# companion advertises is rejected as "not allowlisted" — a silently dead
# bridge rather than a failure anyone would notice. After the second
# `uv sync` deliberately: editing an allowlist must not re-run the install.
COPY integrations/mcp ./integrations/mcp

# The Node forks' dependency trees. `bin/launch` does ZERO installs and ZERO
# network I/O (ADR-031), so node_modules/ has to exist in the image: `npm ci`
# installs exactly the committed integrity-pinned lock, `--ignore-scripts`
# refuses every dependency lifecycle hook, `--omit=dev` keeps it to what runs.
# npm itself is then REMOVED: nothing in the running container may install
# anything, and the image stays lean. (Same contract as scripts/install-mcp-forks.sh.)
RUN for lock in integrations/mcp/*/package-lock.json; do \
      [ -e "$lock" ] || continue; \
      (cd "$(dirname "$lock")" && npm ci --omit=dev --ignore-scripts --no-audit --no-fund); \
    done \
 && rm -rf /usr/local/bin/npm /usr/local/lib/node_modules/npm /root/.npm

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
echo "[solus-api] migrations at head"
# CORPUS C2 (ADR-036): apply the shipped engineering corpus. Idempotent — an
# unchanged tree is a no-op, a new corpus_version upserts/withdraws by id, and
# vectors backfill only where missing. Never blocks serving: a failed ingest
# leaves the previous corpus in place and is reported in the log.
CORPUS_TIMEOUT="${SOLUS_CORPUS_INGEST_TIMEOUT_SECONDS:-300}"
echo "[solus-api] applying the engineering corpus (timeout ${CORPUS_TIMEOUT}s)"
timeout "$CORPUS_TIMEOUT" uv run --no-sync --package solus-api python -m solus_api.corpus ingest \
    || echo "[solus-api] corpus ingest FAILED — serving the previously applied corpus"
echo "[solus-api] starting uvicorn"
cd /app
exec uv run --no-sync --package solus-api uvicorn --factory solus_api.main:create_app \
    --host 0.0.0.0 --port 8000
EOF
RUN chmod +x /app/entrypoint.sh

# The API and TypeScript share these runtime customer-design detection rules.
COPY packages/shared-types/fixtures/tool-knowledge/customer-shapes.json ./packages/shared-types/fixtures/tool-knowledge/customer-shapes.json

# Least privilege: nothing in the boot sequence needs root (uvicorn binds 8000,
# migrations only talk to the DB). uv needs a writable cache dir as non-root.
RUN useradd --create-home --uid 10001 solus && chown -R solus:solus /app
USER solus
ENV UV_CACHE_DIR=/tmp/uv-cache

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
