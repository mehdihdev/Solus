#!/usr/bin/env bash
# Solus hooks H10+H11 — Stop
# H10: agent may not finish with a failing validation pass on its diff (lint, types, tests, secrets, duplication).
#      Loop-guarded: after 3 forced continuations it allows stop with a loud warning.
# H11: advisory reminder about handoff artifacts (completion report + COWORK_QA file).
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H10,"* ]] && exit 0

CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
cd "$ROOT" 2>/dev/null || exit 0
STATE="$ROOT/.claude/state"; mkdir -p "$STATE"
TO="$(command -v timeout || command -v gtimeout || echo "")"
twrap() { if [[ -n "$TO" ]]; then "$TO" "$@"; else shift; "$@"; fi; }

# Loop guard
ACTIVE="$(jqr '.stop_hook_active')"
COUNT=0; [[ -f "$STATE/stop_attempts" ]] && COUNT="$(cat "$STATE/stop_attempts" 2>/dev/null || echo 0)"
if [[ "$ACTIVE" == "true" && "$COUNT" -ge 3 ]]; then
  echo 0 > "$STATE/stop_attempts"
  echo "[H10] WARNING: validation still failing after 3 fix attempts — allowing stop. A HUMAN must review .claude/state/last_validation.md before this branch goes anywhere." >&2
  exit 0
fi

# Scope: diff vs main + working tree
CHANGED="$( { git diff --name-only main...HEAD 2>/dev/null; git status --porcelain 2>/dev/null | awk '{print $NF}'; } | sort -u | sed '/^$/d' || true)"
if [[ -z "$CHANGED" ]]; then echo 0 > "$STATE/stop_attempts"; rm -f "$STATE/last_validation.md"; exit 0; fi
PY="$(printf '%s\n' "$CHANGED" | grep -E '\.py$' | while read -r f; do [[ -f "$f" ]] && echo "$f"; done || true)"
TS="$(printf '%s\n' "$CHANGED" | grep -E '\.(ts|tsx)$' | while read -r f; do [[ -f "$f" ]] && echo "$f"; done || true)"

FAIL=""
run() { local label="$1"; shift; local out; out="$("$@" 2>&1)" || FAIL+="### $label"$'\n'"$(printf '%s\n' "$out" | tail -30)"$'\n\n'; }

if [[ -n "$PY" ]]; then
  R=""; command -v uv >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]] && R="uv run"
  run "ruff (changed .py)"  $R ruff check -q $PY
  run "mypy (changed .py)"  $R mypy --no-error-summary $PY
  run "pytest (full suite)" twrap 600 $R pytest -q
fi
if [[ -n "$TS" ]]; then
  run "eslint (changed .ts)" npx --no-install eslint $TS
  [[ -f apps/desktop/tsconfig.json ]] && run "tsc --noEmit" npx --no-install tsc --noEmit -p apps/desktop
  if npx --no-install vitest --version >/dev/null 2>&1; then
    run "vitest related" twrap 300 npx --no-install vitest related --run $TS
  fi
fi
if command -v gitleaks >/dev/null 2>&1; then
  run "gitleaks (branch commits)" gitleaks detect --no-banner --redact --log-opts "main..HEAD"
  run "gitleaks (working tree)"  gitleaks protect --no-banner --redact
fi
if npx --no-install jscpd --version >/dev/null 2>&1; then
  ALL="$(printf '%s\n' "$CHANGED" | while read -r f; do [[ -f "$f" ]] && echo "$f"; done | tr '\n' ' ')"
  [[ -n "${ALL// /}" ]] && run "jscpd (duplication >5%)" npx --no-install jscpd --silent --threshold 5 --min-tokens 50 $ALL
fi

if [[ -n "$FAIL" ]]; then
  echo $((COUNT + 1)) > "$STATE/stop_attempts"
  printf '%s\n' "$FAIL" > "$STATE/last_validation.md"
  echo "[H10] Validation gate FAILED — fix before finishing (details also in .claude/state/last_validation.md):" >&2
  printf '%s\n' "$FAIL" | head -60 >&2
  exit 2
fi

echo 0 > "$STATE/stop_attempts"; rm -f "$STATE/last_validation.md"
# H11 advisory (non-blocking)
if [[ ",${SOLUS_DISABLED_HOOKS:-}," != *",H11,"* ]]; then
  N="$(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ')"
  if [[ "$N" -gt 10 ]] && ! printf '%s\n' "$CHANGED" | grep -q 'COWORK_QA_'; then
    echo "[H11] note: ${N} files changed and no COWORK_QA_<feature>.md in the diff — if this is feature handoff, Phase 5 artifacts (completion report + Cowork QA file) are still owed." >&2
  fi
fi
exit 0
