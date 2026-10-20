# Completion report: GitHub org member assignment (frontend)

Ticket branch: `SOLUSDEV-317-sol-command-execution` (per the orchestrator's override, worked directly on it). Spec: the "Prompt" section of `2026-10-19-github-org-members-frontend-prompt.md`. Backend partner: the `SOLUSDEV-317/github-member-assignment` worktree session (built in parallel; not merged here).

## What was built

- **Typed client** (`lib/api/resources.teamGithub.ts`, `resources.ts`): `assignGithubMember` (PUT `…/github/members/{github_id}/assignment`, body `{user_id}`, unwraps `{assignment}`), `unassignGithubMember` (DELETE, 204), `GithubAssignment` / `GithubIdentitySource` types, `GithubOrgMember.assignment`, `TeamMemberApi.github`, five new codes in `GITHUB_ORG_ERROR_CODES`, and `githubErrorLogin(err)` to read the other login a refusal names in `details`.
- **Roster state** (`useGithubOrgRoster.ts` + pure `githubOrgRoster.ts`): paged roster (50 a page, Load more by cursor), optimistic assign / unassign with per-row pending, error and `role=status` announcement, rollback on every refusal, invites through the existing `useTeamGithub.inviteMember`. Team-switch guard (`teamRef` after every await) and a load sequence guard; quiet refetch on `liveKeys.teamMembers` and `liveKeys.team` that re-reads every loaded row (up to 100).
- **GITHUB ORG MEMBERS section** (`GitHubOrgMembersSection.tsx`, `GitHubOrgMemberRow.tsx`, `UnassignedTeammateRow.tsx`, `githubOrgMembersView.ts`): explainer (Guide paragraph / Expert line), "N org members · M on this team", login search, `Segmented` filters All / On team / Not on Solus / Unassigned teammates, chips Verified / Assigned / Invited / Not on Solus, Assign / Change / inline-confirmed Unassign, Invite on `not_on_solus` only, plan-limit Upgrade, empty / failed + Retry states.
- **One picker** (`AssignPicker.tsx`): popover listbox, roving focus (arrows, Home, End), Enter/Space pick, Escape returns focus to the trigger, click-out closes, search box past 8 options. Used from both sides (teammate for an org row; org member for a teammate).
- **Token reveal** (`GitHubInviteTokenModal.tsx`, held in `githubInviteTokenStore.tsx`): the one-time token in a small labelled modal; Escape and click-out never discard it; Done asks twice while uncopied. The reveal lives in a Zustand store rendered by a host on Home, so it survives the section unmounting (team switch, demotion, suspension).
- **Card + section container** (`TeamGithubPanel.tsx`): one `useTeamGithub` feeds the card and the section; the section mounts only for owner/admin with an active `Organization` link; focus moves to the section heading after a link this admin started.
- **Card** (`GitHubOrgCard.tsx`): now takes `github` + `teamName` as props; "Link a GitHub organization to **<team>**" for admins; the "Members on GitHub" button and `GitHubRosterModal` are gone (deleted with its test). `useTeamGithub.loadRoster` removed (no callers).
- **Members list** (`MembersPanel.tsx`): GitHub mark (`logoClass('github')`) + `@login` + verified/assigned tag for everyone; admin-only **Assign GitHub…** on unlinked members, offered only while the section is on screen. It goes through `githubAssignFocusStore` (Zustand): the section scrolls into view, switches to Unassigned teammates and opens that teammate's picker.
- **Home** (`HomeScreen.tsx`): Team & invites order MEMBERS → GITHUB ORGANIZATION → GITHUB ORG MEMBERS → TEAM ACTIVITY, keyed by team.
- **Copy** (`githubOrgCopy.ts`): 20 new Guide/Expert keys; the key-iteration test now also fails on any unfilled `{placeholder}`.

## Docs

- `docs/wireflows/home.md` (tier-1, edited directly): Team & invites order; card link-target line; the new GITHUB ORG MEMBERS and members-list GitHub link sections; the team-layer ASCII redrawn for the sidebar + pane layout; stale "grid" wording replaced (team selector, later joiners, TEAM ACTIVITY position, Archived, team switch, live refresh).
- `docs/qa/COWORK_QA_github-org-member-assignment.md`: link → roster → assign / change / unassign → refusals → invite → browsing → who sees what → team switch → live update from a second window → safety.

## Verification

- `npx vitest related --run <every changed file>`: 162 files, 1872 tests passing.
- `tsc --noEmit` for `tsconfig.web.json` and `tsconfig.node.json`: clean.
- eslint on changed files: 0 errors (4 `max-lines-per-function` warnings, all in pre-existing functions: `GitHubOrgCard.test.tsx`, `GitHubOrgCard.tsx` `OverflowMenu`, `useTeamGithub.test.ts`). Prettier clean.
- New tests: client (paths, methods, bodies, 200/204, every new code), pure helpers, hook (optimistic + rollback per code, stale-team drop, live keys, disabled = no roster call), picker (roving focus, disabled options, Escape, click-out, search past 8, openRequest), section (every chip, verified read-only, picker exclusions, Change, Unassign confirm, invite + token once, plan limit, filters incl. Unassigned teammates, search, Load more, members-list hand-off, empty, failure + Retry, Guide/Expert), panel gating, members-list badge + admin affordance, HomeScreen order and hand-off.
- `schema.ts` was **not** regenerated (the backend isn't merged here).

## Phase 4 reviews (code-reviewer + security-reviewer), all addressed

- **Security, MEDIUM:** the token reveal lived inside the conditionally mounted section and could be lost on a team switch, a live demotion or a suspension. Fixed by moving it to `githubInviteTokenStore` + `GitHubInviteTokenHost` (always mounted on Home); regression test added.
- **Security, LOW:** the teammate-side picker allowed overlapping assigns. Fixed (disabled while pending, plus a hook-level pending guard). Not changed: avatars still use `safeHttpsUrl` (any https host), matching the existing card. Restricting to `avatars.githubusercontent.com` would break GitHub Enterprise Server avatars; left for a CSP `img-src` decision.
- **Code review, MEDIUM, all fixed with regression tests:**
  - a quiet live refetch that superseded the first load and then failed left the spinner forever; it now ends in `failed`;
  - a Load more reply that arrived after a refetch replaced the page is now ignored, and pages are de-duplicated by `github_id`;
  - a members-list "Assign GitHub…" request reopened its picker on every filter revisit; it is now consumed once;
  - focus was lost after a pick (the trigger got disabled) and around the Unassign confirm. The trigger now stays enabled (the hook ignores repeats), Confirm takes focus, and Confirm/Cancel return focus to the row's picker;
  - the post-link heading focus could fire again on a later remount; it now resets;
  - a refetch could overwrite a row mid-mutation; pending rows now keep their on-screen state, and a second mutation on a pending row is ignored.
- **Code review, LOW:** the picker now closes on Tab-out, keeps focus inside when every option is disabled (so Escape works), and no longer marks the roving option `aria-selected`. Not changed: short control labels ("Assign", "Change", "Unassign", "Load more", chip and filter names) are single-word labels with no Guide/Expert variants. That matches the existing card and roster ("Invite", "On team", "Retry"); every sentence goes through `githubText`.

## Personal workspace (asked mid-task)

The user saw no change on their **Personal** workspace. That is by design: ADR-039 links an org to a collaborative team only (backend `personal_team_unsupported`), and a collaborative team with one member does show the card. Asked in-chat: **leave as is** (no card on Personal).

## Contract drift vs §3.2

Checked read-only against the backend worktree's uncommitted routers on 2026-10-19 — no drift found in shapes:

- Roster items carry `assignment` (null or the §3.2 object); `solus_status` is `member` exactly when an assignment resolves; `limit` is 1–100 (default 50).
- `PUT` returns `{assignment}`; `DELETE` returns 204.
- `GET /members` items gain `github: null | {github_id, github_login, avatar_url, source}`.
- Refusals `member_has_verified_github` / `member_already_assigned` carry `details: [{github_id, github_login}]`; the UI names that login.

Backend session's final notes (2026-10-19) add, without changing §3.2: `409 installation_revoked` on PUT (now refreshes the card like `installation_missing`), `429 rate_limited` with `Retry-After: 60`, `details[].github_login` may be null (the UI then falls back to the teammate's own login or omits the Find button), and DELETE works on a suspended link. The card now names a `503 github_app_unconfigured` from `install/start` with the "not set up on this server" copy (82ae6d63).

The hand-written types make `assignment` and `github` optional (`?:`) so older fixtures compile; once `make gen-openapi` runs after the merge, tighten them to required if the generated schema says so.

## Decisions under delegated judgment

1. **Roster state lives in a sibling hook** (`useGithubOrgRoster`), not inside `useTeamGithub` as §4.5 suggests. `useTeamGithub` is shared by every viewer; the roster is admin-only, so keeping it apart guarantees non-managers never call the 403 route. `TeamGithubPanel` composes the two.
2. **Verified teammates in the picker** are shown disabled with "@login · verified" rather than hidden, so §4.2's "excludes anyone already verified" and "shows each teammate's own verified GitHub login" both hold. Teammates admin-assigned to a different org member are hidden.
3. **"Not on Solus" filter** includes Invited rows (they are not on the team yet).
4. **Optimistic unassign** shows `not_on_solus`; if that GitHub id has a pending invite the server's next refetch corrects it to `invited`.
5. **`not_a_team_member`** refreshes members by bumping `liveKeys.teamMembers(teamId)` locally (quiet refetch in `useHomeTeam` and the roster) rather than calling `useHomeTeam.refresh`, which reloads the whole team loudly.
6. **`member_already_assigned`** offers **Find @login** (sets the search to the other login) rather than an unassign button on a row that might not be loaded.
7. **`installation_suspended`** on a mutation shows the card's suspended copy on the row and refreshes the card, which then hides the section.
8. The token modal title is "Invite @<login>".

## Open questions for the backend / humans

1. **Unassign while suspended:** the backend deliberately allows `DELETE …/assignment` on a suspended link, but the spec hides the section when suspended, so an admin can't remove labels then. Keep the section hidden, or show it read-only with Unassign only?
2. **`429 rate_limited`** on assign/unassign (30/min per user) currently reads as the generic "Couldn't save that assignment". Worth its own copy?
3. **Assigner gone:** the backend sends `assigned_by: null` on an admin assignment whose assigner's user row no longer exists; the UI then omits the "by …" line (and says "by a former member" if only `name` is null). Fine, or should it always say who?
4. **Invited + assigned:** an org member with a pending invite who gets assigned shows `member` (the server's rule). Fine for the UI; flagging that the Invited chip then disappears.

## Not done / follow-ups

- After the backend merges: `make gen-openapi`, diff, tighten optional fields, rerun the desktop suite.
- No live run of the app against a real org (backend not merged here); the Cowork QA file covers it.
