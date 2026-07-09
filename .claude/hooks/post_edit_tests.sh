#!/usr/bin/env bash
# Solus hook H9 — PostToolUse on Edit|Write|MultiEdit
# Runs the tests that correspond to the edited source file; reminds TDD-first on brand-new source files.
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H9,"* ]] && exit 0

FILE="$(jqr '.tool_input.file_path')"
[[ -n "$FILE" && -f "$FILE" ]] || exit 0
CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
case "$FILE" in /*) REL="${FILE#"$ROOT"/}";; *) REL="$FILE";; esac
cd "$ROOT" 2>/dev/null || true
R=""; command -v uv >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]] && R="uv run"
TO="$(command -v timeout || command -v gtimeout || echo "")"
twrap() { if [[ -n "$TO" ]]; then "$TO" "$@"; else shift; "$@"; fi; }

# Only enforce inside product source roots
case "$REL" in
  packages/api/*|integrations/*|reasoning/*|livebench/*|apps/desktop/src/*) ;;
  *) exit 0;;
esac
BASE="$(basename "$REL")"; NAME="${BASE%.*}"
case "$BASE" in __init__.py|conftest.py|*.d.ts) exit 0;; esac
case "$REL" in */migrations/*) exit 0;; esac
case "$NAME" in *config|*types|*constants) exit 0;; esac

TESTS=""
case "$BASE" in
  test_*.py|*_test.py|*.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx) TESTS="$REL";;
  *.py)       TESTS="$(git ls-files "*test_${NAME}.py" "*${NAME}_test.py" 2>/dev/null | head -3)";;
  *.ts|*.tsx) TESTS="$(git ls-files "*${NAME}.test.ts" "*${NAME}.test.tsx" "*__tests__/${NAME}*" 2>/dev/null | head -3)";;
  *) exit 0;;
esac

if [[ -z "$TESTS" ]]; then
  # New, untracked source file with no test → TDD reminder
  if ! git ls-files --error-unmatch "$REL" >/dev/null 2>&1; then
    echo "[H9] TDD: '$REL' is a new source file with no corresponding test file." >&2
    echo "Write the failing tests first (CLAUDE.md §6), then implement. Expected: tests matching test_${NAME}.py / ${NAME}.test.ts." >&2
    exit 2
  fi
  exit 0
fi

FAIL=""
for t in $TESTS; do
  case "$t" in
    *.py)
      [[ -n "$R" ]] || command -v pytest >/dev/null 2>&1 || continue
      OUT="$(twrap 90 $R pytest -q "$t" 2>&1)" || FAIL+="--- $t ---"$'\n'"$(printf '%s\n' "$OUT" | tail -25)"$'\n';;
    *.ts|*.tsx)
      OUT="$(twrap 120 npx --no-install vitest run --silent "$t" 2>&1)" || FAIL+="--- $t ---"$'\n'"$(printf '%s\n' "$OUT" | tail -25)"$'\n';;
  esac
done
if [[ -n "$FAIL" ]]; then
  echo "[H9] Tests failing after your edit — fix before moving on:" >&2
  printf '%s\n' "$FAIL" >&2
  exit 2
fi
exit 0
