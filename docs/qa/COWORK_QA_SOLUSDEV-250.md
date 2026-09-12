# COWORK QA — Workspace + hardware onboarding UX rework (SOLUSDEV-250)

What changed: plugging in a board now produces a card at the canvas edge that asks one question;
Add › Hardware is three sections (Devices found · Search · Describe something new) plus Sourced and a
collapsed Unassigned parts list; every modal on the Workspace is gone — node actions live in a right
sidebar; the navigator has no top bar (Add top-left, Help top-right, the parent chip goes up); the
canvas packs new nodes beside their parent and clusters documents under their integration account;
detection infers past a USB bridge. This checklist applies to the SOLUSDEV-260 merged tree;
graph events invalidate graph data, while device-list events update the device feed.

Record pass/fail/unverified for each numbered step, with evidence. Wording below describes
expected behavior; Guide and Expert mode can change explanatory copy.

## Setup

- [ ] This checkout's database and Redis are reachable; `cd packages/api && uv run alembic upgrade head`
      reports the single merged head `a26000000003`. Do not reset populated user data.
- [ ] API: `uv run uvicorn --factory solus_api.main:create_app --port 8000` with the `SOLUS_*` settings
      exported (the local runner — livebench — must load; the API log says so at startup).
- [ ] Desktop: `pnpm --filter @solus/desktop dev` (or the packaged app), signed in and onboarded, a
      project selected. Guide mode unless a step says Expert (Settings › SOL mode).
- [ ] Hardware: two Feetech/STS arms on USB (CH343, each with a USB serial) and, if available, an
      Elegoo car (CH340, no USB serial — Arduino sketch printing CSV lines). Start with all unplugged.
- [ ] For Flow 7: a connected Onshape or GitHub account (Home › Connected accounts) with at least one
      document added to the project (Workspace › Add › Integrations).

## Flow 1 — navigator chrome (no top bar)

1. Open Workspace. **Expected:** no toolbar row and no "Project overview / Hover + scroll" line above
   the canvas. An opaque **Add** button sits at the canvas's top-left, a **?** (Help) at its top-right.
   The bottom line shows real counts (`N ENTITIES · N RELATIONS · N SOURCES`) and, while saving a drag,
   `Saving positions…`.
2. Click **?**. **Expected:** a popover "Workspace help" with four instruction lines, the trail
   (`Project`), and a disabled **Project overview** button at the root. Escape closes it; a click
   outside closes it.
3. Double-click a robot (or a card with "N inside"). **Expected:** its children; the chip at the top of
   the stage reads the parent's name and is a button (`Back to <name>`); clicking it goes up one level.
   ← also goes up; Help › Project overview (now enabled) returns to the root and closes the popover.
4. Drag any card by its body (not only the ⠿ handle) anywhere. **Expected:** it stays where dropped,
   `Saving positions…` then nothing; reload — it is still there.

## Flow 2 — a device appears (hot-detect, one question)

5. With Workspace open, plug in an arm. **Expected (≤ 1 s + the API's 1 s tick):** a compact card at
   the canvas's right edge reading `something on USB · looking at what answers…` with a spinner, then
   within ~2 s the sentence `Looks like · 6 servos on a serial servo bus (ids 1–6, STS3215)`; in Guide
   mode one muted line of evidence (`model register names an STS3215`), never repeated. No modal opens.
   Nothing was written: Add › Hardware › Devices found shows the same card, the graph is unchanged.
6. The card asks **What is this?**: an empty name box with the grey placeholder `Name this robot`, a
   **Part of ▾** select (`New robot` first, then existing robots), **Add** (disabled while the name is
   blank for a new robot), **Not now**.
7. Type a name, click **Add** (two interactions in total). **Expected:** the card disappears, a robot
   node with that name appears near the rail and is selected (sidebar opens on it), its sidebar's
   **Connection** line initially says connecting, then reflects success or a portable failure.
   A successful open alone is not proof of streaming: verify accepted telemetry separately.
   Add › Hardware › Devices found no longer lists the confirmed device.
8. Plug in the second arm; on its card choose **Part of ▾ → the first robot**. **Expected:** confirm
   refuses with the backend's own sentence naming the other robot (a device already confirmed to a
   robot names that robot; the uuid is replaced by the robot's name) and offers **Add to that robot
   instead** only when that makes sense; choosing **New robot** + a name adds it.
9. Click **Not now** on a pending card. **Expected:** the card hides for this session (both at the rail
   and in Add › Hardware); unplug and re-plug the device → it returns.
10. Unplug an arm whose robot exists. **Expected:** nothing changes on the canvas; the robot's sidebar
    Connection line becomes `Not connected` after the session ends.
11. Elegoo car (if attached; sketch printing 4 CSV values at ~50 Hz): its card reads
    `Arduino-class board on USB · 4 channels at 50 Hz` (Guide: plus `your sketch names them …` when the
    file was explicitly linked through the private source picker), never `MCU unknown`.
    No request sends the raw workspace path as `repo_root`.
    The identity caption reads `identity from the USB port — keep it in this port`. Add → a robot whose
    Sensors category holds the four channels.
12. A device that answers nothing (e.g. a bare USB-serial adapter): card `something on USB`, then
    `Nothing answered yet — is it powered and free?` with **Retry** and **Not now**; it retries by
    itself twice (5 s, 15 s) and then waits for you.

## Flow 3 — Add › Hardware

13. **Add › Hardware** shows, in order: **Devices found** (the same cards as the rail, or
    `Nothing found yet.` + the enumerate hint in Guide), **Search** (one box), **Describe something
    new** (one field), **Sourced** (`Find a part from suppliers`), then a collapsed **Unassigned
    parts** disclosure. No card grid, no modal except the sourcing panel.
14. Search `SO-101`. **Expected:** platforms and parts in one flat list with kind labels; a platform
    row offers **Add as new robot** → an inline **Robot name** box whose placeholder is the platform's
    name + **Add**; blank + Add creates the robot under the platform's name; typing a name uses it. The
    robot node appears and is selected within a second. A part row offers **Add to <robot>** with a
    **Part of ▾** select when several robots exist; the part lands in its definition's category.
15. Describe something new: type `Wrist IMU`. **Expected:** the **Category** select pre-picks `Sensors`
    with a `guessed` tag you can change; **Part of ▾** defaults to a robot; **Add** creates the part
    and reveals it inside `<robot> › Sensors`; the field clears. With no robot in the project the line
    `No robot yet — this becomes the robot.` appears and Add creates a robot named as typed.
16. Offline (sign out or no project): `Connect this project to add hardware.` and every control
    disabled; nothing is read.
17. Open **Unassigned parts**. **Expected:** nothing is read until opened; each part has
    **Part of ▾** + **Category ▾** + **Add**; adding moves it under that robot. The private source
    picker remains available. Relinking verifies file bytes locally and preserves shared opaque
    references; cloud requests must not expose the selected path.

## Flow 4 — the sidebar replaces every modal

18. Click a robot. **Expected (instant):** the right sidebar shows the robot's name with **Rename**,
    its seven categories with counts and part names (a small provenance tag such as `detected` where
    the config records one), **Connection**, **Pending suggestions** (`No pending suggestions.` or
    Accept / Reject per suggestion with the reason verbatim), **Unassigned parts** with
    **Attach to <robot>**, and **Delete robot…**. The card itself has no Rename/Delete buttons.
19. **Rename** → inline `Robot name` box, **Save name** / **Cancel rename**; a conflicting edit from
    elsewhere shows `Current name: …` and keeps your draft.
20. **Delete robot…** → the line `Delete <name>? Its parts and other links are retained.` with
    **Delete robot** / **Keep**. Keep disarms. Delete removes the robot; its parts stay reachable under
    Add › Hardware › Unassigned parts; a selected category of that robot is cleared.
21. Click `.solus`. **Expected:** the sidebar lists the five sections with honest counts (`EMPTY` or a
    number). Enter `.solus`, click a section: the sidebar offers exactly **Import files…**,
    **Ask SOL to find…** (disabled with `SOL is busy with another turn` while a turn streams),
    **Type it**; Type it opens the inline composer; an entry shows **Edit** (text/SOL notes) and
    **Delete note…** / **Delete file…** → `Delete <name>? …` + **Delete note** / **Keep**. Right-click on
    a section still shows the same three items; right-click › Delete on an entry arms the sidebar's
    confirm step (no modal). CONFIG remains a retained per-entity v2 editor, with CODE environment
    controls intact; it cannot be deleted as an ordinary note or file.
22. Click any other node. **Expected:** the focus summary (name, domain, type · N connections,
    **Ask SOL about this**) and the selectable neighbours. Asking opens SOL with that entity as
    shared focus, preserving Guide/Expert mode and existing action approval requirements.

## Flow 5 — spatial canvas

23. Enter a robot with unplaced categories. **Expected:** the categories spiral around the robot's own
    point (not around a fixed origin); a category you had dragged earlier stays where you put it; the
    frame is centred on the robot.
24. Root level with an integration connected (Flow 7's account). **Expected:** one card per account
    with the provider logo, the account login and `N documents`; its documents are inside it, not at
    the root; no orthogonal tree lines; cross-links are dashed curves between the cards they join.
25. Cards carry a coloured top edge per domain (code / electrical / mechanical / project); an account
    card's edge is neutral.
26. Nowhere on a card, a sidebar or a status line is a uuid or a raw JSON blob visible.

## Flow 6 — performance (DevTools › Network + Performance)

27. Plug in a device: one `GET …/hardware/detected` after the stream's `ready`, then frames on the
    `events` stream — no repeated polling of `/hardware/detected`.
28. Add a robot from a card: the robot node is on the canvas as soon as the confirm response lands (no
    wait for driver opening); record confirm-to-node latency. Cache-hit target is below 500 ms.
    Connection transitions can legitimately cause later graph refreshes; equal-version graph events
    must not be dropped, and simultaneous confirmations must not share a timing start mark.
29. Click a node: sidebar content renders within a frame (< 100 ms); nothing is fetched for the graph.
30. Inspect `performance.getEntriesByType('measure')` for `hw:confirm_to_node:` and
    `hw:receipt_to_card:` measures, plus `ws:click_to_sidebar`; report the durations.
    Receipt-to-card measures begin when the device frame arrives, not at physical plug-in.
    Unplug/replug must produce a fresh appearance measure.

## Flow 7 — integrations in the workspace

31. **Add › Integrations** (the tab is named Integrations, not "From a service"): each connected
    account shows its provider logo and login; documents are named as the provider names them; adding
    one creates its root under the account card and reveals it.
32. Click an account card → sidebar: login heading, its documents (click to reveal), **Add another**
    opens Add › Integrations.
33. Drag an account card: it moves for this session only (reload → back to its default spot); drag one
    of its documents: it persists.

## Edge cases and failure paths

- [ ] Runner absent (API started without livebench): Devices found says so with the reason verbatim;
      Search, Describe, Sourced, Unassigned parts still work.
- [ ] Ambiguous device (two devices with the same serial, or none): card note
      `no unique identity yet — reconnect it to verify`, no Add, **Not now** available.
- [ ] Propose fails (runner error): the backend's sentence verbatim, **Retry**, **Not now**.
- [ ] Permission: a project you cannot write shows the sidebar read-only (no Rename/Delete/Add).
- [ ] Start a connection, then delete the robot before a slow driver opens. Deletion waits for the
      in-flight acquisition to settle and close; no late live session or recreated robot remains.
- [ ] Restart this API runtime: only its own prior connection claims become disconnected. Another
      runtime's metadata and legacy metadata without a runtime identity remain unchanged.
- [ ] While proposals are pending, switch accounts or project A → B → A. Old callbacks do not
      populate the new device feed, confirm cards, or errors.
- [ ] Delete an unassigned part elsewhere before attaching it: show an honest missing-part error.
      Concurrent configuration changes show a stale-edit error; retry uses current data.
- [ ] The Add panel is at least 440 px wide and resizable by its right edge.
- [ ] No string anywhere says "Sources screen", "Sources page", "pick this device explicitly" or
      "Context Model".

## SOLUSDEV-260 executed walk — 2026-09-11

Results below describe this session, not the expected outcomes above. Fixture coverage
is never represented as a physical interaction. Actual desktop screenshots:
`/tmp/solus260-phase6-workspace.png`, `/tmp/solus260-phase6-sol-window.png`, and
`/tmp/solus260-phase6-live-telemetry.png`.

| Step | Result                                                                                                                                                                 |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Live: root navigator, Add/Help and real 189/200/2 counts visible.                                                                                                      |
| 2    | Live: help has four instructions and breadcrumb; Project overview returns to root and closes help. Escape/outside variants remain fixture-tested.                      |
| 3    | Live: robot/category and account document navigation; keyboard variants fixture-only.                                                                                  |
| 4    | Live: dragged the real follower card and reloaded; viewport recentered, so exact screen-coordinate persistence is not claimed. Persistence has fixture coverage.       |
| 5    | Live: both adapters visible, follower six-servo evidence; physical insertion latency unverified.                                                                       |
| 6    | Live: follower named and confirmed through device card.                                                                                                                |
| 7    | Live: connected and accepted channel telemetry. Cache had expired: 2.023 s proposal + 0.1383 s write, 0 inline session seconds; cached latency target unverified.      |
| 8    | Unverified: leader not answering; no false second robot created.                                                                                                       |
| 9    | Fixture-tested; physical reappearance not performed.                                                                                                                   |
| 10   | Live graceful API shutdown/restart gave Disconnected and retained graph; physical unplug not performed.                                                                |
| 11   | Recorded sketch/serial fixtures pass; no physical CH340 board available.                                                                                               |
| 12   | Live: leader card shows no answers, Retry and Not now; no protocol identity invented.                                                                                  |
| 13   | Live: ordered Hardware sections and collapsed Unassigned list.                                                                                                         |
| 14   | Live library listing contains SO-101 platforms; creating another robot not repeated. Import regressions pass.                                                          |
| 15   | Fixture-tested; did not add a fabricated IMU to the real graph.                                                                                                        |
| 16   | Fixture-tested account/project admission; live signout not repeated.                                                                                                   |
| 17   | Live: three actual unassigned CAD entities and local source controls; attach/relink fixture-only. Two equal names are distinct entity IDs.                             |
| 18   | Live: follower sidebar has seven categories, six actuator parts, Connected and honest pending-suggestion empty state.                                                  |
| 19   | Live: Rename opens the current name and Cancel closes without mutation. Save/conflict behavior fixture-tested.                                                         |
| 20   | Live: Delete/Keep confirmation disarmed successfully. Actual release/reclaim verified in Phase 3 live rollback and fixtures.                                           |
| 21   | Live: seven CONFIG records and one filed document retained; full edit/delete/import variants fixture-only.                                                             |
| 22   | Live: robot and generic-node Ask SOL open separate desktop window; approved focus/error behavior covered by 17 sidebar tests.                                          |
| 23   | Live categories displayed; persistence/layout edge cases fixture-tested.                                                                                               |
| 24   | Live: two real account cards, one document/repo each; documents under accounts.                                                                                        |
| 25   | Rebuilt desktop screenshot retained; visual styling governed by existing stylesheet.                                                                                   |
| 26   | Live account/source labels readable after restart. Historical audit text preserves original source label; technical USB evidence remains visible by design.            |
| 27   | Device stream behavior covered by watcher/feed regressions; physical hot-plug network capture unverified.                                                              |
| 28   | Live async lifecycle proven; expired-cache confirm took over 2 seconds, so cached sub-500-ms gate remains unverified.                                                  |
| 29   | Live rebuilt robot click-to-sidebar measure 2 ms.                                                                                                                      |
| 30   | Found and fixed consumed-click timing bug: later Reveal no longer appends a stale measure. Receipt/cached-confirm timings need a new physical appearance/confirmation. |
| 31   | Live: Integrations displays both account logins; connected roots preserved.                                                                                            |
| 32   | Live: Onshape account sidebar document and Add another opens Integrations.                                                                                             |
| 33   | Fixture-tested; live account/document drag/reload not performed.                                                                                                       |

The complete walk is not an all-live pass. Remaining physical, file-picker, provider
and drag/hotkey cases are explicitly retained for human QA rather than inferred.

## Follow-up: startup and provider resilience

Setup: use the SOLUSDEV-260 checkout with its existing root environment, Docker,
Node >=22, installed workspace dependencies and MCP forks. This machine's ignored
`docker-compose.local.yml` selects the preserved `solus_pgdata` volume. Do not
delete either database volume or migrate existing data without a backup.

- [ ] Run `pnpm dev:all`. PostgreSQL and configured local Redis become ready;
      schema checks pass before the API, then Electron starts after API readiness.
- [ ] Sign in and select **My first robot**. Confirm the restored connected sources
      and hardware graph are visible rather than a stale project/not-found state.
- [ ] Confirm KiCad tools are discovered with the desktop companion connected.
      Native KiCad CLI availability is a separate prerequisite for CLI-backed tools.
- [ ] Start Fusion with its native MCP server enabled at localhost:27182 and verify
      Fusion connects. An absent server must remain unavailable, not appear connected.
- [ ] Link the intended workspace before exercising Altium or local file/environment
      tools. AutoCAD/SolidWorks require their actual supported launchers.
- [ ] Send a short SOL message with Think harder. Verify completed assistant output,
      actual selected model and credit accounting; HTTP 200/SSE open alone is not a pass.
- [ ] Stop with Ctrl+C and immediately run `pnpm dev:all` again. No false busy-port
      failure from TIME_WAIT; an actual unrelated listener is still refused.
- [ ] In an isolated disposable test environment, exercise temporary API worker loss:
      a normal reload recovers, while sustained unavailability stops the owned stack.
- [ ] Use mocked provider errors for Retry-After, quota/access refusal and concurrent
      cooldown checks. Do not generate real request floods to force a provider limit.
      Verify no retry after visible stream output and no duplicate debit.

Direct diagnostics confirmed all 11 configured reasoning models work and Astra's
5,000 RPM/2M TPM headers. Embedding access still returned 403 `model_not_found`;
successful reasoning does not establish embedding access or full UI acceptance.
