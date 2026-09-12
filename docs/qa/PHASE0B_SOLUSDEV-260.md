# SOLUSDEV-260 Phase 0b — graph cleanup

The user approved continuing after Phase 0. The approved deletion list is empty.
The later empty-database authorization supersedes the original historical-data setup;
no historical robot, source or configuration retention is claimed verified.

## Governing design and execution

Read workspace-navigation and hardware-onboarding architecture, workspace/hardware API
plans and wireflows, and the hardware-config schema. This maintenance CLI adds no
route, schema or UI flow. Use existing soft deletion; never infer creator identity
from project ownership or arbitrary graph attributes.

Execution: one worker owns `scripts/graph-prune-qa.py` and
`packages/api/tests/test_graph_prune_qa.py`, writing regression tests first. Root
owns this report and the migration preflight. Snapshot/inventory can run alongside
helper implementation; live helper checks and independent code/Python/security
reviews follow implementation. Commit follows verification. Future phases remain
in the supplied order.

## Live evidence

Database `solus`, PostgreSQL 16.14, container `solusdev-260-db`, volume
`solus_pgdata`, bound to `127.0.0.1:5432`. API 8000, renderer 5173, Redis 6379.
Alembic remains `a25100000001`.

Before any cleanup, created a custom-format snapshot:
`/tmp/solus260-snapshots/phase0b-before-cleanup.dump`. `pg_restore --list` succeeded.
SHA-256: `c092bcc6ade81a2478b5c2861391941905e4a1974328c4dbaea0b7594ab17040`.
The snapshot contains account data and remains private outside the repository.

Authenticated workspace inspection shows one `.solus` root with five sections,
6 entities, 5 relations and 0 sources. Direct database inventory confirms these
are the same six legitimate user-created nodes documented in Phase 0. There are
zero live dangling/cross-project edges, CONFIG entries, hardware suggestions or
account connections. No live graph deletion is needed or authorized by the empty
list. Arms and imported documents are absent, so their retention is unverified.

## Phase verification

The final PostgreSQL suite passed **33 tests in 28.47 seconds**, covering dry-run,
apply, repeatability, protected nodes, exact creator attribution, foreign references,
stale attribution and rollback. Tests used only `solus_test_436a6e18_prune`.
Logs: `/tmp/solus260-prune-red.log` and `/tmp/solus260-prune-green.log`. Ruff lint/format and strict mypy pass for both
new Python files; documentation formatting passes.

Independent code/Python and security reviewers passed after the reference and
maintenance-mode findings were fixed. Security approval is explicitly for stopped
writers during maintenance apply; the flag is an operator acknowledgment.

Both live read-only CLI passes returned no candidates. Subsequent SQL confirms
6 live entities, 5 live edges and zero dangling/cross-project edges. No live apply
ran. Current user data remains intact. Apply/rollback behavior is fixture-verified;
historical robots/documents and physical hardware retention remain unverified.
The pre-existing full-suite failures recorded in Phase 0 remain for later phases;
this helper-only phase does not claim the whole repository is green.

## Approved later-phase decision

The user approved one root console logging handler for application logs, including
hardware confirmation timing, for Phase 5. No logging implementation is changed
in this phase.

Ponytail has no callable capability in this session (tool discovery returned none).
Use the required independent reviewers for code simplification and correctness;
do not claim the unavailable plugin ran.

The initial helper integration run passed 24 tests on the isolated PostgreSQL
`solus_test_436a6e18_prune` database. Ruff and strict mypy passed for both new Python
files. Independent code/Python review identified one additional foreign-project
suggestion-reference guard, fixed with regression coverage before commit.
First live dry run returned `candidate_ids: []`, with no test-user allowlist.
No real account was classified as a test account merely to exercise cleanup.

## Operator walkthrough

1. From this checkout with its virtualenv installed, run:
   `.venv/bin/python scripts/graph-prune-qa.py --project-id <project UUID>`.
   Expect a JSON dry-run report with no candidates until test-user IDs are supplied.
2. Add one `--test-user-id <UUID>` for each independently verified test account.
   Only matching manual names with proven creator attribution and no live graph
   links qualify. Missing creator evidence is deliberately ineligible. A project
   creator is not proof of who authored every graph entity.
3. Inspect candidate UUIDs against the project graph and take a private database
   snapshot. Keep actual robot/source/user-created nodes off the deletion list.
4. For maintenance apply, stop every writer sharing the target database and keep
   them stopped through the integrity check. Pass `--apply --writers-stopped`
   alongside the exact reviewed scope. This flag acknowledges the operational
   precondition; it does not detect stopped processes or stop them automatically.
   Never kill a foreign process to meet this precondition.
5. Check live edge endpoints and dependent entries, then repeat the dry run.
   Expect no remaining candidates. Restart only services you own, reload the
   canvas, and verify protected data remains intact.

Apply soft-deletes candidate identities and their eligible direct entries, removes
exact scoped suggestion references, and preserves historical edges/events. Any
live edge (including a binding), artifact-backed entry, foreign reference or
configuration belonging to another graph identity blocks automated eligibility.
This intentionally conservative helper does not recursively prune connected QA
subgraphs or guess creator identities where historical events are unavailable.
