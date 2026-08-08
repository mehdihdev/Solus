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
  echo "[dev:all] packages/api/.env not found — env files are generated from .env.mega (SOLUSDEV-147)."
  echo "          First time:  cp env.mega.example .env.mega  (or: pnpm env:gather)  then fill it in."
  echo "          Then:        pnpm env:sync   (regenerates every per-package .env, incl. SOLUS_SUPABASE_JWT_SECRET)."
  echo "          JWT secret:  Supabase dashboard → Project Settings → API → JWT Secret."
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

# Stripe webhooks can't reach localhost on their own — without the forwarder a
# completed Checkout never flips the local plan/credits. Self-contained: the
# signing secret comes from the CLI itself (env vars override .env values in
# pydantic-settings), so nothing is pasted into .env.mega and it can't drift.
# Only attempted when billing is configured for this checkout (prices/secret set).
STRIPE_FORWARD=""
if grep -qE '^SOLUS_STRIPE_(PLAN_PRICES|WEBHOOK_SECRET)=..' packages/api/.env 2>/dev/null; then
  if ! command -v stripe >/dev/null 2>&1; then
    echo "[dev:all] note: billing is configured but the 'stripe' CLI is missing —"
    echo "          checkouts will complete in Stripe without updating your local plan."
    echo "          Install the Stripe CLI, then restart (or run: pnpm dev:stripe)."
  else
    STRIPE_DEV_SECRET="$(stripe listen --print-secret 2>/dev/null || true)"
    case "$STRIPE_DEV_SECRET" in
      whsec_*) STRIPE_FORWARD=1 ;;  # only a real signing secret shape is trusted
      *)
        STRIPE_DEV_SECRET=""
        echo "[dev:all] note: couldn't get a signing secret from the 'stripe' CLI (run: stripe login) —"
        echo "          checkouts will complete in Stripe without updating your local plan."
        ;;
    esac
  fi
fi

echo "[dev:all] starting API on http://127.0.0.1:8000 (docs at /api/v1/docs)…"
# The signing secret is passed to the API process ONLY (least privilege) — the
# desktop app and forwarder never see it.
if [ -n "${STRIPE_DEV_SECRET:-}" ]; then
  (cd packages/api && SOLUS_STRIPE_WEBHOOK_SECRET="$STRIPE_DEV_SECRET" uv run uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port 8000 --reload) &
else
  (cd packages/api && uv run uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port 8000 --reload) &
fi
pids+=($!)

echo "[dev:all] starting desktop app…"
pnpm --filter @solus/desktop dev &
pids+=($!)

if [ -n "$STRIPE_FORWARD" ]; then
  echo "[dev:all] starting Stripe webhook forwarder (stripe listen)…"
  stripe listen --forward-to http://127.0.0.1:8000/api/v1/webhooks/stripe &
  pids+=($!)
fi

wait
