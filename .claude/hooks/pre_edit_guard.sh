#!/usr/bin/env bash
# Solus hooks H1+H2+H3 — PreToolUse on Edit|Write|MultiEdit
# H1: block edits to human-owned files. H2: enforce ticket-branch discipline. H3: block secrets being written.
set -uo pipefail
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || { echo "[hooks] jq missing — guards skipped. Install jq." >&2; exit 0; }
jqr() { printf '%s' "$INPUT" | jq -r "$1 // empty"; }
hook_disabled() { [[ ",${SOLUS_DISABLED_HOOKS:-}," == *",$1,"* ]]; }

FILE="$(jqr '.tool_input.file_path')"
[[ -z "$FILE" ]] && exit 0
CWD="$(jqr '.cwd')"; CWD="${CWD:-$PWD}"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
case "$FILE" in /*) REL="${FILE#"$ROOT"/}";; *) REL="$FILE";; esac

# ---- H1: protected paths (human territory) ----
if ! hook_disabled H1; then
  case "$REL" in
    DECISIONS.md|CLAUDE.md|packages/contracts/*|.claude/settings.json|.claude/settings.local.json|.claude/hooks/*|.gitlab-ci.yml|.env|.env.*)
      echo "[H1] BLOCKED: '$REL' is human-owned (DECISIONS.md / contracts / harness / CI / env)." >&2
      echo "Propose the change in your design-review questions or completion report instead of editing it (CLAUDE.md §5, §9)." >&2
      exit 2;;
  esac
fi

# ---- H2: branch discipline (ADR-021) ----
if ! hook_disabled H2; then
  BR="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ -n "$BR" && "$BR" != "HEAD" ]]; then
    if [[ "$BR" == "main" || "$BR" == "master" ]]; then
      echo "[H2] BLOCKED: editing files while on '$BR'. Agents never modify main (ADR-021)." >&2
      echo "Checkout the ticket branch first: git checkout -b SOLUSDEV-<n>-<slug> (or the existing one)." >&2
      exit 2
    fi
    if [[ ! "$BR" =~ ^SOLUSDEV-[0-9]+([-/].+)?$ ]]; then
      echo "[H2] BLOCKED: branch '$BR' doesn't match SOLUSDEV-<n>-<slug> or SOLUSDEV-<n>/<task> (CLAUDE.md §5 Branch discipline)." >&2
      echo "If this branch is intentional, a human can set SOLUS_DISABLED_HOOKS=H2 for this session." >&2
      exit 2
    fi
  fi
fi

# ---- H3: secrets about to be written ----
if ! hook_disabled H3; then
  CONTENT="$(printf '%s' "$INPUT" | jq -r '((.tool_input.content // "") + "\n" + (.tool_input.new_str // "") + "\n" + ((.tool_input.edits // []) | map(.new_str // "") | join("\n")))')"
  if [[ -n "${CONTENT//[[:space:]]/}" ]]; then
    HIT="$(printf '%s' "$CONTENT" | grep -nEi \
      -e 'AKIA[0-9A-Z]{16}' \
      -e '\-\-\-\-\-BEGIN [A-Z ]*PRIVATE KEY\-\-\-\-\-' \
      -e 'sk-ant-[A-Za-z0-9_-]{20,}' \
      -e 'gh[pousr]_[A-Za-z0-9]{20,}' \
      -e 'glpat-[A-Za-z0-9_-]{20}' \
      -e '(api[_-]?key|secret|token|passwd|password)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_/+=.-]{16,}["'"'"']' \
      2>/dev/null | grep -viE 'example|placeholder|dummy|changeme|your[_-]|<[^>]+>|xxxx|from_env|secrets_manager' | head -3 || true)"
    if [[ -n "$HIT" ]]; then
      echo "[H3] BLOCKED: possible secret in content for '$REL':" >&2
      printf '%s\n' "$HIT" | cut -c1-80 >&2
      echo "Secrets live in env vars / AWS Secrets Manager only (CLAUDE.md §7). Use a placeholder and document the env var." >&2
      exit 2
    fi
  fi
fi
exit 0
