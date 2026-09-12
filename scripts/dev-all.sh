#!/usr/bin/env bash
# SOLUSDEV-55 — run the whole stack with one command:
#   Postgres/Redis (docker) → FastAPI + ARQ worker → Electron desktop app.
# Ctrl+C tears all of them down.
set -uo pipefail
# Job control, deliberately, in a non-interactive script: it puts every
# background job in its own process group, which is what lets cleanup() kill a
# whole tree instead of just the subshell in front of it. See cleanup().
set -m
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.dev.yml)
if [ -f docker-compose.local.yml ]; then
  COMPOSE+=(-f docker-compose.local.yml)
fi

require() { command -v "$1" >/dev/null 2>&1 || { echo "[dev:all] missing '$1' — please install it."; exit 1; }; }
require docker
require uv
require pnpm

# ONE env file, at the repo root, read directly by every process (API via an
# anchored env_file, desktop via Vite envDir, web via process.loadEnvFile). There
# are no generated per-package copies to keep in step any more.
if [ ! -f .env ]; then
  echo "[dev:all] .env not found at the repo root — that is the only env file."
  echo "          First time:  cp env.example .env   then fill it in."
  echo "          JWT secret:  Supabase dashboard → Project Settings → API → JWT Secret."
  exit 1
fi
if ! grep -qE '^VITE_SUPABASE_(URL|ANON_KEY)=..' .env 2>/dev/null; then
  echo "[dev:all] note: VITE_SUPABASE_* unset in .env — the app will run in dev-bypass auth"
  echo "          (UI works, but API calls will be rejected). Set them for the real flow."
fi

# Resolve only this worktree's app ports; never source executable env text.
require lsof
if ! APP_PORTS="$(uv run --no-sync python scripts/dev_ports.py)"; then exit 1; fi
read -r API_PORT DESKTOP_PORT DATABASE_MODE <<< "$APP_PORTS"
for port in "$API_PORT" "$DESKTOP_PORT"; do
  # Inspect only the configured listening sockets, never process arguments.
  holders="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null)"
  result=$?
  if [ "$result" -gt 1 ]; then
    echo "[dev:all] could not inspect port $port — refusing to start."
    exit 1
  fi
  if [ -n "$holders" ]; then
    echo "[dev:all] port $port is occupied (PID(s): $(tr '\n' ' ' <<< "$holders")) — refusing to start."
    exit 1
  fi
  if ! uv run --no-sync python scripts/dev_ports.py --check-port "$port"; then exit 1; fi
done
export VITE_DEV_PORT="$DESKTOP_PORT"

if [ "$DATABASE_MODE" = "compose" ]; then
  # An occupied dependency port is reusable only when this checkout's Compose
  # service already owns it. A foreign database is never stopped or adopted.
  DB_HOLDERS="$(lsof -nP -t -iTCP:5432 -sTCP:LISTEN 2>/dev/null)"
  DB_SCAN_RESULT=$?
  if [ "$DB_SCAN_RESULT" -gt 1 ]; then
    echo "[dev:all] could not inspect database port 5432 — refusing to start."
    exit 1
  fi
  if [ -n "$DB_HOLDERS" ] || ! uv run --no-sync python scripts/dev_ports.py --check-port 5432 >/dev/null 2>&1; then
    DB_CONTAINER="$("${COMPOSE[@]}" ps -q --status running db 2>/dev/null)"
    DB_BINDING="$("${COMPOSE[@]}" port db 5432 2>/dev/null)"
    if [ -z "$DB_CONTAINER" ] || [[ "$DB_BINDING" != *:5432 ]]; then
      echo "[dev:all] database port 5432 is occupied outside this checkout's Compose service — refusing to start."
      exit 1
    fi
  fi
  echo "[dev:all] starting Postgres…"
  if ! "${COMPOSE[@]}" up -d db; then exit 1; fi
  echo "[dev:all] waiting for Postgres to be ready…"
  DB_READY=""
  for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T db pg_isready -U solus -d solus </dev/null >/dev/null 2>&1; then
      DB_READY=1
      break
    fi
    sleep 1
  done
  if [ -z "$DB_READY" ]; then
    echo "[dev:all] database did not become ready — refusing to start the API."
    exit 1
  fi
else
  echo "[dev:all] using the configured external database."
fi

# A configured local Redis is a real dependency, including admission limiting.
if ! REDIS_MODE="$(uv run --no-sync python scripts/dev_dependencies.py --redis-mode)"; then exit 1; fi
if [ "$REDIS_MODE" = "compose" ]; then
  if ! uv run --no-sync python scripts/dev_ports.py --check-port 6379 >/dev/null 2>&1; then
    REDIS_CONTAINER="$("${COMPOSE[@]}" ps -q --status running redis 2>/dev/null)"
    REDIS_BINDING="$("${COMPOSE[@]}" port redis 6379 2>/dev/null)"
    if [ -z "$REDIS_CONTAINER" ] || [[ "$REDIS_BINDING" != *:6379 ]]; then
      echo "[dev:all] Redis port 6379 belongs to another service — refusing to start."
      exit 1
    fi
  fi
  if ! "${COMPOSE[@]}" up -d redis; then exit 1; fi
fi
if ! uv run --no-sync python scripts/dev_dependencies.py --schema; then exit 1; fi

# Resolve the developer's selected runtime once; forks receive an absolute pin.
# Never source shell profiles or let a fork search PATH for its interpreter.
require node
if [ -z "${SOLUS_NODE_BIN:-}" ]; then
  SOLUS_NODE_BIN="$(node -p process.execPath)"
fi
case "$SOLUS_NODE_BIN" in
  /*) ;;
  *) echo "[dev:all] SOLUS_NODE_BIN must be an absolute Node >= 22 executable."; exit 1 ;;
esac
if ! "$SOLUS_NODE_BIN" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  echo "[dev:all] Node >= 22 required; select it before running pnpm dev:all."
  exit 1
fi
export SOLUS_NODE_BIN

pids=()
# Kill process GROUPS, not the subshells in front of them.
#
# `(cd packages/api && uv run --no-sync uvicorn …) &` records the SUBSHELL's pid in $!.
# Killing just that pid was measured (2026-08-14) to leave THREE processes alive
# and :8000 still bound. The stubborn one is uvicorn's `--reload` worker: it is a
# multiprocessing spawn child that appears as a bare `python3`, so it survives
# the kill AND hides from `pkill -f uvicorn`. It gets reparented to systemd,
# where no terminal can see or Ctrl-C it — which is how a hours-old server keeps
# serving pre-merge code and greets the next start with a bare Errno 98.
#
# `set -m` above makes each job its own process group whose id equals the job
# pid, so the negative-pid form reaches the whole tree. TERM first, then a
# bounded wait — an unresponsive child gets KILL rather than an orphan.
cleanup() {
  trap - INT TERM EXIT   # idempotent: EXIT would otherwise re-enter after INT
  # Nothing started yet — an early exit (missing .env, busy port) lands here
  # too, and under `set -u` an empty array would abort with "pids[0]: unbound".
  [ "${#pids[@]}" -eq 0 ] && return 0
  echo
  echo "[dev:all] shutting down…"
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  for _ in $(seq 1 10); do
    kill -0 "${pids[0]}" 2>/dev/null || break
    sleep 0.5
  done
  for pid in "${pids[@]}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
}
trap cleanup INT TERM EXIT

# Stripe webhooks can't reach localhost on their own — without the forwarder a
# completed Checkout never flips the local plan/credits. Self-contained: the
# signing secret comes from the CLI itself (env vars override .env values in
# pydantic-settings), so nothing is pasted into .env and it can't drift.
# Only attempted when billing is configured for this checkout (prices/secret set).
#
# Gated on the ROOT .env — the file the API actually reads. This used to grep
# packages/api/.env, which never held a single SOLUS_STRIPE_* key, so the whole
# block was skipped in silence: no forwarder, and not even the "billing is
# configured but the stripe CLI is missing" hint. The test is deliberately loose
# (any two characters, so even an empty `{}` map passes): running the forwarder
# costs nothing, and what actually matters is injecting the CLI's signing secret
# into the API process below. `stripe-setup check` is what tells you whether
# billing is really configured.
STRIPE_FORWARD=""
if grep -qE '^SOLUS_STRIPE_(PLAN_PRICES|WEBHOOK_SECRET)=..' .env 2>/dev/null; then
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

echo "[dev:all] starting API on http://127.0.0.1:$API_PORT (docs at /api/v1/docs)…"
# The signing secret is passed to the API process ONLY (least privilege) — the
# desktop app and forwarder never see it.
if [ -n "${STRIPE_DEV_SECRET:-}" ]; then
  (cd packages/api && SOLUS_STRIPE_WEBHOOK_SECRET="$STRIPE_DEV_SECRET" uv run --no-sync uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port "$API_PORT" --reload) &
else
  (cd packages/api && uv run --no-sync uvicorn --factory solus_api.main:create_app --host 127.0.0.1 --port "$API_PORT" --reload) &
fi
pids+=($!)
API_PID=$!
API_READY=""
for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null; then break; fi
  if uv run --no-sync python scripts/dev_dependencies.py --ready "$API_PORT"; then
    API_READY=1
    break
  fi
  sleep 0.5
done
if [ -z "$API_READY" ]; then
  echo "[dev:all] API failed to become ready; see its startup error above."
  exit 1
fi

# Queue-backed work needs a consumer whenever Redis is configured. The worker
# reads the same anchored runtime Settings as the API, without receiving the
# temporary Stripe webhook signing secret. It is a primary owned child.
WORKER_PID=""
if [ "$REDIS_MODE" != "disabled" ]; then
  echo "[dev:all] starting background job worker…"
  (cd packages/api && uv run --no-sync arq solus_api.worker_main.WorkerSettings </dev/null) &
  WORKER_PID=$!
  pids+=("$WORKER_PID")
fi

# The companion is skipped unless this is set (apps/desktop/src/main/companion.ts),
# so without it the bridge pill can never leave "offline" in dev and no MCP tool
# is reachable. Respects an existing value.
export SOLUS_COMPANION_DEV_CMD="${SOLUS_COMPANION_DEV_CMD:-uv run --no-sync python -m solus_companion}"

# A fork without its private virtualenv dies at spawn with
# `.venv/bin/python3: No such file or directory`, three times, and the bridge
# then reports servers it cannot actually run. Cheap to detect, and the message
# is the whole fix — the install is deliberately NOT run from here, because
# ADR-031 keeps installs out of every launch path.
for lock in integrations/mcp/*/requirements.lock.txt; do
  [ -e "$lock" ] || continue
  fork="$(dirname "$lock")"
  if [ -f "$fork/bin/launch" ] && [ ! -x "$fork/.venv/bin/python3" ]; then
    echo "[dev:all] note: vendored MCP forks are not installed — those servers will fail to start."
    echo "          Run once:  make mcp-forks"
    break
  fi
done

echo "[dev:all] starting desktop app…"
pnpm --filter @solus/desktop dev &
pids+=($!)
DESKTOP_PID=$!

if [ -n "$STRIPE_FORWARD" ]; then
  echo "[dev:all] starting Stripe webhook forwarder (stripe listen)…"
  stripe listen --forward-to "http://127.0.0.1:$API_PORT/api/v1/webhooks/stripe" &
  pids+=($!)
fi

# Only primary services determine stack lifetime. An optional forwarder exit
# must not take down the API or desktop. A primary exit always reaps our tree.
# Uvicorn's reload supervisor can survive a dead worker. Allow transient reload
# gaps, but do not leave a desktop connected to a permanently unhealthy API.
# Probe every five seconds, while checking child liveness twice per second.
# Three consecutive failures allow normal reloads without repeated imports or
# leaving a failed worker hidden behind a living reload supervisor.
API_FAILURES=0
API_HEALTH_TICKS=0
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$DESKTOP_PID" 2>/dev/null; do
  if [ -n "$WORKER_PID" ] && ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "[dev:all] background job worker stopped; shutting down this launch."
    exit 1
  fi
  if [ "$API_HEALTH_TICKS" -eq 0 ]; then
    if uv run --no-sync python scripts/dev_dependencies.py --ready "$API_PORT"; then
      API_FAILURES=0
    else
      API_FAILURES=$((API_FAILURES + 1))
      if [ "$API_FAILURES" -ge 3 ]; then
        echo "[dev:all] API remained unhealthy after reload grace; shutting down this launch."
        exit 1
      fi
    fi
  fi
  API_HEALTH_TICKS=$(((API_HEALTH_TICKS + 1) % 10))
  sleep 0.5
done
echo "[dev:all] API, desktop or background worker stopped; shutting down this launch."
exit 1
