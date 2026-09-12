#!/usr/bin/env bash
# Materialize the fork-private dependency trees the vendored MCP servers launch
# from: a `.venv/` per Python fork, a `node_modules/` per Node fork.
#
# ADR-031 splits this out deliberately: `bin/launch` does ZERO network I/O and
# ZERO installs, and resolves a fixed `<fork>/.venv/bin/python3`. Something has
# to create that interpreter, and this is it — the "companion install/update
# step" the fork READMEs and `bin/launch` both point at. Without it every
# vendored server dies with
#   /usr/bin/env: '<fork>/.venv/bin/python3': No such file or directory
# and the companion retries it three times before giving up, so the bridge
# connects with no usable tools.
#
# Hash-verified, always: the lockfiles carry `--hash=sha256:` for every wheel
# and `--require-hashes` makes pip refuse anything that does not match. These
# are third-party CAD integrations running on an engineer's machine with access
# to their designs; an unverified install here is the supply-chain hole the
# vendoring rules exist to close.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v uv >/dev/null 2>&1 || { echo "[mcp-forks] missing 'uv' — please install it."; exit 1; }

# The interpreter the forks are locked against. Kept explicit rather than
# inherited so a developer's shell python cannot change what gets installed.
BASE_PYTHON="${SOLUS_MCP_FORK_PYTHON:-python3.12}"
command -v "$BASE_PYTHON" >/dev/null 2>&1 || {
  echo "[mcp-forks] missing '$BASE_PYTHON' — set SOLUS_MCP_FORK_PYTHON to a 3.12 interpreter."
  exit 1
}

installed=0
skipped=0
for lock in integrations/mcp/*/requirements.lock.txt; do
  [ -e "$lock" ] || continue
  fork="$(dirname "$lock")"
  name="$(basename "$fork")"

  # A lockfile without a POSIX launcher is nothing this platform can run
  # (Windows-only CAD tools ship `launch.cmd` only).
  if [ ! -f "$fork/bin/launch" ]; then
    echo "[mcp-forks] $name: no POSIX launcher — skipping"
    skipped=$((skipped + 1))
    continue
  fi

  venv="$fork/.venv"
  stamp="$venv/.solus-lock-sha256"
  want="$(sha256sum "$lock" | cut -d' ' -f1)"

  # Idempotent: re-running is free, and a changed lockfile forces a rebuild.
  # The venv is REPLACED rather than updated — an incrementally-patched
  # environment is not the one the hashes describe.
  if [ -x "$venv/bin/python3" ] && [ "$(cat "$stamp" 2>/dev/null || true)" = "$want" ]; then
    echo "[mcp-forks] $name: up to date"
    skipped=$((skipped + 1))
    continue
  fi

  echo "[mcp-forks] $name: materializing $venv ($BASE_PYTHON, hash-verified)…"
  rm -rf "$venv"
  # `--copies`, and NOT `uv venv`, on purpose. uv symlinks the interpreter out
  # to the system python, and the companion REFUSES that: it fully resolves
  # `.venv/bin/python3` and requires the result to live inside the integrations
  # root ("REFUSED private interpreter … resolves outside", config.py). The
  # private interpreter is meant to be part of the verified tree, so it must be
  # a real copy. uv still does the installing below — it is only the venv
  # bootstrap that has to be stdlib.
  "$BASE_PYTHON" -m venv --copies "$venv"
  uv pip install --quiet --python "$venv/bin/python3" --require-hashes -r "$lock"

  # bin/launch resolves exactly this path, and the companion re-resolves it
  # against the install root — check both, or the failure resurfaces at spawn
  # as the error this script exists to prevent.
  [ -x "$venv/bin/python3" ] || { echo "[mcp-forks] $name: FAILED — no $venv/bin/python3"; exit 1; }
  case "$(readlink -f "$venv/bin/python3")" in
    "$ROOT"/integrations/mcp/*) ;;
    *)
      echo "[mcp-forks] $name: FAILED — interpreter resolves outside the fork tree;"
      echo "            the companion would refuse it. Is $BASE_PYTHON a real interpreter?"
      exit 1
      ;;
  esac
  echo "$want" >"$stamp"
  installed=$((installed + 1))
done

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
