# Python CI follow-up — SOLUSDEV-260

## Changes and authority

The user explicitly requested fixing the reported Python failures and removing
`test:python` from CI. The job, its private PostgreSQL service and JUnit artifact
configuration are removed. Python lint/type checks, Node validation, Gitleaks,
build and deployment rules remain. Python tests remain runnable locally.

Governing sources: root AGENTS.md; DECISIONS.md ADR-007; the CI README and
COWORK_QA_ci_performance.md; docs/architecture/hardware-onboarding.md and
docs/schemas/hardware-config.md for migration proof. No application API,
wireflow, schema, migration revision or runtime behavior changes.

The supplied job log reported 7,329 passes, one failure and 28 fixture errors:

- The migration fixture rejected the canonical `solus_test` base name. It now
  accepts that exact name as well as the existing safe suffixed names. It still
  derives a different hashed migration database per checkout/base/worker; schema
  resets reject the original base and every non-migration target.
- The worktree watcher test made two same-size writes without ensuring an mtime
  change. It now explicitly advances the fixture's mtime, so it tests worktree
  ref observation independently of filesystem timestamp granularity. The
  production watcher retains its bounded stat-only behavior.

## Setup

- [ ] Use the SOLUSDEV-260 feature checkout and locked Python 3.12 workspace.
- [ ] Have Git and a disposable PostgreSQL 16 instance with pgvector available.
      Never point tests at development or production data. The test database
      user must be able to create the separate migration database.
- [ ] Set `SOLUS_TEST_DATABASE_URL` to an asyncpg URL ending in `/solus_test`
      for the canonical-name reproduction. Supply local test connection details
      through the environment, not a committed environment file.
- [ ] Keep network access to localhost available for companion socket tests.
- [ ] Use `uv run` or activate the workspace virtual environment so fixture
      subprocesses also resolve its Python interpreter. Calling only
      `.venv/bin/python` without adjusting `PATH` can leave mock subprocesses
      on a system interpreter without the MCP dependency.
- [ ] The human commits/pushes and opens or reopens the MR. No agent push, merge,
      deployment or pipeline execution is part of this change.

## Test walkthroughs

1. [ ] Run both complete migration test modules:

   ```sh
   uv run --no-sync pytest packages/api/tests/test_hardware_data_migration.py \
     packages/api/tests/test_hardware_migration_constraints.py -q -rfE
   ```

   Expect success with the canonical base. Cover extraction, preserved IDs and
   provenance, conflicting data rollback, deleted history, duplicate/invalid
   constraints, locking, concurrent first writes and schema reset isolation.

2. [ ] Inspect the URL guard regressions in the constraints module. Confirm
       canonical and suffixed names work for serial and xdist worker identities;
       unsafe names/workers/drivers/query overrides fail before database access.
       Resetting `solus_test` itself must still fail.
3. [ ] Run `uv run --no-sync pytest packages/companion/tests/test_watch.py -q`.
       Expect all cases to pass, including common worktree refs, source and
       dependency edits, ignored build output, symlinks and bounded traversal.
       The common-ref test must still change its fingerprint after an explicit
       mtime advance; it must not use a sleep or read Git ref contents.
4. [ ] Run `uv run --no-sync pytest infrastructure/ci/tests -q`.
       Expect passing pipeline selection and secret scan checks. Python-changing
       MRs select lint/type checks and Gitleaks; Node checks remain selected for
       Node changes. Tags have no Python test job. Main still selects only image
       build and staging deployment. Feature pushes do not duplicate MR pipelines.
5. [ ] Validate the YAML with GitLab CI Lint using the CI README instructions.
       Expect valid syntax without errors/warnings; a main simulation contains
       only `build:api-image` and `deploy:staging`.
6. [ ] After the human pushes, inspect the new MR pipeline. Confirm there is no
       `test:python` job and no Python JUnit artifact. Other applicable validation
       jobs must remain. Record the pipeline link and fixed commit.

## Local verification evidence

- CI selection tests first failed because the unwanted job was still present;
  after removal, all 61 CI regression tests passed.
- Canonical base acceptance tests first failed for both serial and worker modes;
  after the fixture fix, all 51 migration/guard tests passed on disposable
  PostgreSQL using the exact `solus_test` base name (34 seconds).
- The unchanged watcher test failed under a simulated timestamp collision;
  after explicit timestamp control it passed, as did all five watcher tests.
- The complete companion and CI regression suites passed together: 362 tests.
- Ruff formatting/lint and strict mypy passed for all four changed Python files;
  the final changed files passed Gitleaks.
- Full Python run: 7,370 passed, seven failed, two skipped, one expected failure,
  six live tests deselected, in 13m43s. All seven failures were in PDF tests because
  the local virtual environment lacked the already-locked `pypdfium2==5.13.0`.
  Installed that exact version with wheel hashes from uv.lock, then reran the
  complete PDF module: all 35 passed, including the seven failed cases. No
  dependency manifest or lockfile changed. The complete suite was not repeated
  after this local dependency repair; evidence is the full run plus that rerun.
- GitLab CI Lint: valid, no errors/warnings, no `test:python` in the job inventory.
  Main simulation retained only build and deployment. No pipeline was started.
- No repository commits or pushes were made. The Ponytail plugin is unavailable;
  fresh code, Python and security reviewers provide the review passes.

Removing the job is the requested CI policy change. The local verification above
is separate from pipeline status; future changes require local Python testing
as described in the CI README because the pipeline no longer supplies it.
