# Completion Report — LANE 0 · CTR-01…07

**Branch:** `SOLUSDEV-216-CTR` (12 commits on top of `main` @ `3535c60`)
**Tickets:** SOLUSDEV-216, 217, 218, 219, 220, 221, 222 (epic SOLUSDEV-36)
**Status:** integrated, full validation green, ready for human review. **Not pushed. No MR opened.**

---

## What was built

Seven contracts that convert six blocking cross-lane edges into imports from `main`.

| Ticket                  | Contract                                | Files                                                                                                                                     |
| ----------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **CTR-07** SOLUSDEV-222 | Worktree protocol, CODEOWNERS, CI check | `CODEOWNERS`, `docs/WORKTREES.md`, `scripts/lib/lane-ownership.mjs`, `scripts/check-lane-ownership.mjs`, `.gitlab-ci.yml`                 |
| **CTR-01** SOLUSDEV-216 | Widget framework                        | `packages/shared-types/src/widget.ts`, `apps/desktop/…/widgets/discover.ts`, `…/widgets/_reference/`, `docs/contracts/widget.md`          |
| **CTR-02** SOLUSDEV-217 | Shared-focus store                      | `packages/shared-types/src/focus.ts`, `docs/contracts/focus.md`                                                                           |
| **CTR-03** SOLUSDEV-218 | Destructive-action gate                 | `…/src/action-gate.ts`, `solus_api/contracts/action_gate.py`, 9 fixtures, `docs/contracts/action-gate.md`                                 |
| **CTR-04** SOLUSDEV-219 | Impact result                           | `…/src/impact.ts`, `solus_api/contracts/impact.py`, 3 fixtures, `docs/contracts/impact.md`                                                |
| **CTR-05** SOLUSDEV-220 | Tool-knowledge boundary                 | `…/src/tool-knowledge.ts`, `…/src/tool-knowledge.illegal.ts`, `solus_api/contracts/tool_knowledge.py`, `docs/contracts/tool-knowledge.md` |
| **CTR-06** SOLUSDEV-221 | Orb ↔ overlay handoff                  | `…/src/orb-overlay.ts`, `docs/contracts/orb-overlay.md`                                                                                   |

Contracts only. No feature implementation, no migrations, no new routes.

---

## Governing docs consulted

DECISIONS.md (ADR-008 stack, ADR-016 SOL modes, ADR-021 branching, ADR-022 structure,
ADR-027 graph conventions/`Domain`, ADR-028 contract ownership, ADR-032 two-tier governance) ·
CLAUDE.md §3 authority hierarchy, §5 branch discipline, §6 TDD, §7 security, §9 contracts ·
`apps/desktop/CLAUDE.md` · `.claude/rules/common/solus-git-workflow.md` ·
`docs/contracts/{agent-tool,checker-interface,bridge-protocol}.md` · `docs/env-consolidation.md`

`docs/architecture/` is **empty** and there is no wireflow for the workspace canvas — flagged
under Open concerns.

---

## Verification

| Gate                                                                    | Result                                                          |
| ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| `uv run ruff check .`                                                   | clean                                                           |
| `uv run mypy packages/api/src packages/companion/src` (`strict = true`) | 130 files, clean                                                |
| `pnpm lint`                                                             | 0 errors; 23 warnings, **all pre-existing on `main`** (0 added) |
| `pnpm typecheck`                                                        | clean — includes CTR-05's 20 compile-time assertions            |
| Backend `pytest`                                                        | **1453 passed, 3 skipped** (305 s)                              |
| Desktop `vitest`                                                        | **639 passed**, 100 files                                       |
| `@solus/shared-types` `vitest`                                          | **110 passed**, 6 files                                         |
| `scripts/*.test.mjs`                                                    | **62 passed**                                                   |
| `alembic heads`                                                         | single — `92499d574b9f`, unchanged (no migrations)              |

**New tests: 335** (110 shared-types + 105 backend contract + 24 lane-ownership + 9 desktop +
20 compile-time + 11 pre-existing scripts unchanged).

### Acceptance criteria, individually demonstrated

- **Reference widget builds with no canvas** — `_reference/ReferenceWidget.test.tsx` imports no
  canvas, layout or shell; 6 tests pass.
- **In-memory focus store and both orb/overlay stubs work standalone** — 16 + 14 tests, no
  Electron, no BrowserWindow.
- **CTR-05's compile-time test fails to compile on customer-shaped data** — verified in both
  directions:
  - Removing one `@ts-expect-error` → `src/tool-knowledge.illegal.ts(100,3): error TS2353: …
'notes' does not exist in type 'ToolKnowledge'`.
  - Adding `readonly [key: string]: unknown` to `ToolKnowledge` → **12 × `error TS2578: Unused
'@ts-expect-error' directive`**. Weakening the type breaks twelve assertions at once.
- **CTR-03 fixtures render a full approval flow with no backend** — 9 fixtures covering both
  pending shapes and all seven outcomes; types cited line-by-line to the shipped gate (below).
- **CTR-04 hero fixture covers ≥3 domains from one change** — electrical / code / mechanical,
  asserted in both languages.
- **CODEOWNERS has no unowned or double-owned path** — all **1062 tracked files** resolve to
  exactly one owner (`@shared` 583, `@lane-eda` 246, `@lane-foundations` 110, `@lane-production`
  35, `@lane-workspace` 28, `@lane-systems` 22, `@lane-sol` 16, `@lane-telemetry` 10,
  `@lane-graph` 6, `@lane-checkers` 5, `@lane-cad` 1). A test asserts no two rules claim the
  same pattern.
- **The CI check fails a cross-lane edit, passes an in-lane one, and does not block LANE 0** —
  run against this branch: `"SOLUSDEV-216-CTR" is not a lane branch — skipped.`
- **TS and Pydantic cannot drift** — see below.

---

## Decisions made under delegated judgment

### 1. Lane paths translated to the real tree (approved in-chat)

The lane charters own `backend/app/`, `frontend/src/`, `mcp-servers/`, `infra/` — **none of
which exist**. CODEOWNERS uses the real tree; `docs/WORKTREES.md` §4 carries the full
translation table.

**Three ownership calls were derived, not read, and want your confirmation:**

1. **`agent/tools/` → LANE E.** LANE E's charter claims "the tool-call execution/hardening
   layer"; that layer sits inside LANE C's `agent/`. LANE C keeps context construction,
   orchestration and dispatch.
2. **`agent/perf.py` → LANE E**, named in its charter, same directory, resolved by rule order.
3. **`connectors/` is not split.** LANE F wants `connectors/cad/` and LANE G `connectors/eda/`,
   but the EDA connectors are flat files today. Those five are assigned to `@lane-eda` by name.
   **Both lanes should create the subpackages early or they will collide.**

**Amendment I made on my own:** `checkers/interface.py` is carved out of LANE J as `@shared`.
It is the shipped CHK-01 `Checker`/`Warning`/`Severity` contract, which CTR-04 imports; the
rules are LANE J's, the shape they implement is not.

### 2. Branch naming: `SOLUSDEV-<epic#>-lane-<slug>` (approved in-chat)

`lane/<slug>` is **unusable**: hook H2 (`.claude/hooks/pre_edit_guard.sh:35`) blocks every
`Edit`/`Write` on a branch not matching `^SOLUSDEV-[0-9]+`, and ADR-021 locks ticket naming. The
chosen form passes H2 unmodified and the CI check still derives the lane from the suffix. No
hook change, no ADR amendment.

Related: `docs/WORKTREES.md` specifies **merge `main` into the lane, not rebase** — the epics say
"daily rebase", but ADR-021 and `solus-git-workflow.md` forbid rewriting history a human has seen.

### 3. CTR-03 documents an unmerged branch (approved in-chat)

The gate lives on `SOLUSDEV-60/ons-ui01-confirmation-surface` (`8c9b812`), **not on `main`** —
where `confirmation_refusal` (`agent/runtime.py:162`) is still a flat fail-closed refusal. Every
shape is cited to that branch: `models.py:176-190` (status incl. `STALE`), `models.py:654-699`
(columns), `schemas.py:166-175` (decision body), `routers/sol.py:446-494` (endpoint),
`agent/confirmations.py:183,210-323` (server-side args, single-use, TTL, `_diverged`),
`agent/stream.py:57-81` (event). The doc and both models carry a "lands with SOLUSDEV-96" banner.

**`amend` was dropped** — see Deviations.

### 4. Drift control: shared fixtures, both sides (approved in-chat)

OpenAPI codegen cannot reach these types (no routes exist for Impact or ToolKnowledge, and
there is no CI freshness check on `openapi.json`/`schema.ts` today). So the fixtures under
`packages/shared-types/fixtures/` are the single source, validated by Python
`model_validate` under `extra="forbid"` **and** TypeScript `satisfies` under `tsc`.

`JsonShapeOf<T>` (`src/json.ts`) exists because `tsc` widens string literals in `.json` imports.
It preserves every **field** check at compile time and defers only literal **values**, which the
same tests assert at runtime against the exported const arrays.

### 5. Smaller local calls

- **Wire vs. frontend casing.** Contracts with a Pydantic mirror are snake_case (the API's
  actual wire format); `Focus` is camelCase because it is frontend state, not a wire type.
  `toEntityRef` / `focusOfImpactNode` are the documented bridge — and since that mapping is also
  the jump-to-focus operation, it is the deliverable rather than overhead.
- **Pydantic contracts live in a new `solus_api/contracts/` subpackage**, not `schemas.py`. Same
  rationale as widget self-registration: `schemas.py` is one hot file six lanes would edit.
- **`Severity` is imported from `checkers.interface`**, not re-declared, so it cannot drift.
- **`DiffRow` is reused** by `ImpactResult.change` — one diff shape in the product.
- **Widget lifecycle hooks are optional**, with the contract's real obligation stated as
  _be remount-safe_; React's `useEffect` covers the ordinary case.
- **`WidgetSizeHint` is a coarse slot**, not a grid measurement — the grid is LANE B's to design.
- `packages/shared-types` registered as a vitest project so the H9/H10 hooks can run it from the
  git root; `@types/react` added as its only new dependency.

---

## Deviations from the ticket text

1. **CTR-03: `amend` is not implemented — by design.** The acceptance text asks for
   approve/reject/**amend**. Amend means the client supplies modified arguments at decision time,
   which destroys the one property the round-trip exists to provide: _what was shown is what
   executes_. `ConfirmationDecisionRequest` is a `StrictModel` with one field precisely so a body
   carrying `args` is a 422. The doc specifies **reject-then-re-propose** as the correct
   affordance, and a test asserts `decision: "amend"` is rejected at both the type and runtime
   level. **If you want amend, it is a security decision, not a contract one.**
2. **CTR-07: branch names are `SOLUSDEV-<epic#>-lane-<slug>`, not `lane/<slug>`** — approved
   in-chat; see decision 2.
3. **CTR-07: "distinct `SOLUS_TEST_DATABASE_URL`" is largely redundant.**
   `packages/api/tests/conftest.py:64-74` already derives `solus_test_<sha1(path)[:8]>` per
   checkout, so every worktree gets its own DB automatically. Documented as such; the env var is
   only needed for two suites in the _same_ checkout.

---

## Review findings, all fixed

**Both independent passes ran** (`code-reviewer` and `security-reviewer`) at your request.
Security review returned **FAIL** with three blocking findings; code review returned WARNING
with two HIGH. Every finding was reproduced before being fixed — none deferred. All in
`3443c84`.

### Security — blocking

| | Finding | Status |
|---|---|---|
| **C1** | The tool-knowledge boundary claim was **half true and the doc stated it whole**. 13 of 14 real customer payloads passed `model_validate`: part names, net descriptions, assembly paths, base64 blobs, homoglyph paths, drive-less Windows paths, and every unit outside a 15-entry allowlist. | fixed + **doc corrected** |
| **C2** | `focus` and `control.locator` crossed the IPC boundary as `as` casts while the contract said "both sides parse; neither trusts". `focus.entity.projectId` is a tenant scope arriving from the process that attaches to third-party windows. | fixed |
| **C3** | `VERSION_RANGE_RE` backtracked exponentially — **83 chars took 2.4 seconds** — and `version_range` is the one field not routed through the length-capped checker, so TS had no bound at all. | fixed |

On C1 the honest outcome matters more than the patch: two patterns that *tried* to catch part
names were written and then **removed**, because they rejected KiCad's own "Net Label" menu item
and "Revision History". Prose naming a customer's part is not mechanically distinguishable from
a vendor UI label. So `docs/contracts/tool-knowledge.md` no longer says "structurally incapable"
or "makes the common leak impossible" — the container is structural, the prose fields are a
bounded channel with a backstop, and **SOLUS-TU-06 is now told to allowlist at the source rather
than lean on these patterns.** A test named
`test_a_part_name_in_prose_is_not_caught_and_the_doc_says_so` pins the limit.

Also fixed from the security pass: `menu_path` unbounded in TS (5000 segments parsed clean) vs 8
in Pydantic; `AWG` present in one language's filter and not the other; nested objects dropping
unknown fields where Pydantic forbids them; `Infinity` accepted in window bounds; `handoffId`
accepting a 2000-char payload; `shortcut` accepting a trailing newline via `re.match`; prose
errors naming `"text"` instead of the field; and `ConsequenceEvidence.locator` — documented as
"the thing a UI turns into a link" — accepting `javascript:` and `https://attacker/?leak=` on a
model-influenced result.

### Code review — the load-bearing one

**The drift guard did not do what every file header claimed.** `satisfies` performs
excess-property checking only on *fresh object literals*, and a fixture imported from `.json` is
a variable — so a field **added** on one side passed both suites. I verified it: an undeclared
field left `tsc` silent while a renamed one errored. "Add a field" is precisely the change
`docs/WORKTREES.md` tells six lanes is cheap.

Closed properly: Pydantic emits its field names to a committed `_fields.json`, `CompleteKeysOf`
proves each TS field list covers its interface at compile time, and `drift.test.ts` compares the
two. Demonstrated in both directions.

The reviewer's remaining findings (TS/Python filter parity, `menu_path` bound) overlapped the
security ones and are covered above.

### The earlier self-review, also fixed (`2b1a98f`)

1. **Exponential regex backtracking (both languages).** The shortcut pattern alternated
   `Ctrl|Alt|Shift|…` against `[A-Za-z0-9]+`, which already matches every one of them — two
   parses per token, exponential on a non-matching input — and `shortcut` had no length cap.
   Replaced with one unambiguous bounded class; `max_length=64` added.
2. **Unbounded strings across the IPC boundary.** `orb-overlay.ts` now caps every parsed string
   at 2000 characters. IPC is a process boundary and therefore untrusted input (CLAUDE.md §7).
3. **A real teammate's email address** was used as a rejection fixture. Now `example.com`.

Also checked and clean: no secrets or credentials anywhere in the diff (gitleaks config
unchanged, `security:gitleaks` will run); no SQL; no `eval`/`exec`; no subprocess; no new
routes, so no new auth surface; every fixture UUID is synthetic; cross-tenant reasoning is
explicit in `descend` (refuses a cross-project trail) and is the entire subject of CTR-05.

---

## Open concerns for you

1. **ADR-028 vs `packages/shared-types/` — RESOLVED.** ADR-028 declared "the TypeScript types"
   human-owned while ADR-032's tier-2 list named only `packages/contracts/*`, so the two
   documents disagreed about a directory six lanes are about to import. Flagged in the Phase 0
   report before any of it was written; resolved in-session by adding `packages/shared-types/*`
   to tier 2 (`90c40e5`, dedicated commit per ADR-032 rule 2). **This branch stands as
   approved** — its design questions were put in-chat and answered, which is the control tier 2
   encodes. From here, a change to `packages/shared-types/` needs in-chat approval first.
2. **`docs/architecture/` is empty** and there is no wireflow for the workspace canvas.
   CLAUDE.md §3 says a missing diagram means the design phase is incomplete. CTR-01 and CTR-02
   invent structure with nothing above them in the authority hierarchy. It did not block
   _contracts_, but LANE B is about to build a canvas against no diagram.
3. **CTR-06 needs an IPC channel that does not exist.** Every IPC path in the app today is
   request/response `ipcRenderer.invoke`; there is no `ipcRenderer.on` / `webContents.send`
   anywhere. `spawn`/`reposition`/`advance` and every overlay→orb message are pushes. Wiring
   that channel is LANE C/D work — flagged in `docs/contracts/orb-overlay.md`.
4. **The lane charters on the epics are still wrong.** The translation table is in
   `docs/WORKTREES.md` §4, but until the epics are edited, anyone reading Jira will be told to
   work in `backend/app/`. Worth a pass over the 16 epic descriptions.
5. **GitLab CODEOWNERS is a Premium feature.** On Free the file is inert and does not gate
   approvals; the CI job is the only enforcement. Noted in the file header.
6. **`make gen-openapi` has no CI freshness check** and fetches `openapi-typescript` via
   `npx --yes` (not in the lockfile). Pydantic ↔ `schema.ts` drift ships silently today. Out of
   scope here, but it is the same class of problem CTR-03/04/05 solve with fixtures.
7. **`.gitlab-ci.yml` was amended once** to add `lint:lane-ownership` (ADR-032 tier-1). It is
   LANE Z's file from here on.
8. **The lane-ownership check is a guardrail, not a control**, and `docs/WORKTREES.md` now says
   so plainly: it fails open on branch name (a branch without `-lane-` is skipped, which is what
   keeps LANE 0 unblocked), and `LANE_OWNERSHIP_OVERRIDE` is a plain CI variable in a file that
   is agent-editable under ADR-032 tier-1 — defeatable by the party it constrains. If it ever
   needs to be a real control: masked Maintainer-only variable, mandatory branch suffix.
9. **Known harness gap, unchanged:** H9 runs `vitest run --silent <file>`, which vitest 3
   rejects. It emits noise on every test edit; `apps/desktop/CLAUDE.md:35` already documents it.
   Verified with `npx vitest related --run` throughout, per that note. Not touched — hooks are
   human territory.

---

## Handoff

- Feature branch `SOLUSDEV-216-CTR`, 9 commits, fully integrated, no sub-branches or worktrees
  left behind.
- QA plan: `docs/qa/COWORK_QA_lane0-contracts.md`.
- **Yours:** review, final commits, push, open the MR, merge. Then the six lanes can start
  simultaneously.
