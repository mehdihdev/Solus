# Completion report — SOLUSDEV-244 · HOME H5: The team layer in Home

Branch: `SOLUSDEV-244-home-h3-root-preferences` (shared with CORPUS C2 and STORE ST3–ST5 sessions;
local commits only, no push, no MR). Cowork QA: `docs/qa/COWORK_QA_home-h5-team-layer.md`.
Sibling reports: `COMPLETION_SOLUSDEV-244-home-h3.md`, `COMPLETION_SOLUSDEV-244-home-h4.md`.

## What already existed and was reused, not rebuilt

Teams, the personal team, one-time invite tokens (7-day expiry, returned once at creation and
never on listings), roles with owner-only delete and admin-gated role changes, the ADR-025
auto-grant of existing projects to a later joiner, the `409 plan_limit_reached` enforcement with
its `{limit, current, max, upgrade}` details, `TeamSelect`, `LiveMembers`, `InviteModal`,
`ActivityModal`, `activityText`, the join and new-team dialogs. Each was consolidated into Home;
the Team screen's inline pieces (header, activity panel) were extracted, not copied.

## What H5 built (design-gate answers: retire the Team screen; Settings keeps Team, drops Members; add Leave; rename/delete on Home and Settings)

- **A team-switch choke point** (`teamSwitch.ts`): closes a project of the previous team THROUGH
  `switchWorkspaceProject(null)` (so focus, SOL session selection, extension selection, toast,
  companion are all dropped), then moves `teamId`; a project already in the target team stays
  open; re-selecting the active team is a no-op; `team.switched` data event. Audit note added to
  `projectSwitch.ts`. Before H5 a switch was `setTeamId` alone and an open project from the old
  team survived it.
- **Plan limits stated honestly** (`lib/api/planLimit.ts`, `PlanLimitNotice`): the server's
  `plan_limit_reached` block is read instead of folded into "try again"; New team, Join team and
  Invite show the server's sentence with **Upgrade** (→ Billing) inside the dialog; the strip shows
  "N of M collaborative teams on your plan · your personal team never counts" proactively from the
  subscription's `max_teams`, and at the limit a warn note with Upgrade. Unknown subscription ⇒
  no line. Join refusals are named (invalid/used token, expired, other email, already a member).
- **`useHomeTeam`**: the active team's detail, members, pending invites (a member's 403 on the
  invite listing is tolerated), the team feed with cursor paging, my role, my plan position;
  mutations `invite` (follows the collaborative team the server spins up from a personal team),
  `revoke`, `changeRole`, `remove`, `leave` (falls back to the personal team; `last_owner` named),
  `rename`, `deleteTeam` (falls back to the personal team). Keyed on the team id with a
  stale-response guard.
- **Home**: `TeamStrip` (name, member count, "personal workspace", switcher only with more than
  one team, ⋯ menu with Rename admin+, Leave, Delete owner-only and never on the personal team,
  Join / New team / Invite for managers, the limit line); `LiveMembers` in the right column
  (roles, remove, revoke, `+ Invite`); `TeamActivityPanel` under the grid (six rows, actor
  attribution, view-all with the server total and Load more); `HomeTeamModals`; a **gone** state
  for a deleted team ("Go to my personal workspace") instead of "restart the backend".
- **InviteModal**: the one-time token with **Copy token**; **Done** while uncopied asks a second
  time; the personal-team spin-up is explained. The token is never logged, never in an event, and
  masked in this run's evidence.
- **Retired**: the Team screen (rail item, menu entry, `MainScreen 'team'`), Settings → Members.
  Settings keeps its Team section (rename, notify, danger zone).
- **Fixed on the way**: the desktop's `deleteTeam` never sent the `?confirm=true` the API demands,
  so every team delete from the desktop (Settings, pre-existing) answered 400. Found in the live
  run; the confirm dialog is the confirmation.
- Docs: `docs/wireflows/home.md` (team layer, switching teams, removed sections),
  `docs/wireflows/activity-feed.md` (surface moved), `docs/api/API.md` (self-leave on the
  DELETE-member row; the personal-team invite row now cites ADR-025/023 and the once-only token).

## Governing docs

ADR-023 (limits as data; hard block with a clear message; invitee's own plan), ADR-024 (credits
per user — nothing team-level to show), ADR-025 (personal team solo and exempt; roles; per-project
auto-grant), ADR-032; `docs/wireflows/home.md`, `docs/wireflows/activity-feed.md`,
`docs/api/API.md` §2.2; `apps/desktop/CLAUDE.md`. `docs/design/SPEC.md` and
`docs/design/screens/` do not exist in this repo.

## Verification

- Desktop: 2 884 tests green across 275 files after the retirement (new suites: teamSwitch 5,
  planLimit 7, useHomeTeam 13, TeamStrip 6, TeamActivityPanel 3, PlanLimitNotice 2,
  HomeTeamModals 7, MembersPanel 10, HomeScreen +6, modals +2, useHomeData +4); renderer and main
  typecheck clean except another session's uncommitted `bom/BomScreen` import. No API code changed.
- **Real run, API** (private uvicorn from a clean worktree of HEAD — another session's uncommitted
  `connectors/worker.py` did not import at the time): user A on BASIC created Rover Lab → "Rover
  MK2" and Arm Lab → "Arm v1"; a third team answered `409 plan_limit_reached`
  `{limit: max_teams, current: 2, max: 2, upgrade: /settings/billing}`; A invited B (token
  returned once, absent from the invite listing); B had no access before joining (404).
- **Real run, desktop** (the real Electron app over CDP), screenshots in the job scratch dir:
  - `h5-a-home.png`: Rover Lab · 1 member, the switcher, "2 of 2 collaborative teams on your plan
    · your personal team never counts", the at-limit note with Upgrade, the Rover MK2 card, the
    members card with the pending invite, TEAM ACTIVITY.
  - opened Rover MK2 then switched to Arm Lab in the strip: the open project became none (pill
    "No project"), the grid showed Arm v1 (`h5-a-switched.png`).
  - New team "Third": the dialog showed the server's limit sentence with Upgrade; Upgrade landed on
    Billing (`h5-b-limit-dialog.png`, `h5-b-billing.png`).
  - Invite teammate: the one-time token was revealed (43 chars, masked in the screenshot), Done
    asked a second time while uncopied, the pending invite then listed (`h5-c-invite-token.png`).
  - B signed in on their personal team (0 of 2), pasted the token in Join team: Home switched to
    Rover Lab (1 of 2, 2 members) and showed **Rover MK2** with no per-project share
    (`h5-d-joined.png`); at the API B listed and opened the project (200) and was still 404 on Arm
    Lab. The run's teams were deleted afterwards.
- One suite failure in the shared checkout during the run was another session's (worker.py);
  none in H5's scope.

## Decisions under delegated judgment

- Layout: the strip above the grid; MEMBERS above CONNECTED ACCOUNTS; TEAM ACTIVITY under the grid.
- "Approaching" is not a concept here: the limit line is always shown when the cap is finite; the
  at-limit note appears exactly when the server would refuse.
- Leave is offered to every member of a collaborative team; the server's `409 last_owner` is
  surfaced as "make someone else an owner first". Ownership transfer UI is not built (the API
  supports it via PATCH role=owner by an owner) — noted below.
- `MainScreen 'team'` was removed from the union rather than aliased: `lastMain` is never
  persisted, so no stored value can reference it.
- `data-testid` hooks (`team-name`, `team-limit`, `plan-limit`, `invite-token`) are the CDP and
  test anchors.

## Deviations / open concerns

- **Phase 4 reviews completed and were remediated (commit after 9ab573e).** Security review
  verdict was FAIL on three HIGHs, all fixed: H1 member removal and invite revoke ran on one click —
  both now confirm with the person named and the consequence ("They lose access to every project
  in it"); H2 the `?confirm=true` fix had reawakened Settings' inline two-step delete that named
  nothing — it now renders the shared delete dialog naming the team and the cascade; H3
  authorization failures on role/remove/revoke were swallowed — they now return named outcomes
  (`forbidden`, `last_owner`, `failed`) shown inline. MEDIUMs: M1 the invite listing's catch is
  narrowed to 403/404 (a 500 is a failure, not "no invites"); M2 the at-limit sentence is the
  server's own, no client claim about what an upgrade buys; M3 inviting from the personal team
  now says BEFORE Send that a counted collaborative team will be created; M5 the hostile-text test
  covers member names/emails, the team name and feed payloads. LOWs: L1 a failed clipboard write is
  said and the token is not marked copied; L2 the server sentence is length-bounded; L3
  `useTeamData` is slimmed to what Settings renders (detail, role, rename, notify, delete — four
  fewer calls per Settings visit). Code review HIGHs: `deleteProject` also lacked the API's
  `?confirm=true` (every desktop project delete answered 400 — fixed, test pinned); the hook's
  refreshers and load-more had no stale guard (a late refresh from the team you left could land
  under the new team) — fixed with a team-id ref and a test. Dead `listActivity` removed.
- **Not fixed (pre-existing, reported): security M4** — the invite token travels in the accept
  URL path, and the API's unhandled-error logger records `request.url.path`, so a 500 on that route
  would write a live token to logs. Fix needs an `API.md` §2.2 amendment (token in the body) or
  path redaction in `core/errors.py`; worth its own ticket.
- **Not built**: ownership transfer UI (API-only), pagination of the members list (the API is
  unpaginated), invite-token hashing at rest (pre-existing; the token is stored plaintext in
  `invites.token` and also placed in the invitee's notification — both pre-date H5 and are worth a
  ticket), `listActivity` dead export in `resources.ts` (pre-existing).
- ADR-025 lists three roles; the system has four (`viewer`). Tier-2 doc; flagged, not edited.
- The desktop still folds unknown 409s into "unreachable" for non-team calls (`errors.ts`), by
  design; only team actions read the limit block.
- Values a human must set: none new.
