#!/usr/bin/env bash
# Build the Solus local-bridge companion into dist/companion/ (SOLUSDEV-154 / BRG-04).
#
# Produces:
#   dist/companion/solus-companion   PyInstaller onefile binary (host OS/arch —
#                                    build per-platform; no cross-compilation)
#   dist/companion/mcp/              vendored MCP server tree (templates excluded)
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
uv run --package solus-companion --with pyinstaller pyinstaller \
  --onefile \
  --name solus-companion \
  --distpath dist/companion \
  --workpath dist/companion-build \
  --specpath dist/companion-build \
  -p packages/companion/src \
  --noconfirm \
  packages/companion/src/solus_companion/__main__.py

# Vendored MCP servers ride along; *.template.md are repo scaffolding, not payload.
rsync -a --delete --exclude '*.template.md' integrations/mcp/ dist/companion/mcp/

echo "companion built: dist/companion/solus-companion (+ mcp/)"
