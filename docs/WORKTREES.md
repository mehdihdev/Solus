# Worktrees & Lanes — the rules of the road

**Ticket:** SOLUSDEV-222 (SOLUS-CTR-07) · **Authority:** CLAUDE.md §5, ADR-021, ADR-032, `CODEOWNERS`

Sixteen lanes build in parallel, each in its own terminal. Worktrees isolate the
filesystem; they do **not** stop two lanes editing the same file and colliding at merge.
Directory ownership does. This document is the protocol; `CODEOWNERS` is the map; the
`lint:lane-ownership` CI job is the enforcement.

---

## 1. One lane = one branch = one worktree

|                     |                                                                     |
| ------------------- | ------------------------------------------------------------------- |
| **Branch**          | `SOLUSDEV-<epic#>-lane-<slug>` — e.g. `SOLUSDEV-214-lane-workspace` |
| **Worktree**        | one per lane, one terminal per worktree                             |
| **Owner handle**    | `@lane-<slug>` in `CODEOWNERS` — the slug is the same string        |
| **Sync**            | merge `main` **into** the lane, daily                               |
| **Boundary**        | a lane never edits outside its owned paths                          |
| **Cross-lane need** | becomes a LANE 0 contract ticket, never a direct edit               |

### Why not `lane/<slug>`

The lane epics say `lane/<slug>`. That name **cannot be used**: hook H2
(`.claude/hooks/pre_edit_guard.sh:35`) blocks every `Edit`/`Write` on a branch not
matching `^SOLUSDEV-[0-9]+([-/].+)?$`, and ADR-021 locks ticket-based naming. A lane
branch called `lane/workspace` fails on the first file touched, on every file, forever.

`SOLUSDEV-<epic#>-lane-<slug>` satisfies both: it passes H2 unmodified, it carries the
epic number so the branch traces to its ticket, and the CI check still reads the lane
from the `-lane-<slug>` suffix. No hook change, no ADR amendment.

### Why merge, not rebase

The epics say "daily rebase on `main`". ADR-021 and `.claude/rules/common/solus-git-workflow.md`
forbid rewriting history a human has seen, and a lane branch is pushed and reviewed. So:
**`git merge main` into the lane**, never `git rebase main`. Same currency, no rewritten
history, and the merge commits are the record of when each lane last synced.

---

## 2. Spawning a lane worktree

From the main checkout, once per lane:

```bash
LANE=workspace            # the CODEOWNERS slug
EPIC=214                  # the lane's epic number

git worktree add ../solus-$LANE -b SOLUSDEV-$EPIC-lane-$LANE main
cp .env.mega ../solus-$LANE/          # secrets: never committed, never generated
cd ../solus-$LANE
make bootstrap                        # pnpm install + uv sync --all-packages + make hooks
pnpm env:sync                         # .env.mega -> .env, apps/*/.env, packages/api/.env
```

Notes that cost an hour each if skipped:

- **`make hooks` is part of `make bootstrap`** and does `chmod +x .claude/hooks/*.sh`. A
  worktree without it has every guard silently disabled — no branch check, no secret
  scan, no Stop gate.
- **`.env.mega` is the only file you copy by hand.** Every per-package `.env` is
  _generated_ from it by `pnpm env:sync`; never hand-edit a generated file
  (`docs/env-consolidation.md`).
- **The test database is already per-worktree.** `packages/api/tests/conftest.py:64-74`
  derives `solus_test_<sha1(abs path to packages/api)[:8]>` and creates it on demand, so
  two worktrees never share a suite DB. You only need to export
  `SOLUS_TEST_DATABASE_URL` when running **two suites inside the same checkout** (e.g.
  an xdist run alongside a manual one). Never point it at a dev database.
- **Run pytest from `packages/api`**, not the repo root — the root has a wider
  `testpaths` and different collection behaviour.

Tearing a lane down after its MR merges:

```bash
cd /path/to/main/checkout
git worktree remove ../solus-$LANE
git branch -d SOLUSDEV-$EPIC-lane-$LANE
```

---

## 3. Ownership

`CODEOWNERS` maps every path to exactly one owner. Read it top-down; **later rules win**.
The `*` default assigns everything unclaimed to `@shared`, so there is no unowned path by
construction.

**`@shared` is not a free-for-all.** A lane MR touching an `@shared` path **fails** the CI
check. That is the design: the cross-lane need becomes a LANE 0 contract ticket. A human
may set `LANE_OWNERSHIP_OVERRIDE=1` on a pipeline for a one-off; agents never do, and the
violations still print in the log.

**GitLab CODEOWNERS is a Premium feature.** On Free the file is inert — it does not gate
approvals. The CI job is the only real enforcement, and it parses `CODEOWNERS` as its
single source of truth, so there is no second map to keep in sync.

⚠️ **The check is a guardrail, not a control.** It fails open on the branch name: a branch
without a `-lane-<slug>` suffix is skipped entirely, so `SOLUSDEV-214-workspace` edits anything
unchecked. That is deliberate — it is what keeps LANE 0 and ordinary ticket branches from being
blocked — but it means the check catches mistakes, not a determined bypass. Likewise
`LANE_OWNERSHIP_OVERRIDE` is a plain CI variable, and `.gitlab-ci.yml` is agent-editable under
ADR-032 tier-1, so the override is defeatable by the party it constrains. If this ever needs to
be a real control, gate it on a masked, Maintainer-only project variable and make the branch
suffix mandatory. Today: treat it as the thing that stops an honest mistake becoming a merge
conflict.

### Checking before you push

```bash
node scripts/check-lane-ownership.mjs                    # against your branch + diff vs main
node scripts/check-lane-ownership.mjs --branch SOLUSDEV-214-lane-workspace path/one path/two
```

Exit 0 = compliant, or not a lane branch. Exit 1 = cross-lane edit.

---

## 4. The lane charters describe a repo that does not exist

The `Owns:` blocks on the lane epics were written against a tree Solus never had. They are
**translated** here, and the 16 epic charters were corrected to match on 2026-08-05 (each
carries a "Paths corrected" note). `CODEOWNERS` is the authority; this table is the map
between the two.

| Charter says                                         | Actually                                                                                                                   |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `backend/app/**`                                     | `packages/api/src/solus_api/**`                                                                                            |
| `backend/app/core/`                                  | `packages/api/src/solus_api/core/` (infrastructure) — LANE 0 contract models go in `packages/api/src/solus_api/contracts/` |
| `frontend/src/**`                                    | `apps/desktop/src/renderer/src/**`                                                                                         |
| `frontend/src/workspace/`                            | `apps/desktop/src/renderer/src/features/workspace/`                                                                        |
| `frontend/src/features/<x>/`                         | `apps/desktop/src/renderer/src/features/<x>/`                                                                              |
| `frontend/src/orb/`                                  | `apps/desktop/src/renderer/src/features/sol/` + `components/ui/SolOrb.tsx`                                                 |
| `frontend/electron/**`                               | `apps/desktop/src/main/**` (and `src/preload/`)                                                                            |
| `mcp-servers/<tool>/`                                | `integrations/mcp/<tool>/`                                                                                                 |
| `infra/`                                             | `infrastructure/`                                                                                                          |
| `tests/integration/`, `tests/hardware/`, `tests/qa/` | only `tests/e2e/` exists                                                                                                   |

Three ownership calls were **derived**, not read literally, and should be confirmed by the
epic owners:

1. **`agent/tools/` → LANE E.** LANE E's charter claims "the tool-call execution/hardening
   layer"; that layer is `packages/api/src/solus_api/agent/tools/`, which sits inside LANE
   C's `agent/`. LANE C keeps context construction, orchestration and dispatch.
2. **`agent/perf.py` → LANE E**, named explicitly in LANE E's charter, same directory
   conflict, resolved by rule order in `CODEOWNERS`.
3. **`connectors/` is not split.** LANE F wants `connectors/cad/` and LANE G
   `connectors/eda/`, but today the EDA connectors are flat files in `connectors/`. Those
   five files are assigned to `@lane-eda` by name. **Both lanes should move their code into
   the subpackages early**; until they do, they share a directory and will collide.

Paths no feature lane claimed are `@shared`, including: `packages/contracts/`,
`packages/companion/`, `packages/shared-types/`, `apps/desktop/` root config
(`package.json`, `tsconfig*.json`, `electron.vite.config.ts`, `vitest.config.ts`),
`apps/desktop/src/renderer/src/{components,lib,store,theme,routes,assets}/`, `reasoning/`,
`scripts/`, `docs/` (except `docs/contracts/`), `brand/`, `packages/api/migrations/`, and
every root config file. Several of these — notably `apps/desktop/package.json` and the
renderer's `lib/`/`components/` — will be needed by more than one lane. That is the point:
each such need surfaces as a failed check and a contract ticket, not a silent collision.

---

## 5. Changing a contract after the lanes start

A contract on `main` has six lanes building against it. Changing it is expensive by design.

- **Additive is cheap.** A new optional field, a new enum member, a new message variant —
  open a LANE 0 ticket, land it on `main`, lanes pick it up on their next daily merge.
  Nothing breaks because nothing existing changed shape.
- **Breaking is a founder call.** Renaming a field, tightening a type, removing a variant.
  It requires every consuming lane merged-up in the same window, and it is agreed in-chat
  before it is written — never as a side effect of feature work (ADR-032, CLAUDE.md §9).
- **A lane never edits a contract to unblock itself.** If the shape is wrong, the lane
  stops and opens a LANE 0 ticket. This is the rule the whole parallel plan rests on: the
  cost of a wrong shape is one ticket; the cost of six lanes each patching it locally is
  six divergent copies and a merge nobody can review.

`packages/shared-types/`, `packages/api/src/solus_api/contracts/` and `docs/contracts/`
are `@shared` precisely so this rule has teeth.

---

## 6. What agents never do

Unchanged from ADR-021 and `.claude/rules/common/solus-git-workflow.md`, restated because
parallel lanes multiply the blast radius:

- Never `git push`, never open or merge an MR, never touch `main`, never force-push.
- Never work on another lane's branch or in another lane's worktree.
- Never bypass a hook or the ownership check to land a diff.

Humans review the integrated lane branch, push, open the MR, and merge.
