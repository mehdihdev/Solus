# Wireflow — Home, the cross-project surface (SOLUSDEV-242 / HOME H1)

Home manages ACROSS projects and connects WHOLE accounts. Everything
project-specific (documents, the graph, Live Bench, installed widgets, SOL)
lives in the workspace screens. Home is `MainScreen 'home'`, the first rail
item, the "All projects" entry of the project pill (`project-topbar.md`), and
`Solus → Home` in the menu row. `docs/api/API.md §5` ("/") is the route map.

```
| Welcome back, Maya                                                                    |
| Projects in Strider  [Strider ▾]                              [✉ Join team] [👥 New team] |
|                                                                                       |
| ┌─ Rover MK2 ──────── CURRENT ⋯ ┐ ┌─ Arm ───────────────── ⋯ ┐ ┌ ┄┄┄┄┄┄┄┄┄┄┄┄┄ ┐  ┌ CONNECTED ACCOUNTS ┐ |
| │ six-wheel rover                │ │                          │ ┆   + New project  ┆  │ GitHub   Connect  │ |
| │ RECENT ACTIVITY                │ │ RECENT ACTIVITY          │ ┆                  ┆  │ GitLab   Connect  │ |
| │ connected github "…" · 2h ago  │ │ created the project · 1d │ └ ┄┄┄┄┄┄┄┄┄┄┄┄┄ ┘  │ Onshape  Connect  │ |
| │ updated a project · 3h ago     │ │                          │                       └───────────────────┘ |
| │ All activity →        [Open]   │ │ All activity →  [Switch to]│                                          |
| └────────────────────────────────┘ └──────────────────────────┘                                            |
| ▸ ARCHIVED (1)                                                                                             |
```

## Scope: the ACTIVE team

- Home shows ONE team's projects: the active team, `workspaceStore.teamId`,
  resolved by the rule in `features/workspace/activeTeam.ts` (kept while it is
  still one of my teams, else the personal team). The Team screen resolves the
  same way, so the two never disagree.
- **Team selector** (`TeamSelect`, shared with the Team screen): hidden with a
  single team. Choosing another team re-scopes the grid; a slow answer for the
  previous team never lands on the new one.
- **Opening or switching a project makes its team the active team.** The
  project pill's switcher lists every team's projects; picking one from another
  team moves Home and the Team screen there too.
- Account-level actions stay on Home: `Join team` (invite token) and `New team`
  (both make the new team active), and the **CONNECTED ACCOUNTS** card
  (SOLUSDEV-241: OAuth binds at account scope; each project picks what it
  tracks on its Sources page). See "Connected accounts" below (HOME H2).

## Connected accounts (SOLUSDEV-242 / HOME H2)

```
| CONNECTED ACCOUNTS                                                          |
| [On] Onshape · ada@example.com                                              |
|      Used in Rover and Arm · Read only                        [Revoke]      |
| [Gh] GitHub · octocat                                                       |
|      Connected in a project, not yet on your account   [Sign in to move]   |
|      ⚠ Connected in Rover before account-level connections. Sign in once   |
|        to move it to your account — Rover keeps syncing until then.         |
| [Gl] GitLab                                                                 |
|      Not connected                                            [Connect]     |
| [Ki] KiCad                                                                  |
|      Connects from a project's Sources page as a committed     PER PROJECT  |
|      export — no account to link                                            |
| [Fu] Fusion 360 (local)                                                     |
|      Connects on this computer from a project's Sources page   PER PROJECT  |
```

- **Every tool the registry knows is listed** — a missing row reads as
  "unsupported". OAuth tools link an account here; committed-export tools
  (KiCad, Altium) and local-companion tools connect per project from the
  project's Sources page, and their row says so instead of offering a Connect.
- **Connect** opens the connect wizard in account mode (rail
  `Choose access → Sign in`; no document picking here — that is the project's
  Sources page, W2).
- **Scope is stated on every linked row**: `Read only`, `Read and edit`, or
  `Access level not recorded`. Scopes are fixed in connector code; nothing on
  this surface widens one.
- **Legacy grants** (`GET /users/me/connections/legacy`): a project-scoped grant
  from before account-level connections, made by this user, is listed under its
  provider as "Connected in a project, not yet on your account" with a note
  naming the projects and stating plainly that they keep syncing until it is
  moved. It is not a usable grant here (no Revoke). **Sign in to move** runs the
  account-mode wizard; the finished sign-in PROVES the account and the server
  claims every legacy grant for that account the user can act on (the source
  then mirrors the account grant; its own token is retired after the commit).
  A grant whose account the user has already connected here is claimed on the
  next Home load with no sign-in (`POST /users/me/connections/adopt` runs before
  the list). A project whose recorded access mode differs from the account
  grant's is never moved silently — it keeps its own token (its Sources page is
  where that changes; W2 follow-up).
- **Re-authorize** appears on a row whose last sign-in failed, with the
  provider's message; it runs the same account-mode wizard and lands on the SAME
  row (I1 dedupes by account), so the old token is replaced only once the new
  consent succeeded.
- **Revoke** is confirmed and names the projects it disconnects (unchanged).
- Hidden while offline (honest empty state elsewhere on Home).

## Project grid

- One card per live project of the active team: accent graph glyph, name
  (bold, ellipsised), description, `CURRENT` mono mark on the open project.
- **Recent activity per project**: up to 2 rows (`PROJECT_CARD_ACTIVITY_COUNT`)
  of that project's own events, humanised (`activityText`) with relative time.
  Rows come from ONE fetch of the team feed (`GET /teams/{id}/activity?limit=50`)
  split by `project_id` — a window, honestly labelled: a project absent from the
  team's latest rows reads "No recent activity." Team-level rows (invites,
  members) do not appear on cards; the Team screen carries them.
- `All activity →` opens the project's own dialog (`ProjectActivityModal` over
  the shared `ActivityModal`, titled `<project> — activity`): server-filtered
  `?project_id=`, `Load more` while `has_next`, `N EVENTS` = the project's own
  `meta.total`.
- Footer button: `Open` (no project open, or this one) / `Switch to` (another
  project is open). Clicking anywhere on the card body does the same. Opening
  lands on the project Overview (SOLUSDEV-164).
- `⋯` menu (member+): `Rename` (name dialog) · `Archive` · `Delete` (owner only,
  ADR-025, confirmed). The menu never opens the project. A failed archive raises the
  shell toast "That didn't work".
- **New project** tile (member+): dashed, last in the grid; the name dialog
  creates in the active team and opens the project. In an empty team it adds
  "Create one to start building the graph." Viewers see "No projects in this
  team yet."

## Archived

- `▸ ARCHIVED (N)` collapsed by default beneath the grid; absent when N = 0.
  Archive hides without deleting: rows keep the name, offer `Unarchive`
  (member+) and `✕` delete (owner only, confirmed). Archived projects never appear
  in the grid or the project pill.

## Switching projects — nothing carried across

Every switch — a card, the pill, the Team screen, or the dead-project
validator — goes through `switchWorkspaceProject()` (`projectSwitch.ts`), the
single choke point. It swaps the project, sets the active team, clears the
focus engine (entity ids are project-scoped), the Store's detail selection, and
the shell toast; the shell drops `alert` and `ext-page` detail routes to
Overview; per-screen hooks discard responses for a project the user has left.
SOL sessions are keyed by project: a parked confirmation in project A stays
parked in A and is never selected for B. Archiving or deleting the OPEN project
closes it (the shell drops to no project) so nothing stays scoped to a hidden
or deleted project. The switch is reported as the
`project.switched` data event. The module header lists every project-scoped
store and how it is kept honest; new project state is added there.

## States

- **Loading**: centred spinner.
- **Offline / signed out**: the honest card ("Sign in to Solus…" or "…can't
  reach its API…"), never a demo project (SOLUSDEV-152).
- **No teams**: "You're not on any teams yet. Create one, or join with an
  invite token." with the account actions still available.

## Removed (SOLUSDEV-242)

- The per-team cards listing every team's projects, and the merged cross-team
  RECENT ACTIVITY panel with its all-activity dialog (`activity-feed.md` §Home
  surface). Activity on Home is per project now; the Team screen keeps the team
  feed.
