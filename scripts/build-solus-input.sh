#!/usr/bin/env bash
# Build the SOL drive helper bundle into dist/solus-input/ (SOLUSDEV-319 drive
# slices 3/3b; docs/architecture/sol-drive.md §2.1 and §5 "Helper packaging";
# ADR-041 H1 and its 2026-10-27 amendments C1 and 3b).
#
# Produces:
#   dist/solus-input/SolusInput.app/Contents/Info.plist
#   dist/solus-input/SolusInput.app/Contents/MacOS/solus-input   the helper; launchd runs it as `serve`
#   dist/solus-input/com.solusforge.solus.input.agent.plist      electron-builder copies it to
#                                                                Solus.app/Contents/Library/LaunchAgents/
#
# electron-builder ships the bundle at <resources>/SolusInput.app. Signing runs only
# when SOLUS_SIGN_IDENTITY is set (hardened runtime, per-binary identifiers);
# identities and notarisation are human; SOLUS_TEAM_ID is required with it and
# is checked against each binary's requirement. A release build refuses every call
# until the team ID placeholder in Sources/SolusInputCore/Signing.swift is set.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build-solus-input: SolusInput.app is macOS only (this is $(uname -s))" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

package=apps/desktop/native/solus-input
app=dist/solus-input/SolusInput.app

swift build --package-path "$package" -c release --product solus-input
bin="$(swift build --package-path "$package" -c release --show-bin-path)"

rm -rf dist/solus-input
mkdir -p "$app/Contents/MacOS"
cp "$package/bundle/Info.plist" "$app/Contents/Info.plist"
cp "$bin/solus-input" "$app/Contents/MacOS/"
cp "$package/bundle/com.solusforge.solus.input.agent.plist" dist/solus-input/

# A release helper must never carry the debug-only unsigned-dev path. Probe: a
# release build answers anything but `serve` with a usage reply that says
# unsignedDev:false; a debug build would run the command instead.
probe="$("$app/Contents/MacOS/solus-input" trust)"
if [[ "$probe" != *'"code":"usage"'* || "$probe" != *'"unsignedDev":false'* ]]; then
  echo "build-solus-input: the release solus-input is not agent-only (got: $probe); refusing" >&2
  exit 1
fi

# The Developer ID requirement, as Sources/SolusInputCore/Signing.swift builds it.
requirement() {
  printf 'anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = "%s" and identifier "%s"' "$1" "$2"
}

if [[ -n "${SOLUS_SIGN_IDENTITY:-}" ]]; then
  if [[ ! "${SOLUS_TEAM_ID:-}" =~ ^[A-Z0-9]{10}$ ]]; then
    echo "build-solus-input: SOLUS_TEAM_ID (10-character Apple team ID) is required when signing" >&2
    exit 1
  fi
  sign() {
    codesign --force --options runtime --timestamp \
      --entitlements "$package/bundle/entitlements.plist" \
      --sign "$SOLUS_SIGN_IDENTITY" "$@"
  }
  sign --identifier com.solusforge.solus.input "$app/Contents/MacOS/solus-input"
  sign "$app"
  codesign --verify --strict --deep "$app"
  if codesign -d --entitlements - "$app/Contents/MacOS/solus-input" 2>/dev/null | grep -q '<key>'; then
    echo "build-solus-input: the helper carries entitlements; it must carry none" >&2
    exit 1
  fi
  codesign --verify -R="$(requirement "$SOLUS_TEAM_ID" com.solusforge.solus.input)" \
    "$app/Contents/MacOS/solus-input"
  echo "solus-input built and signed: $app"
else
  echo "WARNING: SOLUS_SIGN_IDENTITY is not set; $app is UNSIGNED. A release agent exits at" >&2
  echo "         start (own signature) and refuses every peer (caller_untrusted) until it is" >&2
  echo "         signed and the team ID placeholder in Signing.swift is replaced." >&2
  echo "solus-input built (unsigned): $app"
fi
