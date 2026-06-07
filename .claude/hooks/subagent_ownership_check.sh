#!/usr/bin/env bash
# Solus hook H12 — SubagentStop
# Enforces the Phase 2 file-ownership map: changed files must match a manifest in .claude/state/ownership/*.list.
# Manifests are written by the orchestrator before spawning subagents (one glob/prefix per line, # comments allowed).
# Limitation: checks the union of all active manifests (per-subagent attribution isn't available at this hook).
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H12,"* ]] && exit 0

CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
OWN="$ROOT/.claude/state/ownership"
[[ -d "$OWN" ]] || exit 0
PATTERNS="$(cat "$OWN"/*.list 2>/dev/null | sed '/^[[:space:]]*$/d;/^#/d' || true)"
[[ -z "$PATTERNS" ]] && exit 0

CHANGED="$(git -C "$ROOT" status --porcelain 2>/dev/null | awk '{print $NF}' || true)"
[[ -z "$CHANGED" ]] && exit 0

BAD=""
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  ok=0
  while IFS= read -r pat; do
    # shellcheck disable=SC2053
    if [[ "$f" == $pat || "$f" == ${pat%/}/* ]]; then ok=1; break; fi
  done <<< "$PATTERNS"
  [[ $ok -eq 0 ]] && BAD+="$f"$'\n'
done <<< "$CHANGED"

if [[ -n "$BAD" ]]; then
  echo "[H12] Files changed outside every task's ownership manifest (.claude/state/ownership/*.list):" >&2
  printf '%s' "$BAD" >&2
  echo "Revert these changes, or stop and have the orchestrator/human update the ownership map (CLAUDE.md §5 Phase 2)." >&2
  exit 2
fi
exit 0
