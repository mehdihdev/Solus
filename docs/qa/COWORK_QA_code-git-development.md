# Git development QA — SOLUSDEV-261

Live observation, 2026-09-12: SOL exposed all five Git tools and invoked
`code.git_status` once. The real companion returned `workspace_unavailable`,
because this QA project has no linked folder. This verifies tool delivery and
honest refusal, not a repository operation through the live project. SOL's total
callable-tool count includes cloud tools and must not be called the companion
inventory; the repaired bridge reports 29 companion tools.

## Setup

1. [ ] Start this checkout with `pnpm dev:all`; select the QA project and connect
   the companion. Link a disposable ordinary Git repository using native Home →
   Local folder → Link folder. Never select a repository merely by supplying a
   path to a SOL tool: the linked folder defines its scope.
2. [ ] Prepare a branch with one commit and a small staged change. Git identity
   must be configured in this disposable repository. Do not use ForgeTS for writes:
   read-only testing found2 staged,18 unstaged,42 untracked files and1 conflict.
3. [ ] Expect eleven Code tools after the reviewed companion restarts. Git is
   pinned to the host's trusted system executable. This first transport supports
   ordinary contained .git directories and refuses unsupported layout/configuration.

## Reads and approvals

1. [ ] Ask SOL for status, recent log and staged/unstaged diffs. Compare against
   the editor/terminal. Large observations must identify truncation.
2. [ ] Ask SOL to commit the staged change. The card must display the full branch
   ref, current HEAD/index fingerprint, every staged path, complete diff and message.
   Indentation/newlines must be visible. No staging/commit occurs before approval.
3. [ ] Reject the card and verify no commit. Propose again, approve manually and
   compare resulting commit parent, message and diff. Unstaged edits remain intact.
4. [ ] Change the branch to another branch at the same commit/index while a card
   is pending. Approval must refuse as stale, even though the commit OID is equal.
5. [ ] Similarly change index/HEAD after preview; refuse. Resolve manually and
   re-propose; never allow SOL to resolve unrelated conflicts implicitly.

## Push (user-operated; agents never push in this ticket)

1. [ ] Configure a disposable GitHub/GitLab SSH remote, native key and existing
   verified known-host record. No credential value enters SOL or tool arguments.
2. [ ] Ask SOL to propose pushing one exact local commit to one explicit branch.
   Inspect destination, outgoing commits, old remote tip and new commit. A new
   branch must explicitly show an absent prior tip. No force/tags/mirror/deletion.
3. [ ] User approves only the intended disposable push. Independently read the
   remote ref and compare the resulting repository graph node/change signal.
4. [ ] Move the remote tip before approval; expect stale refusal. Missing trusted
   authentication must not invoke arbitrary helpers or change host-key records.

## Failure and cross-feature checks

- [ ] Missing folder/disconnected companion/wrong project cannot execute a write.
- [ ] Extra arguments, coerced booleans, escaping paths and unsafe controls refuse.
- [ ] An oversized patch refuses instead of silently truncating consent.
- [ ] Hooks, custom helper/configuration and external Git directories refuse.
- [ ] Ignored dependency symlinks do not block reads; tracked escapes still refuse.
- [ ] A post-write readback failure says the target may have changed, asks for
  inspection and prohibits automatic retry. It must not say nothing was applied.
- [ ] Failed/uncertain execution creates Error logging with the actual outcome.
- [ ] Approved repository changes update the existing local change-signal/graph path.
  This live graph round-trip remains unchecked until a folder is linked and a user
  approves a disposable change. Final command tails are not streaming log evidence.

## Evidence at handoff

41 Git tests;83 confirmation/bridge tests;246 Code/KiCad-registration tests;18 approval
card tests passed. Independent code/security reviews passed. Read-only ForgeTS status
was tested directly; no file changes, live commit or live push were performed.
Full Phase3 still requires gated file/build/test/flash and incremental output proof.

## Incremental output acceptance (SOLUSDEV-261)

Use the disposable linked workspace `tmp/integration-check-kicad`, with its real
`.venv` (Python3.12.3, pytest9.0.3). Preserve the connected ForgeTS repository.

1. [ ] Through SOL Build, create a small module, a build script which compiles it,
   and a test which asserts its actual behavior. Verify saved-file readback.
2. [ ] Request code.run for the build script. Inspect the compact card: exact
   workspace interpreter, script, arguments, timeout and state-bound preview.
3. [ ] The user approves. While the process is still running, expect plain-text
   output in a bounded scroll area, then the normal final result and output tails.
4. [ ] Request code.test for the disposable test. Approve its concrete card and
   verify test result/readback. No repository commit, push or board access.
5. [ ] Request an explicitly failing disposable run. After user approval expect
   nonzero exit status and the normal Error Logging entry, not a success claim.
6. [ ] Reject a separate card: no command or progress buffer is created.
7. [ ] A second member of the same project cannot read the first member's output.
8. [ ] Disconnect during a command: no automatic command replay. Output does not
   authorize retry or resolve the final result. Never approve an uncertain action
   again to recover output.
9. [ ] Noisy/overlong output marks truncation, keeps memory bounded, and cannot
   starve the final result. Oversized records suppress the affected output stream
   to avoid exposing a continued credential; final redacted tails remain available.

Implemented verification: native+companion388 tests,89.01% coverage; actual MCP
stdio early-output-before-completion proof. Cloud bridge/approval suite133 tests,
plus8 bounded/redaction-buffer cases and populated same-project-owner privacy /
approved lifecycle cases. UI51 tests before the small display extraction; affected
23 tests reran green afterward. Python/TypeScript/security peer review passed.
These test results are distinct from the unchecked live steps above.
# Durable approval recovery — September 13

- [x] Reload the chat with pending build/test cards. The original server-backed
  cards return with unchanged IDs, previews and expiry; no command runs on reload.
- [x] Reject the redundant failure card after the user's separate failure test
  completed. The card disappears without executing a second command.
- [x] Approve refreshed build and pytest cards after the earlier previews expired.
  Actual results: build exit 0; pytest exit 0, 3 passed with 3 non-failing
  inherited-configuration warnings (`asyncio_mode`, `timeout`, `timeout_method`).
  Both results persisted at 2026-09-13 17:37 UTC; neither command was rerun
  during read-only verification.
- [ ] Reopen again; decided cards must not return as awaiting approval.
- [x] Automated owner/conversation isolation, concurrent duplicate requests,
  expiry, separate arguments and delayed-response-after-decision regressions pass.

The active-card API is documented in `docs/api/API-implementation.md` §11. It
returns only the current user's unexpired pending cards for the owned conversation,
without tool arguments. Thirty-minute expiry and single-use execution are unchanged.
Typing agreement in a chat does not execute arbitrary code. Repeating an identical
pending request reuses its original card. Historical assistant prose remains history;
the current card state and execution result are authoritative.

## lint:node repair — SOLUSDEV-261

The CI failure reproduced as three `complexity` errors (and 152 warnings).
Extracted the linked-folder header and equivalent scan/project/attempt helpers;
no route, UI flow, expiry, or project-scope behavior changed. Governing documents:
`docs/architecture/local-folders.md`, `docs/api/local-folder.md`, and the LOCAL
FOLDER section of `docs/wireflows/home.md`.

- [x] Root `pnpm lint`, matching `lint:node`: exit 0, zero errors, 151 warnings.
- [x] Existing folder-card, hook and binding suites: 57 tests pass before and
  after refactoring, including stale project completions and offline states.
- [x] Desktop Node and renderer type checks; scoped formatting and diff checks.
- [x] Independent code and security reviews of this repair: no findings.
- [ ] Optional visual smoke: Home → Local folder still shows the same linked
  path, scan state, editor availability and detected project rows.
