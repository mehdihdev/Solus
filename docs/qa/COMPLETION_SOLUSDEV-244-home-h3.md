# Completion report — SOLUSDEV-244 · HOME H3: Root-level preferences (how this user engineers)

Branch: `SOLUSDEV-244-home-h3-root-preferences` (shared with CORPUS C2 and STORE ST3/ST4 sessions;
local commits only, no push, no MR). Cowork QA: `docs/qa/COWORK_QA_home-h3-root-preferences.md`.

## What H3 built

A **document the user writes** — the one part of `~/.solus` they own — and its path into every
SOL turn.

- **`~/.solus/preferences.json`** (ADR-034 amendment 2026-09-06, human-approved in-chat):
  `schema_version` 1, `freeText` (≤ 2 400 chars) plus five sections `codeStyle`, `mechanical`,
  `electrical`, `documentation`, `unitsStandards` (≤ 800 chars each), `updatedAt`. Written only by
  the desktop MAIN process: strict parse in main (the renderer's copy is never trusted), atomic
  temp+rename, 0600 under the re-tightened 0700 home, 64 KiB byte cap, corrupt ⇒ empty document,
  newer `schema_version` ⇒ read-only. Contract: `docs/contracts/local-state.md`
  § `preferences.json`; TS shape `packages/shared-types/src/engineering-preferences.ts`. No Python
  twin — no Python process reads the file (the companion never consumes it; the API validates the
  request body with its own schema).
- **Home card "HOW YOU ENGINEER"** (`features/preferences/`): view of the written sections, an
  editor with one textarea per section and a `n / cap` counter, Save (optimistic, revert on
  failure) / Cancel, honest read-only and "desktop app only" states. Present on the offline Home
  too — it is machine-local. No toggles (the ticket's trap).
- **Ride-along**: the renderer store hydrates once from main (`prefs:read`, sender-gated) and
  `sendMessage` attaches the document to every turn as `MessageCreate.preferences` (omitted when
  nothing is written). The **server keeps no copy**: the transcript stores the message, never the
  preferences; the `sol.message` event records `chars` of the message only.
- **Prompt layering** (`agent/prompt.py::system_prompt`): Solus rules → citation note → mode note →
  **engineering conventions** (Solus-authored framing, one nonce-fenced
  `kind=engineering_preferences` block of labelled non-empty sections, Solus-authored trailer) →
  the SOLUSDEV-233 styling note (`kind=user_preference`). The framing tells SOL to apply the
  conventions to every engineering recommendation and to **name the convention that changed an
  answer** (Guide mode also explains the default), states the order — a project's `.solus`
  conventions (reserved `kind=project_preferences`, empty this ticket) override root, root overrides
  shipped references (`kind=context_corpus`, CORPUS C2) — and that they can never change rules,
  tools, scope, or what counts as data. Budget: 6 400 chars at cap, under the 8 000-char block cap;
  the schema refuses over-cap fields (`422`) so non-desktop callers cannot widen it.
- **Red team**: `Surface.ENGINEERING_PREFERENCES` with three payloads (standing approval for a
  write, cross-project read, fence escape) in `fixtures/injection_corpus.py`; `test_prompt.py`
  proves fence containment and ordering, `test_sol_red_team.py` proves the tool set, action mode and
  the confirmation gate are structurally untouched.

## Governing docs

DECISIONS.md ADR-034 (amended 2026-09-06 for this ticket; ADR-032 tier-2 approval recorded
in-chat), ADR-016 (mode note precedes user layers), ADR-036 (corpus is context data, below
preferences), CLAUDE.md §7; `docs/architecture/solus-folder.md` §6/§9 (status updated — the ROOT
half of Ticket D shipped; team/project instructions remain deferred); `docs/contracts/local-state.md`;
`docs/wireflows/home.md` § "How you engineer" (added); `docs/api/API.md` §2.9 row and
`docs/api/API-implementation.md` streaming-turn body (`preferences?` documented).
`docs/design/SPEC.md` and `docs/design/screens/` named by the standing rules do not exist in this
repo; the wireflow and architecture docs above governed instead.

## Verification

- shared-types: 250 tests (20 new). Desktop: 267 files / 2 787 tests green, `pnpm typecheck` clean
  (main + renderer). API: 1 075 passed on an isolated test DB (`solus_test_home`; excluded the
  peers' in-progress `tests/corpus/` and `tests/bom/`); the ONE failure,
  `test_extension_bundle_download.py::test_publisher_downloads_own_pending_bundle_with_verifiable_headers`
  (`422 == 202`), is in the extension publish path this diff does not touch — reported to the STORE
  session (last commit there: 956e04d).
- **Real run, API level** (private uvicorn on :8001, live Anthropic): the PCB clearance question
  WITH `electrical: "prefer 0.1 mm clearance minimum on all boards"` → "set … **0.1 mm** … That figure
  comes straight from your saved convention"; the same question WITHOUT → "6 mil (0.15 mm) …
  driven by manufacturing capability". Driver: job scratch `drive_h3.py`.
- **Real run, desktop** (the actual Electron app via `electron-vite dev
-- --remote-debugging-port=9222`, driven over CDP; API on :8001): wrote the preference in the Home
  card → `~/.solus/preferences.json` landed at mode 0600 with the exact text and `updatedAt`;
  SOL page → the answer recommended 0.1 mm and said "Your saved engineering convention is to prefer
  0.1 mm minimum clearance on all boards, so that's the floor I'm applying here"; cleared the field in
  the card → file holds the empty document; new chat, same question → "6 mil (0.15 mm) … a safe, easy
  default", no convention named. Screenshots: `h3-home-written.png`, `h3-sol-with-pref.png`,
  `h3-sol-without-pref.png` in the job scratch dir. The test file was removed afterwards.
- Lint/format/type hooks (H7/H8) clean on every touched file; ruff + mypy clean on the API files.

## Decisions under delegated judgment

- Field caps 800 / 2 400 chars (6 400 total, ~1 600 tokens) — under the 8 000-char fence cap and
  the retrieval budget; approved with the ADR text.
- Over-cap text is **truncated on read** by the desktop parser (the file is the user's) but
  **refused (422)** at the API (a non-desktop caller must not widen the prompt). The editor's
  `maxLength` means a desktop user never hits the 422.
- Labels the model reads: Code style · Mechanical · Electrical · Documentation · Units and
  standards · Notes; empty sections are omitted from the block.
- The card lives in Home's right column under CONNECTED ACCOUNTS and stays on the offline Home.
- The SOLUSDEV-233 custom-instruction card is kept as a distinct, server-stored styling note (user
  answer in the design gate).
- `sendMessage` now awaits the preferences load before opening the stream (one microtask when
  already loaded); one existing solChatStore test was adjusted to wait for the stream to open.
- Added `mode=ctx.sol_mode` to `build_context` at the CORPUS C2 session's request (a9c0… commit
  10f6680 introduced the keyword); it only orders corpus ties.

## Deviations / open concerns

- **Phase 4 review subagents did not complete.** Both the fresh-context `code-reviewer` and the
  `security-reviewer` runs were terminated by the account's spend limit (HTTP 429, resets 2:20 pm
  PT). A self-review of the full diff was done instead (no `console.*`, no `any`, immutability,
  typed client, fences/trailers, sender gating, byte caps); the two subagent passes should be
  re-run before the MR is opened.
- Harness gap (documented in `apps/desktop/CLAUDE.md`, re-confirmed): hook H9 invokes
  `vitest run --silent=<file>`, which vitest 3 rejects, so every desktop test edit prints a
  non-blocking error; the H10 Stop gate path is unaffected.
- In the desktop run Home showed the "can't reach its API" state because the harness injected the
  bearer token after the first load; the preferences card worked regardless (machine-local), and
  the SOL page used the token. Not a product defect.
- `~/.solus/preferences.json` is one file per machine (approved); two accounts on one machine share
  it.
- Values a human must set: none new. The live run used the existing root `.env` (DB, JWT secret)
  and `make seed-secrets` for the Anthropic key.
