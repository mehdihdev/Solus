#!/usr/bin/env bash
# Build the SOL drive helper bundle into dist/solus-input/ (SOLUSDEV-319 drive
# slice 3; docs/architecture/sol-drive.md §5 "Helper packaging"; ADR-041 H1 and
# its 2026-10-27 amendment).
#
# Produces:
#   dist/solus-input/SolusInput.app/Contents/Info.plist
#   dist/solus-input/SolusInput.app/Contents/MacOS/solus-input          the helper (bundle executable)
#   dist/solus-input/SolusInput.app/Contents/MacOS/solus-input-launch   execs it, responsibility disclaimed
#
# electron-builder ships it at <resources>/SolusInput.app. Signing runs only
# when SOLUS_SIGN_IDENTITY is set (hardened runtime, per-binary identifiers);
# identities and notarisation are human. A release build refuses every call
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
swift build --package-path "$package" -c release --product solus-input-launch
bin="$(swift build --package-path "$package" -c release --show-bin-path)"

rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$package/bundle/Info.plist" "$app/Contents/Info.plist"
cp "$bin/solus-input" "$bin/solus-input-launch" "$app/Contents/MacOS/"

if [[ -n "${SOLUS_SIGN_IDENTITY:-}" ]]; then
  sign() {
    codesign --force --options runtime --timestamp \
      --entitlements "$package/bundle/entitlements.plist" \
      --sign "$SOLUS_SIGN_IDENTITY" "$@"
  }
  sign --identifier com.solusforge.solus.input.launch "$app/Contents/MacOS/solus-input-launch"
  sign --identifier com.solusforge.solus.input "$app/Contents/MacOS/solus-input"
  sign "$app"
  codesign --verify --strict --deep "$app"
  echo "solus-input built and signed: $app"
else
  echo "WARNING: SOLUS_SIGN_IDENTITY is not set; $app is UNSIGNED. A release helper refuses" >&2
  echo "         every identify/capture/act call (caller_untrusted) until it is signed and the" >&2
  echo "         team ID placeholder in Signing.swift is replaced." >&2
  echo "solus-input built (unsigned): $app"
fi
