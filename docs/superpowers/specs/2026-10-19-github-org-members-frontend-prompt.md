# Frontend prompt: GitHub org linking and member assignment on the redesigned Home

Status: READY to paste, 2026-10-19. The §3.2 backend is being built in parallel. It builds on SOLUSDEV-216 (ADR-039) and the SOLUSDEV-317 Home redesign.

**Backend dependency:** §3.2 describes a **new** API (assigning GitHub org members to Solus members). It is not built yet, and it needs the ADR-039 amendment in §6 approved first. The frontend can start against the documented contract with a mocked client, but it can't ship until the backend lands.

**No new GitHub registrations.** The root `.env` already configures both:

- the OAuth App, for personal connects: `SOLUS_GITHUB_CLIENT_ID` / `SOLUS_GITHUB_CLIENT_SECRET`;
- the GitHub App, for team org links: all six `SOLUS_GITHUB_APP_*`.

---

## Prompt (paste into a frontend agent session)

> **SOLUSDEV-\_\_\_: link a GitHub organization to a team and assign its members to Solus teammates (desktop, redesigned Home)**
>
> You are a frontend agent working under `/Users/mehdihdev/Solus/CLAUDE.md` and `apps/desktop/CLAUDE.md`. Work on your ticket branch only; never push or open MRs.
>
> TDD is required (vitest + Testing Library). Use the typed client only, no raw fetch. Use Zustand for any cross-component state, and keep updates immutable. Use design tokens only. Every sentence shown to the user needs a Guide and an Expert variant (`settingsStore.solMode`).
>
> Do NOT register or configure any GitHub OAuth App or GitHub App, and do not touch `.env*`. Both registrations already exist and are configured server-side.
>
> ### 0. Working in parallel with the backend
>
> - **Contract.** The assignment API in §3.2 is being built right now by a separate backend session, on its own branch cut from `SOLUSDEV-317-sol-command-execution`. Cut your branch from that same base. Linking, the roster and GitHub invites (§3.1) already exist there.
> - **Code against §3.2 exactly.** Add the new client functions and types by hand in `resources.teamGithub.ts` / `resources.ts`, and mock them in every test. Do **not** regenerate `schema.ts` until the backend branch is merged into yours.
> - **When the backend lands** (a human merges it into your branch):
>   - run `make gen-openapi`;
>   - diff the generated shapes against your hand-written types and fix any drift, since the backend route plan wins;
>   - run the full desktop suite again;
>   - list the drift in your completion report.
> - **Don't block on it.** If a §3.2 detail is ambiguous, pick the reading the spec implies, note it in the completion report, and keep going. Don't edit backend files.
>
> ### 1. Goal
>
> On the redesigned Home, in the **Team & invites** pane view:
>
> 1. **Link.** A team owner/admin links a **GitHub organization** to the **active Solus team**. The link always belongs to the team shown in the sidebar switcher; to link a different team, switch teams first.
> 2. **Roster.** Admins see **every member of that GitHub org**, with how each one relates to the Solus team.
> 3. **Assign.** Admins can **assign** each GitHub org member to a Solus team member, change it, or remove it. They can still **invite** org members who aren't on Solus yet.
> 4. **Members list.** Everyone on the team sees, in the members list, which GitHub account each teammate is linked to.
>
> **Assignment is a label, not a permission.** It records "GitHub user X is our teammate Y", so the roster and GitHub activity show the right person. It never grants Solus access, never changes a role, and never counts as identity proof when someone accepts an invite. Say so in the UI (Guide mode explains it; Expert gets one short line).
>
> ### 2. Read first (governing docs, in authority order)
>
> 1. `DECISIONS.md`: ADR-039 and the assignment amendment (ADR-039 §6a, see the spec packet). ADR-016 covers SOL modes.
> 2. `docs/api/github-orgs.md`: existing routes, error codes, §6 decisions. The new assignment routes go in a new section (spec §3.2).
> 3. `docs/wireflows/home.md`:
>    - L33-124: the redesign layout (sidebar + one pane; the Team & invites view at ~L110).
>    - L418-446: the GitHub organization card states.
>    - **Its team-layer ASCII (~L321-334) and some "grid" wording (L132-134, L448-451, L490, L517) are stale** from before the redesign. Update them as part of this ticket. Wireflows are tier-1, so you edit them directly and call it out in the completion report.
> 4. This spec packet: `docs/superpowers/specs/2026-10-19-github-org-members-frontend-prompt.md`.
>
> ### 3. API
>
> #### 3.1 Already live (SOLUSDEV-216)
>
> The typed client is `lib/api/resources.teamGithub.ts`. The hook is `features/workspace/useTeamGithub.ts`.
>
> | Call                                                         | Route                                  | Role       | Use                                                                                                                                         |
> | ------------------------------------------------------------ | -------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
> | `startGithubInstall(teamId, redirectUri)`                    | `POST /teams/{t}/github/install/start` | admin+     | Returns `{install_url, state}`. The existing `githubInstallFlow.runGithubInstall` drives the browser + loopback; reuse it, don't rewrite it |
> | `completeGithubInstall`                                      | `POST …/install/complete`              | admin+     | `linked` or `requested` (an org owner must approve on GitHub)                                                                               |
> | `getTeamInstallation`                                        | `GET …/installation`                   | viewer+    | `TeamInstallation \| null`. Includes `bound_source_count` for the unlink confirm                                                            |
> | `unlinkTeamInstallation`                                     | `DELETE …/installation`                | admin+     | `{disabled_sources, manage_url}`                                                                                                            |
> | `listTeamGithubMembers(teamId, {cursor, limit})`             | `GET …/members`                        | **admin+** | Org roster, page `{items, total, cursor}`. A viewer/member gets 403, so don't call it for non-managers                                      |
> | `createInvite(teamId, {github_user_id, github_login, role})` | `POST /teams/{t}/invites`              | admin+     | Suggested invite. The response carries a one-time `token` (show it once)                                                                    |
> | `listMembers(teamId)`                                        | `GET /teams/{t}/members`               | viewer+    | `TeamMemberApi[]`                                                                                                                           |
>
> Existing error codes are in `GITHUB_ORG_ERROR_CODES`. `githubOrgErrorCode(err)` narrows them, and `githubOrgCopy.ts` has Guide/Expert text for each.
>
> #### 3.2 NEW: required from the backend (build against this contract)
>
> Add these to the typed client in `resources.teamGithub.ts` / `resources.ts` exactly as below. Mock them in tests. If the backend lands with different shapes, the route plan wins, so adapt.
>
> ```
> type GithubIdentitySource = 'verified' | 'admin'
>
> // GET /teams/{t}/github/members — each item gains `assignment`
> GithubOrgMember = {
>   github_id: number, github_login: string, avatar_url: string | null,
>   solus_status: 'member' | 'invited' | 'not_on_solus',   // 'member' ⇔ assignment != null
>   assignment: null | {
>     user_id: string, name: string | null, email: string,
>     source: GithubIdentitySource,          // 'verified' = they linked their own GitHub; not editable
>     assigned_by: { user_id: string, name: string | null } | null,   // null when verified
>     assigned_at: string | null
>   }
> }
>
> // PUT /teams/{t}/github/members/{github_id}/assignment   (admin+)
> //   body { user_id }  → 200 { assignment }   (upsert: replaces an existing ADMIN assignment of this github_id)
> // DELETE /teams/{t}/github/members/{github_id}/assignment (admin+) → 204
>
> // GET /teams/{t}/members — each TeamMemberApi gains
> github: null | { github_id: number, github_login: string, avatar_url: string | null,
>                  source: GithubIdentitySource }
> ```
>
> New error codes. Add them to `GITHUB_ORG_ERROR_CODES` with Guide/Expert copy:
>
> | Code                                                             | When                                                                   | UI                                                                  |
> | ---------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------- |
> | `400 not_a_team_member`                                          | `user_id` isn't a live member of this team                             | "That person isn't on this team anymore — refresh." Refetch members |
> | `400 not_an_org_member` (existing)                               | The GitHub id left the org                                             | Row error; refetch roster                                           |
> | `409 github_identity_verified`                                   | That GitHub account is verified to someone, so an admin can't override | Shouldn't happen if the UI disables it; show the message            |
> | `409 member_has_verified_github`                                 | The chosen teammate has verified a _different_ GitHub account          | Name it: "Noor already linked @noor-a"                              |
> | `409 member_already_assigned`                                    | The chosen teammate is already assigned to another org member          | Name the other login; offer to unassign there first                 |
> | `404 assignment_missing`                                         | DELETE on nothing                                                      | Refetch silently                                                    |
> | `409 installation_missing` / `installation_suspended` (existing) | No usable link                                                         | Card state handles it                                               |
>
> Live updates: assignment changes publish `team.members_changed` (`liveKeys.teamMembers(teamId)`) and `team.updated`. Refetch both the roster and `listMembers` on either.
>
> ### 4. What to build
>
> **4.1 Team & invites view** (`features/workspace/HomeScreen.tsx` `MembersView`). The order is:
>
> 1. MEMBERS (`LiveMembers`)
> 2. **GITHUB ORGANIZATION** (the existing `GitHubOrgCard`, kept; restyle to the redesign's section look)
> 3. **GITHUB ORG MEMBERS**, a new **inline** section shown only when the team is collaborative, an org is linked, the account type is `Organization`, and the viewer is owner/admin
> 4. TEAM ACTIVITY
>
> Today the roster lives in `GitHubRosterModal`. Replace that modal with the inline section (the pane is up to 1180px wide), and keep the one-time-token reveal as a small modal (`ModalShell labelledBy closeOnEscape`; Escape/click-out stay disabled while the token is shown). Delete `GitHubRosterModal` if nothing else uses it, and drop the card's "Members on GitHub" button in favour of the inline section.
>
> **4.2 GitHub org members section.** A table-like list, with roles `table`/`row` or `ul`/`li` plus labelled controls. One row per org member:
>
> - Avatar (`safeHttpsUrl` only), `@login` (text, never HTML), and a status chip:
>   - **Verified**: `assignment.source === 'verified'`. Show the teammate's name. Read-only, with a tooltip/Guide line: "They linked this GitHub account themselves."
>   - **Assigned**: `source === 'admin'`. Show the teammate's name, plus "by <admin> · <relative time>".
>   - **Invited**: there's a pending invite.
>   - **Not on Solus**
> - **Assign control** (admin only):
>   - A teammate picker. Use an accessible combobox or `<select>` with a search filter once the team has more than 8 members.
>   - It lists live team members, excludes anyone already verified or assigned to a _different_ org member, and shows each teammate's own verified GitHub login when they have one.
>   - Actions: Assign, Change (same picker), Unassign (confirm inline, no modal).
>   - Verified rows have no assign control.
> - **Invite** (only on `not_on_solus` rows): the existing GitHub-id invite. Plan-limit refusals show `PlanLimitNotice` with **Upgrade** (`onUpgrade` → billing).
> - **Header and controls:**
>   - Header: "N org members · M on this team". Pagination via **Load more** (cursor); search by login client-side over the loaded rows.
>   - Filters as a `Segmented` control: All / On team / Not on Solus / Unassigned teammates. "Unassigned teammates" lists Solus members with no GitHub link, so an admin can work from the teammate side too.
> - **Per-row mutation:** each row has its own pending state. Updates are optimistic with rollback on error, and the error shows on that row. Other rows are never blocked.
> - **Empty and error states:**
>   - Empty org: an honest note.
>   - Roster fetch failure: a one-line note plus Retry.
>   - Suspended installation: the card's warn row, with the section hidden.
> - **Explainer:** Guide mode shows a one-paragraph explainer at the top (assignment is a label for attribution; it doesn't give access, and the person still joins through an invite). Expert shows one line.
>
> **4.3 Members list** (`features/team/MembersPanel.tsx` `LiveMembers`, used by everyone):
>
> - Each member row shows their GitHub link from `TeamMemberApi.github`, if any: the GitHub mark (`logoClass('github')`, so it follows the theme) plus `@login`, and a small "verified"/"assigned" tag.
> - Only admins get a quick "Assign GitHub…" affordance on members with no link. It scrolls to and filters the org members section, rather than opening a second picker implementation.
>
> **4.4 Linking flow on the redesigned Home:**
>
> - Keep the `GitHubOrgCard` states: unlinked admin, unlinked member, unconfigured, linking, requested, linked, suspended, offline.
> - Make the target team explicit in the link copy: "Link a GitHub organization to **<team name>**".
> - The personal team never shows the section, and the sidebar ACCOUNT nav's "Team & invites" status is unchanged.
> - After linking succeeds, focus moves to the new GitHub org members section heading.
>
> **4.5 State and data:**
>
> - Extend `useTeamGithub` with `assign(githubId, userId)` and `unassign(githubId)`, plus roster state (`items`, `cursor`, `total`, per-row pending/error).
> - Keep the existing races handled: team switch mid-flight (the `currentTeamId()` guard), stale `loadSeq`, and reset on `teamId` change. The card is already keyed by `team_id`; key the new section the same way.
> - Refetch the roster on `liveKeys.teamMembers(teamId)` and `liveKeys.team(teamId)` via `useLiveRefetch`. `useHomeTeam` already refetches `listMembers` on `teamMembers`.
>
> **4.6 Look and motion:** match the redesign:
>
> - Section labels: `Mono` uppercase 9.5–10px `var(--mut)`.
> - Bordered sections: `var(--sur)` / `1px solid var(--bd)` / radius 4.
> - Rows: `home-row-in` + `homeStagger(i)`. Interactive rows/buttons: `.interactive`.
> - Menus: `popover-in` with click-out.
> - Tokens only: `--acc`, `--ok`, `--warn`, `--err`.
> - Respect reduced motion.
>
> ### 5. Tests (write first)
>
> - **Client:** new paths, methods and bodies; the 200 / 204 envelopes; every new error code narrowed by `githubOrgErrorCode`.
> - **Hook:**
>   - assign and unassign update rows optimistically and roll back on each error code;
>   - a team switch mid-assign drops the stale result;
>   - live keys trigger a refetch;
>   - non-managers never call `listTeamGithubMembers`.
> - **Section:**
>   - every chip state;
>   - verified rows have no control;
>   - the picker excludes teammates already linked elsewhere and shows their verified login;
>   - Change and Unassign;
>   - Invite only on `not_on_solus`, with the token shown once in the modal;
>   - plan-limit Upgrade;
>   - Load more and search;
>   - each filter, including "Unassigned teammates";
>   - empty, failure + Retry, suspended;
>   - Guide and Expert copy for every new string (extend the `githubOrgCopy` key-iteration test).
> - **Members list:** the GitHub badge renders with verified/assigned tags; the admin-only "Assign GitHub…" scrolls and filters.
> - **Accessibility:**
>   - labelled controls; roving focus inside the picker;
>   - row status announced via `role="status"` after a mutation;
>   - focus moves to the section heading after linking;
>   - the token modal keeps focus.
> - **HomeScreen:** the section mounts only for collaborative teams with an Organization link and a manager viewer; the order of the Team & invites view.
>
> ### 6. Done means
>
> - Verify with `npx vitest related --run <changed files>` from the repo root.
> - Typecheck with `pnpm exec tsc --noEmit -p tsconfig.web.json --composite false` and the node config.
> - Root eslint shows 0 errors on changed files, and prettier is clean.
> - `docs/wireflows/home.md` is updated: the Team & invites view, the GitHub org members section, the members-list badge, and the stale team-layer ASCII and "grid" wording fixed.
> - `docs/qa/COWORK_QA_github-org-member-assignment.md` covers link → roster → assign / change / unassign → invite → verified-row read-only → non-admin view → team switch → live update from a second window.
> - A completion report that lists any contract drift from §3.2.
>
> **Out of scope:** backend work, auto-assignment by email, bulk assign, GitLab groups, and changing roles from the roster.

---

## Backend work this prompt depends on (separate task, before or alongside the frontend)

Approval comes first: the ADR-039 amendment below is a tier-2 change and needs in-chat approval of the concrete text. Then the backend needs:

- **Table** `team_github_identity_links`: team_id, github_user_id, github_login (from the roster), user_id, assigned_by, assigned_at, and soft delete.
  - Live partial uniques on (team_id, github_user_id) and (team_id, user_id).
  - Verified links are derived from GitHub `AccountConnection`s and never stored here; they win over admin rows.
- **Routes** from §3.2: the `assignment` field on the roster, the `github` field on `GET /members`, and PUT/DELETE assignment (admin+, rate limited).
- **Effects:** activity `github_org.member_assigned` / `member_unassigned`, matching data events, and the `team.members_changed` live hint.
- **Cleanup:** remove a teammate's admin link when they leave the team.
- **Tests:** cross-tenant tests, plus "assignment never satisfies invite accept" and "assignment never changes role/access".
- **Docs:** update `docs/api/github-orgs.md` and `docs/schemas/team-installations.md`.

### Proposed ADR-039 amendment (needs approval before it goes into DECISIONS.md)

> **ADR-039 amendment: admin-assigned GitHub identities (2026-10-19).**
>
> 1. A team admin may assign a GitHub org member to a live Solus team member. The assignment is team-scoped, at most one each way, and stored with who assigned it and when.
> 2. An assignment is a **label for attribution and display only**. It never grants or changes Solus access, roles, or project grants. It never satisfies invite-acceptance identity proof (§6 still requires a verified GitHub id). It is never exposed to non-members.
> 3. A **verified** link wins. A verified link is a teammate's own connected GitHub account, or their Supabase GitHub identity. An admin can't assign a verified GitHub id to someone else, or assign a different id to a teammate who has a verified one.
> 4. An assignment is removed when the teammate leaves the team, or when the team's GitHub link is revoked.
