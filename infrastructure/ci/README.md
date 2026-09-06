# CI performance and staging handoff

Implemented 2026-09-06 on `SOLUSDEV-242-workspace-graph-w2`, at the user's explicit
request to keep the CI fix on the existing branch. Governed by root `AGENTS.md`,
ADR-006/007/032, and `infrastructure/aws/README.md`. No application API, wireflow,
contract, or architecture topology changes.

## Pipeline split

| Pipeline            | Jobs                                                                   |
| ------------------- | ---------------------------------------------------------------------- |
| Merge request       | Relevant Python/Node lint, type checks and tests; secret scan          |
| Main                | `build:api-image` → `deploy:staging` only                              |
| Tag                 | Both validation groups and full-history secret scan; no staging deploy |
| Feature-branch push | No duplicate branch pipeline                                           |

Verified GitLab project safeguards: `main` rejects direct pushes; merging requires
a successful pipeline; skipped pipelines cannot merge. Keep these settings in
place. Changes to CI run both validation groups; Python scripts and the root
Vitest configuration are also covered by the appropriate change filters.

## Evidence and changes

The AWS runner is `t4g.micro` (1 GiB RAM), not the larger machine described by old
CI comments. Recent jobs execute sequentially on runner `53798823`; `needs: []`
cannot manufacture additional runner capacity. CPU credits remained available
during the observed slow runs.

| Observed run                                                                   | Python result | Test execution |
| ------------------------------------------------------------------------------ | ------------- | -------------- |
| [Earlier serial job](https://gitlab.com/solus9903722/Solus/-/jobs/16326931387) | 4,511 passed  | 27m 03s        |
| [Two-worker job](https://gitlab.com/solus9903722/Solus/-/jobs/16328100372)     | 4,525 passed  | 48m 07s        |

These are different revisions, not a controlled benchmark, but they support the
reported regression after introducing workers. CI now uses normal serial pytest
execution. It retains all test discovery and explicitly excludes opt-in live
provider tests. Slow-test durations and JUnit results are saved for diagnosis.

The disposable PostgreSQL service disables `fsync`, `synchronous_commit`, and
`full_page_writes`. Fixture cleanup repeatedly truncates tables; crash durability
adds substantial disk overhead to this throwaway data. SQL constraints,
transactions, authorization tests, migrations, and test isolation remain active.
These options are confined to the CI service, never persistent databases. See
[PostgreSQL's non-durable settings](https://www.postgresql.org/docs/16/non-durability.html).

Controlled local benchmark, identical 43 source/project/team tests with two
workers and PostgreSQL 16: **35.73s → 9.77s** with those options. The same tests
passed in **13.39s serially** with the options. The workstation has more resources
than the runner; these figures are not a predicted GitLab completion time.

Other improvements:

- Ruff uses its small dedicated image, pinned to the version in `uv.lock` and
  checked by a regression test. It no longer installs the application or CAD
  dependencies for lint.
- `uv sync --all-packages --locked` rejects stale locks. Subsequent Python
  commands use `--no-sync`, avoiding additional resolution or environment changes.
- Python type checking and Node lint are the only dependency-cache writers.
  Other jobs only restore caches; cold caches still install dependencies normally.
- MR secret scanning examines every introduced commit, including merge-resolution
  patches and content later deleted. Scanner-policy changes anywhere in the range
  and tag pipelines still scan all history and refs. Invalid ranges fail closed.
  The prior scan inspected 594 commits / 350 MB in 6m 30s on every run.
- Docker exclusions now live at the root build context. Local dependencies,
  caches, environment files, Git metadata and agent state are excluded. The
  existing Dockerfile inputs are retained, including MCP allowlists.

The last observed successful image build took 83s and deploy job took 12.5s,
excluding queue time. Main no longer repeats tens of minutes of validation ahead
of those jobs. Actual post-change timing requires the next human-pushed pipeline.
The deploy job requests the ECS rollout; its completion does not mean the rollout
has already become healthy.

## Verification

- GitLab CI Lint dry-run with `ref: main`: valid, zero warnings/errors, exactly
  `build:api-image` and `deploy:staging`. No pipeline or deployment was triggered.
- All **4,706 application Python tests** passed against a disposable PostgreSQL
  instance with the new settings. The combined run took 7m 44s locally. Eight
  infrastructure assertions had been collected before their scanner arguments
  changed during review; the entire current infrastructure suite was rerun:
  **60 passed**. Existing skips, opt-in live exclusions and the expected failure
  were retained.
- **38 scanner tests** also pass in the actual Python CI image after installing
  Git; shell syntax, Ruff formatting/lint and strict mypy checks pass.
- Real pinned Gitleaks, offline with synthetic repositories only: MR and full
  scans both reject merge-only markers, whether retained or later deleted.
- Lock freshness check passes; the dedicated Ruff image passes repository lint.
- Local API image build passes, with a 14.91 MB transferred build context.
- Fresh code, Python and security reviews approve; all findings were fixed.

No cloud resources, runner size, project settings, remote branches, or deployed
services were changed. The Ponytail plugin is unavailable in this session; the
fresh code review provided the simplification pass. QA steps are in
`docs/qa/COWORK_QA_ci_performance.md`.

To run the local CI checks:

```sh
uv run --locked --all-packages pytest infrastructure/ci/tests -q
```

To validate proposed YAML without starting a pipeline:

```sh
jq -n --rawfile content .gitlab-ci.yml \
  '{content:$content,dry_run:true,include_jobs:true,ref:"main"}' > /tmp/solus-ci-lint.json
glab api --method POST projects/82668446/ci/lint \
  --header 'Content-Type: application/json' --input /tmp/solus-ci-lint.json
```

The local policy checks intentionally support only the expressions used here;
GitLab CI Lint remains the authoritative configuration validator.
