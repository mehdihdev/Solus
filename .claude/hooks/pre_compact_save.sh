#!/usr/bin/env bash
# Solus hook H14 — PreCompact
# Saves a work-state snapshot before context compaction so long feature sessions don't lose the thread.
set -uo pipefail
INPUT="$(cat)" || true
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H14,"* ]] && exit 0
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
STATE="$ROOT/.claude/state"; mkdir -p "$STATE"
TS="$(date +%Y%m%d-%H%M%S)"
F="$STATE/precompact-$TS.md"
{
  echo "# Pre-compaction snapshot $TS"
  echo "branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  echo; echo "## Working tree"; git -C "$ROOT" status --porcelain 2>/dev/null || true
  echo; echo "## Recent commits"; git -C "$ROOT" log --oneline -5 2>/dev/null || true
} > "$F"
ls -t "$STATE"/precompact-*.md 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
echo "Preserve through compaction: the current ticket/branch, in-progress files, unfinished protocol phase, and unanswered design-review questions. Snapshot saved to $F."
exit 0
