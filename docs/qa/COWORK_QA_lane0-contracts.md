# Cowork QA — LANE 0 Platform Contracts (CTR-01…07)

**Branch:** `SOLUSDEV-216-CTR` · **Tickets:** SOLUSDEV-216…222

## What you are testing, and what you are not

This ticket ships **contracts** — types, schemas, docs, fixtures and reference stubs — not
features. There is **no new UI to click and no new API endpoint to call.** Nothing in the
running application changes behaviour.

So this QA pass is not a click-through. It verifies the three claims the contracts make, each
of which is a _developer_ experience:

1. A lane can build a widget with **no canvas in the repo**.
2. Customer content is **structurally incapable** of entering the tool-knowledge store.
3. A lane branch **cannot** edit another lane's paths without CI failing.

Everything below is a terminal command with an expected result. Assume you have the repo and
this file, and nothing else.

---

## Setup

```bash
cd <repo root>
make bootstrap        # pnpm install + uv sync --all-packages + chmod the hooks
```

No database, no services, no `.env` needed — every check here is offline. (`make bootstrap`
will not create `.env` files; that is `pnpm env:sync`, and nothing here reads them.)

- [ ] `make bootstrap` completes without error.

---

## Flow 1 — The whole thing builds and passes

- [ ] `uv run ruff check .` → `All checks passed!`
- [ ] `uv run mypy packages/api/src packages/companion/src` → `Success: no issues found in 130 source files`
- [ ] `pnpm lint` → **0 errors** (23 warnings are pre-existing on `main`; count them if you like)
- [ ] `pnpm typecheck` → completes, no output after `Done`
- [ ] `pnpm test` → shared-types **110 passed**, desktop **639 passed**, scripts **62 passed**
- [ ] `cd packages/api && uv run pytest -q` → **1453 passed, 3 skipped** (~5 minutes)
- [ ] `cd packages/api && uv run alembic heads` → exactly one line, `92499d574b9f (head)`

Fail if: any command errors, or `alembic heads` prints more than one head.

---

## Flow 2 — A widget builds with no canvas (CTR-01)

The claim: a lane blocked on the workspace canvas is not actually blocked.

- [ ] `grep -rn "^import" apps/desktop/src/renderer/src/widgets/ | grep -iE "workspace|canvas|shell|features/"`
      → **no matches.** The reference widget and the loader import nothing from the shell.
      (Plain `grep canvas` over the directory _does_ match — the word appears in comments
      explaining what the canvas will do with a manifest. Check the `import` lines, not prose.)
- [ ] `npx vitest related --run apps/desktop/src/renderer/src/widgets/_reference/ReferenceWidget.tsx`
      → **6 passed**, exercising empty / loading / ready / error and the focus-change callback.
- [ ] `ls apps/desktop/src/renderer/src/widgets/` → `_reference/` and `discover.ts` only. There
      is **no registry file, no index of widgets, no switch statement**. That absence is the feature.

### Edge case: two widgets claiming the same id

- [ ] Copy the reference widget to a second directory:
      `cp -r apps/desktop/src/renderer/src/widgets/_reference apps/desktop/src/renderer/src/widgets/_dupe`
- [ ] `npx vitest related --run apps/desktop/src/renderer/src/widgets/discover.ts`
      → **fails**, naming both `widget.manifest.ts` paths and the duplicate id `reference`.
- [ ] `rm -rf apps/desktop/src/renderer/src/widgets/_dupe` and re-run → passes again.

Fail if: the duplicate is silently ignored, or the error does not name the files.

---

## Flow 3 — The approval flow renders with no backend (CTR-03)

- [ ] `ls packages/shared-types/fixtures/action-gate/` → **9 files**: two `pending-*`, seven
      `outcome-*`.
- [ ] `cat packages/shared-types/fixtures/action-gate/pending-with-diff.json` → carries
      `summary`, `args`, and a `preview` of `before → after` rows. **A card can be rendered from
      this alone.**
- [ ] `cat packages/shared-types/fixtures/action-gate/pending-args-only.json` → `before` is
      `null` on every row. This is the firmware-flash case: nothing is _replaced_, so the rows
      report what the action will run with.
- [ ] `npx vitest run --project shared-types action-gate` → **14 passed**
- [ ] `uv run pytest packages/api/tests/contracts/test_action_gate.py -q` → **22 passed**

### The trap this contract exists to document

- [ ] `grep -l '"ok": true' packages/shared-types/fixtures/action-gate/outcome-*.json` →
      **exactly one file** (`outcome-approved.json`).
- [ ] Read `outcome-rejected.json`, `outcome-expired.json`, `outcome-stale.json`. Every one is a
      normal 200-shaped body with `"ok": false`.
      **A UI that treats HTTP 200 as success is wrong** — that is the headline of
      `docs/contracts/action-gate.md`.
- [ ] `outcome-stale.json` and `outcome-expired.json` carry _different_ messages. Stale = the
      world moved; expired = time ran out. A UI must be able to say which.

### Edge case: a client trying to change the arguments it approves

- [ ] `uv run pytest packages/api/tests/contracts/test_action_gate.py -k "carrying_arguments" -v`
      → passes. A decision body with `args` is a **422**, never a merge.

---

## Flow 4 — One change, three domains (CTR-04)

- [ ] `python3 -c "import json;d=json.load(open('packages/shared-types/fixtures/impact/hero-motor-3a.json'));print([n['domain'] for n in d['nodes']])"`
      → `['electrical', 'code', 'mechanical']`
- [ ] Read `hero-motor-3a.json`. One motor changed to 3 A produces: an under-rated TB6612FNG
      driver (**critical**), a stale PWM ceiling at `firmware/motor_ctl/motor_ctl.cpp:88`
      (**warning**), and a marginal 24 AWG harness (**warning**). None of the three is the file
      anyone edited.
- [ ] Every consequence has a `rationale` that explains _why it matters_, not just a rule name.
- [ ] `npx vitest run --project shared-types impact` → **15 passed**
- [ ] `uv run pytest packages/api/tests/contracts/test_impact.py -q` → **20 passed**

### Empty and truncated states

- [ ] `no-impact.json` has `"nodes": []` — nothing downstream broke. **A real answer**, and a
      widget must render it as one, not as an error.
- [ ] `truncated.json` has `"truncated": true` — the traversal was bounded. A widget that hides
      this presents a partial answer as complete.

---

## Flow 5 — ⚠ Customer content cannot enter tool knowledge (CTR-05)

**This is the highest-risk item on the board.** The store is read by every tenant.

- [ ] `npx vitest run --project shared-types tool-knowledge` → **38 passed**
- [ ] `uv run pytest packages/api/tests/contracts/test_tool_knowledge.py -q` → **63 passed**

### The compile-time proof, demonstrated

- [ ] `pnpm --filter @solus/shared-types typecheck` → clean. Twenty `@ts-expect-error`
      assertions in `src/tool-knowledge.illegal.ts` all hold.

**Break it deliberately, in two ways. Both must fail.**

- [ ] **(a) Remove one assertion.** Delete the line
      `// @ts-expect-error no notes field — the classic place a design review gets pasted`
      from `packages/shared-types/src/tool-knowledge.illegal.ts`, then run
      `pnpm --filter @solus/shared-types typecheck`.
      → `error TS2353: Object literal may only specify known properties, and 'notes' does not
  exist in type 'ToolKnowledge'.`
      **Restore the line** and confirm it passes again.

- [ ] **(b) Weaken the type itself.** In `packages/shared-types/src/tool-knowledge.ts`, add
      `readonly [key: string]: unknown;` as the last field of `interface ToolKnowledge`, then run
      `pnpm --filter @solus/shared-types typecheck`.
      → **12 × `error TS2578: Unused '@ts-expect-error' directive.`**
      Adding one escape hatch breaks twelve assertions at once.
      **Revert the change** (`git checkout packages/shared-types/src/tool-knowledge.ts`).

Fail if: either break compiles clean. That would mean the boundary is a comment.

### The Onshape trap

- [ ] `uv run pytest packages/api/tests/contracts/test_tool_knowledge.py -k "imported_custom_feature or recent_file" -v`
      → both pass.
- [ ] Read the "Onshape `featurespecs` trap" section of `docs/contracts/tool-knowledge.md`.
      Onshape's per-document `featurespecs` returns a customer's **imported custom features** —
      vendor-looking data that is actually customer content, arriving in exactly the fields a
      real control would use. Confirm the doc names it and explains why the type refuses it.
- [ ] Confirm the doc has a **"What this contract does not do"** section. If it claims the
      pattern list is exhaustive, that is a bug — it is not, and the doc must say so.

---

## Flow 6 — Both sides of the handoff build alone (CTR-06)

- [ ] `npx vitest run --project shared-types orb-overlay` → **14 passed**
- [ ] `grep -n "electron\|BrowserWindow" packages/shared-types/src/orb-overlay.ts` →
      **no matches.** The contract and both stubs are framework-free.
- [ ] Read the two "building … against no …" describe blocks in `orb-overlay.test.ts`. One
      drives the orb with a stub overlay; the other drives the overlay with a stub orb.
- [ ] The failure path is real: `createStubOverlay(port, { failSpawn: "…" })` makes attaching
      fail, so a consumer cannot ship without handling it.

---

## Flow 7 — The lane guardrail (CTR-07)

- [ ] `node scripts/check-lane-ownership.mjs --branch SOLUSDEV-214-lane-workspace apps/desktop/src/renderer/src/widgets/impact/W.tsx`
      → `OK`, exit 0. **A legitimate in-lane edit passes.**
- [ ] `node scripts/check-lane-ownership.mjs --branch SOLUSDEV-214-lane-workspace packages/api/src/solus_api/agent/runtime.py`
      → `BLOCKED`, exit 1, naming `@lane-sol`. **A cross-lane edit fails.**
- [ ] `node scripts/check-lane-ownership.mjs --branch SOLUSDEV-216-CTR CODEOWNERS`
      → `not a lane branch — skipped`, exit 0. **LANE 0 is never blocked.**
- [ ] `node scripts/check-lane-ownership.mjs --branch SOLUSDEV-9-lane-typo Makefile`
      → exit 1, and the message **blames the branch name**, not the diff.
- [ ] `node --test scripts/lib/lane-ownership.test.mjs scripts/check-lane-ownership.test.mjs`
      → **25 passed**

### No unowned, no double-owned

- [ ] Run:
      `bash
  node -e 'import("./scripts/lib/lane-ownership.mjs").then(async m=>{const{readFileSync}=await import("node:fs");const{execSync}=await import("node:child_process");const r=m.parseCodeowners(readFileSync("CODEOWNERS","utf8"));const f=execSync("git ls-files",{encoding:"utf8"}).split("\n").filter(Boolean);console.log("files",f.length,"unowned",f.filter(x=>!m.ownerOf(x,r)).length)})'
  `
      → `files 1062 unowned 0`
- [ ] The "no two rules claim the same pattern" test in `lane-ownership.test.mjs` passes — that
      is the double-owned check.

### Read the protocol

- [ ] `docs/WORKTREES.md` §2 gives a **one-command worktree spawn**. Follow it for a throwaway
      lane and confirm the worktree comes up:
      `bash
  git worktree add ../solus-qa -b SOLUSDEV-999-lane-qa main
  cp .env.mega ../solus-qa/ 2>/dev/null || true
  cd ../solus-qa && make bootstrap && cd - && git worktree remove ../solus-qa && git branch -D SOLUSDEV-999-lane-qa
  `
- [ ] §4 contains the **charter → reality translation table**. Spot-check that
      `backend/app/**` maps to `packages/api/src/solus_api/**` and that `mcp-servers/` maps to
      `integrations/mcp/`.
- [ ] §5 states the rule for changing a contract after lanes start: additive via a LANE 0
      ticket, breaking is a founder call.

---

## Flow 8 — Cross-contract consistency

- [ ] `grep -n "SEVERITIES" packages/shared-types/src/impact.ts` and
      `grep -n "class Severity" -A 8 packages/api/src/solus_api/checkers/interface.py`
      → the same three values in the same order. Impact **imports** the Python one rather than
      re-declaring it.
- [ ] `ImpactResult.change` uses the same `DiffRow` the approval card renders — one diff shape.
- [ ] `docs/contracts/orb-overlay.md` has a **scope note** distinguishing per-user IPC payloads
      (may mention the user's own design) from the shared tool-knowledge store (may not). If
      that distinction is missing or muddled, flag it — conflating the two is how a leak happens.

---

## Flow 9 — Documentation currency

Each contract must have a doc that a lane can build from without reading the source.

- [ ] `ls docs/contracts/` contains `widget.md`, `focus.md`, `action-gate.md`, `impact.md`,
      `tool-knowledge.md`, `orb-overlay.md`, plus `docs/WORKTREES.md`.
- [ ] `docs/contracts/action-gate.md` opens with a **warning banner** that the gate is not yet
      on `main` and lands with SOLUSDEV-96. If that banner is missing, the doc is describing an
      API that does not exist for anyone on `main`.
- [ ] Every doc ends with a **"Changing this contract"** section.
- [ ] `docs/contracts/action-gate.md` cites real files and line numbers. Spot-check one against
      the branch: `git show SOLUSDEV-60/ons-ui01-confirmation-surface:packages/api/src/solus_api/schemas.py | sed -n '166,176p'`
      → a `ConfirmationDecision` model whose only field is `decision: Literal["approve", "reject"]`.

---

## Known non-issues (do not file these)

- **23 eslint warnings** — all pre-existing on `main`, none added by this branch.
- **H9 hook noise on test edits** — `vitest run --silent <file>` is incompatible with vitest 3's
  argument parsing. Documented at `apps/desktop/CLAUDE.md:35`. Verify with
  `npx vitest related --run <file>` instead.
- **`react` act(...) warnings** in the desktop suite — pre-existing, tests pass.
- **CODEOWNERS does not gate MR approvals** — that is a GitLab Premium feature. On Free the CI
  job is the enforcement, and it works (Flow 7).

## Result

- [ ] All flows pass → contracts are ready for the six lanes to build against.
- [ ] Any flow fails → record the command, the expected result, and the actual output.
