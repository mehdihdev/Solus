# Wireflow — Workspace (SOLUSDEV-240 / WORKSPACE W1)

The Context Model rail item becomes **Workspace** (route id `workspace`). The graph stays
central; the new left rail is the project `.solus` — where documents, hardware configs and notes
are brought in and organised. Visual reference: `docs/ui-reference/app/v4/workspace.jsx`
(direction "01 · Signal": Plex Sans/Mono, amber accent, hairline borders, 3–6px radii).
Data: `docs/api/solus.md`.

```
| rail | .solus (290)          |  entity list over the dotted canvas          | inspector (318) |
|      | .solus  RIGHT-CLICK … |                                              |                 |
|      | ┌ Hardware configs  EMPTY ┐ |  .solus                                 | Focus summary   |
|      | ┌ Project details   2  ┐ |  motor_driver                              | Neighbors       |
|      | │ ▤ FSAE Rules 2027.pdf │ |  …                                        |                 |
|      | │ ¶ 48 V bus            │ |                                            |                 |
|      | ┌ Error logging AUTO+YOU EMPTY ┐                                       |                 |
|      | ┌ Documentation     EMPTY ┐ |  2 ENTITIES · 1 RELATION · 0 SOURCES    |                 |
|      | ┌ Code environment  EMPTY ┐ |                                            |                 |
|      | Project-level. SOL files …  |                                            |                 |
```

## Rename

- Rail label, View-menu label, Overview tile and `data-screen-label` read **Workspace**. The
  Alert detail still lights the Workspace rail item.
- Only the screen id changed (`graph` → `workspace`). The `graph.*` extension namespace and the
  SOL context section kind `graph` are contracts and are untouched.

## The `.solus` panel (left rail, 290px, always visible)

- Header: `.solus` in mono, `RIGHT-CLICK A SECTION` micro-label.
- Five section cards in fixed order: Hardware configs · Project details · Error logging ·
  Documentation · Code environment. Each shows its entry count or `EMPTY`; Error logging carries
  an amber `AUTO + YOU` chip (SOL writes here too).
- Entry rows: icon by kind — file (imported artifact, mono name + `media_type · size`), SOL
  (amber, mono), text (UI font). Long text wraps; nothing is truncated silently.
- Footer copy: "Project-level — not `~/.solus`, which is this machine's. SOL files artifacts
  here. Empty sections are fine — they're not placeholders, they're honest."
- Offline / no project: the panel shows the five sections with `—` counts and a muted "Sign in
  and open a project to see its .solus"; no mutations are offered.

## Right-click a section → three actions (identical on every section)

```
+ PROJECT DETAILS -----------+
| Import files…              |
| Ask SOL to find…           |
| Type it                    |
+----------------------------+
```

- **Import files…** — native file picker. Client rejects > 8 MiB with "That file is over 8 MiB —
  Solus keeps .solus imports small." Otherwise: upload → file into the section → the row appears
  with `imported just now`. The file becomes a `document` node under `.solus` in the graph. On
  failure the row never appears; toast "Import failed — <reason>".
- **Ask SOL to find…** — an inline textarea inside the card (amber border), placeholder
  `What should SOL find? e.g. 'FSAE EV rules on fusing'`, buttons `Cancel` / `Ask SOL`. Sends a
  SOL turn `Find for .solus › <Section label>: <query>` through the project's chat session (the
  orb pulses as for any turn). When the turn settles the panel refetches; toast
  `Filed to .solus › <label>` if the section grew, else `SOL answered but filed nothing — open SOL
to read the reply`. While a turn is already streaming for this project the action is disabled
  with "SOL is busy with another turn".
- **Type it** — the same inline textarea, placeholder `Type it — plain text`, buttons `Cancel` /
  `Add`. Adds a text entry; ≤ 4000 chars (counter appears past 3500).

## Right-click an entry

- Text or SOL entry: **Edit** (inline textarea prefilled) · **Delete** (immediate; toast with the
  section name).
- Imported file: **Delete** opens the existing confirm modal — "Remove FSAE Rules 2027.pdf from
  .solus? Its graph node and file go with it." — because it removes a graph node.

## Graph side

- `.solus` is an entity like any other: it sorts first in the list, clicking it focuses it, and
  the inspector's Neighbors widget lists the imported documents. That is "appears under the
  `.solus` node".
- Empty-state honesty: a fresh project has exactly one entity. The list still renders (the
  `.solus` node must be clickable) and the canvas overlays "An empty project — on purpose · Only
  the `.solus` node is here — nothing else is drawn until something real arrives. Connect a source
  or import a file." The corner counts stay the server's honest node counts.

## Events

`solus.entry_added` / `solus.entry_updated` / `solus.entry_deleted` server-side (solus.md §7);
the desktop emits nothing extra.
