# Completion report — SOLUSDEV-242 · HOME H2: Connections move to account scope

Branch: `SOLUSDEV-242-home-cross-project-surface` (shared with H1; local commits only, no push, no MR).
Cowork QA: `docs/qa/COWORK_QA_home-h2-account-connections.md`. H1's report: `COMPLETION_SOLUSDEV-242-home-h1.md`.

## What already existed (SOLUSDEV-241 / I1) and was reused, not rebuilt

Account-scoped OAuth (`oauth/start` without a project), the Home **Connected accounts** card
(connect, list with the projects using it, confirmed revoke), the project wizard skipping the
sign-in when a linked account exists, the account document listing, and the per-project
document add/remove routes. H2's acceptance "connect Onshape once in Home; pick two documents in
Workspace with no second OAuth" is I1's model; it is re-verified here by
`test_a_second_project_reuses_the_adopted_account_with_no_oauth` and the live run below.

## What H2 built

**Migration without re-auth** (`services/connections.py::adopt_legacy_sources`,
`POST /users/me/connections/adopt`): every project-scoped OAuth grant the caller authorized
(a `source/…` ref with no connection row — pre-I1 wizard connects and token connects) becomes an
account connection: the access, refresh and hosted add-on secrets are copied under the
connection's ref, the source mirrors the connection (`bind_source`, so every credential path is
unchanged and the project keeps syncing), an account already connected on Home is reused rather
than duplicated, and the project-owned copies are deleted only after the commit. Idempotent;
owner-only; committed-export and already-bound sources are ignored; a source whose token is gone
is skipped, never given an empty grant. Home's hook calls it before listing.

**No scope widened, re-consent said plainly.** The connection records the access mode the source
recorded. When the source never recorded one, the connection carries `needs_reauth =
access_unknown`; the API row exposes `origin` (`home` | `migrated`) and `needs_reauth`
(`access_unknown` | `token_error` | null). Home states the scope on every row (Read only / Read
and edit / Access level not recorded), marks a migrated grant, and offers **Re-authorize** with
the copy "existing syncs keep working until then". Re-authorize runs the same account-mode
wizard as Connect; the finished sign-in lands on the same row (I1's dedupe by account), which now
clears the flag and records the chosen access — the old token survives until the new one
succeeded. Connector scope sets are untouched (Onshape read = `OAuth2Read`, write = `OAuth2Read
OAuth2Write`; asserted in a test).

**Allowlist pinned.** A parametrised test asserts `127.0.0.1` and `localhost` redirects at any
port are accepted (the existing test covers the rejection).

**Activity/events.** `connection.adopted` per project (humanised on the desktop, with
`connection.revoked` which had no text before); a `connection.adopted` data event.

## Governing docs

CLAUDE.md, DECISIONS.md (ADR-025, ADR-032), `docs/api/API.md` §2.1/§2.5 (amended: the adopt
route and the two new row fields), `docs/wireflows/home.md` (new "Connected accounts" section),
`docs/wireflows/sources-connect-wizard.md` (I1's linked-account rails, unchanged),
`docs/qa/COMPLETION_SOLUSDEV-241-i1-connection-model.md`. `docs/design/SPEC.md` and
`docs/design/screens/` do not exist in the repository. No tier-2 file was touched.

## Verification

- API: `tests/test_connection_adoption.py` (12 new), `tests/test_integrations.py` (+3 parametrised
  allowlist cases); `test_connections.py`, `test_integrations.py`, `test_sources*.py` green after
  the change to `complete_connection`. ruff + mypy clean.
- Desktop: full suite green (see the H1/H2 commit messages for counts); typecheck and eslint clean
  on touched files. New/updated: `ConnectedAccountsCard.test.tsx` (+3), `useAccountConnections.test.ts`
  (+2), `connectedAccounts` helpers, `resources.test.ts`, `activityText.test.ts`.
- **Run for real** against a private API instance (port 8001, the dev Postgres, the dev
  `SOLUS_SECRETS_KEY` local store) and a scratch renderer: a pre-I1 Onshape source was seeded for
  the QA user in Rover with an encrypted token and refresh token and no connection row. Opening
  Home adopted it (one `POST …/adopt`, one list): the row read "Onshape · ada-legacy · Used in
  Rover · Access level not recorded · moved from a project" with the re-consent note, Re-authorize
  and Revoke, and no Connect; Re-authorize opened the account-mode wizard (rail Choose access →
  Sign in); dismissing it left the row and the grant intact; Rover's Sources page still listed the
  source connected. Database and secret-store checks: the source's `connection_id` and `secret_ref`
  point at the new connection, the token and refresh token moved intact, both old refs are gone,
  a second adopt returned nothing, and Arm bound to the connection by id with **zero**
  `oauth/start` calls in the API log; Home then read "Used in Rover and Arm". Screenshots in the
  session scratchpad (not committed).

## Decisions under delegated judgment

1. Adoption is an explicit idempotent POST the Home hook calls before listing — not a side effect
   of GET and not an Alembic step, because the secrets live outside the database.
2. Ownership follows `Source.created_by`: the person who authorized owns the account; teammates keep
   using the source through the mirror (I1's model). A source with no `created_by` is never adopted.
3. Token-connected (PAT) sources are adopted too — the token is the user's account credential.
4. "Re-consent is unavoidable" is signalled only where Solus genuinely cannot say what the grant
   allows (no recorded access mode). Granted scopes are not persisted at exchange time today, so
   a scope drift between an old token and the connector's current scope set cannot be detected;
   recording `granted_scope` from the exchange response is a small follow-up, not done here.
5. When a legacy source recorded a DIFFERENT access mode than an account already connected on
   Home, the account's current grant wins and the source mirrors it (one live grant per account is
   an I1 invariant). The narrowing is visible on the row; no token is mixed.

## Deviations / open concerns

- A real Onshape OAuth completion in a browser, and therefore a real Re-authorize landing and a
  real document pick, were not run (no headless way; same limit as I1). The unit tests drive both
  through the real routes with a fake connector; the QA plan covers them.
- A legacy source with no `account_external_id` adopts into a connection without one; a later
  re-auth of that account cannot be matched by identity and would create a second row (the unique
  index only guards non-null ids). Revoke cleans it up; noted in the QA edge cases.
- The `sources` row seeded for the live run remains in the dev database (project Rover of team
  "Strider QA", user h1-qa@solus.dev), adopted, alongside the H1 seed data.
- No `.env` values are required. Secret backend, Onshape/GitHub OAuth client settings are as
  documented by I1.
