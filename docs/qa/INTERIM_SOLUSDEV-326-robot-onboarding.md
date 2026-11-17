# INTERIM — SOLUSDEV-326 robot onboarding, P0–P3 (the push point)

**Merged since:** origin/main SOLUSDEV-327 (the SOL sidebar) at `0ddef136`. The Hardware screen's SOL is now that sidebar; the page's own docked panel is deleted (§4).

Date 2026-11-17. Branch `SOLUSDEV-326-robot-onboarding`, `f5042483..HEAD` (151 commits before this doc, nothing pushed). Phases done: P0 recon, P1 data model, P2 SOL tools and cards, P3 Hardware page. P4–P10 are not started.

**Who this is for:** the humans reviewing before a push, and the Live Bench branch, which rebases on this.

**Change rule:** from here on, any change to a P1 contract or to the card model needs the user's OK first.

| Phase | Last commit                                                                                          | Suites record                            |
| ----- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| P0    | `f1570e9a`                                                                                           | `RECON_SOLUSDEV-326-robot-onboarding.md` |
| P1    | `934f444b`, plus the security pass to `432b7929`                                                     | `acceptance/P1-suites.md`                |
| P2    | contract `4610bcd8`, code to `af365693`, follow-ups to `bdc1e4a2`                                    | `acceptance/P2-suites.md`                |
| P3    | `3528b2c9`, review follow-ups to `b4fcc3fb`, live-check fixes to `16acaebe`, decisions to `81a7877a` | `acceptance/P3-suites.md`                |

## 1. Contract and data-model changes

### Graph and hardware config (P1)

Docs: `schemas/hardware-config.md`, `api/hardware.md` §1–3 and §1a, `architecture/hardware-onboarding.md`, `contracts/telemetry-packet.md` §2a/§3, `api/workspace.md`, `api/sourcing.md`.

- **`robot_category` is retired.** A robot contains its parts directly, through a live manual `contains` edge.
  - Migration `a32600000001` (frozen recipe `migrations/robot_categories_retire.py`) re-points the category→part edges to the robot and copies the category key onto that edge's `attrs.category`. It then retires the nodes with `retired_by`/`moved_from`.
  - A new robot is one node.
  - `robot_category` stays only as a legacy kind and as the library vocabulary.
  - Request-body `category` fields are gone.
- **Identity list.** `EntityHardwareConfig.identity` is now `list[BrainIdentity{kind host|mcu|onboard, binding, via, protocol}]`.
  - `BusMapEntry` gains `brain`, so uniqueness is (brain, protocol, address).
  - Old single-identity payloads upgrade on read (`config_of`, `ConfigDraft`). `schema_version` stays 2.
  - `resolve_runtime_config(...).per_brain()` emits one v1 document per brain, so the drivers are unchanged.
  - The old v2 model is frozen in `migrations/hardware_config_v2.py` for the backfill.
- **DAG topology.** A part may sit behind two brains.
  - Each identity becomes one `hardware_brain`, keyed uuid5 on `device_ref`.
  - Brains carry `attrs.clock` (`offset_ms`, `jitter_ms`, `measured_at`, `method`).
  - Every edge still goes through `write_edge`.
- **Telemetry channels** gain optional `range` and `display` (telemetry-packet §2a/§3).
- **`in_graph` and `onboarded_by`** (attrs on the robot, its parts, its own brains and its config node):
  - Teammates see hardware only once it is added to the graph (`GraphReadScope.viewer_id`; reads that bypass the scope apply the same predicate).
  - A part wired into an in-graph robot joins the graph (user decision, P1).
  - Taking hardware out is onboarder-only (403) and is refused while a config another person can see names it (409). The message says whose hardware it is and what to do.
  - The rulings and residuals are in `api/hardware.md` §1a.
- **Device memory.** `machine.attrs.devices` and `machine.attrs.dismissed[user]` are owner-only. They are stripped from `serialize_entity` and from model reads.
- **New routes:**

  - `PUT /hardware/entities/{id}/graph {in_graph}`
  - `POST /hardware/devices/dismissals` and `DELETE /hardware/devices/dismissals`
  - `GET /hardware/expected` (P3)
  - `GET /sol/cards/open`

  `GET /detected` rows gain `bound_to`, `dismissed`, `last_seen` and `state`. No route was removed.

### Action gate (P2, approved 2026-11-16, `4610bcd8`)

`contracts/action-gate.md` §"Cards, open cards, notices and answers", with its twins and fixtures.

- **`Card`**: kind, title, body, more, field, primary, secondary, receipt, resumes.
  - It is stored in `tool_confirmations.card` (migration `a32600000002`).
  - It is sent on the `tool_confirmation` frame and on the confirmation list. The list rows carry `card`, not args.
- **`GET /sol/cards/open`** returns `{card: OpenCard|null, queued}`.
- **`MessageCreate.notice`** and **`MessageCreate.answer`**.
- **`working`** on the `tool_call` frame.
- **Resume** after a card whose stored `card.resumes` is true, capped at 40.

**Unchanged:** the decision body, `ConfirmationStatus`, approval with the STORED args, `invoke_stored` and the STALE check.

**Implementation rulings inside the contract:**

1. The server forces confirmation on notice turns and card resumes, whatever the client sends (`408148ed`). An answer turn keeps the person's own setting.
2. Rejecting a device-offer card is that person's "Not now" for the device: the server dismisses it (P3, `b1d0eb9b`). `OpenCard` carries no args, so the client could not do it.
3. An answer, edit or "Ask again" goes to the card's own `OpenCard.conversation_id`, not to whatever chat is open.
4. A second notice for the same device within 2 s gets `409 notice_debounced`.

Items 3 and 4 were written into the contract text at the push point (`3e627fc7`).

## 2. SOL's hardware tools (P2)

`agent/tools/hardware_onboarding.py`, `hardware_cards.py`, `hardware_graph_cards.py` and `ask_user.py`.

**Registration:** the tools are registered only for a person (`user_id`), and only when `watcher_wanted` holds: a local runner exists and this is not production. A hosted API has none of them, and the prompt says so.

| Tool                                                                                                       | Card                                                       | Notes                                                                                                                                                                               |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hardware.list_devices`, `expected_parts`, `list_parts`, `read_evidence`, `search_library`                 | —                                                          | Reads. Compact results under `TOOL_RESULT_CAP`.                                                                                                                                     |
| `hardware.inspect_device`                                                                                  | approval only when listening would restart a running board | Listen budget 0.5 s. The approval is a stored-only `restart_approved` marker, and `invoke` re-checks `listen_restarts`. A plug-in's inspection answers the first call within 120 s. |
| `ask_user`                                                                                                 | offer / problem                                            | Writes nothing but its question row. It refuses titles that imitate approvals or Solus.                                                                                             |
| `hardware.add_parts`, `add_connection`, `apply_evidence`, `link_part`, `import_definition`, `set_in_graph` | ✓ always                                                   | Static `requires_confirmation`. Never on any auto-run list (ratchet). Previews render stored args only.                                                                             |

**Plug-in path:**

1. The watcher sees a new, unbound, undismissed device.
2. The API runs the inspection with no model call. It skips a running board that the open would restart.
3. The row reads `inspecting`.
4. Then one of three things happens:
   - If the page is open, it sends a `notice` turn.
   - If not, the shell toasts. Opening the page afterwards sends the notice it owes.
   - "+ Add hardware" announces every unclaimed device.

Model calls in development: 0 real (fixture provider only). The scripted plug-in test reaches its first card at model call 2.

**Not built:** a `prepare_presence` SOL tool. The SOLUSDEV-262 route and `hardware.flash_presence` are unchanged, and this moves to P5 with the flash path.

## 3. The card model on screen (P3)

`features/hardware/`, `docs/wireflows/hardware-onboarding.md`.

- **The slot** is one fixed 132 px region that shows the caller's oldest open card across conversations; the rest queue.
  - It refetches on mount, focus, every decision and every stream frame, and every 5 s while visible.
  - Without a card it shows SOL's `working` line, then `Identifying` from the device feed (never for a dismissed row), then the idle line.
- **Kinds:**
  - **offer:** primary plus "Not now". Not now is a reject, which dismisses a device offer.
  - **approval:** the title starts "Approve:".
  - **step**
  - **problem:** an expired card becomes a Problem card with "Ask again".
  - A question card's buttons answer through `MessageCreate.answer`, never through decide.
- **Done so far** is built from the tool-authored `receipt` of approved cards.
- **The parts list** shows robot groups ("Add robot"), lone parts ("Add"), and the collapsed "Described, not seen yet" group from `GET /hardware/expected`. Status is derived from current state: Connected, Not connected, Last seen, Identifying, Unknown but streaming, Not seen yet.
- **Deviations from the design, where safety or the user's call won:**
  - A card takes focus only when it follows the person's own press. An approval card then focuses the card itself, never Approve; an offer or question focuses its primary.
  - A card read from the server ignores presses for its first 450 ms.
  - The approval fill is the `--warn` token mix, not the literal rgba.
  - The rail is icon-only (user decision).
  - An edit turn is `<label>: <JSON-quoted value>`.

## 4. The SOL sidebar on the Hardware screen (after the merge of SOLUSDEV-327)

`features/sol/sidebar/SolSidebarHost.tsx` (main's sidebar, mounted in `WorkspaceShell`), `docs/wireflows/sol-sidebar.md`, `docs/wireflows/hardware-onboarding.md`. The page's own docked panel (`SolPanel`, `DockedThread`, `DockedComposer`) is deleted (`a2f5b8df`): the Hardware screen has one SOL, the shell's sidebar, opened with its toggle or ⌘J / Ctrl J.

- **Same session, Hardware surface:** on the Hardware route the sidebar's chat is `useSolChat(projectId, 'hardware')`, the surface the page's slot uses.
- **Forced mode:** every Hardware-surface send, chip, answer, notice, resume and in-thread decision goes as `action_mode: "do"` plus `force_confirmation: true` (`surfaceSettings`). There is no Guide/Build switch on any surface since SOLUSDEV-327.
- **Cards stay in the slot:** the sidebar hides the in-thread rows that carry a Solus card (`cardsInSlot`); a row with no card stays in the thread and is decided there.
- **No process strip** on Hardware.
- **Always docks** on Hardware, at any window width (elsewhere it overlays under 1100 px). The parts list's narrow layouts are container queries on the page (`.hw-page`), so they follow the room beside the sidebar.
- **Copy:** tag `HARDWARE`, its own greeting, two chips and the placeholder "Ask SOL, or tell it what you have" (`sidebarCopy.ts`).
- **Toast:** a SOL reply raises the shell toast unless the SOL page or the open sidebar is showing it (`9334a3ac`). With the sidebar closed on Hardware it rises.
- **Event:** `sol.sidebar_toggled` accepts `screen: "hardware"` (`0ad7370f`).
- **Thread lines (every surface):**
  - A notice the server wrote is a quiet Solus line.
  - An answer is a receipt, "Answered: <label>".
  - A parked call's step reads "waiting for your OK", never "✕ unauthorized".

**For Live Bench:** Live Bench already has main's sidebar; there is nothing to mount. `SolSurface` (`features/sol/solCardTurns.ts`) is `'hardware'` only today. If Bench turns must force confirmation, give the sidebar's chat a Bench surface: add the value, decide it in `surfaceSettings`, and pass it in `SolSidebarHost` as Hardware's is.

## 5. Files the Live Bench branch touches (rebase list)

**API, kept minimal:**

| File                                  | Commits                                                                                                                                                                                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `solus_api/livebench/sessions.py`     | `986874be` (channel range/display), `cbc88df0` (per-viewer read scope), `f9a68fef` (one opener, each reachable brain), `aaf2a294` (event attribution), `56754b1d` (serial owner, typed busy), `85c9a116` (holder named only to its member) |
| `solus_api/livebench/bench_router.py` | `986874be`, `7d54ad64` (per-viewer telemetry reads), `f9a68fef`, `0fefe4e4`/`aaf2a294` (an event keeps its hardware and session), `62e3ea93`, `4617c9da` (409 `device_busy`), `85c9a116`                                                   |
| `solus_api/hardware/connections.py`   | `f9a68fef`                                                                                                                                                                                                                                 |

**Desktop `features/bench` (P1, in the approved plan):**

- `SignalWidget.tsx` and `benchStream.ts` (`986874be`): the chart domain comes from `range`, and `display` comes from the channel.
- `scene/MappingReview.tsx` (`e6335d1b`): device keys and the port note per brain.

**Shell:**

- `features/workspace/railItems.tsx` (new; the Hardware item sits between Workspace and Live Bench), `WorkspaceShell.tsx`, `menuBar.constants.ts`, `palette/paletteItems.ts`. The `hardware` keyword moved off Live Bench.
- The Bench "Add hardware" entry and the DeviceBenchView banner now open the Hardware page. `useAddHardwareRequest` and `openAddRequest` are deleted.
- `features/sol/sidebar/SolSidebarHost.tsx` (main's, mounted in `WorkspaceShell`) now knows the Hardware route: the `'hardware'` surface, `cardsInSlot`, always docked (`sidebarHooks.ts`), HARDWARE copy (`sidebarCopy.ts`). `features/sol/SolPanel.tsx`, `SolPanel.css`, `DockedThread.tsx` and `DockedComposer.tsx` are deleted; `useFollowStream.ts` is main's version again.

**Renderer deletions (P2-T7 and P3):**

- `features/graph/hardware/*`: HardwareAddPanel and its children, DeviceCard, PendingDeviceCards, the scheduler, `deviceCardRules`, `detectedDevicesStore`.
- The eight robot cards and two snippet builders.
- `RobotOrphans`, `useOptimisticGraph`.
- `lib/api/{hostTopology,partSuggestions,presence,presenceWiring,topologyExtraction}`.
- 31 test files.
- Kept: `HardwareConfigPanel`, `HardwareSourcesPanel`, `GraphSuggestions`.

**Untouched:** `livebench/findings/`, Live Bench UI layout, `packages/contracts/`, `DECISIONS.md`.

## 6. Decisions made at this push point (2026-11-17, in chat)

1. **An edit answers its card.** Before, editing a field (for example "Robot name") rejected the card, so the server dismissed the device and logged a false `hardware.device_dismissed`.
   - Now the edit goes as `MessageCreate.answer` on that card.
   - The server expires the card without deciding it: no dismissal and no event.
   - The server writes the turn `<field.label>: "<text>"`, marked `attrs.answer {edit: true, label}`.
   - Contract §Cards 5: `3e627fc7`. API: `81a7877a`. Desktop, on the slot and the SOL page: `69e6928c`.
2. **ADR-043 approved verbatim**, committed `a9f58b17`. It is SOL's only path to bus writes, guided steps, calibration writes and motion (P7/P8). Its status line reads "Proposed", as approved; a human may flip it to Accepted.
3. **`code.exec` serial access will be tightened in P5.** Serial device nodes will be denied inside `code.exec`, so the token-gated upload and `read_chip` become the only paths from code to a board. This needs the user's PROVENANCE re-review sign-off.
4. **A device already plugged in is announced once per app session**, the first time the Hardware page opens (`17b9475a`).
   - A replug, a bind or a dismissal makes it a new arrival again.
   - "+ Add hardware" still re-announces everything unclaimed.
5. **Contract lines written** (`3e627fc7`):
   - `409 notice_debounced` in §Cards 4;
   - an answer is posted in its card's own conversation, in §Cards 5.

## 7. Known gaps and residuals

**Deferred to P5's serial lane, before any live step:**

- The legacy line reader is keyed by tty path instead of `usb:port-…`.
- `FRESH_PLUG_S` is judged by `st_ctime`. A udev chmod makes a long-running board look fresh, so the plug-in path could open it without a card. The plug-in path never opens a board it would restart, but this check is what decides that.
- `SerialOwner.hold()` leaks on an exception.

**Before any card that flashes, writes a bus or moves hardware (P5/P7):** the card body must name the complete concrete action, or show the stored preview rows behind "more". Today `add_parts` names 3 parts plus "and N more".

**Accepted residuals:**

- Findings and activity rows about hidden parts stay visible to teammates.
- Hardware stays hidden if its onboarder leaves the project.
- `bound_repo_config_ids` is project-wide.
- An over-tall card (kicker + field + more) overlays the Done so far row; the list does not move.

**Until P6:** the start card's primary, "Connect a robot computer", sends that sentence to SOL, which has no host tools yet and can only say so.

**Pre-existing, not changed:** a SOL turn that failed (for example "Trial ended") keeps its error line in the open thread until the next reload.

**Harness:** the H10 Stop gate's full-suite `pytest` keeps running after the hook gives up. Its runs on `solus_test_d7fa72c2` overlapped the fixers' targeted runs (deadlocks, spurious failures). The follow-ups were therefore verified on `solus_test_d7fa72c2_p3fu`. A human should look at the hook's timeout.

**Delegated calls in P3:**

- "+ Add hardware" re-announces every current offer. That costs one SOL turn per press while an unclaimed device is plugged in.
- A notice still inside its 2 s window when the page closes is announced on the next open, if the device is still an offer.

## 8. Verification at this point

`acceptance/P3-suites.md`, at code commit `a28eea26`:

| Suite                      | Result                                                                                             |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| API                        | 13,380 passed. 16 failed, all pre-existing (`test_sim_acceptance`, `test_turn_budget`, id for id). |
| livebench, companion, libs | 1,458 passed. 1 failed, pre-existing (CH343 bench test).                                           |
| MCP and code fork          | 1,353 passed. 2 failed, pre-existing (host-environmental).                                         |
| Desktop vitest             | 629 files, 6,886 tests passed.                                                                     |
| shared-types               | 322 passed.                                                                                        |
| Static checks              | typecheck clean; ruff and mypy clean.                                                              |
| Migrations and API schema  | One alembic head, `a32600000002`. No openapi drift.                                                |

ESLint reports 34 errors, all inherited from main in files this branch never changed.

**Re-run at `16acaebe`, after the follow-ups and live-check fixes.** The follow-ups touched only `apps/desktop`, `packages/api` and docs, so the livebench and MCP rows above still stand.

| Suite          | Result                                                                                                                                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| API            | 13,396 passed and 13 skipped. 16 failed: the same pre-existing ids. The cad-store and live-access tests passed separately (68 of 68). Run on `solus_test_d7fa72c2_p3fu`. |
| Desktop vitest | 632 files, 6,935 tests passed.                                                                                                                                           |
| shared-types   | 322 passed.                                                                                                                                                              |
| Static checks  | typecheck, ruff and mypy clean.                                                                                                                                          |
| Migrations     | One alembic head.                                                                                                                                                        |

**After the push-point decisions (`81a7877a`):**

- Desktop: 632 files, 6,946 tests passed.
- API: the 36 SOL, answer, notice, plug-in and hardware-card test files passed, 756 tests.
- typecheck, ruff and mypy are clean.
- No openapi drift.

**Value you must set:** `fs.inotify.max_user_watches` (for example 524288), otherwise `pnpm dev:all` dies with ENOSPC.

## 9. Live check (2026-11-16, fixture models)

This check predates the merge of SOLUSDEV-327: the "docked SOL panel" and "the panel" below are the page's own panel, since replaced by the SOL sidebar (§4). It has not been re-run.

**Setup:**

- The real API on the `solus_onboarding` copy (migrated to `a32600000002`), on :8326. The copy's expired trial was extended so turns could run.
- The renderer dev server, driven in Chromium. Signed in with a locally minted dev token.
- Every model call answered by a script (scratchpad launcher). Nothing reached a model provider.
- The Arduino (`/dev/ttyUSB0`, CH340) plugged in throughout and never opened: its node's ctime is unchanged.

**Model calls:** 5, all scripted SOL rounds: no text-only calls, no embeddings, 0 real calls.

| Step                 | Seen                                                                                                                                                                                                           |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rail → Hardware      | The page draws its header, "+ Add hardware", the start card in the slot, "Robot parts · 0" and the docked SOL panel.                                                                                           |
| Arduino at API start | Listed as `usb:port-5-1.2.3`, state `unknown`. The plug-in path did not open a running board.                                                                                                                  |
| "+ Add hardware"     | Dismissals were cleared and one notice turn was sent after 2 s. The notice text was written by the server (`authored_by=solus`).                                                                               |
| SOL `inspect_device` | It parked "Approve: restart the board to listen" (kicker "Approval · This changes the hardware"; Restart and listen / Not now) 2.5 s after the press. Focus stayed on "+ Add hardware".                        |
| Not now              | The device was dismissed server-side (`hardware.device_dismissed`). The card resumed SOL, whose `ask_user` question card arrived 0.5 s later; focus went to "Yes", since the card followed the person's press. |
| Yes                  | The answer was stored as `Chose "Yes"` with `attrs.answer`. The slot went back to the start card, and SOL's reply landed in the panel.                                                                         |
| Reload               | The thread was rebuilt from history. The stored tool turns read "parked, awaiting your approval" and "rejected by you; nothing was applied".                                                                   |

**Found live:**

- A notice turn drew as the person's own bubble after a reload, and drew nothing before it. **Fixed** in `e9cbe3c9`: it is now a quiet Solus line, both live and after a reload.
- An answer read "Answered" live but `Chose "Yes"` after a reload. **Fixed** in `e9cbe3c9`: one receipt, "Answered: Yes", in both places.
- A parked step read "✕ … unauthorized" while its card waited (a pre-existing renderer behaviour from main). **Fixed** in `16acaebe`:
  - live, it reads "○ waiting for your OK", then "approved by you" or "rejected by you";
  - after a reload, it reads "asked for your OK".
- Re-checked in the running app after the fixes. All three render as described.
- A device present before Solus started was not shown until "+ Add hardware". **Decided and fixed** (§6 item 4, `17b9475a`).
