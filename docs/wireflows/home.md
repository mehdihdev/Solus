# Wireflow — Home, the cross-project surface (SOLUSDEV-242 / HOME H1)

Home manages ACROSS projects, carries the TEAM layer (SOLUSDEV-244 / HOME H5:
the active team, its members and roles, one-time invites, join by token, the
team feed — the separate Team screen is retired), and connects WHOLE accounts.
Everything project-specific (documents, the graph, Live Bench, installed
widgets, SOL) lives in the workspace screens. Home is `MainScreen 'home'`, the first rail
item, the "All projects" entry of the project pill (`project-topbar.md`), and
`Solus → Home` in the menu row. `docs/api/API.md §5` ("/") is the route map.

```
| Welcome back, Maya        │ CURRENT PROJECT                                                  |
| Strider ▾              ⋯ │ Rover MK2                              [Live Bench] [Open workspace] |
| 3 members                 │ ( Overview )  Sources   .solus   Activity                        |
|                           │ ┌ ON THIS COMPUTER ──┐ ┌ SOURCES ───────────────┐ ┌ .SOLUS ──────┐ |
| PROJECTS · 2          [+] │ │ ~/code/rover       │ │ [Gh] GitHub [Pick repos]│ │ Hardware cfg │ |
| ┌ Rover MK2           ⋯ ┐ │ │ [Open in editor]   │ │      strider/rover-fw 42│ │ Project det. │ |
| │ six-wheel rover        │ │ │ Show in… More ▾    │ │ [On] Onshape [Pick docs]│ │ …            │ |
|                           │ │                    │ │ Add additional sources  │ │              │ |
| │ connected github · 2h  │ │ └────────────────────┘ └───────────────────┘ └───────────────────┘ |
| └────────────────────────┘ │ ┌ RECENT IN THIS PROJECT ─────────────────────── All activity → ┐ |
| ┌ Arm                 ⋯ ┐ │ │ connected github "…"                                   2h ago  │ |
| │ No recent activity.    │ │ └──────────────────────────────────────────────────────────────┘ |
| └────────────────────────┘ │                                                                  |
| ▸ ARCHIVED (1)             │                                                                  |
|                            │                                                                  |
| ┌ ACCOUNT ───────────────┐ │                                                                  |
| │ Connected accounts  1 HEALTHY │                                                            |
| │ Team & invites   3 MEMBERS │                                                               |
| └────────────────────────┘ │                                                                  |
```

## Layout: sidebar + one pane (SOLUSDEV-317 redesign, concept B)

Home is a full-height sidebar beside one pane; each scrolls on its own.

- **Sidebar** (300 px, `aside "Projects"`): the greeting; the team block
  (`TeamStrip`: name, ⋯ menu, "personal workspace · N members", the switcher
  with more than one team, the plan-limit line); the project list
  (`HomeProjectList`, `data-testid="project-list"`); and, pinned at its foot,
  the **ACCOUNT** card (`HomeAccountNav`).
  - Each project row (`project-row-<id>`): name; its linked git repo under
    the name (provider logo + `config.repo`, "+N" for more — read once per
    project per Home mount via `useProjectRepos`, the current project's from
    its live source list; no line when none or when the read failed);
    description; its latest activity line ("No recent activity." when none);
    the row ⋯ menu (Edit details / Archive / Delete, unchanged role gating)
    over the card's corner. The whole card is the select button (border,
    fill, hover tint). The current project has the accent border and
    `aria-current`. The project pane names the same repo under its title
    (`RepoLine`, shared by both). **Clicking a row selects it** —
    the old "Switch to": the current project moves, Home stays, nothing
    opens. `+` (members and up) opens New project; an empty list says "Create
    one to start building the graph."; the archived section is beneath.
  - There is no health dot — nothing in the API reports per-project health
    yet; empty beats invented.
  - **The team name is the switcher** (`TeamSelect`): with more than one team
    it is a button ("<name> ▾", accessible name "<name>, switch team") whose
    menu lists every team as `menuitemradio`, the active one checked and
    personal ones marked; picking another switches the active team. With one
    team it is plain text. There is no separate select.
  - The team ⋯ menu carries the account-level actions: **Invite teammate**
    (owners and admins), **Join team**, **New team**, then Rename / Leave /
    Delete with their existing gating.
  - ACCOUNT rows swap the pane (`aria-pressed`), each with a status that is
    left out until known: **Connected accounts** — "N HEALTHY", "N NEED
    ATTENTION" (warn; any linked grant not connected-and-healthy) or "NONE
    LINKED"; **Team & invites** — "JUST YOU", or "N MEMBERS · M PENDING".
- **Pane** (`data-testid="home-pane"`), three views:
  - **Project** (default, and whenever a row is selected): CURRENT PROJECT,
    name, description, **Live Bench** (navigates to Bench) and **Open
    workspace** (opens it). Four tabs:
    - **Overview** — concept 1: one **PROJECT SETUP** card beside a
      **RECENT** rail. The card lists, in one rhythm: ON THIS COMPUTER (the
      folder, `ProjectFolderCard compact bare`: path, scan line, Open in
      editor, Show in file manager, More ▾ → Change folder / Unlink); SOURCES
      (the SOURCES block below, every tool); and .SOLUS — WHAT SOL KNOWS
      (`SolusSummaryRow`: five segments, one per section, filled when it holds
      something; "N of 5 sections filled · <Section> (count) · …", or "Nothing
      yet"; **Add instructions** opens the .solus tab). The rail shows up to 5
      of the project's rows with a dot per kind (connected/created ok,
      disconnected warn, sync accent) and **All activity →** (Activity tab).
    - **Sources** — the full LOCAL FOLDER card (with detected projects) and
      the SOURCES block with every tool.
    - **The SOURCES block** (`ProjectSourcesSummary`): one row per tool the
      project holds something from, or whose account is already linked
      (holding tools first): the tool's logo (`ProviderMark`) and name; under
      it each of THIS project's sources — a git source by its repo
      (`config.repo`, e.g. "strider/rover-firmware"), anything else by name
      (a local folder by machine) — with its entity count, status word or its
      own error message; "Nothing in this project yet" for a linked tool with
      nothing here; the entity total sits in its own right-hand column. Each
      tool row offers its **project-level next step** as a text link
      (`nextStep`, shared with Connected accounts: Pick documents, Pick
      repositories, Enter details, Add to project, Choose file) through the
      SAME connect wizard; the local folder offers **Open folder** (reveals
      THIS machine's linked folder; nothing when it isn't linked here).
      **A local folder that is a clone of the project's GitHub/GitLab repo**
      (its `remote` — docs/api/local-folder.md §2 — matches that source's
      host and `config.repo`, case-insensitive) sits directly under the repo's
      row, joined by an accent connector between the two logos; the repo row
      says "Cloned on <machine>", the folder row "Clone of <owner/repo>". Tools neither linked nor
      used are left out. **Add additional sources** opens the Connected
      accounts view.
    - **.solus** — `SolusCard` on its own.
    - **Activity** — the project's own feed (`ProjectActivityFeed`,
      server-filtered `?project_id=`, its own `meta.total`, Load more).
    - No current project → "Select a project on the left to see its folder,
      sources and .solus."
  - **Team & invites** (`TeamInvitesView`, SOLUSDEV-317 design A, "one
    roster"): a header (team, counts, search, Invite teammate), the GitHub
    organization as a one-row strip (collaborative teams only) — or, on a solo
    team, two setup steps — then ONE People table (teammates, pending invites,
    org members not on the team) beside the TEAM ACTIVITY rail.
  - **Connected accounts**: `ConnectedAccountsCard`, unchanged. Opened from a
    project's **Add additional sources**, it carries **← Back to <project>**
    above the card, returning to that project's pane; opened from the sidebar
    (or after any other navigation) it has no back link.
- **Motion** (`features/workspace/home.css`, the house fade-rise: transform
  and opacity only, all of it off under `prefers-reduced-motion`): the pane
  eases in on every change of view or project, the tab panel on every tab;
  project rows, SOURCES rows and the RECENT rail stagger in (30 ms apart,
  capped at the 9th row — `homeStagger`); one accent indicator slides between
  the project tabs; cards ease their border and fill on hover and selection;
  .solus segments ease as they fill.
- Every card keeps its own rules below; only WHERE it sits changed. Ask SOL
  from Home is deferred until SOL accepts a starting prompt.

## Scope: the ACTIVE team

- Home shows ONE team's projects: the active team, `workspaceStore.teamId`,
  resolved by the rule in `features/workspace/activeTeam.ts` (kept while it is
  still one of my teams, else the personal team). The Team screen resolves the
  same way, so the two never disagree.
- **Team selector** (`TeamSelect`, shared with the Team screen): hidden with a
  single team. Choosing another team re-scopes the project list; a slow answer for the
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
    Selecting a project row re-scopes every row in place.
- **What already exists, beneath the row** (indented under the mark):
  - each linked **account grant**: login (one line, clipped), health badge,
    "Used in … · scope", quota meter (H4), optional Re-authorize for OAuth accounts, confirmed
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
- **Re-authorize** remains available on linked OAuth accounts for deliberate
  credential/application rotation, including healthy or quota-degraded accounts.
  Failed sign-ins additionally show the provider's message. It runs the same
  account-scope wizard and lands on the
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
  an error and needs no sign-in to resolve the quota itself. The grant stays
  CONNECTED. Optional Re-authorize remains available for independent credential
  rotation; it does not reset usage or the provider-exhaustion latch.
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

- The card sits in the project pane (Overview and its own **.solus** tab) and shows the
  CURRENT project's `.solus` (docs/api/solus.md): the five sections with honest
  counts ("EMPTY" when none). It re-scopes when a project row is selected. No
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

The team layer lives in the sidebar's team strip and the pane's **Team &
invites** view (SOLUSDEV-317 layout: sidebar + one pane; the old two-column
grid is gone):

```
| SIDEBAR                     | PANE — Team & invites                                                        |
| Welcome back, Maya          | TEAM & INVITES                                                               |
| Strider · 3 members [▾] ⋯   | Strider                                     [search people] [+ Invite teammate] |
| 2 of 2 collaborative teams… | 3 members · 1 pending invite · 4 more people in strider-robotics            |
|                             | ┌ (gh) strider-robotics · Organization · 14 repos  ● ACTIVE [Manage ↗] ⋯ ┐ |
| PROJECTS                    | └ Linked by Maya K · 3d ago · all repos ──────────────────────────────────┘ |
| ▸ arm-firmware   CURRENT    | ┌ PEOPLE · 8      [Everyone|Team|Invites|Not on Solus|No GitHub] ┐ ┌ TEAM   ┐ |
| ▸ chassis                   | │ PERSON        ROLE       GITHUB                        ACTIONS │ │ ACTIV- │ |
|                             | │ Maya K        Owner      @maya-k VERIFIED                      │ │ ITY    │ |
| ACCOUNT                     | │ Noor A        [Admin ▾]  @noor-a ASSIGNED by Maya [Unlink] ✕   │ │ …      │ |
|  Team & invites  3 · 1      | │ Sam Ortiz     [Member ▾] No GitHub linked [Link GitHub…]   ✕   │ │        │ |
|  Connected accounts         | │ dev@team.dev  Member (pending)  —                      [Revoke]│ │        │ |
|                             | │ IN STRIDER-ROBOTICS, NOT ON THIS TEAM · 4                      │ │        │ |
|                             | │ @jlee-fw      —          NOT ON SOLUS [Link to teammate…][Invite]│ └────────┘ |
|                             | └ A GitHub link is a label for attribution — never access. [Load more] ┘     |
```

Solo team (only its owner, no pending invite), the state a new team starts in:

```
| TEAM & INVITES · Team 2                                                             |
| Just you so far. Two optional steps make this a working team.                       |
| ┌ ① Invite a teammate ─────────────────┐ ┌ ② Link a GitHub organization to Team 2 ┐ |
| │ [teammate@team.dev      ] [Send invite]│ │ …org owner approves… [Link organization]│ |
| └──────────────────────────────────────┘ └──────────────────────────────────────────┘ |
| ┌ PEOPLE · 1 ──────────────────────────────────────────┐ ┌ TEAM ACTIVITY ┐          |
| │ mehdi@mehdi.us   Owner   No GitHub linked             │ │ …             │          |
| └───────────────────────────────────────────────────────┘ └───────────────┘          |
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
- **LOCAL FOLDER card** (the project pane: compact on Overview, in full on Sources;
  moved here from the retired Project Overview hub): the CURRENT project's working
  copy on this machine (`ProjectFolderCard`) — Select folder / Clone a repo,
  then the path (one line, clipped with "…", full path in the title), **Open in
  editor** / Show in file manager / Change folder / Unlink. Re-scopes when a project row is selected. No
  current project → "Open or switch to a project to link a working copy on
  this computer." Not under the desktop bridge → its honest note.
  Select/Change folder opens the native directory picker. Navigating into a
  directory does not select it: **Select this folder** confirms the choice.
  Solus waits for the machine registry to acknowledge the link before updating
  the displayed path or requesting a graph scan. A failed local save is shown
  inline and retains the previous link. Show in file manager only reveals it;
  it never selects, changes or integrates a folder. Clone uses the same
  acknowledged local-link sequence after the repository is created.
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
- **MEMBERS card** (the pane's Team & invites view): roster with roles;
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
  and its project list shows those projects without any per-project sharing.
- **GitHub organization** (`GitHubOrgCard`, SOLUSDEV-216 / ADR-039). On COLLABORATIVE teams only (absent on the personal team), as a one-row **strip** above the People table: the org avatar, `login · Organization · N repos`, "Linked by … · scope", a ● ACTIVE / ● SUSPENDED badge, **Manage on GitHub ↗** and ⋯. On a solo team with nothing linked it is **setup step 2** instead (`variant="step"`). The strip and the People table share one `useTeamGithub` (`TeamInvitesView`), keyed by team.

  - **The link always belongs to the active team** (the one in the sidebar switcher). Admins see "Link a GitHub organization to **<team name>**"; to link another team, switch teams first.
  - **Unlinked, admin+:** "Link your GitHub organization so everyone on the team can add its repos — no personal sign-in" and a **Link organization** button.
    - The button calls `install/start`, opens the install URL in the system browser, waits on the loopback, then calls `install/complete`.
    - Progress copy says the org owner approves on GitHub.
    - Refusals are named: `plan_limit_reached` (with **Upgrade**), `already_linked`, `installation_linked_elsewhere` ("This organization is linked to another Solus team — unlink it there first"), `installation_not_accessible`, and `installation_admin_required` ("Only an owner of <org> on GitHub can link it — ask one to link it from Solus").
    - `github_app_unconfigured` hides the button with the honest note "GitHub organizations aren't set up on this server".
  - **Unlinked, member or viewer:** "No GitHub organization linked — ask a team admin". No button.
  - **Linked:**
    - Shows the login, type, and repo count (from `/github/repos` meta).
    - Shows who linked it and when (`linked_by` null → "Linked by a former member").
    - Shows the access scope ("all repositories" or "selected repositories").
    - **Manage on GitHub ↗** opens `manage_url`.
    - The **⋯** menu (admin+) holds **Unlink** behind a confirm naming the count of project sources it disconnects. After the unlink, the dialog offers **Uninstall on GitHub ↗**.
  - **Suspended:** a warn row, "Suspended on GitHub — syncs paused until an org owner unsuspends Solus".
  - The roster is no longer a modal or a section of its own: org members are rows of the People table (SOLUSDEV-317, design A). After this admin links an org, focus moves to the People table's heading.
  - **A member left the org** (`github_org.member_removed_notice`): an in-app notification to admins and an activity row. Solus does not remove anyone.
  - Live: `team.updated` refetches the card.

- **People table** (SOLUSDEV-317 design A, ADR-039 amendment 2026-10-19; `RosterTable`). One table — PERSON · ROLE · GITHUB · ACTIONS — in this order: teammates, pending invites, then (only for an owner/admin whose team has an active `Organization` link) a group "IN <ORG>, NOT ON THIS TEAM · n". Nobody else ever calls `GET /github/members` (admin-only). A suspended or User link shows no org rows.
  - **Header:** "N members · M pending invites · K more people in <org>", a search over names, emails and logins, and **+ Invite teammate** (managers; the email invite dialog). Filters (`Segmented`): **Everyone / Team / Invites / Not on Solus / No GitHub**; "Not on Solus" only with org rows.
  - **Teammate rows:** name (email under it only when there is a name), role (a select for managers, never on the owner), the GITHUB cell, and ✕ remove (managers, confirmed with the person named). GITHUB: `@login` tagged **VERIFIED** (their own account; read-only) or **ASSIGNED** ("by <admin> · <time>"); managers with org rows get **Unlink** on an assigned label (confirmed inline) and **Link GitHub…** on a teammate with none (the picker lists org members nobody is linked to). Everyone sees the links; only managers change them.
  - **Invite rows:** the email or `@login`, "Invite sent … · expires in Nd", "<role> (pending)", `@login INVITED` for a GitHub invite, **Revoke** (confirmed).
  - **Org rows:** avatar (https only, else initials), `@login`, NOT ON SOLUS / INVITED, **Link to teammate…** (the picker: live teammates, minus anyone linked to a different org member; a teammate who verified a different account shown disabled with "@login · verified") and **Invite** (not on Solus only; the one-time token shows once in `GitHubInviteTokenModal`, held outside the table so a team switch or a live demotion never loses it; a plan limit shows **Upgrade** on the row). An org member a GitHub invite row already stands for is not listed twice.
  - **Assignment is a label, not a permission.** It never grants access, never changes a role, and never satisfies invite acceptance; the table's footnote says so (Guide paragraph / Expert line).
  - **Per row:** a pending spinner, an optimistic update rolled back on error, the error on that row (`role=alert`) and a `role=status` announcement after a change; other rows never block. Refusals: `not_a_team_member` (refetches members), `not_an_org_member` and `github_identity_verified` (refetch the roster), `member_has_verified_github` / `member_already_assigned` (name the other login, **Find @login** fills the search), `assignment_missing` (refetch silently), `installation_missing` / `installation_revoked` / `installation_suspended` (the strip refetches).
  - **The picker** (`AssignPicker`): a listbox popover portalled to `document.body` (rows animate in and are their own stacking contexts), flipped above the trigger when there is no room below, closed by Escape, Tab, a click away, a page scroll or a resize; roving focus with arrows / Home / End; a search box past 8 options.
  - **States:** the org part loading → a spinner row; failed → a note with **Retry**; **Load more** pages the org roster (50 a page); a filter or search with no match → "No organization members match this view."
  - Live: `team.members_changed` and `team.updated` refetch the loaded org rows quietly; `useHomeTeam` refetches `GET /members` on `team.members_changed`.
- **Solo team setup** (`TeamSetupSteps`): a collaborative team with only its owner and no pending invite replaces the search and Invite button with "Just you so far. Two optional steps make this a working team." and two cards: **① Invite a teammate** (an inline email form; the token shows once in the shared modal; bad email and plan limit named inline) and **② Link a GitHub organization to <team>** (the GitHub card's step variant, only while nothing is linked and the server supports it — once linked, the strip shows instead).

- **TEAM ACTIVITY** (the rail beside the People table, stacking under it on a narrow window; `TeamActivityPanel`): the
  humanised team feed, six rows with actor attribution, `View all activity (N)
→` opening the dialog with `Load more` (`activity-feed.md`). Per-project rows
  stay in the project pane.
- **Leave** moves Home to the personal workspace; the last owner is told to
  make someone else an owner first (`409 last_owner`). **Delete** likewise
  lands on the personal workspace.
- **Gone**: a stored team that no longer exists (deleted, or the user was
  removed — a 404, `useHomeData` status `gone`) reads "This team is no longer
  available…" with `Go to my personal workspace` — never "restart the backend".
- Settings keeps its Team section (rename, notify-on-new-project, the owner
  danger zone); its Members section is retired in favour of Home.

## Project list (SOLUSDEV-317 redesign; replaces the project grid)

- One row per live project of the active team: name (bold, ellipsised),
  description, and its LATEST activity line (humanised, relative time) or
  "No recent activity." The current project carries a CURRENT marker and
  `aria-current`; the whole row is the click target (hover tint, focus ring).
- **Selecting a row** makes that project current through the switch choke
  point (`switchWorkspaceProject`, surface `home`) and shows the Project view
  of the pane — it does NOT leave Home. Opening is the pane's
  **Open workspace** (lands on the project's Workspace).
- **Recent activity** rows come from ONE fetch of the team feed
  (`GET /teams/{id}/activity?limit=50`) split by `project_id` — a window,
  honestly labelled. The pane's RECENT ACTIVITY shows up to 5 of the current
  project's rows (`HOME_PANE_ACTIVITY_COUNT`); team-level rows (invites,
  members) appear only in the Team & invites view's TEAM ACTIVITY.
- `All activity →` (pane) opens the Activity tab (`ProjectActivityFeed`):
  server-filtered `?project_id=`, `Load more` while `has_next`, `N EVENTS` =
  the project's own `meta.total`.
- `⋯` menu (member+): `Edit details` (name + description, `ProjectEditModal`;
  the retired Overview hub's edit) · `Archive` · `Delete` (owner only,
  ADR-025, confirmed). The menu never opens the project. A failed archive raises the
  shell toast "That didn't work".
- **New project** (member+): the list's `+`; the name dialog
  creates in the active team and opens the project. In an empty team it adds
  "Create one to start building the graph." Viewers see "No projects in this
  team yet."

## Archived

- `▸ ARCHIVED (N)` collapsed by default beneath the project list; absent when N = 0.
  Archive hides without deleting: rows keep the name, offer `Unarchive`
  (member+) and `✕` delete (owner only, confirmed). Archived projects never appear
  in the project list or the project pill.

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
moves, `useHomeData` blanks the project list and reloads it for the new
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

## Live refresh — SOLUSDEV-312

Home's team layer (members, invites for admins, project list, activity, the GitHub org card and roster) and the
team switcher refresh quietly from the account event stream: `team.*` hints
refetch the affected list, `membership.changed`/`access.revoked` refetch `me`
and the team list (a team you were removed from disappears; one you joined
appears). There is no new visible UI and no toast; a dropped stream reconnects
with backoff and revalidates everything on `ready`.
