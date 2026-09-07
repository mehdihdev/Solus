# Wireflow — Home, the cross-project surface (SOLUSDEV-242 / HOME H1)

Home manages ACROSS projects, carries the TEAM layer (SOLUSDEV-244 / HOME H5:
the active team, its members and roles, one-time invites, join by token, the
team feed — the separate Team screen is retired), and connects WHOLE accounts.
Everything project-specific (documents, the graph, Live Bench, installed
widgets, SOL) lives in the workspace screens. Home is `MainScreen 'home'`, the first rail
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
  tracks from the same card — the Sources page is retired, SOLUSDEV-244). See
  "Connected accounts" below (HOME H2).

## Connected accounts (SOLUSDEV-242 / HOME H2)

```
| CONNECTED ACCOUNTS                                                          |
| (Mechanical) ( Electrical ) ( Simulation ) ( Software )     ← domain tabs   |
| ── one shape for every tool ────────────────────────────────────────────── |
| [On] Onshape                                            [Pick documents]   |
|      1 account linked · 2 connected in Rover                               |
|        ada@example.com  HEALTHY                                [Revoke]    |
|          Used in Rover and Arm · Read only                                 |
|        Chassis v3                                          [Disconnect]    |
|          ● connected · 1,204 entities                                      |
| [Fu] Fusion                                                    [Connect]   |
|      Server ready                                                          |
| ── Electrical ──────────────────────────────────────────────────────────── |
| [Ki] KiCad                                                 [Choose file]   |
|      Committed export · per project · 1 connected in Rover                 |
|        rover.xml                                           [Disconnect]    |
|          ● connected · 42 entities                                         |
| ── Simulation ──────────────────────────────────────────────────────────── |
| [Mu] MuJoCo                                                      [Start]   |
|      Ready · 1 session running in Rover                                    |
|        STREAMING  MuJoCo demo                12 INGESTED          [Stop]   |
| [Is] Isaac Sim                                                  (Start)    |
|      Unavailable on this machine · No in-app start — use a script or …     |
| ── Software ────────────────────────────────────────────────────────────── |
| [Gh] GitHub                                                    [Connect]   |
|      Not connected                                                         |
| [Gl] GitLab                                          (Pick repositories)   |
|      1 account linked · Open or switch to a project first.                 |
```

- **Domain tabs** (SOLUSDEV-244): four pills — Mechanical, Electrical,
  Simulation, Software — in that order, Mechanical selected on open. One tab
  is shown at a time (`role="tablist"`/`tab`/`tabpanel`), and each switch
  remounts the panel with a short fade-and-rise (`accounts-panel-in`; off under
  `prefers-reduced-motion`). A tool's domain is classified in the app by
  provider type (`accountDomains.ts`); a provider the app has no entry for lands
  under Software rather than disappearing. A domain with nothing to connect yet
  says so in place of rows. There is no footer line under the card.
- **One shape for every tool.** Each row is: mark, name, one status line, and
  ONE primary button — the **next step** for that tool. Beneath it, what already
  exists, each item with its own confirmed action. The next step is offered
  even when something already exists (a second account, a second export, a
  second session are one click away). Every step runs through the connect
  wizard modal (`ConnectWizardModal`, W2) — the same rail, header and copy the
  Onshape sign-in uses:
  - **OAuth tool, nothing linked** → `Connect` (account scope: rail
    `Choose access → Sign in`; no picking here).
  - **OAuth tool, account linked** → the connector's own next step on the
    CURRENT project, reusing the linked account so the rail skips the sign-in:
    `Pick documents` / `Pick repositories` (its declared selection), else
    `Enter details` (its config fields), else `Add to project`. Status line
    "N accounts linked · M connected in <project>".
  - **Committed-export tool** (KiCad, Altium) → `Choose file` (project scope:
    rail `Choose export → Build graph`). Status "Committed export · per project
    · M connected in <project>".
  - **Local tool** (Fusion) → `Connect`: the wizard's single step
    `Connect on this computer` shows the registry's `connect_notice` verbatim and
    its host, and closes on Got it. Status line is the live bridge word
    (`toolStatusText`).
  - **Simulator** (Simulation tab, `SimulationPanel`) → `Start`, which opens
    `SimulatorStartModal` in the wizard's visual language: MuJoCo starts the
    builtin demo scene; Gazebo asks for topics; MCAP replay for a path under the
    server's data root; Isaac has no in-app start and its Start is disabled with
    that reason. A refused start shows the backend's message in the modal.
  - A project-bound step with **no current project** stays visible but
    disabled, with "Open or switch to a project first." under the status line.
    "Switch to" on a project card re-scopes every row in place.
- **What already exists, beneath the row** (indented under the mark):
  - each linked **account grant**: login (one line, clipped), health badge,
    "Used in … · scope", quota meter (H4), Re-authorize when needed, confirmed
    **Revoke** naming the projects it disconnects;
  - each **legacy grant** (`GET /users/me/connections/legacy`): "Connected in a
    project, not yet on your account", **Sign in to move** → once the matching
    account is linked, confirmed **Move to your account** (unchanged from H2);
  - each **source the current project holds** for the tool
    (`GET /projects/{id}/sources` filtered by type): name, status dot, entity
    count, confirmed **Disconnect** (retains entities — the shared
    `DisconnectSourceModal`);
  - each **running session** for a simulator: link state, label, ingest count,
    **Stop** (`SessionChip`).
- **Scope is stated on every linked account**: `Read only`, `Read and edit`, or
  `Access level not recorded`. Scopes are fixed in connector code; nothing on
  this surface widens one.
- **Re-authorize** appears on a grant whose last sign-in failed, with the
  provider's message; it runs the same account-scope wizard and lands on the
  SAME grant (I1 dedupes by account), so the old token is replaced only once the
  new consent succeeded.
- Hidden while offline (honest empty state elsewhere on Home). The Simulation
  tab with no project says "Open a project to run a simulation…"; with the API
  unreachable it says so, never a fabricated inventory.

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

## The project's `.solus` (SOLUSDEV-253; replaces the HOW YOU ENGINEER card)

```
| .SOLUS  Rover FW                                                     |
| Everything SOL knows about this project — notes, files and what SOL  |
| filed. Yours to read and change; SOL reads it on every turn.         |
| → Hardware configs                                            EMPTY  |
| ↓ Project details                                                 1  |
|   ┌ Wheelbase 1.6 m, 6S battery                                    ┐ |
|   │ you · now                                        Edit  Delete  │ |
|   └────────────────────────────────────────────────────────────────┘ |
|   [Add a note] [Import file]                                         |
| → Error logging                                     AUTO + YOU    8  |
| → Documentation                                               EMPTY  |
| → Code environment                                            EMPTY  |
```

- The card sits in Home's right column under CONNECTED ACCOUNTS and shows the
  CURRENT project's `.solus` (docs/api/solus.md): the five sections with honest
  counts ("EMPTY" when none). It re-scopes with "Switch to" on a card. No
  project open → "Open or switch to a project to see its .solus."; offline →
  "Solus can't reach its API — …"; never an invented row.
- A row opens in place (grid-row slide, chevron turn; `prefers-reduced-motion`
  honoured): typed and SOL-filed notes (text, "you"/"filed by SOL", relative
  time, Edit, Delete), imported files (name, media type, size, Delete).
  **Add a note** opens the Workspace's own composer; **Import file** picks a
  file (8 MiB cap). Delete is armed on the first click ("Confirm delete?", red)
  and confirmed on the second; it disarms by itself after 4 s.
- Everything goes through the Workspace's `useSolusConfig`/`useSolusActions`:
  a note added here IS the node the Workspace's `.solus` shows, and Impact
  reaches it through the same `contains` edge.
- **HOW YOU ENGINEER (HOME H3, SOLUSDEV-244)** moved to **Settings**, under
  Appearance — the same View → Edit → Save document, still machine-local
  (`~/.solus/preferences.json`, ADR-034), still read by SOL on every turn. Home
  no longer hosts it, online or offline.

## The team layer (SOLUSDEV-244 / HOME H5)

```
| Strider · 3 members  [Strider ▾] ⋯          [✉ Join team] [👥 New team] [+ Invite teammate] |
| 2 of 2 collaborative teams on your plan · your personal team never counts                   |
| ⚠ You're at your plan's collaborative-team limit. Leave a team, or upgrade…   [Upgrade]     |
|                                                                                             |
| ┌ project grid (H1) ─────────────────────┐  ┌ MEMBERS · 3 · 1 PENDING        [+ Invite] ┐   |
| │ …                                     │  │ Maya K  maya@…            ● OWNER          │   |
| └───────────────────────────────────────┘  │ Noor A  noor@…      [member ▾] ✕           │   |
| ┌ TEAM ACTIVITY                  RECENT ┐  │ new@…   INVITE PENDING · MEMBER        ✕   │   |
| │ Maya invited noor@… · 2h ago          │  └────────────────────────────────────────────┘   |
| │ … (6 rows)                            │  ┌ CONNECTED ACCOUNTS ┐  ┌ .SOLUS           ┐      |
| │ View all activity (41) →              │  └────────────────────┘  └──────────────────┘      |
| └───────────────────────────────────────┘                                                    |
```

- **The team strip** always names the active team (`TeamStrip`): name, "personal
  workspace" on the personal team, member count from the team detail; the
  **switcher** (`TeamSelect`) only when the user belongs to more than one team;
  a **⋯ menu** with `Rename team` (admin+), `Leave team` (any member of a
  collaborative team; never on the personal team), and `Delete team` (owner
  only, never on the personal team, confirmed by the shared delete dialog naming
  the team and "every project in it"); `Join team` (token) and `New team` for
  everyone; `Invite teammate` for owners and admins.
- **Plan position, stated proactively**: "N of M collaborative teams on your
  plan · your personal team never counts" whenever the subscription's
  `max_teams` is known and finite (ADR-023: BASIC 2, PRO unlimited; ADR-025:
  the personal team is exempt). At the limit, a warn note carries the
  **Upgrade** button (→ Billing). Unknown subscription ⇒ no line (nothing
  invented).
- **Named refusals, never a silent failure**: `New team`, `Join team` and
  `Invite teammate` read the server's `409 plan_limit_reached` and show its
  sentence with **Upgrade** inside the dialog; a join refusal says which —
  invalid or used token, expired, issued to another email, already a member.
  The invitee's OWN plan is what blocks a join (ADR-023 cross-plan rule).
- **LOCAL FOLDER card** (right column, between MEMBERS and CONNECTED ACCOUNTS;
  moved here from the retired Project Overview hub): the CURRENT project's working
  copy on this machine (`ProjectFolderCard`) — Select folder / Clone a repo,
  then the path (one line, clipped with "…", full path in the title), **Open in
  editor** / Open Folder / Unlink. Re-scopes with "Switch to" on a card. No
  current project → "Open or switch to a project to link a working copy on
  this computer." Not under the desktop bridge → its honest note.
  **SOLUSDEV-249 (INTEGRATIONS I2):** linking also files the folder as a `local`
  source for THIS machine (`POST /local-folder`; unlink disconnects it). Under
  the path: the scan state — "Scanning…" (shimmer), "Scanned <ago>", or the
  sync's `last_error.message` verbatim. Then the **detected list**, one row per
  tool project the scan derived (KiCad, Altium, CAD folder, Arduino sketch,
  Python) with mark, name, relative path and its Open buttons built from the
  API's `open_targets` ("Open in KiCad" / "Open in Altium" / "Open in editor" /
  "Open"); rows fade in staggered, reduced-motion respected. Every Open control
  launches through the companion (`POST …/open`) — bridge offline → disabled
  with "Solus companion is offline on this machine", never hidden; a tool's
  refusal (`launched: false`) shows its reason inline. The folder's own
  "Open in editor", when disabled, writes its reason under the buttons
  (offline companion, VS Code missing, not scanned yet) — a tooltip alone was
  not enough (SOLUSDEV-253). Nothing detected → "Nothing
  Solus recognises in this folder yet (KiCad, Altium, CAD, Arduino, Python)."
  The same Open buttons appear in the Workspace inspector for a focused
  `local_*` node that belongs to this machine's folder (`LocalOpenPanel`), and
  the source itself is listed under Connected accounts › Software as
  "Local folder · <machine>".
- **SOLUSDEV-250 (INTEGRATIONS I3) — the "VSCode item", properly named:** under Connected
  accounts › Software, right below the Local folder row and only when a local source exists for
  this machine, a **Code environment** row (mark `Py`): status "<python> · <venv or 'no virtual
  environment'> · N requirement(s)" from a live probe, or the honest offline / "code server not
  running" / "not probed yet" line; a second line in the error colour when the checker found pin
  conflicts ("N dependency conflict(s) — split proposed"). **Details** opens the Code environment
  modal: INTERPRETER, VIRTUAL ENVIRONMENT, REQUIREMENTS, CONFLICTS (each warning verbatim with its
  pins), PROPOSAL (one card per environment, or "Single environment"), and **Ask SOL to set it
  up**, which hands SOL a prefilled request; every install/run/test SOL then proposes arrives as
  an approval card showing the exact command. Failed runs/tests appear in Workspace › .solus ›
  Error logging automatically.
- **MEMBERS card** (right column, above LOCAL FOLDER): roster with roles;
  owners and admins change roles (admin / member / viewer — ownership is
  transferred, not picked) and remove members, never on an owner row; pending
  invites with `Revoke`; `+ Invite` in the header for managers. **Remove and
  Revoke are confirmed** in a dialog naming the person and the consequence
  ("They lose access to every project in it" / "Its token stops working"). A
  refused mutation (403, last owner, failure) is shown inline under the roster,
  never swallowed.
- **Invite** (`InviteModal`): email in, then the **one-time join token shown
  once** with `Copy token`; `Done` while the token is uncopied asks a second
  time ("You won't see this token again"). The token is never logged or listed
  again (the server returns it only at creation). Inviting from the PERSONAL
  team spins up a new collaborative team server-side (ADR-025 keeps the
  personal team solo): the invite dialog says so BEFORE Send ("creates a new
  collaborative team (it counts against your plan) and Home switches to it"),
  and Home follows it.
- **Later joiners** get the team's existing projects automatically (the
  ADR-025 auto-grant on accept, `invites.py`); the joined team becomes active
  and its grid shows those projects without any per-project sharing.
- **TEAM ACTIVITY** (left column, under the grid; `TeamActivityPanel`): the
  humanised team feed, six rows with actor attribution, `View all activity (N)
→` opening the dialog with `Load more` (`activity-feed.md`). Per-project rows
  stay on the project cards.
- **Leave** moves Home to the personal workspace; the last owner is told to
  make someone else an owner first (`409 last_owner`). **Delete** likewise
  lands on the personal workspace.
- **Gone**: a stored team that no longer exists (deleted, or the user was
  removed — a 404, `useHomeData` status `gone`) reads "This team is no longer
  available…" with `Go to my personal workspace` — never "restart the backend".
- Settings keeps its Team section (rename, notify-on-new-project, the owner
  danger zone); its Members section is retired in favour of Home.

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
  project is open). `Open` — and a click anywhere on the card body — opens the
  project, landing on its Workspace (the Overview hub is retired, SOLUSDEV-244).
  `Switch to` does NOT leave
  Home: it makes that project current through the switch choke point
  (`switchWorkspaceProject`, surface `home`), so the accounts card's
  "Attach in …" and the Simulation tab re-scope in place and the card's footer
  flips to `Open`.
- `⋯` menu (member+): `Edit details` (name + description, `ProjectEditModal`;
  the retired Overview hub's edit) · `Archive` · `Delete` (owner only,
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

## Switching teams — a broader swap

Every team switch — the strip's selector, a created or joined team, leaving or
deleting the active team, the gone-team button — goes through
`switchWorkspaceTeam()` (`teamSwitch.ts`). If the open project belongs to
another team it is closed THROUGH `switchWorkspaceProject(null)`, so every
project-scoped store in that module's audit table is cleared; then `teamId`
moves, `useHomeData` blanks the grid and reloads the project list for the new
team, and `useHomeTeam` (keyed on the team id with a stale-response guard)
reloads members, invites and the feed. A project already in the target team
stays open. Reported as the `team.switched` data event.

## States

- **Loading**: centred spinner.
- **Offline / signed out**: the honest card ("Sign in to Solus…" or "…can't
  reach its API…"), never a demo project (SOLUSDEV-152).
- **No teams**: "You're not on any teams yet. Create one, or join with an
  invite token." with the account actions still available.

## Removed (SOLUSDEV-242)

- The per-team cards listing every team's projects, and the merged cross-team
  RECENT ACTIVITY panel with its all-activity dialog (`activity-feed.md` §Home
  surface). Activity on Home is per project on the cards; since HOME H5 the
  single-team TEAM ACTIVITY panel also lives on Home (it was the Team screen's).

## Removed (SOLUSDEV-244 / HOME H5)

- The separate Team screen (`MainScreen 'team'`, its rail item and menu entry)
  and Settings → Members: both consolidated into Home above.
