# Cowork QA — HOME H2: Connections move to account scope (SOLUSDEV-242)

OAuth binds the WHOLE ACCOUNT once, on Home. Picking documents happens later in a project's
Sources page against that account. A project-scoped connection made before account-level
connections is listed on Home as "sign in once to move it": ONE sign-in proves the account, after
which the row offers **Move to your account** — an explicit confirmation naming the projects and
the grant (no second OAuth per project, never a silent move). Nothing is copied, nothing is
widened, and the project keeps syncing on its own token until the move. Every tool the
registry knows is listed — file-export and local tools say they connect per project. This plan
assumes the running application and nothing else.

## Required setup

- API and desktop running; one signed-in, email-verified user ("A"). A second user ("B") on the
  same team for §5.
- Onshape OAuth configured on the API (`SOLUS_ONSHAPE_CLIENT_ID/SECRET`) and an Onshape account
  A can sign in to with at least two documents. GitHub OAuth configured is a bonus for §6.
- Team A with projects **Rover** and **Arm**.
- **A legacy, project-scoped grant.** If this deployment has a project source connected BEFORE
  account-level connections (Sources page shows it connected, but Home lists no account for that
  provider), use it in Rover. Otherwise seed one: an operator inserts a `sources` row of type
  onshape for Rover with `secret_ref = source/<id>/onshape`, `connection_id NULL`,
  `created_by = A`, an `account_login`, and the encrypted token in the secret store (the QA
  harness script used by the implementation session does exactly this).

Mark each step ☐ pass / ✗ fail. Note the screen and the exact text on failure.

## Flow 1 — A legacy project grant is listed, honestly unmoved

1. Sign in as A. On **Rover → Sources**, confirm the legacy Onshape source is listed and connected. ☐
2. Open **Home**. Expected under CONNECTED ACCOUNTS: an **Onshape** row naming the account
   (e.g. "Onshape · ada-legacy"), the line "Connected in a project, not yet on your account", a
   warning note "Connected in Rover before account-level connections. Sign in once to move it to
   your account — Rover keeps syncing until then.", and a **Sign in to move** button. No Revoke on
   that row, no separate Connect for Onshape. ☐
3. Reload Home. Expected: the same single row (nothing moved, no duplicates). ☐
4. **Rover → Sources → Sync now**. Expected: the sync runs on the project's own token as before. ☐
5. The card also lists **KiCad** and **Altium** ("Committed export · attached per project") and any
   local companion tool ("Connects on this computer · attached per project"). With Rover open each
   has an **Attach in Rover** button that lands on Rover's Sources page; with no project open the
   row reads "open a project to attach it from its Sources page" and has no button. ☐

## Flow 2 — One sign-in moves it; a second project needs no OAuth

6. Home → **Sign in to move** on the Onshape row. Expected: the connect wizard opens in account mode,
   rail **Choose access → Sign in** only (no document picking). Choose **Read only**, complete the
   sign-in in the browser **with the same Onshape account the legacy source used**. ☐
7. Expected: the wizard ends "Connected as <login>". Home now shows TWO Onshape rows: the linked
   account ("Not used by any project yet · Read only", Revoke) AND the legacy row, whose note now
   reads "…Your linked account matches — move it so Rover uses your account grant." with a
   **Move to your account** button. Nothing has moved yet: Rover → Sources still shows the old
   source unchanged. ☐
   7b. Click **Move to your account**. Expected: a dialog "Move Onshape to your account?" stating
   "Rover will use your linked Onshape account (read only access). The project's own Onshape
   token — and any add-on grant on it — is removed; syncing continues on your account." Cancel:
   nothing changes. Confirm: the legacy row disappears and the linked row reads "Used in Rover ·
   Read only". ☐
8. Rover → Sources: the source is still connected; **Sync now** works (now on the account grant).
   Rover's recent activity shows "moved the onshape connection to account scope". ☐
9. Open **Arm → Sources**, click the **Onshape** tile. Expected: rail **Pick documents → Build graph**
   and "Using your linked account · <login>". Click Connect Onshape: **no browser opens**; pick
   **two** documents; build. Home: "Used in Rover and Arm". ☐
10. Sign in with a DIFFERENT Onshape account than the legacy source used (optional). Expected: a new
    linked row for that account, and the legacy row stays listed and unmoved — a grant moves only to
    the account that proves it. ☐

## Flow 3 — Already connected on Home: the move needs no sign-in

11. With an Onshape account connected on Home (Flow 4 step 13), have an operator seed a legacy
    project-scoped source for the SAME account in another project (or connect one through an old
    wizard build). Open Home. Expected: a legacy row with **Move to your account** (no wizard, no
    browser); nothing moves until you confirm the dialog. Reload Home twice: still unmoved. ☐
    11b. If the linked account is **Read and edit** and the legacy source never recorded an access
    mode, the dialog says "(read and edit access)" — confirming is the user's explicit acceptance
    of the wider grant for that project. With a **Read only** linked account the dialog says
    "(read only access)". ☐
    11c. With more than one project on the legacy row, the dialog names them ("Rover and Arm will
    use…") and reads "Each project's own Onshape token…". ☐
    11d. Rover → Sources → Onshape tile with a legacy source present and a linked account: the wizard's
    "Using your linked account" connect reuses the legacy source; afterwards the project rides the
    account grant and the legacy row is gone from Home. ☐
12. A legacy source whose recorded access mode differs from the account grant (e.g. the project
    recorded read-only, the account is read and edit) is **not** moved: it stays listed as legacy
    and keeps its own token; nothing on Home widens or narrows it. ☐

## Flow 4 — Connect an account on Home, then pick documents in Workspace (fresh account)

13. As a user with no Onshape connection: Home → **Connect** on Onshape → choose **Read only** →
    sign in. Expected: the row shows "<login> · Not used by any project yet · Read only" with
    Revoke and no Re-authorize. ☐
14. Rover → Sources → Onshape: no browser opens; pick two documents; build. Home: "Used in Rover ·
    Read only". ☐
15. Choose **Read and edit** on a fresh Connect for a different account (or after Revoke).
    Expected: the row reads "Read and edit". Nothing on Home ever changes a scope without a new
    sign-in. ☐

## Flow 5 — Ownership and the teammate

16. Sign in as B (member of Team A). Home: B sees **no** Onshape account (A's grant is A's). ☐
17. B → Rover → Sources: the Onshape source connected by A is listed and B can **Sync now** (the
    shared grant works through the source). ☐
18. A legacy source whose row A created but whose token B authorized (old "switch account"): A's
    sign-in with A's account does NOT move it; B's sign-in with B's account does. ☐
19. Remove B from Team A (or make B a viewer). Expected: B's Home no longer lists Team A's legacy
    grants, and B's sign-in moves nothing in Team A. ☐

## Flow 6 — Errors, revoke, and the allowlist

19. Cancel an OAuth sign-in in the browser. Expected: the wizard shows the cancellation; Home shows
    no half-made account (a pending handshake never lists). ☐
20. On a row whose last sign-in failed (status error): the note shows the provider's message plus
    "Re-authorize to reconnect." and Re-authorize is offered. Such a row never proves an account
    (the legacy row keeps offering Sign in to move). ☐
    20b. Revoke the linked account while a legacy row shows Move to your account, then click Move.
    Expected: the move fails honestly (dialog error) and Rover keeps its own working token. ☐
21. **Revoke** the Onshape row. Expected: the confirmation names Rover and Arm; after confirming, both
    projects' Onshape sources show disconnected and the row is gone. ☐
22. Desktop loopback: the OAuth redirect to `http://127.0.0.1:<port>/...` and `http://localhost:<port>/...`
    both complete; a redirect to any other host is refused (400 `invalid_redirect_uri`). ☐

## Operator notes

- If the secret store is unreachable, disconnecting a source or deleting a project that still owes
  a retired token family fails loudly (HTTP 500) rather than leaking the family; retry once the
  store is back. Nothing is lost: the marker stays on the row.

## Cross-feature checks

- Home's project cards and the Team feed show `connection.adopted` / `connection.revoked` events. ☐
- A revoked or deleted account never leaves a row on Home or a working source anywhere. ☐
- The SOL agent's write gate for a bound source follows the CONNECTION's recorded grant: a
  `read` grant never lets SOL propose an edit to Onshape. ☐
