# Cowork QA — ⌘K command palette (SOLUSDEV-317)

Governing doc: `docs/wireflows/command-palette.md`. Mark each check **PASS / FAIL** with a note.

## Setup

- The desktop app is running against a reachable API, and you are signed in as a user with
  data-collection consent **on**.
- **Account A** belongs to two teams: "Team One" with projects **P1** and **P2**, and "Team Two"
  with project **P3**. P1 has a synced source and a graph with at least one nested node, for
  example a robot assembly that contains a part named "IMU".
- **Account B**: a different user in an unrelated team with project **PX**, which has a node with a
  distinctive name such as "ZETA_SENSOR".
- Optional: one extension with a page view installed in P1 (it appears in the rail).

## 1. Opening and closing

| #   | Steps                                                               | Expected                                                                                             | ✓   |
| --- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --- |
| 1.1 | On Home, press ⌘K (Ctrl+K on Windows/Linux)                         | Palette opens centred near the top. Field focused, **All** selected, footer shows Esc / ↑↓ / Tab / ↵ |     |
| 1.2 | Press ⌘K again                                                      | Palette closes                                                                                       |     |
| 1.3 | Click the menu-row search box (`Search pages, projects, nodes… ⌘K`) | Palette opens                                                                                        |     |
| 1.4 | Press Esc. Reopen and click ✕. Reopen and click the dim backdrop    | Each closes it                                                                                       |     |
| 1.5 | Reopen and click inside the palette panel, not on a result          | It stays open                                                                                        |     |
| 1.6 | Click into the SOL composer (or any text field) and press ⌘K        | Palette opens and nothing is typed into the field                                                    |     |

## 2. Pages

| #   | Steps                                                     | Expected                                                                                          | ✓   |
| --- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | --- |
| 2.1 | Open with an empty query                                  | **Pages** lists Home, Workspace, Live Bench, SOL, Store, Billing, Settings (then extension pages) |     |
| 2.2 | Type `telem`                                              | Live Bench is the result (keyword match)                                                          |     |
| 2.3 | Press ↵                                                   | Palette closes. Live Bench opens and its rail item is active                                      |     |
| 2.4 | With P1 open, type the extension's page label and press ↵ | The extension's page view opens, the same as its rail button                                      |     |

## 3. Projects and teams

| #   | Steps                                                  | Expected                                                                                                               | ✓   |
| --- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- | --- |
| 3.1 | Empty query                                            | **Projects** shows P1, P2, P3, each with its team name. **Teams** shows Team One "2 projects" and Team Two "1 project" |     |
| 3.2 | Type part of P2's name and press ↵                     | The project pill reads P2 and the Workspace screen shows P2's graph                                                    |     |
| 3.3 | Open P1. Open the palette, type `Team Two` and press ↵ | Home opens with Team Two active. P1 closes (pill reads "No project")                                                   |     |
| 3.4 | Open P1. Pick Team One                                 | P1 stays open. Home shows Team One                                                                                     |     |
| 3.5 | Archive P2 from Home, then search for it               | P2 is no longer listed                                                                                                 |     |

## 4. Nodes (the open project's graph)

| #   | Steps                                                                                                                         | Expected                                                                                                     | ✓   |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --- |
| 4.1 | No project open. Tab to **Nodes**                                                                                             | "Open a project to search its nodes."                                                                        |     |
| 4.2 | Open P1 and go to Home. Open the palette and type `imu`                                                                       | **Nodes** lists IMU with `domain · type`                                                                     |     |
| 4.3 | Press ↵                                                                                                                       | Workspace opens on IMU's containment level. IMU is centred and selected, and the sidebar/widgets focus on it |     |
| 4.4 | From Workspace, at the top level, search for another nested node and open it                                                  | The view enters that node's level and selects it                                                             |     |
| 4.5 | Empty query on **All**                                                                                                        | No **Nodes** section. Nodes need a query or the Nodes filter                                                 |     |
| 4.6 | **Nodes** filter, empty query                                                                                                 | Lists the project's nodes (up to 50)                                                                         |     |
| 4.7 | On a large graph, open the palette right after switching projects                                                             | `Loading…` shows until the graph arrives, then the nodes appear                                              |     |
| 4.8 | Rename a node in its source tool, sync, then search for the new name                                                          | The new name is found. The old name is not                                                                   |     |
| 4.9 | Stop the API, open P1's Workspace (graph fails), pick a node from the palette, wait 20 s, restart the API and retry the graph | The graph loads without selecting the old pick                                                               |     |

## 5. Keyboard and filters

| #   | Steps                                                       | Expected                                                                           | ✓   |
| --- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------- | --- |
| 5.1 | Press ↓ repeatedly past the last row, then ↑ past the first | The selection wraps both ways and the active row scrolls into view                 |     |
| 5.2 | Press Tab four times, then Shift+Tab                        | Cycles All → Pages → Projects → Teams → Nodes, then back. Focus stays in the field |     |
| 5.3 | Click the **Projects** tab                                  | Only projects are listed and the first one is highlighted                          |     |
| 5.4 | Type `zzzz`                                                 | `No results for “zzzz”`                                                            |     |

## 6. Recents

| #   | Steps                                                                      | Expected                                         | ✓   |
| --- | -------------------------------------------------------------------------- | ------------------------------------------------ | --- |
| 6.1 | Open Live Bench, then P2, from the palette. Reopen it                      | **Recents** shows P2 first, then Live Bench      |     |
| 6.2 | With P1 open, jump to IMU, then switch to P2 with the project pill. Reopen | IMU is not in Recents. Pages and projects remain |     |
| 6.3 | Sign out, then sign back in as the same user. Open the palette             | Recents is empty                                 |     |
| 6.4 | Quit and relaunch the app                                                  | Recents is empty (in-memory only)                |     |

## 7. Isolation and safety

| #   | Steps                                                                                     | Expected                                       | ✓   |
| --- | ----------------------------------------------------------------------------------------- | ---------------------------------------------- | --- |
| 7.1 | As Account A, search `ZETA_SENSOR` and Account B's team and project names                 | No results                                     |     |
| 7.2 | Sign out of A and sign in as B on the same machine. Open the palette with an empty query  | No Recents from A. Only B's teams and projects |     |
| 7.3 | In a test source, name a node `<img src=x onerror=alert(1)>`. Sync, then search for `img` | It shows as literal text. No image, no alert   |     |

## 8. Data events (consent on)

| #   | Steps                                           | Expected                                                                                                            | ✓   |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | --- |
| 8.1 | Open a node result at rank 2 after typing `imu` | A `search.palette_opened` row with `project_id` = P1 and payload exactly `{kind: "node", rank: 2, query_length: 3}` |     |
| 8.2 | Open a project from the palette                 | A `project.switched` row with `surface: "palette"`                                                                  |     |
| 8.3 | Turn consent off and open a result              | No new data-event rows (the call still succeeds)                                                                    |     |

## 9. Cross-feature

| #   | Steps                                                       | Expected                                                        | ✓   |
| --- | ----------------------------------------------------------- | --------------------------------------------------------------- | --- |
| 9.1 | Open the notifications popover, then press ⌘K               | Palette opens above everything                                  |     |
| 9.2 | Open an alert detail or extension page, then pick a project | Lands on the new project's Workspace (no stale detail route)    |     |
| 9.3 | Stop the API and open the palette                           | Pages still work. Projects/Teams are empty with no error dialog |     |
