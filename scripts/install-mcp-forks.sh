#!/usr/bin/env bash
# Build the vendored MCP forks' runtimes for development.
#
# Python forks (ADR-031 amendment 2026-11-19, docs/architecture/mcp-fork-runtime.md):
# each fork's env lives in the per-user app-data `mcp-envs/<fork>/` — the same
# place a packaged Solus builds it from Settings → Python for local tools — and is
# built by the companion's own `runtime provision`, so dev and prod share one
# code path and one trust rule. An in-tree `<fork>/.venv` is ignored by the
# companion now. Set SOLUS_COMPANION_MCP_ENVS_ROOT to isolate a worktree.
#
# Hash-verified, always: `runtime provision` installs with --require-hashes
# --only-binary=:all: --no-deps from each fork's committed lockfile.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v uv >/dev/null 2>&1 || { echo "[mcp-forks] missing 'uv' — please install it."; exit 1; }

# The base interpreter (CPython 3.12 or 3.13). Explicit so a developer's shell
# python cannot silently change what the envs are built from.
BASE_PYTHON="${SOLUS_MCP_FORK_PYTHON:-python3.12}"
BASE_PYTHON_PATH="$(command -v "$BASE_PYTHON" || true)"
[ -n "$BASE_PYTHON_PATH" ] || {
  echo "[mcp-forks] missing '$BASE_PYTHON' — set SOLUS_MCP_FORK_PYTHON to a 3.12/3.13 interpreter."
  exit 1
}

# The companion CLI finds the forks beside its binary when packaged; in the
# repo it must be told (it fails, never "succeeds", without a forks tree).
export SOLUS_COMPANION_INTEGRATIONS_ROOT="${SOLUS_COMPANION_INTEGRATIONS_ROOT:-$ROOT/integrations/mcp}"

installed=0
skipped=0
echo "[mcp-forks] building Python fork envs from $BASE_PYTHON_PATH (hash-verified)…"
python_rc=0
uv run --package solus-companion python -m solus_companion runtime provision --all \
  --python "$BASE_PYTHON_PATH" || python_rc=$?
if [ "$python_rc" -ne 0 ]; then
  echo "[mcp-forks] Python fork provisioning failed (exit $python_rc) — see the JSON lines above."
  exit "$python_rc"
fi
installed=$((installed + 1))

# ---------------------------------------------------------------- Node forks --
# Same contract as the Python forks above, different ecosystem: `bin/launch`
# resolves a FIXED interpreter and does zero installs, so the node_modules/ tree
# it needs has to be materialised here from the committed, integrity-pinned
# package-lock.json. `npm ci` (never `npm install`) installs exactly the lock;
# `--ignore-scripts` refuses every dependency lifecycle hook — the supply-chain
# hole the vendoring rules exist to close; `--omit=dev` keeps the tree to what
# actually runs.
#
# A missing/old Node is a SKIP, never a failure: most developers touch no Node
# fork, and the Python forks above must still install on their machine. The
# cloud image installs these for real (infrastructure/docker/api.Dockerfile).
NODE_BIN="${SOLUS_NODE_BIN:-$(command -v node || true)}"
NODE_MAJOR=""
if [ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]; then
  NODE_MAJOR="$("$NODE_BIN" --version 2>/dev/null | sed -n 's/^v\([0-9][0-9]*\)\..*/\1/p')"
fi

for lock in integrations/mcp/*/package-lock.json; do
  [ -e "$lock" ] || continue
  fork="$(dirname "$lock")"
  name="$(basename "$fork")"

  if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 22 ] || ! command -v npm >/dev/null 2>&1; then
    echo "[mcp-forks] $name: needs node >= 22 and npm on PATH at install time — skipping"
    echo "            (set SOLUS_NODE_BIN=/absolute/path/to/node, or install Node 22)"
    skipped=$((skipped + 1))
    continue
  fi

  stamp="$fork/node_modules/.solus-lock-sha256"
  want="$(sha256sum "$lock" | cut -d' ' -f1)"
  if [ -d "$fork/node_modules" ] && [ "$(cat "$stamp" 2>/dev/null || true)" = "$want" ]; then
    echo "[mcp-forks] $name: up to date"
    skipped=$((skipped + 1))
    continue
  fi

  echo "[mcp-forks] $name: materializing $fork/node_modules (npm ci, lock-pinned, no scripts)…"
  (cd "$fork" && npm ci --omit=dev --ignore-scripts --no-audit --no-fund)
  [ -d "$fork/node_modules" ] || { echo "[mcp-forks] $name: FAILED — no node_modules"; exit 1; }
  echo "$want" >"$stamp"
  installed=$((installed + 1))
done

echo "[mcp-forks] done — $installed installed, $skipped unchanged/skipped."
if [ "$installed" -gt 0 ]; then
  echo "[mcp-forks] restart the app (or 'pnpm dev:all') so the companion relaunches them."
fi
