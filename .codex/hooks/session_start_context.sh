#!/usr/bin/env bash
# Solus hook H13 — SessionStart
# Injects orientation context: branch/ticket, repo state, last validation status, harness pointers.
set -uo pipefail
INPUT="$(cat)" || true
[[ ",${SOLUS_DISABLED_HOOKS:-}," == *",H13,"* ]] && exit 0
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
cd "$ROOT" 2>/dev/null || true
BR="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
TICKET="$(printf '%s' "$BR" | grep -oE '^SOLUSDEV-[0-9]+' || echo 'n/a')"
DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
LASTV="passing/none"
[[ -f .claude/state/last_validation.md ]] && LASTV="FAILING — read .claude/state/last_validation.md first"
CMDS="$(ls .claude/commands 2>/dev/null | sed 's/\.md$//' | tr '\n' ' ' || true)"
SNAP="$(ls -t .claude/state/precompact-*.md 2>/dev/null | head -1 || true)"

cat <<CTX
[Solus session context]
Branch: $BR | Ticket: $TICKET | Uncommitted files: $DIRTY | Last validation: $LASTV
${SNAP:+Recent pre-compaction snapshot: $SNAP (read it if resuming mid-feature)}
Pre-work check (CLAUDE.md §3): identify the governing docs before coding — DECISIONS.md → docs/architecture → docs/api → docs/wireflows → directory CLAUDE.md.
Harness: always-follow rules in .claude/rules/ecc/ · skills in .claude/skills/ (consult before improvising a procedure) · subagent personas in .claude/agents/.
Slash commands: ${CMDS:-none installed}
Hooks are active (H1–H14). If a hook blocks you, fix the cause — never bypass, never edit .claude/hooks or settings.json.
CTX
exit 0
