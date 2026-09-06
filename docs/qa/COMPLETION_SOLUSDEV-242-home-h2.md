# Completion report — SOLUSDEV-242 · HOME H2: Connections move to account scope

Branch: `SOLUSDEV-242-home-cross-project-surface` (shared with H1; local commits only, no push, no MR).
Cowork QA: `docs/qa/COWORK_QA_home-h2-account-connections.md`. H1's report: `COMPLETION_SOLUSDEV-242-home-h1.md`.

## What already existed (SOLUSDEV-241 / I1) and was reused, not rebuilt

Account-scoped OAuth (`oauth/start` without a project), the Home **Connected accounts** card
(connect, list with the projects using it, confirmed revoke), the project wizard skipping the
sign-in when a linked account exists, the account document listing, and the per-project
document add/remove routes. H2's acceptance "connect Onshape once in Home; pick two documents in
Workspace with no second OAuth" is I1's model; it is re-verified here by
`test_a_claimed_source_serves_a_second_project_with_no_oauth` and the live run below.

## What H2 built

**Migration by proof, not by hint** (`services/connections.py`, `routers/connections.py`,
`routers/integrations.py`). A source connected before I1 holds its own token under a `source/…`
ref. Its row's `created_by` is NOT proof of whose token it holds (the pre-I1 "switch account" path
let a teammate complete a handshake on someone else's row — security review C1), so nothing is
moved blind. Instead:

- `GET /users/me/connections/legacy` lists the caller's own legacy grants (creator hint, live
  non-viewer membership, live project) so Home can say "sign in once to move it".
- A finished Home handshake PROVES a provider account (`claimable_connection_id` on the legacy
  row); the MOVE itself is the user's explicit, confirmed request naming the sources
  (`POST /users/me/connections/adopt {source_ids, confirm_access}`) — never a side effect of
  loading Home or of a handshake. The source MIRRORS the grant — nothing is copied, no secret
  exists without a row that owns it — and keeps syncing. The grant is re-read FOR UPDATE and the
  sources locked; the project-owned token family is DERIVED from the source id (an underscore
  marker, never patchable, never serialized, names no ref) and deleted after the commit, a failed
  delete retried, never leaked, never a 500.
- **Nothing widened.** A recorded access mismatch is refused (`skipped: access_mismatch`); a
  `write` grant on a source that never recorded its access needs the user's explicit acceptance
  (`confirm_access`, stated in the confirmation) or is refused (`access_unknown`). Connector scope
  sets are untouched and asserted.
- Membership is enforced on every read and write (removed members, viewers and deleted projects
  see and move nothing); the adopt route requires a verified user.

**Home card.** Every catalog tool is listed (the user reported the card hid most tools): OAuth
tools link an account; committed-export and local-companion tools say where they connect
instead. Linked rows state their scope (Read only / Read and edit / Access level not recorded);
legacy rows read "Connected in a project, not yet on your account" with a note naming the projects
and stating plainly that they keep syncing until moved, plus **Sign in to move** (the account-mode
wizard) or, once the account is proved, **Move to your account** behind a confirmation that names
the projects, the grant, and the removal of the project's own token; a row whose last sign-in
failed offers **Re-authorize** with the provider's message.
Re-authorize/Sign in land on the same row (I1's dedupe), so the old token is replaced only once the
new one succeeded.

**Allowlist pinned.** A parametrised test asserts `127.0.0.1` and `localhost` redirects at any
port are accepted. **Activity/events**: `connection.adopted` per project (humanised on the
desktop, with `connection.revoked`).

## Governing docs

CLAUDE.md, DECISIONS.md (ADR-025, ADR-032), `docs/api/API.md` §2.1/§2.5 (amended: the adopt
route and the two new row fields), `docs/wireflows/home.md` (new "Connected accounts" section),
`docs/wireflows/sources-connect-wizard.md` (I1's linked-account rails, unchanged),
`docs/qa/COMPLETION_SOLUSDEV-241-i1-connection-model.md`. `docs/design/SPEC.md` and
`docs/design/screens/` do not exist in the repository. No tier-2 file was touched.

## Verification

- API: `tests/test_connection_adoption.py` (17 cases: listing without moving; the Home sign-in
  claim; claim on load for an already-connected account; two projects one connection; a second
  project with no OAuth; an errored source healed by the proved grant; **C1** creator ≠ token
  owner never claimed by the creator, claimed by the owner; **C2** removed member, viewer and
  deleted project claim nothing; **H1** access mismatch reported, never widened; concurrent
  adopts claim once with no 500; a failed secret delete is retried not leaked; an errored
  connection never claims; 401/403), `tests/test_integrations.py` (+3 allowlist cases).
  `test_connections.py`, `test_integrations.py`, `test_sources.py`, `test_onshape_call_budget.py`
  green. ruff + mypy clean.
- Desktop: full suite green; typecheck and eslint clean on touched files. `ConnectedAccountsCard.test.tsx`
  (legacy row, side-by-side, all catalog tools, scope, Re-authorize), `useAccountConnections.test.ts`
  (adopt-before-list, legacy list, failure isolation), copy helpers, `resources.test.ts`, `activityText.test.ts`.
- **Run for real** (private API on 8001 against the dev Postgres and the dev local secret store;
  scratch renderer; Electron harness): see "Live run" below.

## Decisions under delegated judgment

1. **No silent migration.** The ticket allows "where re-consent is unavoidable, say so plainly";
   proving whose account a legacy token belongs to IS unavoidable without a handshake, so one
   sign-in per account is the proof, and the move is one confirmed click per legacy row that names
   what changes (CLAUDE.md §7: destructive effects need explicit confirmation with the concrete
   action shown). A user who has already linked the account on Home skips the sign-in, not the
   confirmation.
2. Ownership follows the proved provider account (`account_external_id` vouched by the provider
   at handshake), never `created_by`; `created_by` only decides what Home SHOWS as legacy.
3. Token-connected (PAT) legacy sources are claimable the same way (a PAT for the same account).
4. Access mismatch is reported, not resolved: changing a project's grant belongs on that project's
   Sources page (W2 follow-up), where the concrete change can be confirmed.
5. Granted scopes are still not persisted at exchange time, so drift between an old token and the
   connector's current scope set cannot be detected; recording `granted_scope` is a small follow-up.

## Deviations / open concerns

- A real Onshape OAuth completion in a browser — and therefore a real "Sign in to move" landing —
  was not run (no headless way; same limit as I1). The claim-on-completion path is driven through
  the real routes with a fake connector in the tests; the live run proves the claim-on-load path
  with a connection row written the way a real handshake writes it.
- The user reported the card "doesn't show all the available options": fixed on this branch by
  listing every catalog tool (previously only OAuth tools rendered).
- Dev database state left behind: the QA user's Rover Onshape source (claimed to a seeded
  connection) and the H1 seed data (team "Strider QA"); safe to leave or delete.
- No `.env` values are required.

## Phase 4 reviews

Three rounds. The first H2 commit (`004b703`) received a **FAIL** from the security review:
adoption trusted `Source.created_by` as proof of the token's owner (C1, cross-user grant theft) and
mutated team rows with no membership check (C2), plus H1 (silent widening), M1–M6, and the code
review's ERROR-masking, dead-branch, concurrency and rollback findings. The second commit
(`73e419c`) replaced blind adoption with proof-based claiming and received a second **FAIL**: the
durable retirement list was stored in a member-writable, member-readable config blob, so any
verified user could aim the sweep at arbitrary secrets (C-NEW-1); claiming ran as a silent
page-load/handshake side effect (H-NEW-1); an unrecorded access was widened onto a write grant
(H-NEW-2); plus M-NEW-1..5 and LOWs. The third commit (`fdf0ef8`) answered every item and received
**PASS with fixes required** (1 HIGH, 3 MEDIUM, 4 LOW) from security and **APPROVE** (1 MEDIUM,
1 LOW) from code review; the final commit closes those too:

- HIGH-1 the client blanket-sent `confirm_access: true`: now the confirmation names the resolved
  grant's scope and sends acceptance only for a read-and-edit grant; no move is offered when the
  grant cannot be named. Tests on the hook and the card.
- MEDIUM-1 the Sources-page reuse path (`POST /projects/{id}/sources {connection_id}` on a legacy
  row) left the row's own token live forever: it now retires the family and sweeps after commit
  (pre-existing on main, fixed here with the new helper). Test added.
- MEDIUM-2 an owed retirement was lost when the row was torn down: source disconnect and project
  teardown delete the derived family when the marker is present. Test added.
- MEDIUM-3 the sweep is bounded (`SWEEP_BATCH = 200`; the remainder is the next call's work).
  Test added with the batch monkeypatched to 1.
- LOW-1 stale hosted add-on state after a move is dropped with the marker (test); LOW-2 API.md now
  states that a proving live member may move a row they did not create; LOW-3 the client moves in
  batches of 50 (test); LOW-4 (showing whose account a source rides) is a W2 follow-up.
- Code review MEDIUM: every named source id is accounted for in the response even when its grant is
  revoked in the same instant (test); LOW: the confirmation pluralises for multi-project rows.
- Noted by the security reviewer for the record: `deps.live_membership` checks neither
  `Membership.status` nor `Team.deleted_at` (nothing sets the latter today); the adopt path is
  stricter than the central middleware. If soft-deleted teams are introduced, the middleware needs
  the filter first.

Standing invariants confirmed untouched by every round: the SOL confirmation gate, the never-raises
tool invariant, the tool-knowledge tenancy boundary, connector scope sets, and the redirect
allowlist (now pinned by test).
