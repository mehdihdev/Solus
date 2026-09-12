# Cowork QA — CI performance

Updated 2026-09-12: the user requested removal of `test:python`. Python tests
are now local verification; Python lint/type checks, Node checks and Gitleaks
remain in CI. Historical timings in the CI README are not current job claims.

## Setup

- [ ] Use GitLab project `solus9903722/Solus`, with the reviewed CI commits applied
      to the human-managed feature branch. Humans push, open/merge MRs and create tags.
- [ ] Confirm `aws-arm` runner is online, staging's existing AWS variables are
      configured, `main` rejects direct pushes, and successful MR pipelines are required.
- [ ] Keep skipped pipelines disallowed for merging. Do not expose CI variables,
      tokens, or job credentials in screenshots or notes.
- [ ] Record pipeline links, job durations and queue durations. Baselines and
      local verification are in `infrastructure/ci/README.md`.

## Before merge

1. [ ] Run GitLab CI Lint using the command in the CI README. Expect a valid main
       simulation containing exactly `build:api-image` and `deploy:staging`.
2. [ ] Open the human-pushed CI MR pipeline. A `.gitlab-ci.yml` change must select
       Python lint/typecheck, Node lint/typecheck/test, and the secret scan; no
       `test:python` job or deployment.
3. [ ] Inspect Python lint: expect the lockfile-pinned Ruff image, no workspace
       dependency installation, and the existing lint check passing.
4. [ ] Run Python tests locally using the CI README setup and command. Ensure
       Git, pgvector and the OCCT/OpenGL runtime are available. Expect a passing
       suite and local slow-test timings. No Python JUnit artifact is expected
       from the pipeline after removal of the job.
5. [ ] Confirm the pipeline no longer queues a Python test job. Record remaining
       job and queue durations separately; the removed job's historical timing
       is not evidence of faster Python tests.
6. [ ] Inspect caches on a second run: Node lint and Python typecheck upload;
       other jobs restore only. A missing cache must reinstall and still pass.
7. [ ] Confirm the secret scan covers the MR commit range, including deleted
       content. A change to `.gitleaks.toml` or `.gitleaksignore` must trigger a full
       history scan. No real credentials are needed for testing.
8. [ ] Run `uv run --locked --all-packages pytest infrastructure/ci/tests -q` locally.
       Expect passing checks, including merge-only content, discarded policy edits,
       invalid revisions and scanner exit propagation.

## Selection and failure paths

1. [ ] Inspect separate representative MR simulations/pipelines: Python changes
       select Python checks; desktop changes select Node checks; Python scripts select
       their Python checks as well; documentation-only changes still select scanning.
2. [ ] In a disposable local copy, change a dependency manifest without updating
       its lock. The locked sync must fail. Restore the copy afterward.
3. [ ] A validation failure must prevent merge. A failed image build must prevent
       the staging deploy job. Do not intentionally break shared staging to test this.
4. [ ] A feature push with an existing MR must not create a second branch pipeline.
       A tag simulation must select validation and a full scan, with no staging deploy.
5. [ ] Confirm non-durable PostgreSQL options appear only on the disposable test
       service. Staging task definitions and persistent database settings are unchanged.

## After the human merges

1. [ ] Open the main pipeline. Expect only `build:api-image` followed by
       `deploy:staging`, with no repeated lint, type checks, tests or secret scan.
2. [ ] Inspect the image build: all Dockerfile copies succeed, dependencies remain
       cached when manifests are unchanged, and required MCP allowlists are included.
3. [ ] Confirm deploy starts only after a successful image build and is not
       automatically interrupted by newer commits once running.
4. [ ] Inspect the ECS rollout and verify staging `/healthz` and `/readyz` return
       healthy responses. A green deploy job only means the rollout was requested.
5. [ ] Record the new pipeline and job timings. Report any remaining runner queue
       delays separately; this change does not increase runner capacity or AWS spend.
