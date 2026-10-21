# Wireflow — ⌘K command palette (SOLUSDEV-317)

A quick switcher modelled on Claude's ⌘K: one field that jumps to any page,
project, team or graph node. It adds a way **in** to places the shell already
has. It never adds a destination, and it never acts on the robot.

```
┌────────────────────────────────────────────────────────────┐
│ 🔍 Search pages, projects, teams, nodes…               ✕   │
│ [All] Pages  Projects  Teams  Nodes                        │
├────────────────────────────────────────────────────────────┤
│ Recents                                                    │
│   ⌁ Live Bench                                         ↵   │
│ Pages                                                      │
│   ⌂ Home · ⧉ Workspace · ⌁ Live Bench · ◉ SOL · ▦ Store …  │
│ Projects                                                   │
│   ▣ Mars Rover                  Rover Lab                  │
│ Teams                                                      │
│   ☺ Rover Lab                   2 projects                 │
├────────────────────────────────────────────────────────────┤
│ Close Esc   Navigate ↑ ↓   Change type Tab   Open ↵        │
└────────────────────────────────────────────────────────────┘
```

## Opening and closing

- **Open**: ⌘K on macOS, Ctrl+K elsewhere, from anywhere in the workspace
  shell (a renderer keydown, not a global OS hotkey). The same shortcut closes
  it. Clicking the menu-row search box (`Search pages, projects, nodes… ⌘K`)
  opens it too.
- **Close**: Esc, the ✕, a click on the dim backdrop, or opening a result.
- It opens with an empty query, the **All** filter and the field focused.

## Results

| Kind    | Source                                                                                           | Detail line                     | Opening it                                                                                                   |
| ------- | ------------------------------------------------------------------------------------------------ | ------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Page    | Home, Workspace, Live Bench, SOL, Store, Billing, Settings, then the rail's extension page views | `Extension` for extension pages | Navigates exactly like the rail                                                                              |
| Project | The user's active projects in every team (same data as the project pill)                         | team name                       | Opens it through the project switch (`surface: "palette"`) and lands on its **Workspace**                    |
| Team    | The user's teams                                                                                 | `N project(s)`                  | Makes it the active team through the team switch (an open project of another team closes); lands on **Home** |
| Node    | Entities of the **open project only** (never another project's graph)                            | `domain · type`                 | Lands on **Workspace**, enters the node's level, centres it and selects it (shared focus + path)             |

- **Empty query, All**: Recents (if any), then Pages, Projects, Teams. Nodes
  need a query here so a large graph doesn't bury everything else. They are
  listed in full under the **Nodes** filter.
- **Typing** ranks within each kind: prefix › word start › substring ›
  letters in order. Labels outrank keywords (for example `telemetry` finds
  Live Bench), and keywords outrank the detail line.
- Under **All**, each kind is capped (pages 8, projects 6, teams 4, nodes 8).
  A filter shows up to 50.
- **Filters**: All · Pages · Projects · Teams · Nodes. Tab / Shift+Tab cycle
  them, or click one. Focus stays in the field.
- **Keyboard**: ↑/↓ move (they wrap), ↵ opens, and the active row shows ↵.
  Hover also moves the highlight.

A node jump waits for the project's graph to load. If it isn't served within
15 seconds (for example a failed read the user retries much later), it is
dropped, so a node picked long ago is never selected unprompted.

## Recents

The last 8 results opened, newest first, shown in the empty **All** view (up to
6). They live in memory only. They are cleared on sign-out or user change, and
node recents are cleared when the open project changes. A recent that no
longer resolves (deleted project, removed node) silently disappears.

## Empty and loading states

- `Loading…` (a quiet status line) while the user's projects or the open
  project's graph are still arriving. Results already known stay visible.
- `No results for “<query>”` when nothing matches.
- **Nodes** filter with no project open: `Open a project to search its nodes.`
- Anything else empty: `Nothing here yet.`

## Data event

Opening a result emits `search.palette_opened` `{kind, rank, query_length}`
(API.md §2.13). It never includes the query text or the result's label.

## Out of scope (this ticket)

Searching across projects (needs a server search route), nets/files as their
own kinds, and action commands ("Connect a tool…", "Ask SOL") in the palette.
