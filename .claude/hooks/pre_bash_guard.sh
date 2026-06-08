#!/usr/bin/env bash
# Solus hooks H4+H5 — PreToolUse on Bash
# H4: the remote and main are human territory (ADR-021). H5: dangerous commands blocked or routed to human approval.
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
hook_disabled() { [[ ",${SOLUS_DISABLED_HOOKS:-}," == *",$1,"* ]]; }

CMD="$(jqr '.tool_input.command')"
[[ -z "$CMD" ]] && exit 0
# ECC lesson: never pattern-match heredoc bodies (doc content false-positives) — scan only the pre-heredoc head.
HEAD="${CMD%%<<*}"
CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"

deny() { echo "$1" >&2; [[ -n "${2:-}" ]] && echo "$2" >&2; exit 2; }
ask()  { jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

if ! hook_disabled H4; then
  [[ "$HEAD" =~ git[[:space:]]+push ]] && deny "[H4] BLOCKED: 'git push' is human-only (ADR-021)." "Finish locally; a human reviews, pushes, and opens the MR."
  [[ "$HEAD" =~ (glab[[:space:]]+mr|gh[[:space:]]+pr) ]] && deny "[H4] BLOCKED: opening MRs/PRs is human-only (ADR-021)."
  [[ "$HEAD" =~ git[[:space:]]+branch[[:space:]]+(-D|-d)[[:space:]]+(main|master) ]] && deny "[H4] BLOCKED: deleting main/master."
  [[ "$HEAD" =~ --force-with-lease|--force([[:space:]]|$)|push[[:space:]]+-f ]] && [[ "$HEAD" =~ git ]] && deny "[H4] BLOCKED: force operations on git refs."
  BR="$(git -C "$CWD" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$BR" == "main" || "$BR" == "master" ]]; then
    [[ "$HEAD" =~ git[[:space:]]+(commit|merge|cherry-pick|revert|add|rm|mv) ]] && deny "[H4] BLOCKED: git write operation while on '$BR'. Agents never modify main (ADR-021)." "Checkout the ticket branch first."
  fi
fi

if ! hook_disabled H5; then
  [[ "$HEAD" =~ rm[[:space:]]+(-[A-Za-z]*[rR][A-Za-z]*[[:space:]]+)+.*(^|[[:space:]])(/|~|/\*|\$HOME|\"\$HOME\")([[:space:]]|$|/\*) ]] && deny "[H5] BLOCKED: recursive delete of a root-level path."
  [[ "$HEAD" =~ (curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba|z)?sh ]] && deny "[H5] BLOCKED: piping remote scripts into a shell. Download, inspect, then run."
  [[ "$HEAD" =~ chmod[[:space:]]+-R[[:space:]]+777 ]] && deny "[H5] BLOCKED: chmod -R 777."
  [[ "$HEAD" =~ (mkfs|dd[[:space:]]+[^|;]*of=/dev/) ]] && deny "[H5] BLOCKED: raw device operation."
  [[ "$HEAD" =~ terraform[[:space:]]+destroy ]] && deny "[H5] BLOCKED: terraform destroy is human-only."
  [[ "$HEAD" =~ [[:space:]]\>[[:space:]]*/etc/ ]] && deny "[H5] BLOCKED: writing to system paths."
  if [[ "$HEAD" =~ [Dd][Rr][Oo][Pp][[:space:]]+([Tt][Aa][Bb][Ll][Ee]|[Dd][Aa][Tt][Aa][Bb][Aa][Ss][Ee]|[Ss][Cc][Hh][Ee][Mm][Aa]) ]]; then
    ask "[H5] Command contains DROP TABLE/DATABASE/SCHEMA — confirm this targets a local dev database only."
  fi
  if [[ "$HEAD" =~ git[[:space:]]+clean[[:space:]]+-[a-zA-Z]*x|docker[[:space:]]+system[[:space:]]+prune ]]; then
    ask "[H5] Destructive cleanup ($(printf '%s' "$HEAD" | head -c 60)…) — confirm."
  fi
fi
exit 0
