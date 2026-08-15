#!/usr/bin/env bash
# SOLUSDEV-55 — run the whole stack with one command:
#   Postgres (docker) → FastAPI backend (:8000) → Electron desktop app.
# Ctrl+C tears all of them down.
set -uo pipefail
# Job control, deliberately, in a non-interactive script: it puts every
# background job in its own process group, which is what lets cleanup() kill a
# whole tree instead of just the subshell in front of it. See cleanup().
set -m
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f docker-compose.dev.yml"

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

echo "[dev:all] starting Postgres…"
$COMPOSE up -d db

echo "[dev:all] waiting for Postgres to be ready…"
for _ in $(seq 1 30); do
  if $COMPOSE exec -T db pg_isready -U solus -d solus >/dev/null 2>&1; then break; fi
  sleep 1
done

pids=()
# Kill process GROUPS, not the subshells in front of them.
#
# `(cd packages/api && uv run uvicorn …) &` records the SUBSHELL's pid in $!.
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

# Refuse to start onto an occupied port, and say WHO has it. uvicorn's own
# "[Errno 98] Address already in use" names neither the offender nor the fix,
# and the usual offender is an orphaned API from an earlier session that no
# terminal can Ctrl-C — so "just restart your shell" does not help either.
#
# Deliberately does NOT kill it: a dev script silently killing a process it did
# not start is how someone loses a debugger they had attached. Print the command
# and let a human decide.
# Two separate questions, because they have different answers: is the port taken
# (any LISTEN), and can we name the owner (only for processes this user owns —
# a root-owned listener shows no pid= at all). Reporting the first without the
# second still beats Errno 98.
port_taken() { [ -n "$(ss -ltnH "sport = :$1" 2>/dev/null)" ]; }
port_holder() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1; }
if port_taken 8000; then
  API_PORT_PID="$(port_holder 8000)"
  echo "[dev:all] port 8000 is already in use — not starting a second API."
  if [ -n "$API_PORT_PID" ]; then
    # The socket is usually held by uvicorn's --reload WORKER, and killing only
    # the worker invites the supervisor to respawn it. Report the whole group and
    # suggest killing that, so one command actually frees the port.
    API_PORT_PGID="$(ps -o pgid= -p "$API_PORT_PID" 2>/dev/null | tr -d ' ')"
    ps -o pid,pgid,lstart,args -p "$API_PORT_PID" 2>/dev/null | tail -n +2 | cut -c1-140 | sed 's/^/          /'
    if [ -n "${API_PORT_PGID:-}" ]; then
      echo "          whole group:"
      pgrep -g "$API_PORT_PGID" 2>/dev/null | while read -r p; do
        ps -o pid,args -p "$p" 2>/dev/null | tail -n +2 | cut -c1-140 | sed 's/^/            /'
      done
    fi
    echo
    echo "          If that is a leftover API from an earlier session, free it with:"
    if [ -n "${API_PORT_PGID:-}" ]; then
      echo "              kill -- -$API_PORT_PGID     # the whole group, supervisor + worker"
    else
      echo "              kill $API_PORT_PID"
    fi
    echo "          (do not 'pkill -f uvicorn' — the --reload worker is a bare"
    echo "           python3, so that misses the process actually holding the port)"
  else
    echo "          The owner belongs to another user (no pid visible). Try:"
    echo "              sudo ss -ltnp 'sport = :8000'"
  fi
  exit 1
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

# The companion is skipped unless this is set (apps/desktop/src/main/companion.ts),
# so without it the bridge pill can never leave "offline" in dev and no MCP tool
# is reachable. Respects an existing value.
export SOLUS_COMPANION_DEV_CMD="${SOLUS_COMPANION_DEV_CMD:-uv run python -m solus_companion}"

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

if [ -n "$STRIPE_FORWARD" ]; then
  echo "[dev:all] starting Stripe webhook forwarder (stripe listen)…"
  stripe listen --forward-to http://127.0.0.1:8000/api/v1/webhooks/stripe &
  pids+=($!)
fi

wait
