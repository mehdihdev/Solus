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
| ┌─ Rover MK2 ──────────────── ⋯ ┐ ┌─ Arm ───────────────── ⋯ ┐ ┌ ┄┄┄┄┄┄┄┄┄┄┄┄┄ ┐  ┌ CONNECTED ACCOUNTS ┐ |
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
|      (once signed in:)                          [Move to your account]      |
|      ⚠ …Your linked account matches — move it so Rover uses your account   |
|        grant.  → confirmation names the project, the grant, the removal     |
| [Gl] GitLab                                                                 |
|      Not connected                                            [Connect]     |
| [Ki] KiCad                                                                  |
|      Committed export · attached per project           [Attach in Rover]    |
| [Fu] Fusion 360 (local)                                                     |
|      Connects on this computer · attached per project  [Attach in Rover]    |
```

- **Every tool the registry knows is listed** — a missing row reads as
  "unsupported". OAuth tools link an account here; committed-export tools
  (KiCad, Altium) and local-companion tools are attached per project, so their
  row offers **Attach in <open project>**, which opens that project's Sources
  page (where the source is added). With no project open the row says "open a
  project to attach it from its Sources page" and has no button.
- **Connect** opens the connect wizard in account mode (rail
  `Choose access → Sign in`; no document picking here — that is the project's
  Sources page, W2).
- **Scope is stated on every linked row**: `Read only`, `Read and edit`, or
  `Access level not recorded`. Scopes are fixed in connector code; nothing on
  this surface widens one.
- **Legacy grants** (`GET /users/me/connections/legacy`): a project-scoped grant
  from before account-level connections, made by this user, is listed under its
  provider as "Connected in a project, not yet on your account" with a note
  naming the projects. It is not a usable grant here (no Revoke). Two states:
  - no proving grant yet → note "…Sign in once to move it to your account —
    Rover keeps syncing until then." and **Sign in to move** (the account-mode
    wizard; the finished sign-in proves the account, nothing moves yet);
  - the user holds the matching CONNECTED grant → note "…Your linked account
    matches — move it so Rover uses your account grant." and **Move to your
    account**, which opens a confirmation stating exactly what happens: "Rover
    will use your linked Onshape account (read only access). The project's own
    Onshape token — and any add-on grant on it — is removed; syncing continues
    on your account." Confirm → `POST /users/me/connections/adopt` with those
    source ids and `confirm_access: true` → the row joins the linked account's
    "Used in". A move is never a side effect of loading Home or of a handshake.
    A project whose recorded access mode differs from the account grant's is
    never moved — it keeps its own token (its Sources page is where that changes;
    W2 follow-up).
- **Re-authorize** appears on a row whose last sign-in failed, with the
  provider's message; it runs the same account-mode wizard and lands on the SAME
  row (I1 dedupes by account), so the old token is replaced only once the new
  consent succeeded.
- **Revoke** is confirmed and names the projects it disconnects (unchanged).
- Hidden while offline (honest empty state elsewhere on Home).

### Health and quota per account (SOLUSDEV-244 / HOME H4)

```
| [On] Onshape · ada@example.com                                DEGRADED     |
|      Used in Rover and Arm · Read only                        [Revoke]     |
|      At least 1,440 of 1,800 Onshape calls this year (estimate)            |
|      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░                                                  |
|      ⚠ Approaching Onshape's call limit. Automatic syncs and SOL's Onshape |
|        calls are paused; your own Sync now still reaches Onshape. At the   |
|        limit Solus switches to cache-only reads and starts no new syncs.   |
| [On] Onshape · ada@example.com                              TOKEN EXPIRED  |
|      ⚠ The provider rejected this account's token. Re-authorize to        |
|        reconnect.                                          [Re-authorize]  |
```

- Every linked row carries a **health badge** — `HEALTHY` (quiet, muted) ·
  `TOKEN EXPIRED` · `DEGRADED` (warn colour) — from the server's `health`,
  which is DERIVED from stored state and never probed: a probe would spend the
  allowance the card protects. `token_expired` outranks `degraded`.
- **Quota position** (metered providers only, today Onshape): "At least N of A
  <Provider> calls this year (estimate)" over a thin bar. Always an estimate
  (ADR-019): a floor on Solus's own calls since the counter started, never a
  remaining balance — the words "remaining" and "left" never appear. Unmetered
  providers (GitHub, GitLab) and an unreachable ledger say nothing about quota:
  empty beats invented.
- **Approaching the limit** (the meter's degraded band, 70% of the allowance;
  an account at 80% is flagged): the badge reads DEGRADED and a warn note says
  what already degrades — automatic syncs and SOL's provider calls pause, the
  user's own Sync now still reaches the provider — and what happens at the
  wall.
- **At the wall** (allowance used, or the provider's 402 latched): the note
  explains cache-only mode — documents already synced stay readable, nothing
  new is fetched, no syncs run until the allowance resets — and says it is not
  an error and needs no sign-in. The grant stays CONNECTED; no Re-authorize.
- **Token expired** — the grant's last handshake failed, or a bound source's
  sync was refused with `invalid_credentials` — offers **Re-authorize** in
  place (the existing account-mode wizard; the row is replaced only once the
  new consent succeeds), even when the grant row itself still reads connected.
- Each transition INTO the degraded band or the wall is recorded once per
  account as an `integration.quota_degraded` / `integration.quota_exhausted`
  data event; loading Home again records nothing new.

## How you engineer (SOLUSDEV-244 / HOME H3)

```
| HOW YOU ENGINEER                                              [Edit] |
| ELECTRICAL                                                           |
| Prefer 0.1 mm clearance minimum on all boards. JST-GH for signal.    |
| UNITS AND STANDARDS                                                  |
| SI units. ISO 2768-m general tolerances.                             |
|                                                                      |
| (editing:)                                                           |
| CODE STYLE                                                  0 / 800  |
| [                                                                  ] |
| MECHANICAL … ELECTRICAL … DOCUMENTATION … UNITS AND STANDARDS        |
| ANYTHING ELSE                                              0 / 2400  |
| [                                                                  ] |
|                                            [Cancel]   [Save]         |
```

- The card sits in Home's right column under CONNECTED ACCOUNTS, and stays on
  the offline Home too: it is **machine-local**, the one part of `~/.solus` the
  user owns (`~/.solus/preferences.json`, ADR-034 amendment 2026-09-06). It is
  the Solus equivalent of a `claude.md` — a **document the user writes**, not a
  settings screen. No toggles.
- View: the sections that have text, labelled (Code style · Mechanical ·
  Electrical · Documentation · Units and standards · Anything else); empty ones
  are hidden. Nothing written yet → the intro line and a **Write** button
  ("SOL follows these on every turn and says when one changed its answer").
- Edit: one textarea per section with a `n / cap` counter (800 chars per
  section, 2 400 for Anything else — the caps are what bound the prompt), Save /
  Cancel. Save is optimistic through the desktop main process (atomic write,
  0600); a failed save keeps the editor open with "Couldn't save your
  conventions — try again." Cancel discards the draft.
- The card always carries the line "Stored on this computer and shared by everyone who
  signs in here." — the file is one per machine (ADR-034), so the sharing is stated, never
  silent. An identity change (sign-out, in-place session swap) drops the loaded copy; the next
  turn re-reads the file under the new identity.
- **Read-only** when the file was written by a newer Solus (shown, no Edit).
  **Unavailable** outside the desktop app ("Your conventions live in ~/.solus and
  are edited in the Solus desktop app.").
- **Effect**: the document rides along with every SOL turn
  (`POST …/sol/conversations/{id}/messages` body `preferences`) and enters the
  system prompt as one fenced data block, layered above the shipped engineering
  references and below a project's own `.solus` (reserved). SOL is told to apply
  the conventions and to say which one changed its answer. Nothing is stored
  server-side; the Custom instruction card on the SOL page (SOLUSDEV-233) stays
  a separate, server-stored answer-styling note.

## Project grid

- One card per live project of the active team: accent graph glyph, name
  (bold, ellipsised), description. The open project is told apart only by its
  footer (`Open` vs `Switch to`) — no mark, no accent border: cards share the
  standard card border, and the whole card is the click target (hover tint and
  focus ring on the card's own edge).
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
