#!/usr/bin/env bash
# Solus hook H6 — PreToolUse on Write (new files only)
# Blocks shadow filenames and duplicate exported symbols; warns on basename collisions.
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H6,"* ]] && exit 0

FILE="$(jqr '.tool_input.file_path')"
[[ -z "$FILE" || -e "$FILE" ]] && exit 0   # only guard NEW files
CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
case "$FILE" in /*) REL="${FILE#"$ROOT"/}";; *) REL="$FILE";; esac
BASE="$(basename "$REL")"; NAME="${BASE%.*}"
case "$REL" in */migrations/*) exit 0;; esac  # alembic files legitimately repeat def upgrade/downgrade (mirrors post_edit_tests.sh:27)

# Shadow-version filenames
if [[ "$NAME" =~ (_v[0-9]+|_new|_copy|_old|_final|_backup|_fixed|2)$ && ! "$NAME" =~ ^test ]]; then
  echo "[H6] BLOCKED: shadow filename '$BASE'." >&2
  echo "Extend the original file instead of creating a parallel '${BASH_REMATCH[1]}' version. If a genuinely distinct implementation is needed, name it for what it does." >&2
  exit 2
fi

# Duplicate exported symbols against the existing codebase
CONTENT="$(jqr '.tool_input.content')"
SYMS="$(printf '%s' "$CONTENT" | grep -oE '^(def|class)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*|^export[[:space:]]+(default[[:space:]]+)?(async[[:space:]]+)?(function|class|const)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' 2>/dev/null | awk '{print $NF}' | sort -u | head -20 || true)"
for s in $SYMS; do
  case "$s" in main|setup|run|init|index|app|App|cli|test*) continue;; esac
  HITS="$(git -C "$ROOT" grep -lE "^(def|class)[[:space:]]+${s}\b|^export[[:space:]].*(function|class|const)[[:space:]]+${s}\b" -- '*.py' '*.ts' '*.tsx' 2>/dev/null | grep -vE '(^|/)tests?/' | head -3 || true)"
  if [[ -n "$HITS" ]]; then
    echo "[H6] BLOCKED: symbol '$s' already exists in:" >&2
    printf '%s\n' "$HITS" >&2
    echo "Reuse or extend the existing implementation — do not recreate it (CLAUDE.md §8). If intentionally distinct, rename to reflect the difference." >&2
    exit 2
  fi
done

# Basename collision — advisory only (monorepos legitimately repeat names)
case "$NAME" in index|__init__|types|main|app|config|setup|conftest|utils|constants) exit 0;; esac
DUPS="$(git -C "$ROOT" ls-files "*/$BASE" 2>/dev/null | head -3 || true)"
[[ -n "$DUPS" ]] && echo "[H6] note: files named '$BASE' already exist ($DUPS) — confirm this isn't a duplicate." >&2
exit 0
