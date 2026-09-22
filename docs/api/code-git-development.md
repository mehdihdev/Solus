# Code repository operations — SOLUSDEV-261

This supplement extends `docs/api/code-environment.md` and the existing owned Code
server. Governing documents: ADR-031/032, architecture/code-environment.md,
architecture/local-machine-actions.md and contracts/action-gate.md,
contracts/bridge-protocol.md. No HTTP route, generic command frame, new server,
contract enum or MachineServer executor is introduced. The integration-check
packet explicitly authorizes building Git reads and gated commit/push operations.
Human provenance sign-offs remain human-owned; implementation and local tests do
not constitute shipping approval.

## Frozen tool interface

All tools use the linked workspace root, never caller-selected repositories,
executables, raw argv, environment, remote URLs or configuration. Reject unknown
fields. Composed names have the `code.` prefix.

| Suffix | Input | Result |
| --- | --- | --- |
| git_status | `{}` | `{ok,branch,head,index_fingerprint,staged,unstaged,untracked,conflicts,truncated}` |
| git_log | `{limit?:10}` integer 1..50 | `{ok,commits:[{oid,subject,authored_at}],truncated}` |
| git_diff | `{scope:"staged"\|"unstaged",paths?:string[]}` max32 paths | `{ok,diff,truncated}` |
| git_commit | `{message,expected_head,expected_index_fingerprint,dry_run?:false}` | Complete plan or execution result |
| git_push | `{remote,branch,expected_head,expected_remote_head,dry_run?:false}` | Complete plan or execution result |

Full Git object IDs must match the repository's object format. An index fingerprint
is SHA-256 of the actual index bytes, represented as four 16-hex chunks separated
by colons. It is not a tree OID: dry-run must not create Git objects with write-tree.
Commit message is nonblank, at most 1000 characters. Remote name max64; branch
max200 and validated by Git ref-format rules. Paths max512, canonical relative
POSIX paths, no empty/dot/dot-dot/option-prefixed segments or symlinks; refuse .git.

## Boundaries and implicit execution

Only ordinary repositories whose `.git` is a real contained directory are supported
in this first slice. Refuse bare repositories, external worktree/common directories,
symlink escapes, alternate object stores, submodules and repository replacement.
Readonly observations may report conflicts; mutations refuse unmerged indexes,
detached HEAD, in-progress merge/rebase/cherry-pick and unsupported sparse indexes.

Use a verified installed Git executable from fixed trusted roots, with argv lists,
closed stdin, bounded output and a process-group timeout. No caller Git options.
Disable optional locks for observation. Scrub inherited Git configuration variables;
ignore global/system config and disable hooks, signing, editors, filesystem monitor,
external diff, textconv and external attributes. Refuse configuration enabling
unknown executable helpers or unsafe transports. Never print credential-bearing
configuration, URLs or raw error output. Short stable refusal codes become MCP
failures, not successful dictionaries.

Read calls have a 10-second command bound and 256KiB aggregate output bound. Returned
text is bounded to 16KiB and explicitly marked truncated. A plan is always complete:
max40 rows, fields max400 characters, with a fingerprint covering the full original
message/patch and state; a patch that cannot fit refuses rather than truncates.

## Commit

Commit only the already staged index. Never git add/reset/amend/checkout/resolve.
Preview names every staged path, the complete staged diff, message, full symbolic
branch reference, HEAD and index fingerprint. The branch reference participates in
the fingerprint and is rechecked even when two branches share the same HEAD.
Unstaged changes remain untouched. Require a nonempty index diff.
Revalidate complete repository identity, HEAD and index immediately before invoking
commit. Serialize owned operations and refuse existing Git locks. An external Git
client is not cooperating with the companion lock: document that final race rather
than claiming OS-level compare-and-swap. Read back the resulting commit's parent,
message and tree/diff; mismatches after execution mean uncertain, nonretryable outcome.

## Push

Push one exact local commit to one explicit branch of an existing configured remote.
No force, deletion, tags, mirror, wildcard refspec, config overrides or URL input.
Preview includes credential-free destination identity, outgoing commits, local HEAD
and observed remote branch tip. Null remote tip means the explicitly previewed
branch does not exist. Refuse multiple URLs/push URLs, URL rewriting, custom remote
helpers, proxy commands and unsafe protocols. HTTPS and fixed native SSH are the
only eligible transports; credential execution must remain a fixed trusted mechanism,
never a repository helper. If supported authentication is unavailable, report that
without falling back to an arbitrary helper or changing credentials.

The initial authenticated transport is a pinned native `/usr/bin/ssh` with
`-F /dev/null`, BatchMode, StrictHostKeyChecking, ProxyCommand=none,
ClearAllForwardings, PermitLocalCommand=no and IdentityAgent=none. Permit only
`git@github.com` or `git@gitlab.com`, port22 and canonical owner/repository paths.
Use existing native default identity files and known-host records; the tool never
reads, returns or changes private keys and never adds a host key. Clear inherited
SSH agent/options. HTTPS requiring credentials is unavailable until a separate
trusted delivery mechanism exists. No arbitrary host probes from repository data.

Freshly check remote tip and local state before push. Use only a normal fast-forward
push, never force-with-lease. Refuse a moved remote tip and non-fast-forward history.
Read back remote tip after success. A timeout or failed post-write read is an uncertain
outcome, never an automatic retry. Tests use an injected disposable local transport;
production must not accept file:// or caller transport flags. Agents do not perform
live pushes under this ticket's standing instructions; the user operates that gate.

## Approval, errors and graph

Both mutations require confirmation and trusted `requires_complete_preview` policy.
`dry_run:true` returns `{ok:true,dry_run:true,preview,fingerprint}` with no filesystem
mutation. Each execution repeats the same plan/state checks. Missing/changed previews
cannot park or execute. Result includes `changed`, `exit_code`, bounded sanitized
output, read-back identities and `uncertain` when appropriate. The existing failed
Code-action recording and local change-signal seams apply; verify their coverage
when registering these operations. Final output tails are not incremental streaming.

## Execution and ownership

Sequence: publish schema → worker Git modules/tests → parent registration/gate →
independent code/Python/security review and temporary-repository proof. Worker owns
only `integrations/mcp/code/solus/git_operations.py`, `git_execution.py` and tests
`test_code_git_operations.py`, `test_code_git_execution.py`. Parent owns this plan,
roster/server/allowlist, bridge complete-preview registration and QA. Write tests first.
Do not touch ForgeTS while testing; it has an existing unresolved conflict.
