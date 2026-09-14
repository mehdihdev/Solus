# CI verification — 2026-09-14

Verified the current working tree on `SOLUSDEV-261-integration-check`, including
the existing uncommitted local-folder renderer fixes. Those renderer changes
must be included in the submitted revision for these Node results to apply.

| Check | Result |
| --- | --- |
| `pnpm lint` (`lint:node`) | PASS after warning cleanup: zero errors, zero warnings |
| `ruff check .` | PASS |
| `pnpm typecheck` | PASS |
| `mypy packages/api/src packages/companion/src` | PASS: 367 source files |
| `pnpm test` | PASS: 279 shared-types, 3,726 desktop, 25 script tests |
| Desktop production build | PASS |
| Web production build | PASS |
| API Docker image build | PASS after runtime packaging corrections |
| API image application-factory smoke | PASS without host mounts or network; fake signing configuration and writable temporary storage only |
| CI secret scan and working-diff scan | PASS: no leaks |
| Python collection | PASS: 9,128 selected tests, six live tests deselected |

## Python suite and corrections

The broad parallel run reported 9,079 passed, three failed, three skipped, one
expected failure and three collection errors in 20m27s. Live-provider tests were
excluded, and each worker used a disposable database.

All reported failures and collection errors were corrected:

- Onshape spec-cache test supplies the complete existing fastened-mate frame fixture.
- KiCad's spawned writers resolve their own fork's package instead of another
  fork's same-named module. The real competing writes and exact winning bytes are tested.
- Altium discovery checks Windows support and explicit Linux/macOS unavailability.
- Isaac tests have qualified module names instead of colliding with API test names.

The combined affected run then passed **199 tests**, including the formerly
colliding API and Isaac suites, all three failing test areas and new packaging
regressions. Separate focused checks and fresh Python/code/security reviews passed.
These counts overlap; the complete 20-minute suite was not repeated after fixes.

The image smoke uncovered two production packaging omissions hidden by the dev
environment: `solus-contracts` was dev-only, and the required tool-knowledge JSON
was absent. The existing dependency is now installed at runtime, with its source
and exact JSON resource copied into the image. No dependency versions, contracts,
runtime permissions or execution gates changed.

No remote pipeline, image publication or deployment was performed. Live Onshape
testing remains paused at the user's unchanged 70% conservation threshold.

## Node warning cleanup

Removed the 152 ESLint warnings through private component, hook, action and test
helper extractions, an explicit cache return type and benchmark output through
stdout. ESLint configuration and thresholds are unchanged. Test names and
assertions remain intact; the existing tests passed before refactoring.

The final working tree passes strict `eslint . --max-warnings 0`, canonical
`pnpm typecheck`, all 279 shared-types, 3,726 desktop and 25 script tests, and the
desktop production build. The generated API schema is unchanged. These results
apply to the entire uncommitted Node cleanup together, including the local-folder
fixes noted above. Python and web-build results above predate this Node cleanup;
their source was not changed by it.

The refactor follows the existing workspace navigation, local-folder, extension
runtime, Home, SOL, onboarding and sourcing architecture/API/wireflow documents.
No public API, user flow, dependency version or provider quota policy changed.
Fresh security review found no regression in IPC/OAuth boundaries, extension
authorization, approvals or stale-response guards. Live provider acceptance
remains paused; local regression tests use fixtures and mocks.

Fresh TypeScript/code review also passed. Its AST audit confirmed unchanged suite
membership, registration order and lifecycle hooks for 1,284 test registrations
across 79 changed test files, with no assertions removed. Formatting, diff
whitespace checks and a Gitleaks scan of the final Node diff passed. The optional
local application smoke handoff is `COWORK_QA_node-warning-cleanup.md`.
