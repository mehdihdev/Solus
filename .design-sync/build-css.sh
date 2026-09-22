#!/bin/sh
# Regenerate the design-sync base stylesheet. Run from the repo root whenever
# apps/desktop/src/renderer/src/assets/main.css or preview-overrides.css changes,
# then re-run the converter.
set -e
./.ds-sync/node_modules/.bin/tailwindcss \
  -i apps/desktop/src/renderer/src/assets/main.css \
  -o .design-sync/.cache/tw.css
cat .design-sync/.cache/tw.css .design-sync/preview-overrides.css > .design-sync/solus-base.css
echo "wrote .design-sync/solus-base.css ($(wc -c < .design-sync/solus-base.css) bytes)"
