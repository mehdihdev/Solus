# Repository contents and personal branches — SOLUSDEV-260

## Setup

- [ ] Start PostgreSQL, Redis, API and Electron with `pnpm dev:all`; API `/readyz` returns 200.
- [ ] Apply migrations through `a26000000005`. Keep existing user data.
- [ ] Sign into a project with connected GitHub and GitLab repositories, each containing two branches and a text code file. Use two project members to test isolation.
- [ ] Link a local checkout through Home → Local folder. For this session the authorized sample is `/home/beeboss/Desktop/ForgeTS`, repository `PotosnakW/ForgeTS_internal`, branch `vlfh_tsfm`. Preserve its existing edits and conflicts.
- [ ] Companion advertises `local.scan_folder` and `machine.read_code_file`. The approved code reader is automatic; generic `machine.read_file` remains confirmation-gated.

## User flows

1. [ ] Open the graph. Find the named local folder root (ForgeTS). Expand it: requirements appear beneath it, rather than replacing the root with a synthetic account group.
2. [ ] Open the GitHub repository node and its branch selector. Expect remote branches, pagination when required, and a notice that the choice affects only your view and SOL context.
3. [ ] Select `vlfh_tsfm`. While acquisition is pending, the previous graph remains usable. On success, the graph and mention search refresh together. The repository inspector remains associated with its base source.
4. [ ] Close the inspector while a selection is pending, then reopen after completion. Expect the selected branch and updated graph, without stale cached results.
5. [ ] In SOL, select a code file using `@`, and ask for an explanation. Expect actual source-based reasoning with line numbers and origin/branch/commit provenance, not a claim based only on the filename.
6. [ ] With a matching local branch and a preexisting saved edit, repeat the explanation. Expect the saved content and a label that it includes local uncommitted changes. No per-file confirmation is needed for this narrow reader.
7. [ ] With an explicitly selected branch different from the local checkout, repeat. Expect committed remote content, clearly labeled; the checkout must not be switched, stashed, reset or edited.
8. [ ] Select two branches pointing at the same commit. Expect their distinct selected labels and correct local-branch matching even though the immutable snapshot is reused.
9. [ ] Open another SOL window. Change the branch in the workspace. Expect stale mention selections to clear and new searches to use the selected graph. An already admitted SOL turn keeps its original scope.
10. [ ] Sign in as a second member. Their graph stays on their own selection/default. The first member's choice must not modify shared source configuration.
11. [ ] Choose the default view. Expect the shared graph again. Reset during an in-flight poll: a late response must not undo the reset or lose the refresh.
12. [ ] Repeat branch selection and code explanation for GitLab. Unsupported providers show no invented Git branch selector.

## Failures and boundaries

- [ ] Disconnect the provider or use an unavailable branch. Expect a useful failure; the previous ready view remains active.
- [ ] Make two rapid selections. Only the latest request may activate; an older enqueue error cannot overwrite it.
- [ ] Remove access as another tenant. All revision routes refuse access without returning project/source contents.
- [ ] Submit a stale or foreign mention ID. Expect a generic refreshable refusal before model admission; no entity-existence details leak.
- [ ] Try a credential path, symlink, binary file, oversized file, or traversal path. Expect refusal without file contents. Unsupported secure-open platforms fail closed.
- [ ] Disconnect the companion. Expect explicitly labeled remote content when available. If a proven local file disappears during reading, expect an error rather than silently substituting remote content.
- [ ] Link two matching local folders. Ambiguous matches must not silently select one. Verify exact branch matching takes precedence where unique.
- [ ] Verify shared fingerprint/link writes and widget defaults do not adopt a personal snapshot. Existing shared links remain intact when returning to default.

## Known verification limits

GitHub and GitLab are the implemented revision providers. Onshape workspace/version selection requires its native revision adapter and is not covered by this change. Automated tests use scripted model responses; live model quality must be checked in steps 5–9. Never paste credentials or private source bodies into QA logs.
