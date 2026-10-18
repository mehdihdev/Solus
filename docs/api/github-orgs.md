# GitHub organizations in teams: a GitHub App installation owned by a team (SOLUSDEV-216)

This is the route plan and wire shapes. It is tier-1 under ADR-032: agents may edit it, and it is reviewed at the MR.

**Governing decision:** ADR-039. It defines the ownership class, the never-stored tokens, suggest-only membership and the signed app webhook.

**Companion docs:**

- `docs/schemas/team-installations.md`: the tables.
- `docs/wireflows/home.md`: the GITHUB ORGANIZATION card.
- `docs/wireflows/sources-connect-wizard.md`: the org section of the repo picker.
- `docs/integrations/github-setup.md`: registering the App.
- Spec packet: `docs/superpowers/specs/2026-10-17-github-orgs-in-teams.md`.

## 1. What it is

A COLLABORATIVE team links one GitHub account through the **Solus GitHub App**. The account is normally an organization, but it can be a user account. Once linked:

- Any member+ of the team binds the installation's repos to the team's projects. Nobody needs a personal OAuth.
- Those sources resolve credentials through the reserved `secret_ref` scheme `github-app/installation/{team_installation_id}`. `connectors/runtime.py::resolve_credentials` mints a 1-hour installation token from the App JWT and caches it for at most 55 minutes. The token is never stored, logged or returned.
- The sources keep syncing when the member who linked the org leaves. The installation belongs to the team, not to a person.
- Freshness comes from the App's single signed webhook. The hourly ETag sweep stays as the backstop.
- Admins see the org roster and can **suggest** invites. GitHub membership never grants Solus access.

The user-owned OAuth App / PAT path (§2.5 of API.md) is unchanged. A team can use both.

## 2. Routes

All responses use the standard envelope.

- **Non-member of the team:** 404.
- **Role too low:** 403 `forbidden`.
- **PERSONAL team:** 409 `personal_team_unsupported` on every route below except `GET installation`, which answers `{installation: null}` there.

### Summary

| Method | Path                                              | Role                                              |
| ------ | ------------------------------------------------- | ------------------------------------------------- |
| POST   | `/api/v1/teams/{team_id}/github/install/start`    | admin+, verified email                            |
| POST   | `/api/v1/teams/{team_id}/github/install/complete` | admin+, verified email                            |
| GET    | `/api/v1/teams/{team_id}/github/installation`     | member+ (viewer included)                         |
| DELETE | `/api/v1/teams/{team_id}/github/installation`     | admin+                                            |
| GET    | `/api/v1/teams/{team_id}/github/repos`            | member+                                           |
| GET    | `/api/v1/teams/{team_id}/github/members`          | admin+                                            |
| POST   | `/api/v1/projects/{project_id}/sources`           | member+ (existing route, extended)                |
| POST   | `/api/v1/teams/{team_id}/invites`                 | admin+ (existing route, extended)                 |
| POST   | `/api/v1/invites/{invite_token}/accept`           | any authenticated user (existing route, extended) |
| POST   | `/api/v1/webhooks/github/app`                     | HMAC signature, no Bearer                         |

### `POST /api/v1/teams/{team_id}/github/install/start`

Request body: `{redirect_uri?: str}`. It must be the desktop loopback or the API host, using the same `_resolve_redirect_uri` rule as connector OAuth.

The route creates a single-use `OAuthState` with a 10-minute TTL, bound to `{user_id, team_id, purpose: "github_app_install"}`.

Response:

```
{ install_url: "https://github.com/apps/<slug>/installations/new?state=<state>",
  state, redirect_uri }
```

Refusals:

- `409 plan_limit_reached`: the linking admin's `max_integrations` is spent (ADR-023, ADR-039 §8).
- `409 already_linked`: the team already has a live installation.
- `503 github_app_unconfigured`: the App settings are missing. The route never half-works.

### `POST /api/v1/teams/{team_id}/github/install/complete`

Request body: `{state: str, code: str, installation_id: int, setup_action: "install" | "update"}`.

GitHub redirects to the App's callback URL with all four values, because the App has _Request user authorization (OAuth) during installation_ enabled. The desktop loopback captures them.

Steps, in order. Any failure leaves nothing bound.

1. **State.** Load the state. It must be unexpired, unused, the same user, the same team, and the purpose `github_app_install`. Otherwise `404 install_state_invalid`. The state is consumed.
2. **Code exchange.** Exchange `code` for a user-to-server token using the App's client id and secret. The token is used in memory for steps 3–4 and then dropped. It is never stored.
3. **Access proof.** `GET /user/installations` (paginated, capped) must contain `installation_id`. Otherwise `403 installation_not_accessible`. This is the hijack guard (ADR-039 §2): a replayed or guessed id fails here.
4. **Installation details.** `GET /app/installations/{id}` with the App JWT returns `account.login/id/type`, `repository_selection`, `suspended_at`, and the API/web base URLs (GHES-ready, ADR-039 §10).
5. **Uniqueness.** If the installation is already bound to **another** live team, return `409 installation_linked_elsewhere`. Rebinding is an explicit unlink on the other team first. If it is already bound to **this** team, it's idempotent: refresh the fields and return 200.
6. **Plan limit.** Re-check the plan limit under the subscription row lock.
7. **Persist.** Insert the `TeamInstallation` row, record activity `github_org.linked`, and emit data event `github_org.linked`. The row listener queues the live hint `team.updated`.

Response `201`:

```
{ installation: TeamInstallationRead }
```

### `GET /api/v1/teams/{team_id}/github/installation`

Response:

```
{ installation: TeamInstallationRead | null }

TeamInstallationRead = {
  id, provider: "github", account_login, account_type: "Organization" | "User",
  account_avatar_url, repository_selection: "all" | "selected",
  status: "active" | "suspended", linked_by: {user_id, name} | null,
  linked_at, html_url,            // https://github.com/<login>
  manage_url,                     // GitHub page to change repo access / uninstall
  bound_source_count              // live project sources reading through it (unlink confirm names it)
}
```

The response never includes a token, the numeric installation id beyond what's needed, or the JWT.

### `DELETE /api/v1/teams/{team_id}/github/installation`

Unlinks the installation:

- soft-deletes the row and sets status `revoked`;
- disables every bound Source (status DISCONNECTED, `last_error {code: "installation_unlinked"}`; mirrors `revoke_connection`);
- drops the cached token;
- records activity `github_org.unlinked` and data event `github_org.unlinked`.

Response:

```
{ disabled_sources: int, manage_url }
```

The desktop then offers the GitHub uninstall page. Solus cannot uninstall the App for the org; only an org owner can.

### `GET /api/v1/teams/{team_id}/github/repos?cursor=&limit=&q=`

Lists the repositories the installation can see (`GET /installation/repositories`, paginated by Link header, bounded walk). Results are cached per installation in the integration cache.

Each item:

```
{ id: full_name, name: full_name, subtitle: "private" | "public",
  config: {repo, branch: default_branch} }
```

This is the same `SelectableItem` shape as the OAuth picker.

Refusals:

- `409 installation_suspended`
- `409 installation_revoked`

### `GET /api/v1/teams/{team_id}/github/members?cursor=&limit=`

Organizations only. A `User` installation returns `400 not_an_organization`.

Calls `GET /orgs/{login}/members` (installation token, `members:read`, paginated, bounded). Each item:

```
{ github_id: int, github_login, avatar_url,
  solus_status: "member" | "invited" | "not_on_solus" }
```

How `solus_status` is decided:

- `member`: a live team member whose verified GitHub id equals `github_id`. The verified GitHub id comes from that user's live GitHub `AccountConnection.account_external_id`, or from the GitHub identity on their Solus login.
- `invited`: a pending invite targets `github_id`.
- Matching uses the numeric id only, never the login or email.

### `POST /api/v1/projects/{project_id}/sources` (extended)

The existing route gains `installation: true`. It is mutually exclusive with `connection_id` and `token`; mixing them returns `400 credential_conflict`.

- The project's team must hold a live, active installation. Otherwise `409 installation_missing`.
- The caller must be member+ on the project's team.
- `config.repo` must be visible to the installation, checked against the repo listing. Otherwise `400 repo_not_in_installation`.
- On success, the Source is created with `installation_id` set (FK to `team_installations.id`) and `secret_ref = "github-app/installation/{team_installation_id}"`.
- It emits data event `github_org.repo_bound`.

A project from **another** team can never reach this team's installation. Lookup is `project.team_id` → installation, never caller input.

### Invites (extended)

`POST /api/v1/teams/{team_id}/invites` accepts **exactly one** of:

- `email`, or
- `github_user_id` + `github_login`, where `github_login` is display-only.

Rules:

- A `github_user_id` invite requires the team to have a live **Organization** installation, and the id must currently be an org member. Otherwise `400 not_an_org_member`.
- `409 invite_pending` and `409 already_member` apply as for email.
- It emits data event `github_org.invite_suggested`.

`POST /api/v1/invites/{invite_token}/accept` checks a `github_user_id` invite against the accepter's verified GitHub id (same source as the roster). A missing or different id returns `403 github_identity_mismatch`. ADR-023 invitee limits and the existing accept errors are unchanged.

### `POST /api/v1/webhooks/github/app`

This is the App's single webhook. There is no Bearer token. The signature is the credential.

1. **Body cap.** Read the body with a hard cap of 2 MiB. Larger bodies return `413` and are not parsed; the ETag sweep covers that push.
2. **Signature.** Verify `X-Hub-Signature-256` with constant-time HMAC-SHA256 against `SOLUS_GITHUB_APP_WEBHOOK_SECRET` **before parsing**. A missing or bad signature returns `401`.
3. **De-dupe.** De-dupe on `X-GitHub-Delivery` using the `github_webhook_deliveries` table (unique id, pruned after 7 days). A repeat returns `204` and does no work.
4. **Routing.** Route by `installation.id` → the live `TeamInstallation` → team. An unknown or unbound installation returns `204`, writes a structured log line, and does no work.
5. **Event handling:**

| Event                                            | Effect                                                                                                                                                                           |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `push`                                           | Enqueue `sync_source` for each CONNECTED Source with this `installation_id` whose `config.repo` equals `repository.full_name` and whose `config.branch` equals the pushed branch |
| `installation.deleted`                           | Revoke and disable sources, as for DELETE above, with activity actor `null`                                                                                                      |
| `installation.suspend` / `unsuspend`             | Set status and `suspended_at`. Sources are marked ERROR with `last_error {code: "installation_suspended"}`, then restored on unsuspend                                        |
| `installation_repositories.removed`              | Disable only the Sources tracking the removed repos (`last_error {code: "repo_access_removed"}`) and invalidate the repo cache                                                   |
| `installation_repositories.added`                | Invalidate the repo cache                                                                                                                                                        |
| `installation.new_permissions_accepted`          | Refresh the stored fields                                                                                                                                                        |
| `organization.member_removed`                    | If that GitHub id maps to a team member: notify admins, record activity `github_org.member_removed_notice`, and emit a data event. **No removal** (ADR-039 §6)                   |
| `organization.member_added` / `member.*`         | Invalidate the roster cache                                                                                                                                                      |
| `repository.renamed` / `transferred` / `deleted` | Mark matching Sources ERROR with an honest `last_error`; never rewrite config silently                                                                                        |
| anything else                                    | `204`, ignored                                                                                                                                                                   |

All payload strings are untrusted data (CLAUDE.md §7). Only ids and the `full_name` / `ref` comparisons above are read.

Response: `204` on every accepted delivery. Work is enqueued (ARQ) or inline under `sync_inline`.

## 3. Credentials

| Setting                                                         | Use                                                                  |
| --------------------------------------------------------------- | -------------------------------------------------------------------- |
| `SOLUS_GITHUB_APP_ID`                                           | App JWT `iss`                                                        |
| `SOLUS_GITHUB_APP_SLUG`                                         | Install URL                                                          |
| `SOLUS_GITHUB_APP_CLIENT_ID` / `SOLUS_GITHUB_APP_CLIENT_SECRET` | User-to-server code exchange at install time                         |
| `SOLUS_GITHUB_APP_PRIVATE_KEY`                                  | PEM, from Secrets Manager in prod. Signs the RS256 App JWT (≤10 min) |
| `SOLUS_GITHUB_APP_WEBHOOK_SECRET`                               | HMAC for §2 webhook                                                  |

Rules:

- If any of these is absent, every route above returns `503 github_app_unconfigured`, and the webhook returns `503`.
- The OAuth App settings (`SOLUS_GITHUB_CLIENT_ID/SECRET`) are separate and unchanged.
- Token minting is `POST /app/installations/{id}/access_tokens`.
- The cache key is the GitHub installation id, with expiry at `min(expires_at − 5 min, 55 min)`. The cache is **process-local only, never Redis**: a bearer token in Redis could reach disk through RDB/AOF snapshots. Every resolve also checks the `TeamInstallation` row is live and `active`, so an unlink in the API process is honoured by a worker that still holds a cached token.
- A `404`/`403` from the mint marks the installation `revoked` and the sync fails with `installation_unavailable`.

Places that must never treat the reserved ref as a SecretStore key: source disconnect, connection revoke, account deletion purge, and the refresh write-back in `call_with_refresh`. The rule is: **never `get`/`put`/`delete` a `github-app/` ref against the SecretStore.**

## 4. Live and events

**Live.** `TeamInstallation` row changes publish `team.updated` on `team:{id}` through the existing row listener. Source status changes already publish their project hints. No new frame type.

**Data events:**

- `github_org.linked`
- `github_org.unlinked`
- `github_org.repo_bound`
- `github_org.invite_suggested`
- `github_org.member_removed_notice`
- `github_org.webhook_dropped`: structured log line only. `emit_event` needs a consenting user, so system-actor outcomes (dropped deliveries, `installation.deleted` from GitHub) are logged and recorded as activity with `actor_id = null`, not as data events

## 5. Ride-along fixes (SOLUSDEV-216)

- **Connector OAuth redirect host.** The connector OAuth redirect host is `localhost:53682` in the desktop (`main/oauthCallback.ts`). `docs/integrations/github-setup.md` now registers exactly that host, and the App's callback list does too.
- **Soft-deleted memberships.** `GET /teams`, `GET /teams/{id}/members`, the team detail `member_count` and the `last_owner` count ignore memberships with `deleted_at` set.
- **Repo pagination.** The OAuth picker's `GitHubConnector.list_repositories` follows the Link header, bounded, instead of stopping at 100.


## 6. Decisions under delegated judgment (SOLUSDEV-216 Phase 2, 2026-10-17)

- **No `DEGRADED` source status.** `SourceStatus` has no `DEGRADED`, so these cases use `ERROR` plus a `last_error.code`: `installation_suspended`, `repo_access_removed`, `repo_renamed`, `repo_transferred` or `repo_deleted`. Unsuspend restores only the sources whose code is `installation_suspended`.
- **`setup_action=request`.** When a non-owner asks an org owner to approve the install, GitHub redirects with `setup_action=request` and **no** `installation_id`. `install/complete` accepts `{state, code, setup_action: "request"}`, consumes the state, binds nothing, and answers `202 {status: "requested"}`. The card then says "Waiting for an org owner to approve Solus on GitHub — link again once they do".
- **User-to-server token.** After the proof step (§2 complete, step 3), the token is revoked at GitHub on a best-effort basis (`DELETE /applications/{client_id}/token`), so it doesn't stay live for 8 h.
- **Repo count.** The card's repo count is `meta.total` from `GET /github/repos`. `TeamInstallationRead` has no count field.
- **Plan accounting.** An installation counts against the linker only while the linker is a live member of the team. Sources bound through an installation never count against whoever created them.
- **PATCH on installation sources.** Changing `config.repo` on an installation-bound source re-runs the `repo_not_in_installation` check. `secret_ref`, `installation_id` and `connection_id` are never patchable.
- **Account id on installation sources.** These sources carry `account_external_id = "installation:{id}"`, so account-keyed caches key per installation, and the I1 account-reuse logic (`reusable_source`, legacy and own-token listings) never adopts or re-points them.
- **GHES limitation.** The per-installation `api_base_url` is honoured by the minter, the App client and the connector. `read_code_file`, `code_content` and `git_revisions` still call `api.github.com` (known limitation, follow-up). The base URL only ever comes from GitHub's installation record, which the App JWT fetches. It is never taken from request input or a webhook payload.
- **GitHub identity sources.** The trusted sources are a live GitHub `AccountConnection.account_external_id`, or the Supabase admin identity when the service-role key is configured. JWT `user_metadata` is never trusted. Without the service-role key, only a linked GitHub account proves identity.
- **Install state passthrough.** We assume `state` survives `installations/new?state=…` through to the callback when user authorization during install is enabled. This is to be confirmed against a live App. If it doesn't survive, `install/start` falls back to a second `login/oauth/authorize?client_id=<app>&state=…` step.
- **The ref names our row, not GitHub's id** (security review, 2026-10-17). `{team_installation_id}` is the `team_installations.id` UUID. A re-link is always a new row, even of the same GitHub installation by another team. So a stale or copied ref (for example on a revision source) points at a soft-deleted row and the status gate refuses it. A ref can never resolve against another tenant's link. Minting and the token cache stay keyed by GitHub's installation id.
- **`install/complete` body.** `installation_id` is required for `install`/`update` and absent for `request`. Unknown fields return 422, so a caller can never supply `api_base_url`. If the team already holds a *different* live installation, the answer is `409 already_linked`. An installation that is suspended on GitHub at link time is stored with status `suspended`. A refused code exchange returns `400 oauth_exchange_failed`, and other GitHub failures return `502` with the connector's code.
- **State handling.** The install state is consumed (committed) before any GitHub call, so it can never be replayed. A state belonging to another user, team or purpose answers `404 install_state_invalid` *without* being consumed, so a stranger cannot burn someone else's handshake. The role, PERSONAL and unconfigured checks run before the state is touched.
- **`github_app_unconfigured`** applies only to `install/start` and `install/complete`. `GET` and `DELETE /installation` keep working, so a team can always see and unlink.
- **Roster and GitHub invites on a suspended or revoked installation.** These answer the `409 installation_*` refusal. A missing installation, a `User` account, or a PERSONAL team answers `400 not_an_org_member` for invites.
- **Roster matching.** Bulk matching uses linked GitHub account connections only. A teammate proven only through the Supabase admin identity shows as `not_on_solus` in the roster. Accept-time proof still uses both sources.
- **No auto-sync on bind.** Binding a repo through the installation does not dispatch a sync, matching the existing connect route. The connect wizard writes the config and triggers `POST …/sync` itself.
