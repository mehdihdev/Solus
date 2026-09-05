# Completion report — SOLUSDEV-241, INTEGRATIONS I1 (the connection model)

**Branch:** `SOLUSDEV-241-corpus-c1-scope-and-licensing` (worked on as instructed — the branch
name predates this ticket's I1 scope; not switched so other agents were not disrupted)
**Commit:** `SOLUSDEV-241: I1 connection model — account-scoped OAuth + integration cache`
**QA plan:** `docs/qa/COWORK_QA_i1-connection-model.md`

---

## Governing docs

`docs/design/SPEC.md` and `docs/design/screens/` named by the standing rules **do not exist** in
this repository on any branch. The closest authorities were used instead:

| Doc | Bearing |
| --- | --- |
| `docs/architecture/change-signal-spine.md` | The caching rules (account-keyed, version-keyed, never a timer) were already specified there; I1 builds them. Amended with "The read side, built". |
| `docs/contracts/connector-interface.md` (Edits 6–8) | `SyncContext`/`SyncResult` unchanged; the cache sits below the interface as Edit 4 says freshness policy must. Tier-2, **not edited**. |
| `docs/api/API.md` §2.1/§2.5 | Amended (tier-1) with the connection routes and the changed OAuth/source rows. |
| `docs/wireflows/sources-connect-wizard.md` | Amended with the linked-account and account-scope rails. |
| `DECISIONS.md` ADR-025 (project = scoping anchor), ADR-027, ADR-030, ADR-032 | A user-owned row outside the team anchor follows the `PanelBinding` precedent; no ADR change needed or made. |

Design-review answers (in-chat): all OAuth connectors move to the model; connections are
user-owned and usable in any of the owner's projects; one Source per provider per project keeps
the document list; Home card + wizard reuse for the desktop.

## What was built

**Backend.** `AccountConnection` (`account_connections`, user-owned; status pending/connected/
error/revoked; access mode in `config`). `Source.connection_id` + a mirrored secret ref
(`connection/{id}/{provider}`) so every credential path — sync, sweep, picker, SOL tools, hosted
add-ons — is unchanged; the one new rule is ownership (`services/connections.py`). OAuth binds
at account scope: `oauth/start` without `project_id` (Home) or with it (wizard, compatible);
completion lands on the existing connection for the same account (token rotation, never a
duplicate). Routes: list/get/revoke my connections, cached account listing, bind a project by
`connection_id`, add/remove a document on a project source, cached `selectable`. Account
deletion sweeps connection secrets; project teardown and source disconnect leave them alone.

**Integration cache** (`connectors/integration_cache.py`): listing / signal / payload entries
keyed on `(provider, account, document, version)`; fetch-through with cross-process
single-flight; oversize payloads used but not stored. The Onshape connector reads the workspace,
microversion, element list, STEP export and part metadata through it. Trust windows by purpose:
a human's sync trusts a recorded signal for the sweep interval, the sweep for five minutes, a
webhook never (`registry.Purpose`, derived from the sync trigger). The webhook doorbell
invalidates the account's listing.

**Desktop.** `Connection` types + client functions; `runAccountConnect` (Home engine);
`runOAuthConnect` binds to a linked account and skips the handshake; the rail drops
`access`/`authorize` when linked and ends at sign-in in account scope; Home's
`ConnectedAccountsCard` (connect, confirmed revoke naming the projects); the Sources wizard
reuses the linked account.

## Acceptance, measured

`tests/test_onshape_call_budget.py` (I1 block, real Onshape connector against a counting fake):

| Criterion | Test | Result |
| --- | --- | --- |
| Two projects share one Onshape doc | `test_two_projects_sharing_one_document_pay_for_it_once` | second project's first sync: **0** counted calls, same entity count |
| Listing costs zero after the first | `test_listing_the_accounts_documents_costs_zero_calls_after_the_first` + `test_connections.py::test_listing_documents_costs_zero_calls_after_the_first` | repeat: **0**; `refresh=true` spends |
| A repeat read costs zero | `test_a_teammates_repeat_sync_costs_zero_calls` | **0** (was ≤2 probes before I1) |
| Teammate's sync serves from cache | same, plus `test_connections.py::test_a_teammate_uses_the_shared_grant_through_the_source` | picker served cached, sync 202 |
| Signal moves only via sweep/webhook | `test_the_sweep_moves_the_signal…`, `test_a_webhook_sync_never_trusts…` | as designed |
| No cross-account sharing | `test_the_shared_cache_never_crosses_accounts` | account 2 pays its own export |

## Test coverage

- API: **3537 passed, 4 skipped, 1 failed** (final run, after the security fixes) on an isolated DB (`SOLUS_TEST_DATABASE_URL`).
  The one failure, `test_bridge_e2e.py::test_full_companion_cloud_round_trip`, **fails
  identically on the pristine tree** (verified by stashing this diff and re-running) — the
  companion mock-server fixture on this machine, not this change.
- New: `test_connections.py` (20), `test_integration_cache.py` (8), 6 budget tests; updated
  `test_integrations.py`, `test_connector_quota.py`. ruff + mypy clean on the API package.
- Desktop: typecheck clean; **737 vitest tests pass**; new suites for `accountConnect`,
  `useAccountConnections`, `ConnectedAccountsCard`, `connectedAccounts`, plus additions to
  `oauthConnect`, `connectSteps`, `useConnectWizard`, `resources`. ESLint: my files are clean;
  the repo carries pre-existing `react-hooks/set-state-in-effect` and `react-refresh` errors in
  untouched files (`useHomeData.ts`, `useMe.ts`, `modals.tsx`, …).

## Run for real

API started from the migrated dev DB (`alembic upgrade head` applied: `a7d3f9c41e88 →
9a1c4e7d2b30`) and exercised with two dev JWTs: Home-style `oauth/start` returns a real
`oauth.onshape.com` authorize URL with `source_id: null`; pending handshakes do not list; the
documents route answers 409 while pending; Bob gets 404 on Alice's connection (read, revoke,
bind); provider mismatch answers 400; OpenAPI lists the five new paths. The desktop renderer was
driven against that live API as the verification user (screenshots in the session scratchpad):
the Home card renders live data (linked GitHub row with "Not used by any project yet", Connect
for GitLab/Onshape), the account-scope wizard shows **Choose access → Sign in**, the revoke
confirmation names the account, and the Sources wizard shows **Pick repositories → Build graph**
with "Using your linked account · i1-octocat". The linked GitHub row was seeded directly in the
dev DB for the UI run (no PAT/OAuth available headlessly) and removed afterwards.

**Not verified live:** a real browser OAuth completion (needs a human), and therefore a real
linked-account sync end to end; the QA file's §2–§8 cover it.

## Decisions under delegated judgment

- Manual "Sync now" trusts a recorded signal for the sweep interval (1 h default); without a
  registered webhook it can be that stale. Documented in the spine doc and the QA file; no
  `force` flag was added (not requested).
- Payloads above 8 MiB are fetched but not cached (`SOLUS_INTEGRATION_CACHE_MAX_PAYLOAD_BYTES`).
- PENDING connections are not listed; a recent pending one is reused by retries; re-authorizing
  an already-linked account rotates its token on the existing row.
- Revoking does not invalidate the account's cached listing (only refresh/doorbell do — spine
  rule); the entry is unreachable without credentials anyway.
- PAT (token) connects and committed-export connectors keep source-owned secrets.
- `ConnectorContext.project_id/team_id` became optional for account-scoped calls; the bridge
  acquirer factory refuses a project-less context explicitly.

## Review outcomes

- code-reviewer: **APPROVE**, no CRITICAL/HIGH/MEDIUM; three LOW notes, all fixed (one identity
  fallback via `account_ref_for`; one cache read in `_locate`; connector-declared
  `validate_selection` instead of a provider check in the router).
- security-reviewer: initial verdict **FAIL** (C1, H1, H2, M1–M5, L1–L7). Fixed in the follow-up
  commit, each with a test where the finding was behavioural:
  - **C1** a second valid OAuth state could re-point an already-CONNECTED account: only a PENDING
    row may complete (`stale_handshake` → 400), bound sources are re-mirrored from the landing
    row, and a partial unique index guards one live grant per (user, provider, account)
    (`test_a_stale_handshake_cannot_repoint_a_connected_account`).
  - **H1** account deletion left sources in surviving teams CONNECTED on a dangling ref: `delete_me`
    now revokes each connection (`test_deleting_the_account_disconnects_sources_in_surviving_teams`).
  - **H2** `refresh=true` had no cost bound: a per-ACCOUNT refresh cooldown (60 s default,
    `SOLUS_INTEGRATION_LISTING_REFRESH_COOLDOWN_SECONDS`) inside the cache's single-flight, and every
    refresh is logged as an `integration.listing_refreshed` data event
    (`test_listing_refresh_is_cooled_down_per_account`). Not done: a dedicated rate bucket —
    `path_limits` is exact-path only and the routes carry ids; the cooldown bounds spend per
    account regardless of how many principals share it.
  - **M1** the registry's fallback defeated the connector's "no account, no cache" guard: the
    scoped factory now passes `None`, so an unidentified account caches nothing.
  - **M2** revoke / account deletion left cached CAD payloads for up to 30 days: the cache keeps a
    per-account key index and `invalidate_account` drops it on revoke and deletion.
  - **M4** `source.config.access` was member-patchable: `PATCH` strips `access`, and the SOL write
    gate reads the CONNECTION's grant when the source is bound
    (`test_access_cannot_be_patched_onto_a_source`).
  - **M5** account-only `oauth/start` skipped the verified-user and plan-limit checks: both now
    apply to every start.
  - **L1–L7**: connector-declared `validate_selection`; oversize text refused before encoding;
    `connection_projects` ignores soft-deleted projects; log lines carry a key kind + hash, never
    an account or document id; the cache has its own `solus:icache` prefix; the ref-derivability
    constraint is recorded on the model; quota ledger keys quote the account ref.
  - **M3 (open — a design decision):** removing a member leaves the team's sources on that member's
    account-wide grant (same as today for source-owned tokens; the lever is the owner's Home
    revoke, all-or-nothing). Proposed follow-up: disconnect a departing member's bound sources on
    removal, and a per-project unbind (`DELETE /users/me/connections/{id}/projects/{p}`). Needs a
    human call on policy; not built.

## Deviations, flags, and values to set

- **`docs/design/SPEC.md` and `docs/design/screens/` are missing from the repo.** The UI was built
  from the wireflow + API §5; reconcile when the design lands.
- Onshape **webhook registration still does not exist** (nothing mints the per-source token); the
  receiver + invalidation are wired, so registering is a follow-up ticket.
- The root `.env` sets `REDIS_URL`/`SOLUS_REDIS_URL` but no Redis is listening locally; the API
  then constructs a lazy Redis client and every cache call fails open (miss). For local dev
  either run Redis or leave `SOLUS_REDIS_URL` empty. No `.env` was edited.
- New settings (all optional, defaults shown): `SOLUS_INTEGRATION_SIGNAL_TTL_SECONDS=3600`,
  `SOLUS_INTEGRATION_SIGNAL_SWEEP_REUSE_SECONDS=300`, `SOLUS_INTEGRATION_LISTING_TTL_SECONDS=604800`,
  `SOLUS_INTEGRATION_PAYLOAD_TTL_SECONDS=2592000`, `SOLUS_INTEGRATION_CACHE_MAX_PAYLOAD_BYTES=8388608`.
- Deploy needs `alembic upgrade head` (one migration, reversible).
- Another process ran `uv run pytest` in this checkout during the session; the shared default
  test DB then deadlocks. All runs here used an isolated `SOLUS_TEST_DATABASE_URL`.
