# Completion report — SOLUSDEV-250 · Workspace + hardware onboarding UX rework

Branch `SOLUSDEV-250-w/r-lane-qa-claude` (worktree, base = main `c5c32f0`). Nothing pushed, no MR opened.
Every phase is one commit (plus review-fix commits) and was run for real against this worktree's API on
:8001 with both CH343 arms attached before it was committed.

| phase           | commit                          | what landed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| --------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 audit         | —                               | the eight-item audit with file:line evidence (plan file); four gate questions answered by the human                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 1 specific bugs | `63090f6`, `e659fc1`, `7a97c0e` | banner removed; empty robot name + placeholder; stale strings replaced + `staleCopy.test.ts` ratchet; Add panel 440 px resizable; "Integrations" tab with logo + login; hot-detect over the project SSE (`DeviceWatcher`, `hardware.devices_changed`, event naming by frame type); whole-card drag                                                                                                                                                                                                                                                                                |
| 2 detection     | `2cebead`, `b168df4`            | bauds 1M/115k2/250k/57k6/9k6; headline by tone (`Arduino-class board on USB` / `an ESP32` / board name / `something on USB`), never "MCU unknown" when a stream exists; sketch print-order parser plugin (Arduino C++ + MicroPython, tree-sitter); repo-config matching by address set; serial-less identity by USB port position (Q1); fixture twin CP210x + MicroPython; then the eight review findings (repo walk confinement, propose timeout → 503, port-binding forgery guards, repo_root confined to the project's registry entry, parser caps, stream clamp, wire bounds) |
| 3 one question  | `0c84802`, `8fd2fbb`, `f05e8a7` | canvas-edge rail cards with one question; Add › Hardware = Devices found · Search · Describe something new · Sourced · Unassigned parts; seven modals deleted; one interrogation per device across remounts/project switches; every pending card can be put away                                                                                                                                                                                                                                                                                                                  |
| 4 sidebar       | `66bbd4c`                       | `NodeSidebar` replaces the inspector and both delete modals (inline two-step); navigator toolbar and meta rows removed (Q4); Add top-left, Help top-right, parent chip = up                                                                                                                                                                                                                                                                                                                                                                                                       |
| 5 spatial       | `61ed800`                       | anchor-relative packing; no tree connector; domain-coloured cards; no ids anywhere; synthetic account anchors clustering documents (never persisted, never focused); rail reserves its width                                                                                                                                                                                                                                                                                                                                                                                      |
| 6 performance   | `89907b8`                       | no full-graph refetch on unchanged versions; `ready` never refetches; optimistic robot insert (parts wait for their edge); memoised cards with stable handlers; perf marks; confirm reuses the preceding proposal (bounded, tenancy-tested cache) with one structured timing line                                                                                                                                                                                                                                                                                                 |

## Governing docs

DECISIONS.md ADR-012/016/025/027/030/031/032/034; `docs/architecture/workspace-navigation.md`,
`hardware-onboarding.md`; `docs/api/API.md`, `hardware.md`, `workspace.md`; `docs/wireflows/workspace.md`,
`hardware-onboarding.md`; `apps/desktop/CLAUDE.md`. No contract (`packages/contracts`) or DECISIONS edit.

Tier-1 amendments made directly (ADR-032, review at the MR): `docs/api/API.md` (events named by frame
type, `hardware.devices_changed` full-list frame, local-only delivery), `docs/api/hardware.md` §1/§4
(headline/tone/stream/identity_basis, repo_root confinement, wire bounds, proposal reuse on confirm),
`docs/architecture/hardware-onboarding.md` (bridge inference, sketch parser, port-position identity),
`docs/architecture/workspace-navigation.md` (sidebar, anchor layer, `'integration'` sentinel),
`docs/wireflows/hardware-onboarding.md` (Flows 1/4/5 rewritten), `docs/wireflows/workspace.md` (no top
bar, corners, sidebar contents, account clustering).

## Decisions taken under delegated judgment

- Hot-detect frames are a full list, not a hint — a deliberate departure from the hub's "hint, not a
  delta" rule for small, ephemeral, machine-local data; delivered through `publish_local` only.
- The one-question card's "Part of ▾" lists existing robots from the snapshot; "New robot" is the
  default; a blank name for a library platform means the platform's name (backend default).
- "Describe something new" guesses the category from the name with a deterministic keyword rule and
  says so (`guessed`); SOL classification is a later ticket.
- Sourced stays (Q2) as one button opening the existing ST5 panel.
- Robot delete became an inline two-step in the sidebar (CLAUDE.md §7 still satisfied: the concrete
  action is shown before it happens).
- `'integration'` is a client-only domain sentinel for account anchors (outside ADR-027's domains).
- Domain colour mapping uses the wire value `code` for software; `simulation`/`workspace` stay neutral.
- The device rail reserves its width (CSS) rather than re-laying the level.

## What was verified live (Playwright MCP against the running API, both arms attached)

| measure                                   | before (main)                                                   | after Phase 3/4                                                | after Phase 6                                                                                    |
| ----------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| plug-in → card visible                    | no live path (Detected modal: open → list 79 ms, reopen needed) | rail card ≈ 2.2 s on a fresh project (SSE tick + auto-propose) | workspace open → rail cards 100 ms; proposal sentence 2.2 s (device interrogation)               |
| confirm → robot node visible              | 2324 ms                                                         | 2144 ms                                                        | **66 ms / 60 ms** (`hw:confirm_to_node` 65.8 ms); one entity page walk after the change, not two |
| node click → sidebar                      | 67 ms (inspector)                                               | 52 ms                                                          | **6–14 ms** (`ws:click_to_sidebar` 6.2–7.2 ms)                                                   |
| server: POST confirm (with session start) | ≈ 2.1 s (re-interrogation)                                      | —                                                              | **60 ms** on the cached proposal; the propose it skips takes 2053 ms on the device               |
| library platform → node                   | —                                                               | 138–151 ms                                                     | unchanged                                                                                        |
| describe something new → revealed part    | —                                                               | 151 ms                                                         | unchanged                                                                                        |

`hw:plug_in_to_card` was not measured: both arms were attached before the workspace opened (the store
is seeded by one `GET /detected`; the mark lands only on a device-change frame).

Also seen live: the SSE `hardware.devices_changed` frame; no "Unassigned parts" banner; Integrations
tab with logos; 440 px resizable Add panel; the two arms onboarded with name + Add each, no modal;
`SO-101` from the search box; "Wrist IMU" from one field; no toolbar rows; Help popover; parent
chip; rename / two-step delete / .solus actions in the sidebar; account anchor with three documents,
its sidebar and "Add another"; an anchor nudge sends no layout PUT, a document nudge does and
survives reload; zoom into a CAD document shows its part; no uuid on any card or sidebar.

## Tests (final tree `89907b8`)

Desktop: 3110 vitest tests (303 files) green; root `pnpm typecheck` clean; eslint 0 errors (length
warnings only). API: full suite on the final tree with `pytest -n 8` on a quiet DB — 4440 passed, 5 skipped —
plus the hardware/router/ratchet slice, 72 passed. livebench: 523. companion: 232. `ruff check .` clean; `ruff format --check` clean on every file this branch
touched (six pre-existing test files on main are unformatted — listed below); mypy --strict clean on
all 18 touched Python sources; both vendor-hygiene ratchets green; `alembic heads` = one head
(`b4c5d6e7f8a9`).

## Reviews

Each phase had a fresh-context review + security lens with two refuters per finding (workflow).
Confirmed and fixed: silent/failed/ambiguous cards could not be dismissed; "Nothing found yet" copy;
dead `__new__` sentinel; source_key nullable on the wire (crashed the real workspace); StrictMode
remount double-proposed every device; `RepoMatchOut.calibration_source` unbounded; registry cap
checked after the read. Refuted (kept as-is, documented): rows/evidence disclosure on the card;
identity caption for `identity_basis: 'none'` (unreachable — such devices have no card); Search fires
its seed read while offline (the API refuses; nothing is shown); partial failure on part → new robot
(the workspace refreshes after step one); runaway thread after a propose timeout (no cross-tenant
vector in the single-user local API; documented in code); port-binding vid/pid on the passive path
(no producer sends a `port-` key there).

## Incidents and things a human should know

- I killed the sibling session's API on :8000 by mistake early on and restarted one from
  `/home/beeboss/Solus/packages/api`; this worktree's API runs on :8001.
- The H10 Stop gate's full pytest run exceeds its 600 s timeout and collides with any concurrent
  pytest on the shared test DB; the suites were verified separately on a quiet DB (numbers above).
- The dev server died periodically (external) and any file edit while driving the UI causes a full
  reload that lands on Home; live checks were done between edits.
- A review verifier used `git stash` mid-review (against the environment rules); the tree was restored
  and checked — nothing lost.
- The Elegoo car was never attached to the bench; its path is covered by the fixture twin
  (`serial_bridge_four_channels.json` + the sketch fixtures) and the port-position binding tests.
- Only one integration account exists in the dev DB (Onshape). Its `account_login` is Onshape's opaque
  user id and is shown verbatim (the wire carries no display name); the "two integrations, four
  documents" gate could not be staged.
- Deleting a robot retains its parts, which keep the device bound — the rail does not re-offer that
  device in that project (Unassigned parts is the path). Parts cannot be deleted through the API.
- Six pre-existing test files on main fail `ruff format --check` (`livebench/tests/lb_deploy_fs_test.py`,
  `lb_firmware_test.py`, four under `integrations/mcp/*/tests/`); untouched by this branch.
- The `hardware.confirm timings` INFO line is emitted but invisible in dev: the app configures no root
  logging handler and uvicorn's `--log-level` covers only its own loggers. Telemetry is Pattern 2; a
  logging config is a separate, human decision.
- The server keeps a device bound after its robot is deleted (R5): confirming it again answers 409
  naming the deleted robot's uuid, which the desktop cannot translate to a name. The rail therefore
  never re-offers such a device; Add › Hardware › Unassigned parts is the path.
- Phase 6 was verified by its gate commands, the full desktop suite and the live run; a fresh-context
  review workflow was not run on Phase 6 — flagging for the MR review.
- Harness noise (unchanged, flagged): H9's `vitest --silent=<file>` parse error on every desktop edit;
  H9 "no corresponding test file" for unstaged new tests.

## Open items (not built)

- SOL-backed category classification for "Describe something new".
- A display name for connections (backend), so an Onshape anchor reads as a person, not an id.
- A "bound only by parts a live robot owns" rule if re-offering a deleted robot's device is wanted.
- `docs/api/hardware.md` still documents `platform_candidates`, which nothing produces.
