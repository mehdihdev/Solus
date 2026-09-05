# Wireflow — Activity Feed Preview & View-All Dialog (SOLUSDEV-233)

Covers the two activity surfaces on the workspace shell. Until a fuller
home/team wireflow lands, this document is the plan of record for the activity
feed UI; `docs/api/API.md §5` remains the route map for the screens hosting it.

## Surfaces

1. **Team screen — `TEAM ACTIVITY` panel** (left column, beside `MEMBERS`,
   below `PROJECTS`). Single-team feed with actor avatars and names.
2. **Home screen — per-project cards** (SOLUSDEV-242, `home.md`). Each
   project card previews up to 2 of ITS OWN rows from one fetch of the active
   team's feed, and `All activity →` opens `ActivityModal` server-filtered by
   `?project_id=` with `Load more`. The merged cross-team panel is gone.

## Panel behavior (both surfaces)

- The panel renders at most **6 rows** (`ACTIVITY_PREVIEW_COUNT`), newest first.
- When the server-reported total exceeds 6, the panel footer shows an
  accent-colored text button: **`View all activity (N) →`**, where N is
  `meta.total` from `GET /teams/{team_id}/activity` (summed across teams on
  Home). No button when the feed fits.
- Empty state copy is unchanged ("No activity yet…" / "Nothing yet.").

## View-all dialog (shared `ActivityModal`)

Flow: click `View all activity (N)` → centered modal (560px card, dim
backdrop) → review feed → close via ✕, click-out.

- Header: `ALL ACTIVITY` + `N EVENTS` + close (✕).
- Body: every loaded row, newest first, in a scroll region capped at 60vh.
  - Team: avatar + **actor name** + humanized event text + relative time.
  - Home: humanized event text + relative time (cross-team, no roster).
- **Team only**: a `Load more` button at the bottom while the server reports
  `has_next`; it appends the next cursor page (50/page) and disables itself
  with `Loading…` while in flight. A failed page keeps the current feed.
- **Home**: no Load more — the merged feed is fetched at up to 50 rows per
  team; the dialog shows everything loaded. When the total exceeds the loaded
  rows and no paging is offered, a muted footer states
  "Showing the most recent X of N events." (feed honesty — the activity feed
  is the team's audit surface, silent truncation is not acceptable).

## Motion

All modal chrome shares one entrance: the backdrop fades in (~160ms) and the
card pops in with a small rise + scale (~220ms) — `ModalShell`, so every dialog
(Invite, New team/project, Join, Delete confirm, Activity) behaves identically.
Anchored popups (notifications popover, project switcher, row menus) slide down
~4px while fading (~160ms); the toast slides in from the right. Transform and
opacity only; every animation is disabled under `prefers-reduced-motion`.
Closing unmounts immediately (no exit choreography).

## Failure / edge paths

- Offline / unreachable API: panels render their honest offline states;
  no preview, no button, no dialog (unchanged behavior).
- Feed of exactly 6 or fewer: no view-all button.
- `meta.total` missing (older server): the client falls back to the loaded
  row count, so the button count never fabricates.
