#!/bin/sh
# Scan every introduced commit; retain full scans when scanner policy changes.
set -eu

refuse() {
    printf '%s\n' "Secret scan refused: $1" >&2
    exit 2
}

validate_commit() {
    case "$1" in
        ''|*[!0-9a-f]*) refuse "expected a full commit SHA" ;;
    esac
    [ "${#1}" -eq 40 ] || refuse "expected a full commit SHA"
    git cat-file -e "$1^{commit}" 2>/dev/null || refuse "commit is unavailable"
}

head=${CI_COMMIT_SHA-}
validate_commit "$head"
set -- gitleaks detect --source . --config .gitleaks.toml --no-banner --redact
# Explicit options replace gitleaks' defaults; retain all refs and emit merge patches.
full_log_opts='--full-history --all --diff-merges=separate'

if [ -n "${CI_COMMIT_TAG-}" ]; then
    exec "$@" "--log-opts=$full_log_opts"
fi

[ "${CI_PIPELINE_SOURCE-}" = merge_request_event ] || refuse "unsupported pipeline source"
base=${CI_MERGE_REQUEST_DIFF_BASE_SHA-}
validate_commit "$base"
[ "$base" != "$head" ] || refuse "merge request commit range is empty"
git merge-base --is-ancestor "$base" "$head" || refuse "merge request base is not an ancestor"

# Inspect commits, not just the final diff: a reverted policy change still warrants a full scan.
policy_changes=$(git log --full-history --format=%H "$base..$head" -- .gitleaks.toml .gitleaksignore)
if [ -z "$policy_changes" ]; then
    set -- "$@" "--log-opts=--full-history --diff-merges=separate $base..$head"
else
    set -- "$@" "--log-opts=$full_log_opts"
fi

exec "$@"
