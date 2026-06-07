# Git Workflow — Solus (replaces ECC git-workflow.md)

This file supersedes generic git-workflow guidance. Authority: CLAUDE.md §5 Branch discipline and DECISIONS.md ADR-021. We use **GitLab**, not GitHub.

## The model
- One ticket = one feature branch = one MR. Branch name: `SOLUSDEV-<n>-<kebab-slug>` (e.g. `SOLUSDEV-34-implement-onshape-integration`).
- Subagent worktrees branch FROM the feature branch, named `SOLUSDEV-<n>/<task>`, and merge back INTO it. The orchestrator removes worktrees and deletes merged sub-branches.
- All work for a feature stays on its branch namespace. Never another feature's branch. Never main.

## What agents do
- Create/checkout the ticket branch and sub-branches.
- Make focused local commits as workflow mechanics. Message format: `SOLUSDEV-<n>: <imperative summary>` (e.g. `SOLUSDEV-34: parse Onshape mass properties into entities`). Body optional; reference the spec section when non-obvious.
- Merge completed sub-branches into the feature branch; clean up worktrees.
- Keep commits small and coherent — one logical change per commit. Never mix refactors with behavior changes in one commit.

## What agents NEVER do (hook-enforced, H2/H4)
- `git push` in any form. The remote is human territory.
- Open or merge MRs (`glab mr`, `gh pr`).
- Commit, merge, or stage anything while on main/master.
- Force-push, rewrite history a human has seen, or delete main.
- Bypass a failing hook to get a commit through.

## What humans do
- Review the integrated feature branch, make any final commits, push, open the MR in GitLab, merge to main after code review, run the Cowork QA pass.

## Conflict hygiene
- Sync the feature branch by merging main INTO it (after a human has pushed/fetched), not by rebasing shared history.
- If a merge conflict touches `packages/contracts/` or any document in docs/, stop and flag — those are human-resolution territory.
