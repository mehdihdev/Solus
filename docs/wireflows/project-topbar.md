# Wireflow — Project top bar (SOLUSDEV-235)

The workspace shell's chrome above the rail. Replaces the single breadcrumb
topbar (`Home / <project> / <screen>`) with two rows. Source of record for the
visuals: the design screenshot attached to the ticket (BOM detail page).

```
| ● ● ●  [ ▣ Elegoo Robot Test ▾ ]                                              |  title row (44px, drag region)
| Solus   View   Robot   Help            (● Bridge attention) [🔍 Search…  ⌘K] 🔔 Sign out |  menu row (40px)
| rail | screen …                                                               |
```

## Title row

- Drawn by the renderer; under Electron on macOS main uses
  `titleBarStyle: 'hiddenInset'` so only the traffic lights remain, and the row
  insets 84px for them. Other platforms keep their native title bar and the row
  renders without the inset.
- The whole row is a drag region (`.app-drag`); the pill opts out.
- **Project pill**: bordered, rounded, accent project glyph · project name
  (bold) · chevron. It IS the project switcher (SOLUSDEV-164): click → menu of
  "All projects" (Home) and every project grouped by team; the current one is
  checked. Reads "No project" when none is open. Switching re-scopes the current
  screen without navigating; an open Store detail page closes.

## Menu row

Left: four menus. "Solus" is the brand entry (bold); the others are muted until
hovered or open. One click opens; hovering a sibling while one is open switches
to it; Escape or click-out closes. Contents are declarative (`MENUS` in
`features/workspace/MenuBar.tsx`) and only reuse existing surfaces — nothing
here does what the rail cannot. **Menu contents are a placeholder pending a
design**; reshape by editing the constant.

| Menu  | Items                                                                                                                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Solus | Home · Settings · Billing · ─ · Sign out                                                                                                                               |
| View  | Home · Workspace · Live Bench · SOL · Store (active screen checked)                                                                           |
| Robot | Connect a tool… (Home › Connected accounts) · Connect a device… (Live Bench) · Ask SOL — disabled with "Open a project to act on its robot." while no project is open |
| Help  | Documentation ↗ · Report an issue ↗ (https anchors → OS browser)                                                                                                     |

Right cluster, unchanged from the previous topbar: bridge pill, search box
(⌘K), notifications bell with unread badge, `Sign out`. The notifications
popover anchors under this row.

## Rail

Unchanged screens, but the brand logo button at the top is gone — "Solus" in the
menu row is the brand. Home remains the first rail item.

## Removed

- The `Home / <project> / <screen>` breadcrumb and the `Store / <extension>`
  variant. The rail's active item and the page heading identify the screen;
  `data-screen-label` on the screen container is kept for tests.
- Brand logo in the rail (SOLUSDEV-233) — superseded by this design.

## Live refresh — SOLUSDEV-312

The notifications bell refetches when the account event stream reports
`notification.created`, so the unread badge updates without a remount. Quiet
refresh only — no toast.
