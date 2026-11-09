#!/usr/bin/env bash
# Build Solus.app main's XPC client for the SOL drive agent (SOLUSDEV-319 drive
# slice 3b; docs/architecture/sol-drive.md §2.1; ADR-041 amendment 2026-10-28)
# into apps/desktop/native/solus-input-xpc/build/Release/solus_input_xpc.node.
#
# Default: against Electron's headers for the electron version in
# apps/desktop/package.json (what Solus.app loads).
# --node: against the local Node's headers instead, for `npm test` in that
# directory (an Electron build cannot load in plain Node).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build-solus-input-xpc: the XPC client is macOS only (this is $(uname -s))" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
root="$PWD"
gyp="$root/node_modules/.bin/node-gyp"
[[ -x "$gyp" ]] || { echo "build-solus-input-xpc: node-gyp not found; run pnpm install" >&2; exit 1; }

cd apps/desktop/native/solus-input-xpc
if [[ "${1:-}" == "--node" ]]; then
  "$gyp" rebuild
  echo "solus-input-xpc built against Node $(node -v) (tests only)"
else
  electron="$(node -p "require('$root/apps/desktop/package.json').devDependencies.electron || require('$root/apps/desktop/package.json').dependencies.electron")"
  electron="${electron#^}"
  electron="${electron#~}"
  "$gyp" rebuild --target="$electron" --dist-url=https://electronjs.org/headers --arch="$(uname -m)"
  echo "solus-input-xpc built against Electron $electron"
fi
