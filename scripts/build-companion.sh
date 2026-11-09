#!/usr/bin/env bash
# Build the Solus local-bridge companion into dist/companion/ (SOLUSDEV-154 / BRG-04).
#
# Produces (host OS/arch — build per-platform; no cross-compilation):
#   Linux/Windows:
#     dist/companion/solus-companion   PyInstaller onefile binary
#     dist/companion/mcp/              vendored MCP server tree (templates excluded)
#   macOS (--onedir, sol-drive.md §5 / ADR-041 amendment 2026-10-28):
#     dist/companion/solus-companion/solus-companion   the binary, in its own folder
#     dist/companion/solus-companion/mcp/              the MCP tree beside it
#   Onedir so every Mach-O is signed in place: a onefile build unpacks
#   unsigned code into a temp dir at run time. config.default_integrations_root
#   looks for `mcp/` beside sys.executable, so the tree goes next to the binary.
#
# electron-builder picks dist/companion/ up via extraResources (see
# apps/desktop/electron-builder.yml) and ships it at <resources>/companion/.
#
# PyInstaller is NOT a project dependency (kept out of every pyproject by
# design), but it IS pinned: the binary it produces is what gets signed and
# shipped, so the bootloader must not change under a rebuild. 6.22.3 is the
# latest 6.x on PyPI as of 2026-10-28 (released 2026-09-12); bump deliberately.
PYINSTALLER_VERSION=6.22.3
# `uv run --with pyinstaller==…` layers it ephemerally over the
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

uv run --package solus-companion --with "pyinstaller==$PYINSTALLER_VERSION" pyinstaller \
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

# macOS signing (sol-drive.md §5): hardened runtime, the companion's own
# identifier, verified against the Solus team's Developer ID requirement.
# Signing is human-gated: it runs only when SOLUS_SIGN_IDENTITY is set.
companion_id=com.solusforge.solus.companion
if [[ "$(uname -s)" == "Darwin" && -n "${SOLUS_SIGN_IDENTITY:-}" ]]; then
  team="${SOLUS_TEAM_ID:-}"
  if [[ ! "$team" =~ ^[A-Z0-9]{10}$ ]]; then
    echo "build-companion: SOLUS_TEAM_ID (10 upper-case letters/digits) is required when signing" >&2
    exit 1
  fi
  # Hardened runtime, no extra entitlements (see companion-packaging.md).
  sign() {
    codesign --force --options runtime --timestamp --sign "$SOLUS_SIGN_IDENTITY" "$@"
  }
  # Nested Mach-Os first (dylibs, extension modules, the Python library), then
  # the main binary; a parent signed before its children would not verify.
  while IFS= read -r -d '' f; do
    if [[ "$(file -b "$f")" == *Mach-O* ]]; then
      sign "$f"
    fi
  done < <(find "$out/_internal" -type f -print0)
  sign --identifier "$companion_id" "$out/solus-companion"
  requirement="anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6]"
  requirement+=" and certificate leaf[field.1.2.840.113635.100.6.1.13]"
  requirement+=" and certificate leaf[subject.OU] = \"$team\" and identifier \"$companion_id\""
  codesign --verify --strict -R="=$requirement" "$out/solus-companion"
  echo "companion built and signed ($companion_id): $out/solus-companion (+ $out/mcp/)"
else
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "WARNING: SOLUS_SIGN_IDENTITY is not set; the companion is UNSIGNED (not shippable:" >&2
    echo "         notarisation needs every Mach-O signed with the hardened runtime)." >&2
  fi
  echo "companion built: $out/solus-companion (+ $out/mcp/)"
fi
