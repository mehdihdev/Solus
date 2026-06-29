#!/usr/bin/env bash
# SOLUSDEV-55 — run the whole stack with one command:
#   Postgres (docker) → FastAPI backend (:8000) → Electron desktop app.
# Ctrl+C tears all of them down.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f docker-compose.dev.yml"

require() { command -v "$1" >/dev/null 2>&1 || { echo "[dev:all] missing '$1' — please install it."; exit 1; }; }
require docker
require uv
require pnpm

if [ ! -f packages/api/.env ]; then
  echo "[dev:all] packages/api/.env not found."
  echo "          cp packages/api/.env.example packages/api/.env  and set SOLUS_SUPABASE_JWT_SECRET"
  echo "          (Supabase dashboard → Project Settings → API → JWT Secret)."
  exit 1
fi
if [ ! -f apps/desktop/.env ]; then
  echo "[dev:all] note: apps/desktop/.env not found — the app will run in dev-bypass auth"
  echo "          (UI works, but API calls will be rejected). Set VITE_SUPABASE_* for the real flow."
fi

echo "[dev:all] starting Postgres…"
$COMPOSE up -d db

echo "[dev:all] waiting for Postgres to be ready…"
for _ in $(seq 1 30); do
  if $COMPOSE exec -T db pg_isready -U solus -d solus >/dev/null 2>&1; then break; fi
  sleep 1
done

pids=()
cleanup() {
  echo
  echo "[dev:all] shutting down…"
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup INT TERM EXIT

echo "[dev:all] starting API on http://127.0.0.1:8000 (docs at /api/v1/docs)…"
(cd packages/api && uv run uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port 8000 --reload) &
pids+=($!)

echo "[dev:all] starting desktop app…"
pnpm --filter @solus/desktop dev &
pids+=($!)

wait
