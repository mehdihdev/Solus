# Completion report: SOLUSDEV-216, GitHub organizations in teams

**Branch:** `SOLUSDEV-216-github-orgs-in-teams`, cut from `main`. Local commits only: nothing is pushed and no MR is open.

**Status:** Implementation and the Phase 4 fixes are complete. The final full-suite results are below.

## What was built

A COLLABORATIVE team links a GitHub **organization** (or user account) through the **Solus GitHub App**. The team owns that installation (ADR-039). Once linked:

- **Repos without personal sign-in.** Any member+ adds the org's repos to the team's projects without a personal GitHub sign-in. Sources resolve credentials through a reserved ref, `github-app/installation/{team_installations.id}`. Each use mints a 1-hour installation token, which is never stored, logged or returned.
- **Survives member churn.** Sources keep syncing when the person who linked the org leaves the team.
- **Freshness.** It comes from the App's single signed webhook. Pushes sync the matching sources, and install, suspend, repo-access and rename events disable or restore sources honestly. The hourly ETag sweep remains as the backstop.
- **Roster and invites.** Admins see the org roster and can **suggest** invites by GitHub id. Accepting requires the accepter's _verified_ GitHub identity. GitHub membership never grants Solus access, and nobody is auto-joined or auto-removed.
- **Ride-along fixes.**
  - The connector OAuth callback host is pinned to `localhost:53682` and regression-tested against the setup doc.
  - Soft-deleted memberships are now ignored in team lists, member counts and the last-owner guard.
  - The OAuth repo picker paginates past 100 repos.

| Layer   | Pieces                                                                                                                                                                                                                        |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Schema  | Migration `a21600000001`: `team_installations`, `github_webhook_deliveries`, `sources.installation_id`, GitHub-id invites, `oauth_states.team_id`, and the new notification type                                              |
| API     | `/teams/{id}/github/install/start`, `install/complete`, `installation` (GET/DELETE), `repos` and `members`. `POST /webhooks/github/app`. `POST /projects/{id}/sources` with `installation: true`. Invites by `github_user_id` |
| Core    | App JWT and token minter (`connectors/github_app.py`), team installation service, link, events, installation sources, roster and identity services                                                                            |
| Desktop | Home **GitHub organization** card and roster modal; wizard "From <org> (team)" picker with search and load-more; install loopback carrying `installation_id`/`setup_action`; 10-minute install wait                           |

## Governing docs

- **ADR-039** (new, approved in-chat 2026-10-17). ADR-015, 019, 023, 024, 025, 030, 035 and 037 also apply.
- `docs/api/github-orgs.md` (new route plan; §6 holds every judgment call) and the `docs/api/API.md` pointer rows.
- `docs/schemas/team-installations.md` (new).
- `docs/wireflows/home.md` (GitHub organization card) and `docs/wireflows/sources-connect-wizard.md` (team org section).
- `docs/integrations/github-setup.md`: GitHub App registration, and the callback host corrected.
- Spec packet: `docs/superpowers/specs/2026-10-17-github-orgs-in-teams.md`.
- **Contracts:** there is **no change** to `packages/contracts/`. The credential seam lives in `connectors/runtime.py::resolve_credentials`.

## Tests

- **Backend.** Roughly 600 new API tests across about 20 files. They cover:
  - cross-tenant isolation on every new route;
  - install-state replay, forgery and concurrency;
  - the admin proof;
  - user-token lifecycle, including cancellation;
  - signature, size and duplicate handling on the webhook;
  - payload injection fixtures;
  - re-link isolation of refs;
  - linker-leaves;
  - plan accounting;
  - the connector contract suite in installation mode;
  - pagination and its SSRF guard;
  - identity spoofing via JWT metadata.
- **Desktop.** Roughly 300 new or extended vitest cases. They cover the card states, copy in both SOL modes, team-switch races, the picker, the loopback parsing and the modal focus behaviour.
- **Final runs:** see the "Final validation" section at the end.

## Phase 4 review outcomes

There were four reviewers: code, security, Python and TypeScript. None found a CRITICAL or HIGH issue in the final code. Two issues the automated commit security review raised during the build were fixed:

1. **Re-link reuse of credential refs.** Refs now name _our_ `team_installations` row, not GitHub's installation id. A stale or copied ref can never resolve against another team's later link.
2. **Privilege escalation on link.** GitHub lists an installation for anyone with access to one repo it covers. Linking now also requires an **active org admin** (or, for a user account, the account itself).

Phase 4 MEDIUM and LOW fixes, all applied:

- **Revocation.** Revocation detected while minting performs the full revoke, so a link can no longer be left stuck in a revoked-but-not-removed state. Destructive webhook events are re-confirmed with GitHub, so replays are safe.
- **Rate limiting.** The webhook has its own rate bucket, and failed signatures are throttled separately. `install/start`, `install/complete` and GitHub invites are rate limited.
- **Install flow.** State is consumed atomically. A same-team race answers `already_linked`. The user-token revoke survives cancellation. Owner-approval redirects work without a code.
- **Access and input.** `/repos` is member+, matching the route plan. Invites store the roster's login, never the client's. Installation-source PATCH is allow-listed. Bind defaults the branch. Repo names are normalised with casefold.
- **Desktop.**
  - Upgrade is threaded through the roster.
  - The overflow menu is an accessible disclosure, and `ModalShell` gains focus management. Escape-to-close is **opt-in**, so existing modals are unchanged.
  - Mode-aware copy everywhere; team-switch and stuck-linking races fixed; offline retry; picker loading and failure states, search and load-more; a robust team-pick hand-off.

## Decisions taken under delegated judgment

All of these are recorded in `docs/api/github-orgs.md` §6:

- **Token cache.** Process-local only, never Redis. A DB status gate runs on every resolve.
- **Source errors.** There is no `DEGRADED` source status; errors use `ERROR` plus a code (`installation_suspended`, `repo_access_removed`, `repo_renamed` and so on).
- **System-actor events.** Logged and recorded as activity with a null actor. No data event, because those need a consenting user.
- **Plan accounting.** A link counts as 1 integration against the linker, only while they're a member. Repo binds are free.
- **Unconfigured App.** `github_app_unconfigured` gates only install start and complete, so a team can always see and unlink.
- **Non-owner installs.** `setup_action=request` binds nothing and answers 202 "waiting for an org owner".
- **Binding and sync.** Binding does not auto-sync; the wizard triggers the sync, matching the existing connect route. PATCH drops unknown config keys on installation sources.

## Deviations and follow-ups, flagged

These are suggested follow-ups, not blockers:

1. **Resolver binding.** The resolver isn't bound to the requesting source or team. Refs are only ever written server-side, and the row-UUID binding already blocks re-link reuse. Passing `source.installation_id`/`team_id` into `resolve_credentials` is defence in depth for a later change.
2. **Webhook sync durability.** Webhook push syncs are scheduled after commit. A crash between commit and run loses that sync. GitHub redelivery is de-duped, and the hourly sweep catches it. Enqueueing to ARQ inside the transaction would close the gap.
3. **Source state after a mint 404.** A sync that hits a mint 404 leaves its source as `ERROR installation_unavailable`, because the runtime overwrites the revoke's `DISCONNECTED`. The link itself is fully revoked. Cosmetic.
4. **GHES coverage.** `read_code_file`, `code_content` and `git_revisions` still call `api.github.com`. GHES is supported by the data model and minter only.
5. **Roster matching.** Roster "On team" matching uses linked GitHub accounts only. The Supabase admin identity path needs the service-role key (SOLUSDEV-82 deferral).
6. **Rate-limit helper.** `routers/invites.py` imports the members router's private rate-check helper. Moving it to a shared module is cleaner.
7. **`schema.ts` churn.** The regenerated `schema.ts` diff is about 27k lines because **main's committed `schema.ts` was already stale**: about 17k lines differ from a fresh generation of main's own `openapi.json`. This branch's real API delta is about 390 lines.
8. **TDD order in two tasks.** T3 and the desktop fix pass wrote tests alongside the code rather than strictly red-first; this is noted honestly. Every other task confirmed red before green.
9. **Two pre-existing test problems:**
   - `test_cad_store.py` parametrizes with `uuid4()`, so the API suite can't run under `pytest -n`.
   - Desktop `WorkspaceScreen.test.tsx` flakes under full-suite load. It passed 3 of 3 runs alone, and this branch doesn't touch it.
10. **Escape and stricter lint.** ModalShell's Escape is opt-in (`closeOnEscape`), used by the new GitHub dialogs only. The package-local desktop eslint config reports errors, both pre-existing ones and new ones in touched files, that the root config, which the hooks enforce, does not.

## Human steps before QA or merge

- **Register the GitHub App** per `docs/integrations/github-setup.md` → "GitHub App for team organizations". You need one per environment, with _Request user authorization during installation_ ON.
- **Set the env vars** `SOLUS_GITHUB_APP_ID`, `_SLUG`, `_CLIENT_ID`, `_CLIENT_SECRET`, `_WEBHOOK_SECRET` and `_PRIVATE_KEY` (or `_PRIVATE_KEY_PATH`). In prod they go in Secrets Manager. `.env*` / `.env.mega.example` are human-owned.
- **Webhook URL.** Expose a public HTTPS webhook URL, `<API>/api/v1/webhooks/github/app`, for webhook QA.
- **Confirm state passthrough** on the live App. `installations/new?state=…` should come back carrying `state` (§6 assumption). `setup_action=request` redirects without a code are already handled.
- **Run the migration:** `alembic upgrade head`.
- **Run the Cowork QA:** `docs/qa/COWORK_QA_github-orgs-in-teams.md`.
- **Push, open the MR and merge.**
- **Parked SOLUSDEV-315 work.** That branch's uncommitted hosted-MCP edits are parked in `stash@{0}` ("SOLUSDEV-315 hosted-MCP WIP"). Run `git stash pop` after checking out the 315 branch.

## Final validation

All runs are on the final branch head, each with a private test DB.

| Check | Result |
|---|---|
| API full suite (serial) | **9063 passed, 6 skipped, 0 failed** (68 min) |
| Desktop full suite (`pnpm --filter @solus/desktop test`) | 4835 passed, 1 failed. The failure is `WorkspaceScreen.test.tsx`, a pre-existing load flake that passed 3 of 3 runs alone. This branch doesn't touch `features/graph` |
| `ruff check src tests` / `mypy src` | clean / clean (417 files) |
| `tsc` web + node | clean |
| eslint (root config, which the hooks enforce) on changed desktop files | 0 errors |
| Migration | single head `a21600000001`; upgrade → downgrade → upgrade tested |
