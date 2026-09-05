# Cowork QA — HOME H2: Connections move to account scope (SOLUSDEV-242)

OAuth binds the WHOLE ACCOUNT once, on Home. Picking documents happens later in a project's
Sources page against that account. A project-scoped connection made before account-level
connections is moved to account scope without a sign-in; where Solus cannot tell what the old
grant allows, Home says so plainly and offers Re-authorize — never forcing it, never widening a
scope. This plan assumes the running application and nothing else.

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

## Flow 1 — A legacy project grant appears on Home as the account it is

1. Sign in as A. Before opening Home, confirm on **Rover → Sources** that the legacy Onshape source
   is listed and connected. ☐
2. Open **Home**. Expected under CONNECTED ACCOUNTS: an **Onshape** row naming the account, reading
   "Used in Rover · Access level not recorded · moved from a project", a warning note "Linked from a
   project before account-level connections; what Solus may do with it was never recorded.
   Re-authorize to confirm — existing syncs keep working until then.", and two buttons:
   **Re-authorize** and **Revoke**. No **Connect** for Onshape. ☐
3. Reload Home. Expected: the same single row (adoption is idempotent; no duplicates). ☐
4. **Rover → Sources**. Expected: the Onshape source is still connected with the same account label.
   Click **Sync now**. Expected: the sync runs on the migrated token (it succeeds, or fails only for
   reasons unrelated to credentials, e.g. an invalid seeded token — say which). ☐
5. Recent activity on Rover's Home card (or the Team feed) includes "moved the onshape connection to
   account scope". ☐

## Flow 2 — A second project uses the migrated account with no OAuth prompt

6. Open **Arm → Sources**, click the **Onshape** tile. Expected: the wizard rail reads
   **Pick documents → Build graph** and, under the button, "Using your linked account · <login>". ☐
7. Click **Connect Onshape**. Expected: **no browser window opens**. The picker lists the account's
   documents. Pick **two** documents. Continue to the build. ☐
8. Home: the Onshape row now reads "Used in Rover and Arm". ☐

## Flow 3 — Re-authorize confirms the scope without dropping the old grant

9. Home → **Re-authorize** on the Onshape row. Expected: the connect wizard opens in account mode
   with the rail **Choose access → Sign in** only (no document picking). ☐
10. Close the wizard without signing in. Expected: the row is unchanged; the note still shows;
    Rover and Arm still sync. ☐
11. Re-authorize again, choose **Read only**, complete the sign-in in the browser. Expected: the
    wizard ends "Connected as <login>". Home's row now reads "Used in Rover and Arm · Read only ·
    moved from a project", the warning note and the Re-authorize button are gone, and there is
    still exactly ONE Onshape row. ☐
12. Rover and Arm → Sources: both sources still connected; Sync now works on the new token. ☐

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
18. If B has a legacy project-scoped grant of their own in Team A: it appears on B's Home, not A's,
    after B opens Home. ☐

## Flow 6 — Errors, revoke, and the allowlist

19. Cancel an OAuth sign-in in the browser. Expected: the wizard shows the cancellation; Home shows
    no half-made account (a pending handshake never lists). ☐
20. On a row whose last sign-in failed (status error): the note shows the provider's message plus
    "Re-authorize to reconnect." and Re-authorize is offered. ☐
21. **Revoke** the Onshape row. Expected: the confirmation names Rover and Arm; after confirming, both
    projects' Onshape sources show disconnected and the row is gone. ☐
22. Desktop loopback: the OAuth redirect to `http://127.0.0.1:<port>/...` and `http://localhost:<port>/...`
    both complete; a redirect to any other host is refused (400 `invalid_redirect_uri`). ☐

## Cross-feature checks

- Home's project cards and the Team feed show `connection.adopted` / `connection.revoked` events. ☐
- A revoked or deleted account never leaves a row on Home or a working source anywhere. ☐
- The SOL agent's write gate for a bound source follows the CONNECTION's recorded grant: a
  `read` grant never lets SOL propose an edit to Onshape. ☐
