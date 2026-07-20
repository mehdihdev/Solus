# Completion Report — SOLUSDEV-152: Remove test data & make Solus production-usable

**Branch:** `SOLUSDEV-152-prod-readiness` (integrated, all sub-branches merged and
deleted) · **Diff vs origin/main:** 127+ files, ≈ +2,900 / −10,900 lines.
**Status:** ready for human review, push, and MR.

## Governing docs consulted

DECISIONS.md (ADR-005/006/007/008/009/016/019/020/021/024/028/032),
docs/api/API-implementation.md, apps/desktop/CLAUDE.md, root CLAUDE.md §5–§9.
docs/architecture and docs/wireflows are empty (.gitkeep) — no structure was invented;
this ticket deletes fabrications and fixes config, it adds no new system structure.
Kickoff Q&A (human-answered): demo data **deleted outright** (no demo mode); ARQ worker
**degraded mode documented** + truthful `/readyz`; TestDesign/ **deleted from HEAD**;
**SOLUSDEV-82 landed first** (merged to main before the desktop workstreams ran).

## What was built (by workstream)

- **WS-A (truth-in-UI):** `workspaceData.constants.ts` (918-line strider-qd12 dataset)
  deleted with all 10 imports. Honest, state-aware empty states on
  Graph/Alerts/Bench/SOL/Home/Team (new shared `ScreenEmptyState`); real live reads
  wired where fakes lived (`useGraphSummary`: real entity/relation/source counts; real
  project name in the topbar). Onboarding de-simulated: real per-source sync progress
  (`buildProgress.ts` on `getSyncs`/`pollSync`), real entity count, honest retryable
  errors; Onshape/ROS tiles removed; KiCad copy corrected; TEMPLATE_ROBOTS and
  BUILD_LOG_LINES deleted. Net −4,150 lines in the renderer alone.
- **WS-B (deploy):** api.Dockerfile — factory CMD, migrations entrypoint (bounded,
  fail-fast), fixed a third boot blocker (deps layer built an empty solus-api wheel),
  non-root user (uid 10001). taskdef.json rewritten to consumed `SOLUS_*` env; secrets
  strictly in `secrets[]`. `/readyz` reports queue/redis truthfully (config-level
  truth; degraded mode never fails readiness). `cancel_job` semantics documented.
  Degraded no-worker mode documented in `infrastructure/aws/README.md`.
  **Empirically verified:** image boots a fresh Postgres → migrations → 200s, as non-root.
- **WS-C (env):** `env.mega.example` is a complete boot checklist — every consumed key
  present/commented, `/api/v1` drift fixed, `AUTO_CREATE_TABLES=false`, dead `.aws.env`
  block removed, `apps/web` block + env-sync target added, SecretStore provisioning of
  AI keys documented (they are secrets named `anthropic_api_key` etc., NOT env vars).
- **WS-D (build guard):** production `electron-vite build` fails hard without
  `VITE_SUPABASE_URL`/`ANON_KEY` (`prodAuthGuard` plugin); all dev-bypass branches are
  dead-code-eliminated from every built bundle (electron-vite v5 forces
  NODE_ENV=production for all builds — bypass exists only in the dev server). Proofs on
  real builds: no-env build fails; env build passes; bundle greps for
  `dev-bypass-token`/`dev@solus.local`/`strider-qd12` → 0 hits.
- **WS-E (identity):** electron-builder → `com.solusforge.solus` / "Solus"; placeholder
  publish feed + dev-app-update.yml removed (auto-update unwired); package.json scaffold
  author/homepage scrubbed. Signing/notarization deferred to SOLUSDEV-148/149.
- **WS-F (hygiene):** TestDesign/ deleted (recover:
  `git checkout 68b8e63 -- TestDesign/`); tmp/ gitignored; temp-PROPOSAL folded into
  `docs/api/gateway-embeddings.md` (0 dangling refs); sol.py budget-gate comment fixed;
  dead `stripe_secret_key` removed; blank-`SOLUS_SECRETS_BACKEND` footgun fixed
  (`'' → None`, prod hard-fail preserved + tested); API-implementation.md refreshed
  (consent/subscription live, `/readyz` semantics, SOL routes live) with captured JSON.

## Verification

Final integrated pass: **pytest 1015 passed / 3 skipped · vitest 78 files, 477 tests ·
env-sync 38 · ruff + format + mypy (96 files) + eslint (0 errors) + tsc all clean.**
TDD used for every behavior change (RED confirmed before implementation in each
worktree task). Alembic single head `20af242f48a0`.

**Phase 4 reviews:** fresh-context code review — APPROVE, 0 critical/high; its one
MEDIUM (orphaned MO-04 classify modules) fixed in `933cd25`. Security audit — PASS,
0 critical/high; its MEDIUM (root container, pre-existing) fixed + verified in
`2d707a3`; its jobs-isolation-test recommendation already covered by
`test_jobs_are_team_scoped`.

## Delegated-judgment decisions

- TestDesign/ deleted from HEAD (user silent on Q3; consistent with "delete outright").
- tmp/pdfs personal images MOVED to session scratchpad (`repo-tmp-rescued/`), not
  destroyed, despite ticket saying delete — irreversibility caution.
- Template drift: `SOLUS_RATE_LIMIT_PER_MINUTE` 60→120, `SOLUS_TRIAL_DAYS` 14→30 to
  match code defaults — flag if the old template values were the intended policy.
- taskdef image tag `latest`→`arm-latest` + ARM64 runtime (matches what CI actually
  builds; the old pair was a guaranteed pull/exec-format failure).
- `/readyz` uses config-level truth, not a live Redis ping (readiness must not gain a
  new crash/latency surface; degraded is an accepted state).
- ClassifyIndicator/useClassifyPreview kept (tested MO-04 work) with UNWIRED headers
  pointing at SOLUSDEV-132/134 rather than deleted.
- `credentialActions` split into `passwordActions`/`linkActions` (lint budget, no
  behavior change) during WS-D.

## Human actions required before/at deploy

1. Secrets Manager: add `database_url` key to the staging DB secret; create the
   Supabase JWT secret and replace the `XXXXXX` ARN suffix in `taskdef.json`; grant the
   execution role `GetSecretValue` on both.
2. `.gitlab-ci.yml` migrate job: proposal at
   `infrastructure/ci/PROPOSAL-migration-deploy-step.md` (decision checklist inside;
   entrypoint migration already covers correctness meanwhile).
3. `API_KEYS_REFERENCE.md` (git-excluded, human-owned) is wrong: provider keys are
   SecretStore refs (`anthropic_api_key`/`openai_api_key`/`google_api_key`), not
   `SOLUS_ANTHROPIC_API_KEY`; `SOLUS_S3_BUCKET` is unconsumed.
4. Stale remote/local ticket branches (100/102/103/111/115/135/147/83/85/86…) verified
   squash-merged — prune at will; SOLUSDEV-89's branch/worktree stays (ticket open).

## Known gaps / follow-ups (not this ticket)

- `cancel_job` marks CANCELLED without aborting; a real fix is cheap (guard
  `_mark_job` overwrite + worker pre-start status check) — belongs to a runtime ticket.
- No `taskRoleArn` in taskdef: connector-credential reads under the AWS secret backend
  need a least-privilege task role when connector sync deploys (SOLUSDEV-144).
- API-implementation.md §1 local-run recipe (SQLite) is broken by JSONB columns —
  pre-existing; needs a rewrite pass.
- Cosmetic test-fixture residue ("Priya"/strider.dev emails) in settings/auth/component
  tests — never ships in bundles.
- Hook harness: H9's `vitest --silent <file>` crashes on vitest 3 and its TDD guard
  misses `.test.tsx` companions / resolves against the main checkout for worktrees;
  H2 rejects the harness's auto `worktree-agent-*` branch names. Humans own hook fixes.

## QA handoff

`docs/qa/COWORK_QA_SOLUSDEV-152.md` — self-sufficient pass/fail plan: setup, fresh
onboarding, all screens in empty + synced states, deploy/env/build-guard proofs,
82-regression surface, and known-good exclusions.
