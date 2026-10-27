#!/usr/bin/env bash
# Build the Solus local-bridge companion into dist/companion/ (SOLUSDEV-154 / BRG-04).
#
# Produces (host OS/arch — build per-platform; no cross-compilation):
#   Linux/Windows:
#     dist/companion/solus-companion   PyInstaller onefile binary
#     dist/companion/mcp/              vendored MCP server tree (templates excluded)
#   macOS (--onedir, sol-drive.md §5 / ADR-041 amendment 2026-10-27):
#     dist/companion/solus-companion/solus-companion   the binary, in its own folder
#     dist/companion/solus-companion/mcp/              the MCP tree beside it
#   A onefile binary runs as a bootloader parent plus a child; on macOS that
#   extra process would sit between the drive helper and Solus.app and fail the
#   helper's caller check (caller_untrusted). config.default_integrations_root
#   looks for `mcp/` beside sys.executable, so the tree goes next to the binary.
#
# electron-builder picks dist/companion/ up via extraResources (see
# apps/desktop/electron-builder.yml) and ships it at <resources>/companion/.
#
# PyInstaller is NOT a project dependency (kept out of every pyproject by
# design): `uv run --with pyinstaller` layers it ephemerally over the
# companion's own resolved environment, so its real deps (websockets, mcp,
# pydantic) are importable during PyInstaller's analysis.
set -euo pipefail

cd "$(dirname "$0")/.."

# The package entry module works as the PyInstaller script directly; -p makes
# `solus_companion` absolute imports resolvable during analysis. If a future
# dep hides imports from the analyzer, add --hidden-import/--copy-metadata
# flags here (see apps/desktop/docs/companion-packaging.md).
if [[ "$(uname -s)" == "Darwin" ]]; then
  mode=--onedir
  out=dist/companion/solus-companion
else
  mode=--onefile
  out=dist/companion
fi

# A previous build of the other mode would leave a file where a folder goes
# (or the reverse); start clean.
rm -rf dist/companion

uv run --package solus-companion --with pyinstaller pyinstaller \
  "$mode" \
  --name solus-companion \
  --distpath dist/companion \
  --workpath dist/companion-build \
  --specpath dist/companion-build \
  -p packages/companion/src \
  --noconfirm \
  packages/companion/src/solus_companion/__main__.py

# Vendored MCP servers ride along; *.template.md are repo scaffolding, not payload.
rsync -a --delete --exclude '*.template.md' integrations/mcp/ "$out/mcp/"

echo "companion built: $out/solus-companion (+ $out/mcp/)"
