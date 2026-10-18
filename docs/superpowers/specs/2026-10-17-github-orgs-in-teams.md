# GitHub Organizations in Teams: design review, plan and build prompt

Status: Phase 1 ANSWERED 2026-10-17. The human said "continue" on the recommended answers, so Q1-Q6 are locked as recommended (see §3). Q7 (ticket number, adjacent defects) is still open. Tier-2: ADR-039 is APPROVED and in DECISIONS.md; no contract change is needed (§4). Q7: the docs live on SOLUSDEV-315; the code goes on a new ticket; the three adjacent defects ride along (localhost/127.0.0.1 callback, membership `deleted_at` filters, repo-listing pagination).
Ticket: SOLUSDEV-**_ (to be assigned). Branch: `SOLUSDEV-_**-github-orgs-in-teams`.

---

## 1. What exists today

| Area             | Current state                                                                                                                                                                                                                                                              | Where                                                                         |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Teams            | Membership is many-to-many. There is one PERSONAL team per user, plus COLLABORATIVE teams. Roles are owner/admin/member/viewer. Invites are by email with a single-use token (7-day TTL) and no email delivery. Inviting from a personal team spawns a collaborative team. | `models.py` L359-429, `routers/teams.py`, `members.py`, `invites.py`, ADR-025 |
| Authz            | `get_team_context` / `get_project_context` / `require_role`. Non-members get 404 and members below the required role get 403.                                                                                                                                              | `deps.py` L264-442                                                            |
| Billing / limits | Billing is per **user**. ADR-023 limits `max_integrations` / `max_teams`, with a hard block checked against the invitee's own plan.                                                                                                                                        | `services/limits.py`, ADR-023/024                                             |
| GitHub connector | It is a classic **OAuth App** with scopes `repo read:user`, and it also accepts a PAT. The grant belongs to the **user** (`AccountConnection.user_id`), and each Source copies the user's `secret_ref`.                                                                    | `connectors/github.py`, `services/connections.py`, ADR-035 amendment L846     |
| Repo listing     | `GET /user/repos` reads **one page of 100** and does no pagination.                                                                                                                                                                                                        | `github.py` L176-193                                                          |
| Webhooks         | There is a per-source token route, but **nothing registers GitHub webhooks** and `X-Hub-Signature-256` is not verified anywhere. Freshness comes from the hourly ETag sweep.                                                                                               | `routers/webhooks.py` L229, `worker.py` L1028                                 |
| Orgs             | Nothing exists: no `read:org`, no `/orgs` calls, no installation concept. The UI mockups already show "GitHub org · fsae-ev · 6 repos".                                                                                                                                    | `docs/ui-reference/app/v2/data.js` L220                                       |
| Live             | ADR-037 hint frames on the `team:{id}` / `user:{id}` channels, derived from row listeners.                                                                                                                                                                                 | `graph/live_publisher.py`, `contracts/live_events.py`                         |

**Core gap:** today every teammate has to run their own GitHub OAuth, and only the account owner can bind it (`owned_connection`). Two problems follow:

- A team has no shared GitHub identity, so if the person who connected leaves, the team's sources break.
- Orgs that restrict third-party OAuth Apps (the GitHub default for new orgs) don't show their repos at all.

## 2. Phase 1 design review

### Critique: what "GitHub Orgs in Teams" must not become

1. **Extending the OAuth App with `read:org` is the wrong lever.** It is still a user grant: it dies when the user leaves, it is subject to the org's OAuth-App restriction policy, it has no app-level webhooks, and it can't scope to selected repos. A **GitHub App installation** owned by the team avoids all four problems. It is also the only way to get one signed webhook stream per org, which closes the missing webhook-registration and signature gap that already exists.
2. **GitHub org membership must not equal Solus team access.** Solus holds proprietary schematics and CAD. Being in a GitHub org (contractors, bots, outside collaborators, 400-person university orgs) is not consent to see robot designs.
   - Auto-join would also bypass ADR-023's hard-block invitee limit and the `require_verified` gate.
   - **Recommendation: the org roster suggests invites and never auto-joins.** Removal from the org notifies admins and never auto-removes.
3. **This is a connection-ownership change and needs an ADR.** ADR-035's amendment says grants belong to the AccountConnection owner, a user. A team-owned installation is a new ownership class. It needs **ADR-039 (tier-2)** before code.
4. **Credential resolution is user-ref based.** The connector contract's `Credentials` path (`packages/contracts/python/solus_contracts/connector.py`) assumes a stored token reached through a `secret_ref`. Installation tokens are short-lived (1 h) and minted from an app JWT. This likely needs a **credential-provider seam in the contract (tier-2)** instead of persisting minted tokens.
5. **Install-callback hijack.** GitHub's setup URL returns `installation_id` in the query string. Anyone could replay an id to bind someone else's org to their own team. The callback must therefore:
   - check a state token bound to user + team;
   - then confirm through the installing user's user-to-server token (`GET /user/installations`) that this user can actually access that installation.
6. **One installation maps to exactly one team.** GitHub allows one installation per org per app, so `installation_id` is unique. Moving an org to another team is an explicit admin rebind, not a second link.
7. **Tenant isolation.** The single app webhook carries events for every org. Routing must go `installation_id` → team → sources. A delivery for an unknown or unbound installation is dropped with a log line and never fans out.
8. **Enterprise: don't foreclose GHES.** Keep the API base and app URLs configurable per installation, not hard-coded to `api.github.com` (ADR-015).

### Suggestions

- Keep the existing OAuth App path for **personal** repos and PAT use. The org path is additive, and the wizard shows both sections: "From <org> (team)" and "Your account".
- Count an org link as **1 integration** against the linking admin's `max_integrations`. Members who bind repos from it consume nothing. (This is open question Q4.)
- Fold in the cheap adjacent fixes the new code path touches anyway:
  - paginate repo listing;
  - verify `X-Hub-Signature-256` on the new app webhook route;
  - de-dupe deliveries on `X-GitHub-Delivery`.
- Match org members to Solus users by **GitHub numeric id**, taken from the user's Supabase GitHub identity or an existing `AccountConnection.account_external_id`. Never match by login or email alone.

### Existing defects found during mapping (flag only, not in scope unless you say so)

- `docs/integrations/github-setup.md` registers the `127.0.0.1` callback, but the connector flow sends `localhost:53682`. GitHub may reject that.
- `list_teams`, `list_members`, `_member_count` and `_owner_count` don't filter `Membership.deleted_at`.
- `packages/api/.env.claude` still uses the dead `SOLUS_GITHUB_OAUTH_REDIRECT_APP` setting.
- Code comments cite ADR-032 for billing/teams, but those decisions are ADR-023/024/025.
- `NotificationApi.payload` in the renderer, but the server sends `attrs`.
- `revoke_invite` emits no data event.

## 3. Phase 1 questions

**Resolution (2026-10-17):** Q1-Q6 are locked to the recommended option. Q7 is open.

1. **Q1. Scope.**
   - Recommended: (a) team-owned GitHub App install with shared repo access, plus (b) a roster with suggested invites.
   - Alternatives: (a) only; or (a)+(b)+(c) automatic membership sync.
2. **Q2. Mechanism.**
   - Recommended: a new GitHub App alongside the existing OAuth App.
   - Alternative: add `read:org` to the OAuth App.
3. **Q3. Membership policy.**
   - Recommended: suggest-only; org removal notifies admins.
   - Alternatives: auto-join with admin opt-in; auto-remove on org removal.
4. **Q4. Plan accounting.** Does the org link count as 1 integration against the linking admin's limit (recommended), against no one, or against every member?
5. **Q5. Who may link or unlink.** Recommended: team **admin+** who is also able to access the installation on GitHub.
6. **Q6. Invite-by-GitHub-login.** Many org members have no public email. Should invites support a `github_user_id` target that is resolved at accept time from the accepter's GitHub identity? (Recommended: yes; this extends `InviteCreate`.)
7. **Q7. Ticket number** and whether the adjacent defects above ride along.

## 4. Governing docs to amend (Phase 2, T0, before code)

**Tier-2 (in-chat approval of the concrete text first):**

- **DECISIONS.md: ADR-039 "Team-owned provider installations (GitHub App)".** It covers:
  - ownership class;
  - installation tokens minted on demand and never persisted;
  - one installation per team;
  - suggest-only membership;
  - app-webhook HMAC as the credential;
  - plan accounting.
- **`packages/contracts/`: NO CHANGE (confirmed 2026-10-17).**
  - The contract only carries the resolved `Credentials` inside `SyncContext`. Resolution itself lives in `solus_api/connectors/runtime.py::resolve_credentials(secret_store, secret_ref)` (L314), which ~6 callers share: sync, worker, `read_code_file`, source_revisions, document_tree.
  - The seam is a reserved ref scheme, `github-app/installation/{team_installation_id}`, that `resolve_credentials` dispatches to the installation-token minter instead of the SecretStore. Every caller inherits it.
  - GitHub doesn't override `refresh_credentials`, so `call_with_refresh` never writes a minted token back to the store.
  - Live hints reuse `team.updated`, so the frame contract is unchanged.

**Tier-1 (edited directly):**

- `docs/api/API.md`: new §2.2/§2.5 routes (below).
- `docs/wireflows/home.md`: a GitHub org card in the team layer.
- `docs/wireflows/sources-connect-wizard.md`: an org section in the repo picker.
- `docs/schemas/`: a `team-installations.md` ERD.
- `docs/integrations/github-setup.md`: GitHub App registration steps.

### Proposed routes

| Method | Path                                              | Role    | Purpose                                                                                                                  |
| ------ | ------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| POST   | `/api/v1/teams/{team_id}/github/install/start`    | admin+  | Returns the GitHub App install URL with `state` bound to user + team                                                     |
| POST   | `/api/v1/teams/{team_id}/github/install/complete` | admin+  | Body `{installation_id, state, code}`. Verifies state, then verifies the user can access the installation, then binds it |
| GET    | `/api/v1/teams/{team_id}/github/installation`     | member+ | Returns `{org_login, org_avatar, repository_selection, repo_count, status, linked_by, linked_at}` and never any token    |
| DELETE | `/api/v1/teams/{team_id}/github/installation`     | admin+  | Unlinks: disables bound sources and deep-links the user to uninstall on GitHub                                           |
| GET    | `/api/v1/teams/{team_id}/github/repos`            | member+ | Paginated repos visible to the installation                                                                              |
| GET    | `/api/v1/teams/{team_id}/github/members`          | admin+  | Org roster with `{github_login, github_id, avatar, solus_status: member\|invited\|not_on_solus}`                         |
| POST   | `/api/v1/projects/{id}/sources`                   | member+ | Existing route, now also accepts `installation_id`, mutually exclusive with `connection_id`                              |
| POST   | `/api/v1/webhooks/github/app`                     | HMAC    | App webhook. Handles `installation*`, `push`, `organization`, `member*` and `repository` events. Returns 204             |

## 5. Execution plan (Phase 2 sketch; `/plan` produces the final version)

```
T0 governing docs + ADR-039 + contract seam  (sequential, human-gated)
 └─ T1 models + migration + GitHub App auth core
      ├─ T2 install/link/unlink routes + team binding     ┐
      ├─ T3 app webhook route + event routing             ├ parallel (disjoint files)
      └─ T4 installation-backed sources + repo listing    ┘
           └─ T5 org roster + invite-by-GitHub-id (after T2)
T6 desktop UI (starts once T0 locks the API shapes; integrates after T2/T4/T5)
T7 Phase 4: review + security + /quality-gate + COWORK_QA
```

| Task | Owns                                                                                                                                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1   | `models.py` (new `TeamInstallation`; `Source.installation_id`), the new migration, `connectors/github_app.py` (app JWT, installation-token mint with ~55-minute cache, GHES-ready base URL), `core/config.py` settings, `env.example` |
| T2   | `routers/team_github.py`, `services/team_installations.py`, limits hook                                                                                                                                                               |
| T3   | `routers/webhooks_github_app.py`, `services/github_app_events.py`                                                                                                                                                                     |
| T4   | `connectors/github.py` (credential provider, pagination), `routers/sources.py` (installation binding branch), `worker.py` (token resolution)                                                                                          |
| T5   | roster service + route, `InviteCreate` / accept extension in `invites.py`                                                                                                                                                             |
| T6   | `features/workspace/` (GitHubOrgCard, roster modal), `features/onboarding/` (repo picker section), `lib/api/resources.ts`, `accountEventKeys.ts`                                                                                      |

---

## 6. Build prompt (paste into a fresh session once §3 is answered)

> **SOLUSDEV-\_\_\_: GitHub Organizations in Teams**
>
> You are the orchestrator for this ticket under `/Users/mehdihdev/Solus/CLAUDE.md`. Create and work only on branch `SOLUSDEV-216-github-orgs-in-teams`, cut from `main`.
>
> **Goal.** Let a Solus COLLABORATIVE team link a GitHub organization through a **GitHub App installation that the team owns**. Once linked:
>
> - Any team member (member+) can bind that org's repos to team projects without a personal GitHub OAuth.
> - Sources keep working when the member who linked the org leaves.
> - Freshness comes from the App's signed webhook stream.
> - Admins see the org roster and can send suggested invites.
>
> The existing user-owned OAuth App / PAT path stays unchanged for personal repos.
>
> **Read first.** Read the spec packet `docs/superpowers/specs/2026-10-17-github-orgs-in-teams.md` (§1-§5 hold the codebase map, critique, decisions and plan). Then read:
>
> - DECISIONS.md ADR-015, 019, 023, 024, 025, 030, 035 (both, plus the 2026-09-12 amendment), 037;
> - `docs/api/API.md` §1.2-1.3, §2.2, §2.5, §3;
> - `docs/contracts/connector-interface.md`;
> - `docs/wireflows/home.md` (team layer) and `sources-connect-wizard.md`;
> - `docs/integrations/github-setup.md`.
>
> **Locked decisions (from the Phase 1 answers):**
>
> 1. Mechanism is a new **GitHub App**. It needs these permissions and no others:
>    - Repository: `contents:read`, `metadata:read`.
>    - Organization: `members:read`.
>    - Events: `installation`, `installation_repositories`, `push`, `repository`, `organization`, `member`.
> 2. **One installation maps to one team.** `installation_id` is unique. Only COLLABORATIVE teams can link; a PERSONAL team gets 409 `personal_team_unsupported`.
> 3. **Installation tokens are minted on demand** from the app JWT (private key from Secrets Manager / `SOLUS_GITHUB_APP_PRIVATE_KEY`). They are cached in memory or Redis for at most 55 minutes and are **never persisted, logged or returned**.
> 4. **Linking is admin+ and needs proof.** The install-complete route checks a server-side state token bound to (user, team) with a 10-minute TTL and single use. It then proves access through the installing user's user-to-server token (`GET /user/installations` must list `installation_id`). Either failure returns 403 `installation_not_accessible`.
> 5. **Membership is suggest-only.** Org members are never auto-joined or auto-removed. On an `organization.member_removed` event:
>    - notify the team's admins;
>    - record a `github.org_member_removed` activity.
> 6. **Invites can target a GitHub identity.** `InviteCreate` gains an optional `github_user_id`, with exactly one of `email` / `github_user_id` set. At accept time, the accepter's GitHub numeric id comes from their Supabase GitHub identity or a live GitHub `AccountConnection`. A mismatch returns 403. ADR-023 invitee limits still apply.
> 7. **Plan accounting:** linking counts as one integration against the linking admin's `max_integrations` (409 `plan_limit_reached` on refusal). Members binding repos consume nothing.
> 8. **Unlink or uninstall.** This applies to `DELETE` and to the `installation.deleted` / `suspend` events:
>
>    - mark the installation revoked;
>    - disable every bound Source (mirror `revoke_connection`);
>    - drop the cached token;
>    - emit live hints.
>
>    `installation_repositories.removed` disables only the affected sources.
>
> 9. **App webhook** route is `POST /api/v1/webhooks/github/app`:
>    - Verify `X-Hub-Signature-256` with constant-time HMAC against `SOLUS_GITHUB_APP_WEBHOOK_SECRET` **before parsing**.
>    - Cap the body (reuse the 64 KB-style cap; size it for push payloads).
>    - De-dupe on `X-GitHub-Delivery`.
>    - Route only through `installation_id` → team → sources.
>    - Drop deliveries for unknown installations with a structured log line.
>    - On `push` to a bound repo/branch, enqueue `sync_source` (ARQ).
>    - Payload strings are untrusted data (§7 prompt-injection rules).
> 10. **Configurable endpoints.** API and web base URLs are stored per installation so GHES isn't foreclosed.
>
> **Governance status.** ADR-039 is already approved and in DECISIONS.md; do not re-litigate it. No `packages/contracts/` change is needed. The credential seam is the reserved `secret_ref` scheme `github-app/installation/{id}`, dispatched inside `connectors/runtime.py::resolve_credentials` (spec §4). If implementation proves a contract change is necessary, stop and ask (tier-2).
>
> Then apply the tier-1 amendments: API.md routes per spec §4, wireflows, a `docs/schemas/team-installations.md` ERD, and the github-setup.md App registration steps.
>
> **Then:**
>
> - Run `/plan` (planner persona) to produce the T1-T7 decomposition, file ownership manifests in `.claude/state/ownership/`, and the parallel split (T2/T3/T4 after T1).
> - Execute with TDD (`tdd-workflow`, `python-testing`).
>
> **Required tests (in addition to the usual):**
>
> - Cross-tenant: team A cannot read team B's installation, repos or roster, and cannot bind B's installation to an A project.
> - Install-callback replay or forged `installation_id`: 403, and nothing is bound.
> - A webhook with a bad, missing or timing-attack signature: 401, body never parsed.
> - Duplicate delivery: processed once.
> - Unknown installation: dropped.
> - Token never appears in logs, responses or the DB (secret-scan assertion).
> - Linker leaves the team: sources still sync.
> - Unlink: sources disabled.
> - PERSONAL team: 409.
> - Plan limit: 409.
> - Viewer or member cannot link or unlink.
> - Invite by `github_user_id`: wrong accepter gets 403.
> - Prompt-injection fixture: a repo or commit message containing instructions flows into the graph as data only.
> - Contract suite: the installation-backed GitHub connector passes the connector contract tests.
>
> **Data events:** `github_org.linked`, `github_org.unlinked`, `github_org.repo_bound`, `github_org.invite_suggested`, `github_org.member_removed_notice`.
>
> **Live:** reuse `team.updated` / `team.members_changed` hints unless ADR-039 approves a new frame. Frames carry ids only.
>
> **Desktop:**
>
> - A GitHub org card on Home's team layer: link, status, repo count, unlink, and a roster modal with invite buttons.
> - An "From <org> (team)" section in the repo picker, above "Your account".
> - The install opens in the system browser. Completion returns via the desktop loopback with the state verified.
> - All REST goes through `lib/api/resources.ts`.
> - Guide and Expert copy for every new message (SOL modes).
>
> **Also in scope: adjacent defects (approved to ride along):**
>
> - **Connector OAuth redirect host.** `docs/integrations/github-setup.md` registers `127.0.0.1:53682`, but `apps/desktop/src/main/oauthCallback.ts` sends `localhost:53682`. Make them agree, with a test.
> - **Membership `deleted_at` filters.** Filter `Membership.deleted_at IS NULL` in `routers/teams.py` (`list_teams`, `_member_count`) and `routers/members.py` (`list_members`, `_owner_count`), with tests.
> - **Repo-listing pagination.** Paginate `GitHubConnector.list_repositories` (Link header, bounded page cap) for the OAuth path as well as the installation path.
>
> **Out of scope:** auto membership sync, GitLab groups, write permissions, GitHub Issues/PRs in the graph, and migrating existing OAuth sources onto the installation. Offer migration only as a follow-up.
>
> **Phase 4/5:**
>
> - `code-reviewer`, `security-reviewer` (installation auth, webhook, tenant routing) and `python-reviewer` / `typescript-reviewer` passes.
> - `/quality-gate`.
> - A completion report.
> - `docs/qa/COWORK_QA_github-orgs-in-teams.md`. It must include: GitHub App setup on a test org, link/unlink, repo bind by a non-linking member, linker-leaves, push-triggered sync, uninstall from the GitHub side, roster invite by GitHub id, and permission and cross-team boundaries.
>
> Never push, open MRs, or touch main.

---

## 7. ADR-039 (approved in-chat 2026-10-17; recorded in DECISIONS.md)

## ADR-039: Team-owned provider installations — GitHub App linked to a team

**Status:** Accepted 2026-10-17 (see DECISIONS.md).

**Context:**

- GitHub access today is a user-owned OAuth App grant (ADR-035 amendment 2026-09-12), so a team has no GitHub identity of its own.
- Each member must authorize separately, and only the grant owner can bind it.
- Sources break when that member leaves.
- Orgs that restrict third-party OAuth Apps expose no repos at all.
- ADR-030's signature-verified GitHub webhooks were never built.

**Decision:**

1. A new ownership class: a **team installation**.
   - A GitHub App installation on an org (or user account) is bound to exactly one COLLABORATIVE team. `installation_id` is unique.
   - PERSONAL teams cannot hold one.
   - The user-owned OAuth App / PAT path (ADR-035) is unchanged and coexists with it.
2. **Linking requires team admin+ and proof of access.** The install callback must present a single-use, 10-minute server state bound to (user, team), and the user's user-to-server token must list the installation (`GET /user/installations`). Unlinking requires admin+.
3. **Installation tokens are never stored.**
   - They are minted on demand from the app JWT. The app private key lives in Secrets Manager.
   - They are cached for at most 55 minutes and never logged, persisted or returned.
   - Sources bound to an installation carry the reserved `secret_ref` `github-app/installation/{id}`, which the runtime resolver dispatches to the minter. The connector contract does not change.
4. **Binding is a team right.** Any member+ of the owning team may bind the installation's repos to that team's projects. A project of another team never resolves the installation; routing is installation → team → project.
5. **The app webhook is the freshness channel.**
   - One endpoint verifies `X-Hub-Signature-256` with constant-time HMAC before parsing, caps the body, and de-dupes on `X-GitHub-Delivery`.
   - It routes only through a bound installation. Unknown installations are dropped and logged.
   - Payload content is untrusted data (CLAUDE.md §7).
   - The hourly ETag sweep stays as the backstop.
6. **GitHub org membership never grants Solus access.**
   - The org roster suggests invites only. An invite may target a GitHub numeric id that is resolved from the accepter's GitHub identity at accept time.
   - Org removal notifies admins and never auto-removes.
   - ADR-023 invitee limits and the verified-email gate still apply.
7. **Revocation.** Unlink, uninstall or suspend disables every bound Source and drops the cached token. Removing a repo from the installation disables only that repo's Sources.
8. **Plan accounting.** A link counts as one integration against the linking admin's `max_integrations`. Binding repos from it is free.
9. **App permissions are read-only and minimal:** `contents:read`, `metadata:read`, `members:read`. Any write permission needs a new ADR.
10. **Configurable endpoints.** API and web base URLs are stored per installation, so GitHub Enterprise Server is not foreclosed (ADR-015).

**Consequences:**

- A second GitHub credential type to operate: an app private key, a webhook secret, and app registration per environment.
- Team sources survive member churn.
- ADR-030 GitHub webhooks become real.
- Existing OAuth-bound sources are not migrated automatically.
- GitLab groups would follow this pattern under their own ADR.
