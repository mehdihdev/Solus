# SOLUSDEV-260 repository context follow-up

## Implemented behavior

GitHub/GitLab repository nodes offer personal branch selection. Immutable graph
snapshots preserve real entity IDs; every graph read, mention lookup and admitted
SOL turn resolves the user's effective scope. Shared source configuration remains
unchanged. Pending/failed acquisition preserves the last usable view, with generation
guards preventing late jobs or enqueue failures from overriding newer selections.
Distinct branch labels remain personal even when their commit snapshot is reused.

SOL can read bounded, line-numbered code rather than relying on metadata. Matching
saved local code takes precedence and is labeled with branch and commit, including
uncommitted edits. Git identity uses tracking remotes, worktree metadata and safe
normalization. The actual local-folder root remains visible in the graph, with
dependencies beneath it. Ambiguous repo matches are refused.

The human approved automatic `machine.read_code_file` activation in-session. The
native reader caps reads at 128 KiB and refuses credential paths, traversal, symlinks,
binary and special files. Generic file reads remain confirmation-gated. Tool-result
text is redacted before truncation and remains untrusted structured data.

`pnpm dev:all` now owns the ARQ worker when Redis is configured, including cleanup
and failure supervision. Without that worker, a branch acquisition would stay queued.

## Governing documentation

- `docs/architecture/source-revisions.md`, `local-folders.md`, `sol-context-layers.md`
- `docs/api/source-revisions.md`, `local-folder.md`
- `docs/schemas/source-revisions.md`
- `docs/wireflows/workspace.md`
- `docs/qa/SOLUSDEV-260-local-code-policy.md`

The new route plan uses the standard data envelope. OpenAPI and desktop schema were
regenerated. Migration `a26000000004` was applied to the existing local database
after a private backup. No user checkout, saved edit, or conflict in ForgeTS was changed.
Follow-up migration `a26000000005` adds the revision-reference index concurrently;
upgrade/rollback/re-upgrade passed in an isolated database before local application.

## Live evidence

- Corrected account authenticated in the browser; ForgeTS is a named local-clone root.
- Real GitHub discovery returned five branches.
- Selecting `vlfh_tsfm` completed background acquisition and refreshed the graph to
  commit `0a3eae0beec8`; the local clone link remained present.
- `@rnn_encoder.py` resolved to `forgets/encoders/rnn_encoder.py` in that view.
- A real SOL turn read saved local text and explained `RNNEncoder`, recurrent/output
  dropout and its forward pass with line references, branch and commit provenance.
- Final verification used the graph-bound `read_code_file` tool, after excluding
  its raw primitive from the model registry and adding entity IDs to graph context.
  It returned saved local content without an approval prompt. A turn while the
  companion was reconnecting correctly used and labeled the remote fallback.
- OpenAI `text-embedding-3-small` calls returned HTTP 200 during these live turns.
- Direct production provider/native-reader checks also read the same 1,026-byte,
  31-line file. No credentials or private source bodies were added to test logs.

## Verification and reviews

Tests were written first, including authorization, races, local identity and read
boundaries. Fresh security review passed; general/Python and TypeScript reviews
found branch-label and failed-reset polling defects, both fixed and re-reviewed.

Recorded focused checks: 57 API content-reader tests; 301 companion tests; 38 launcher
tests; 10 revision-route tests after envelope correction; 8 picker tests; sidebar
18 tests. Final desktop suite: 3,614 passed; desktop build and typecheck pass.
Changed-file
ESLint has no errors (one size warning plus an ignored generated file); Ruff and
mypy checks pass. Existing unrelated
repository-wide lint debt is not represented as green. Coverage percentages were
not measured because the coverage plugin is unavailable.
The requested Ponytail capability is not installed or exposed in this session;
fresh code review and the picker simplification were performed with repository
review agents instead.

Full API run: 5,423 passed, 6 skipped, 5 failed and 28 setup errors. That run
overlapped final edits. Setup errors required an explicit isolated
`SOLUS_TEST_DATABASE_URL`; the bridge fixture also required the virtualenv on PATH.
With those settings, affected groups returned 96 passed and three outdated
hardware-head assertions. Those assertions were corrected and all 16 hardware
constraint tests passed. The already-corrected launcher suite passed all 38 tests.
Final code-reader registry, prompt, runtime/neighbouring tools and context suites
passed 32, 113, 64 and 72 tests respectively. No failures remain from the full
run; this is full-run coverage plus focused final reruns, not a claim of one
uninterrupted all-green run on the final commit.

## Scope and runtime limits

Only GitHub and GitLab revision adapters are implemented. Other providers report
unsupported; Onshape workspaces/versions need a native adapter and are not claimed
as Git branches. Secure local code reads currently use POSIX descriptor traversal;
unsupported platforms fail closed.

Electron on this machine repeatedly failed to launch its GPU child process during
the default launch. Live verification used `--in-process-gpu` passed to Electron,
with the API and worker in separate owned terminals. This workaround changes no
application code or sandbox setting. The browser SOL route was used for the visible
chat check, with the real desktop companion providing local data.

User-flow handoff: `docs/qa/COWORK_QA_repository-revisions.md`.
