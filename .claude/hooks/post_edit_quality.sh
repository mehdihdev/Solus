#!/usr/bin/env bash
# Solus hooks H7+H8 — PostToolUse on Edit|Write|MultiEdit
# H7: auto-format the touched file. H8: file-scoped lint + types; errors feed back to Claude (exit 2) for immediate fix.
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
hook_disabled() { [[ ",${SOLUS_DISABLED_HOOKS:-}," == *",$1,"* ]]; }

FILE="$(jqr '.tool_input.file_path')"
[[ -n "$FILE" && -f "$FILE" ]] || exit 0
CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
cd "$ROOT" 2>/dev/null || true
R=""; command -v uv >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]] && R="uv run"
ERR=""

case "$FILE" in
  *.py)
    if ! hook_disabled H7; then
      $R ruff format -q "$FILE" >/dev/null 2>&1 || true
      $R ruff check -q --fix "$FILE" >/dev/null 2>&1 || true
    fi
    if ! hook_disabled H8; then
      OUT="$($R ruff check -q "$FILE" 2>&1)" || ERR+="$OUT"$'\n'
      OUT="$($R dmypy run -- "$FILE" 2>&1)" || ERR+="$(printf '%s\n' "$OUT" | grep -E ':[0-9]+: (error|note):' | head -15)"$'\n'
    fi;;
  *.ts|*.tsx|*.js|*.jsx)
    if ! hook_disabled H7; then
      npx --no-install prettier --write "$FILE" >/dev/null 2>&1 || true
    fi
    if ! hook_disabled H8; then
      OUT="$(npx --no-install eslint "$FILE" 2>&1)" || ERR+="$(printf '%s\n' "$OUT" | head -20)"$'\n'
    fi;;
  *.json|*.css|*.md|*.yaml|*.yml)
    hook_disabled H7 || npx --no-install prettier --write "$FILE" >/dev/null 2>&1 || true;;
esac

if [[ -n "${ERR//[[:space:]]/}" ]]; then
  echo "[H8] Lint/type issues in $FILE — fix these now before continuing:" >&2
  printf '%s\n' "$ERR" >&2
  exit 2
fi
exit 0
