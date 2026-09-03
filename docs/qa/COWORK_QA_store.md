# COWORK_QA — Store (SOLUSDEV-235, frontend)

End-to-end test plan for the Store page in the Solus desktop app. Written for a
tester with the running app and this file only.

## Scope of this build

Frontend only. The extension catalog ships inside the app; install state is
kept on this machine per project (it survives restarts, it does not sync
between machines or users). Install counts show as `—` and the "In this
project" activity card never shows a run history — both arrive with the
backend. No network is required for any flow below.

## Required setup

- Solus desktop app running, signed in (dev bypass is fine), onboarding done.
- At least one project open (pick one from Home). Project A is used below;
  a second project (B) is needed for the isolation checks in §5.
- For §3 "requirements follow connected sources": Project A should have NO
  KiCad/Altium source connected at the start, and you need the ability to
  connect one (Sources page → Connect a tool → KiCad, committed export).
  If you cannot connect a source, mark §3.3–§3.4 as blocked, not failed.

## 1. Reach the Store

| #   | Step                                                                              | Expected                                                                                                                      | Pass |
| --- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---- |
| 1.1 | With Project A open, click the `+` icon in the left rail (below Team).            | The main area shows the **Store** page. Topbar breadcrumb reads `Home / <project> / Store`. The `+` rail item is highlighted. | ☐    |
| 1.2 | Hover the `+` rail item.                                                          | Tooltip reads "Store".                                                                                                        | ☐    |
| 1.3 | Go to Home, clear the project (or sign in fresh with no project), open the Store. | Page shows "Select a project" with the hint to open one from Home. No cards.                                                  | ☐    |

## 2. Catalog layout

| #   | Step                                                                | Expected                                                                                                                                                                                                                  | Pass |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 2.1 | Read the header.                                                    | Title **Store**; subtitle "Capabilities are installed, not built in. Suggestions come from what's connected — never from what sells."; a two-button grid/list toggle; a primary **+ Create extension** button.            | ☐    |
| 2.2 | Read the INSTALLED section.                                         | Exactly 4 cards in two columns: Live Signals, Scene, Experiments, Cross-domain Findings. Each shows a `SOLUS ✓` badge, a one-line summary, and a green-dot `INSTALLED` status. Below: a **See all installed (7)** button. | ☐    |
| 2.3 | Click **See all installed (7)**.                                    | 7 cards: the 4 above plus Impact Map, Runtime Recognition, Approval Queue. Button now reads **Show fewer**.                                                                                                               | ☐    |
| 2.4 | Click **Show fewer**.                                               | Back to 4 cards.                                                                                                                                                                                                          | ☐    |
| 2.5 | Read POPULAR EXTENSIONS.                                            | 4 cards: BOM (`SOLUS ✓`, `NEEDS EDA`), CAN Telemetry (`SOLUS ✓`, `NEEDS CANBUS`), Datasheet Finder (`COMMUNITY`, `NEEDS EDA`), FSAE Rules Checker (`COMMUNITY`, `NEEDS CAD\|EDA`).                                        | ☐    |
| 2.6 | Click the list icon in the toggle.                                  | Both sections become single-column compact rows; summaries truncate to one line. Toggle shows list as active.                                                                                                             | ☐    |
| 2.7 | Click the grid icon.                                                | Back to two columns.                                                                                                                                                                                                      | ☐    |
| 2.8 | Tab with the keyboard to a card and press Enter.                    | The card opens in detail (same as clicking). Cards show a focus ring.                                                                                                                                                     | ☐    |
| 2.9 | If the API is unreachable (e.g. backend stopped), reload the Store. | A muted note above INSTALLED: "Solus can't see this project's sources right now, so source requirements below are shown as unmet." Cards still render.                                                                    | ☐    |

## 3. Requirements follow connected sources

| #   | Step                                                                     | Expected                                                                                                                                                                                                       | Pass |
| --- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 3.1 | With no EDA source in Project A, open **BOM** from POPULAR.              | Detail header shows a muted `NEEDS EDA` label and a disabled **Install** button (tooltip "Connect a required source first"). Overview → REQUIRES card lists "An EDA source (KiCad, Altium)" with an amber dot. | ☐    |
| 3.2 | Open **FSAE Rules Checker**.                                             | REQUIRES reads "A CAD source (Onshape) or An EDA source (KiCad, Altium)" with an amber dot; Install disabled.                                                                                                  | ☐    |
| 3.3 | Connect a KiCad source to Project A (Sources page), return to the Store. | BOM, Datasheet Finder and FSAE Rules Checker now show `AVAILABLE`. CAN Telemetry still shows `NEEDS CANBUS`.                                                                                                   | ☐    |
| 3.4 | Open **BOM** again.                                                      | **Install** is enabled; REQUIRES dot is green.                                                                                                                                                                 | ☐    |

## 4. Extension detail — Experiments (installed)

| #    | Step                                                                                    | Expected                                                                                                                                                                                                                                                                                                                | Pass |
| ---- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 4.1  | Click the **Experiments** card.                                                         | Detail replaces the catalog. Breadcrumb reads `Store / Experiments`. Header: large play-icon tile, "Experiments", `SOLUS ✓`, meta line `Solus · v1.0.0 · — installs · updated <n>d ago`. Right: **Disable** and **Uninstall** buttons. Tabs: Overview (active), Settings, Permissions.                                  | ☐    |
| 4.2  | Overview tab.                                                                           | WHAT IT ADDS: "Overview widget" and "SOL grounding" rows. IN THIS PROJECT: card reading `IDLE` / "No activity in this project yet." Right column: REQUIRES "No connected source required."; CREDITS `This cycle 0`, `Per run, typical ~1`; LINKS Documentation ↗, Source ↗, Report an issue ↗.                       | ☐    |
| 4.3  | Click **Documentation ↗**.                                                             | Opens in the system browser, not inside the app.                                                                                                                                                                                                                                                                        | ☐    |
| 4.4  | Click **Disable**.                                                                      | Button becomes **Enable**. Overview → IN THIS PROJECT now reads `DISABLED` / "Turned off in this project."                                                                                                                                                                                                              | ☐    |
| 4.5  | Settings tab.                                                                           | "Enable in this project" switch is OFF (reflecting 4.4); "Run frequency" select shows "On every sync"; footnote "Settings apply to this project only. Team defaults are set by an owner."                                                                                                                               | ☐    |
| 4.6  | Turn the switch ON.                                                                     | Header button reads **Disable** again.                                                                                                                                                                                                                                                                                  | ☐    |
| 4.7  | Change Run frequency to **Daily**, switch to Overview and back to Settings.             | Select still shows Daily.                                                                                                                                                                                                                                                                                               | ☐    |
| 4.8  | Permissions tab.                                                                        | Rows: "Read the context graph / Entity names, relations, units / GRANTED (green)"; "Read telemetry streams / Not yet requested / NOT ASKED (muted)". Amber-bordered note: "Extensions never write to hardware directly — anything that would move a motor goes through the approval queue, per your team instructions." | ☐    |
| 4.9  | Click **← Store**.                                                                      | Back to the catalog; breadcrumb reads `Store`.                                                                                                                                                                                                                                                                          | ☐    |
| 4.10 | Open Experiments, then click the `+` rail item.                                         | Returns to the catalog (not the detail page).                                                                                                                                                                                                                                                                           | ☐    |
| 4.11 | Open Experiments, navigate to Live Bench via the rail, then back to Store via the rail. | Catalog shows (rail always lands on the catalog).                                                                                                                                                                                                                                                                       | ☐    |

## 5. Install / uninstall and per-project isolation

| #    | Step                                                                                              | Expected                                                                                                                                                      | Pass |
| ---- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 5.1  | Open **Experiments** → **Uninstall**.                                                             | Confirm dialog: "Uninstall Experiments?" with copy about widgets/checks leaving, graph data staying, settings kept. Buttons Cancel / **Uninstall extension**. | ☐    |
| 5.2  | Click **Cancel**.                                                                                 | Dialog closes; still installed.                                                                                                                               | ☐    |
| 5.3  | **Uninstall** → **Uninstall extension**.                                                          | Returns to the catalog. INSTALLED shows **See all installed (6)**; Experiments now appears under POPULAR EXTENSIONS with `AVAILABLE`.                         | ☐    |
| 5.4  | Open Experiments from POPULAR.                                                                    | Header shows **Install** (enabled). Settings tab: controls disabled with "Install this extension to change its settings." Overview → `NOT INSTALLED`.         | ☐    |
| 5.5  | Click **Install**.                                                                                | Header switches to **Disable** / **Uninstall**; status `IDLE`. Run frequency from 4.7 (Daily) is still there.                                                 | ☐    |
| 5.6  | Restart the app, open Project A, open the Store.                                                  | Install state from 5.5 and 4.7 persisted.                                                                                                                     | ☐    |
| 5.7  | Switch to Project B (topbar switcher) while on the Store.                                         | Catalog re-scopes: Project B shows the default 7 installed; any changes made in A are not reflected.                                                          | ☐    |
| 5.8  | Uninstall BOM in Project B (after installing it), switch back to A.                               | A's BOM state is unchanged.                                                                                                                                   | ☐    |
| 5.9  | Uninstall every installed extension in Project B.                                                 | INSTALLED reads "Nothing installed in this project yet."; no See-all button.                                                                                  | ☐    |
| 5.10 | Install every extension (needs an EDA/CAD/CAN/runtime source for the gated ones; otherwise skip). | POPULAR reads "Everything in the catalog is installed in this project."                                                                                       | ☐    |

## 6. Create extension

| #   | Step                          | Expected                                                                                                                                                                                        | Pass |
| --- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 6.1 | Click **+ Create extension**. | Dialog "Create an extension" explaining the manifest model, stating the authoring flow is not available in this build, with a "Read the manifest documentation ↗" link and a **Close** button. | ☐    |
| 6.2 | Click outside the dialog.     | It closes.                                                                                                                                                                                      | ☐    |
| 6.3 | Reopen and click **Close**.   | It closes.                                                                                                                                                                                      | ☐    |

## 7. Cross-feature checks

| #   | Step                                                                      | Expected                                                                                            | Pass |
| --- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---- |
| 7.1 | Sign out while on an extension detail page, sign back in, open the Store. | Catalog shows (no stale detail page). Install state for the project is still as left.               | ☐    |
| 7.2 | Change theme / accent in Settings → Appearance, return to the Store.      | Every Store surface re-skins (badges, toggle, buttons, warn note). No element keeps the old colour. | ☐    |
| 7.3 | Open the notifications bell while on the Store, then click a card.        | Popover closes; detail opens.                                                                       | ☐    |
| 7.4 | With the SOL mini-orb visible, open the Store.                            | Orb still visible bottom-right; not covered by the page.                                            | ☐    |

## Known limitations (not defects)

- Install counts always read `— installs`.
- IN THIS PROJECT never shows a run timeline.
- Team-wide defaults are described in the Settings footnote but cannot be set.
- Install state is per machine; another workstation will show defaults.
