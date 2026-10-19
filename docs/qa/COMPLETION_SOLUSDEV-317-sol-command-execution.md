# Completion report — SOLUSDEV-317: SOL executes commands

Branch: `SOLUSDEV-317-sol-command-execution`, cut from the unpushed SOLUSDEV-216 head `ff54804c`, so
it carries that work too. 92 commits, 164 files. All sub-branches are merged and their worktrees
removed. Nothing has been pushed.

## What was built

SOL can now run any command the user approves, not only the typed Python, pytest, git and Arduino
verbs it had before.

| Area                                  | What                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Code server (`integrations/mcp/code`) | `code.exec` (one-shot, streamed output); `code.process_start/status/stop` (long-running, at most 4, bounded output rings, killed on shutdown or unlink, orphans reaped on restart); `code.profile_capture/list/delete` (ROS-style environments from a sourced setup file, secret-filtered, stored in `~/.solus`, values never sent to the cloud). OS sandbox for **every** executing tool: macOS `sandbox-exec`, Linux Landlock through a stdlib-only helper; refused when unavailable. The environment probe no longer executes the workspace venv. |
| Command policy                        | Cloud `CommandPolicy` plus a mirrored server table. Denied: shells, wrappers, privilege elevation, inline code, git through exec, remote loaders. Risk badges: network, install, destructive, hardware, remote, runs_shell, project_scripts. A behavioural parity test checks that cloud and server agree.                                                                                                                                                                                                                                           |
| Cloud (`packages/api`)                | Complete-preview approval cards (program path, argv, cwd, environment, profile, sandbox with limitations, risk, fingerprint). Commands are refused instead of parked when redaction would hide argv. One-use plan snapshot. 3000-char outcome tail. Resume turn (`resume_confirmation_id`, once per card, at most 6 in a row). Three process routes, scoped to the caller's own bridge. Five events, recording program basename only. Build-mode prompt guidance. Confirmation routes moved to `routers/sol_confirmations.py`.                       |
| Companion                             | Streams `code.exec` output. Never replays acting `code.*` tools.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Desktop                               | Command card header and badges, expanded preview, Cmd/Ctrl+Enter (armed once the preview has been in view 700 ms; repeats ignored; a fresh keydown is needed; a composer draft wins), output kept after completion, automatic resume, Running processes strip with Output and Stop.                                                                                                                                                                                                                                                                  |

## Governing documents

- **DECISIONS.md:** ADR-031 amendment of 2026-10-18 (`e8af5338`), approved in-chat.
- **Allowlist:** the 7 new entries in `integrations/mcp/code/allowlist.yaml` (`a00bfefd`), approved in-chat.
- **Spec:** `docs/api/code-command-execution.md`, new and authoritative, including the §9 Phase 4 amendments.
- **Updated docs:**
  - `docs/api/code-environment.md`
  - `docs/architecture/local-machine-actions.md`
  - `docs/architecture/code-environment.md`
  - `docs/wireflows/sol-page.md`
  - `docs/wireflows/sol-window.md`
- **Cowork QA:** `docs/qa/COWORK_QA_sol-command-execution.md`

## Verification

| Suite                                                                                                                          | Result                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Desktop (Vitest), full                                                                                                         | 476 files, **5020 passed**. Typecheck clean.                                                                                                                                                                                                |
| Code server + companion (macOS)                                                                                                | 1240 passed. 31 failed, all known before this ticket: 30 Arduino tests (Arduino CLI not installed on this machine) and `test_code_git_execution::test_aggregate_process_output_is_bounded` (`killpg` EPERM inside the Claude Code sandbox). |
| Code server on Linux (container, kernel 7.2, Landlock ABI 10)                                                                  | 599 passed, real-Landlock tests included. The 5 failures were only files missing from the partial copy. Run before the Phase 4 server fixes.                                                                                                |
| API, targeted 317 suites (policy, gate, previews, red team, resume, process routes, confirmations, sol, errors, bridge e2e, …) | **583 passed**                                                                                                                                                                                                                              |
| API, full serial run on the integrated branch (before the Phase 4 fixes)                                                       | 9262 passed, 1 failed (`test_errors` screenshot echo; fixed in `635a551b`, now passing)                                                                                                                                                     |
| Live E2E: real code server through `bin/launch`, MCP stdio, real `sandbox-exec`                                                | **16/16**: confinement, `.git` protection, refusals, profiles, process start/output/stop, kill on shutdown                                                                                                                                  |
| ruff + mypy on every changed `.py` (the H10 scope)                                                                             | clean                                                                                                                                                                                                                                       |

**Not run:** an in-app run of SOL with a real model turn. The dev environment has no
`openai_api_key`, which the existing routing in `orchestration/models.yaml` needs for standard
turns (`seed-provider-keys.py --check`), and the running companion predates this branch. The
Cowork QA file covers the in-app flows. Coverage percentage was not measured, because `pytest-cov`
is not installed.

## Phase 4

- **Security review:** FAIL. 1 critical (the probe executed workspace `.pth` code unsandboxed) and 4 high (argv hidden by redaction, no tamper check on processes, HOME as the workspace, executable caches). All are fixed, plus every medium and low except L4 (residual, below).
- **Code review:** WARNING. 1 high (a failed command was labelled "refused") and 6 medium. All fixed.
- **Automated per-commit security reviews:** about 15 rounds on the deny tables and the sandbox, all addressed. The decisive design call was to deny `git` through `exec` and make the gitdir read-only on macOS, instead of chasing git option grammar.

## Decisions made under delegated judgment

1. Linux accepts any Landlock ABI ≥ 1, so Jetson-class 5.15 kernels work. The card lists the limitations, for example "truncate not confined" below ABI 3.
2. `git` is denied in `code.exec` and `code.process_start`. SOL uses the dedicated git tools. Pull, checkout and clone through SOL would need new git tools in a follow-up.
3. Writable caches were narrowed to data-only directories, which only tightens the approved ADR set. One side effect: `uv venv --python X` cannot download a missing Python inside the sandbox.
4. Cmd/Ctrl+Enter arms only once the preview has been in view, and a composer draft blocks it.
5. Name matching fails closed by prefix outside the workspace and uses exact names for workspace scripts. A workspace link whose target is outside the workspace is judged by the target's real name.
6. Profile capture is refused when `code.profile_list` is unreadable, because the card could not say "replaces existing" otherwise.
7. The resume chain counts claimed-but-streaming resumes, and the conversation row is locked.

## Residual risk (recorded in SECURITY_REVIEW.md addenda)

- The server re-plans at execute time without the approved fingerprint, a sub-second window.
- On macOS, a copied `launchctl` or `osascript` binary escapes the literal `process-exec` denials. The AppleEvents and LaunchServices mach denials still apply.
- On Linux, `.git` metadata protection is detection only. A descendant that leaves the process tree after a snapshot can survive a stop.
- The deny list is defence in depth. Allowed programs such as `make`, `npm run` and `awk` still run project code, and they are badged on the card.

## Needs a human

1. **Sign-offs:** both developers sign the `code` fork's PROVENANCE and the SECURITY_REVIEW 317 section and addenda. The review status is DRAFT.
2. **Allowlist text:** the `probe_environment` reason in `allowlist.yaml` still says "pip list". This is a human allowlist edit.
3. **Hook limit:** the H10 gate's "pytest (full suite)" step runs the whole repository under a 1000 s cap. The API suite alone takes about 2 hours serially, so that step cannot pass in this repository. Flagged per CLAUDE.md §5.
4. **Unrelated commit on this branch:** `5f56c511` "Home redesign — project sidebar beside one project pane" was not made by this work. Its `ProjectFolderCard.tsx::LinkedFolder` fails eslint complexity (13 > 10). Move or fix it before the MR.
5. **Unrelated commit in the merge:** the merge included `a21600000001` (a SOLUSDEV-216 migration) with parameterized downgrade SQL. That change was made to pass the gate and belongs with 216.
6. **Before in-app QA:** seed `OPENAI_API_KEY` (`scripts/seed-provider-keys.py --only openai`) and restart the companion or `dev:all`.
7. **Push and MR.**

## Spec or tooling defects found during implementation

- The spec originally said "no generic command executor" in two documents. Both are now superseded with notes.
- A second top-level `conftest.py` makes mypy resolve the API tests' `from conftest import …` to the wrong file. The code-server fixtures moved to `sandbox_fixture.py`.
- `routers/sol.py` was already above 800 lines. It shrank from 1359 to 1144 lines, which is still over the limit.
