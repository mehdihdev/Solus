# Cowork QA — HOME H4: Health and quota per connected account (SOLUSDEV-244)

Every linked account on Home's CONNECTED ACCOUNTS card now carries a health badge (HEALTHY /
TOKEN EXPIRED / DEGRADED) and, for a metered provider (Onshape), its quota position as an
estimate. The card flags "approaching the limit" BEFORE the wall and says what degrades; at the
wall it explains cache-only mode instead of showing an error; an expired token offers Re-authorize
in place. Nothing here calls the provider — the state is derived from what Solus already holds.
This plan assumes the running application and nothing else.

## Required setup

- API running WITH Redis (`SOLUS_REDIS_URL` set — without it no quota position is shown, only
  health) and the desktop app; one signed-in, email-verified user with a team and a project.
- An Onshape account connected on Home (CONNECTED ACCOUNTS → Onshape → Connect) whose provider
  account id you know (`account_connections.account_external_id`, call it `<acct>`), or an
  operator-seeded `account_connections` row (provider onshape, status connected, an
  `account_external_id`, no secret needed for these checks).
- Operator access to Redis for §2–§3. The ledger key is
  `solus:intq:onshape:acct:<acct>:<current UTC year>`; the latch key is
  `solus:intq:onshape:acct:<acct>:402`; the transition marker is `…:<acct>:seen`. The allowance is
  `SOLUS_ONSHAPE_ANNUAL_CALL_ALLOWANCE` (default 1 800); the degrade band starts at 70%.
- Data-collection consent ON for the user (Settings → Privacy) so §5's events are recorded.

Mark each step ☐ pass / ✗ fail. Note the screen and the exact text on failure.

## Flow 1 — A healthy account

1. Open **Home**. On the Onshape row: a quiet `HEALTHY` badge beside the account name; the usage
   line ("Used in …" / "Not used by any project yet" · scope) unchanged; below it "At least N of
   1,800 Onshape calls this year (estimate)" with a thin bar (N may be 0). No warning note. ☐
2. The GitHub / GitLab rows (connected or not) show a badge when connected and **no** quota line
   or bar — nothing is invented for an unmetered provider. ☐
3. Stop Redis (or unset `SOLUS_REDIS_URL` and restart the API) and reload Home. Expected: the
   badge stays, the quota line and bar disappear (position unknowable), no error. Restore. ☐

## Flow 2 — Approaching the limit (the acceptance: 80% is visibly flagged)

1. Set the ledger to 80%: `SET solus:intq:onshape:acct:<acct>:<year> 1440`. Delete `…:seen`.
   Reload Home (or navigate away and back). ☐
2. Expected on the Onshape row: badge `DEGRADED` in the warning colour; "At least 1,440 of 1,800
   Onshape calls this year (estimate)"; the bar about 80% full in the warning colour; a warning
   note: "Approaching Onshape's call limit. Automatic syncs and SOL's Onshape calls are paused; your
   own Sync now still reaches Onshape. At the limit Solus switches to cache-only reads and starts no
   new syncs." No Re-authorize button; Revoke still present. ☐
3. The words "remaining" and "left" appear nowhere on the row. ☐
4. Behaviour matches the note: in a project using this account, **Sync now** on the Sources page
   still runs (a user action); an automatic sweep or a SOL tool call against Onshape is refused
   with `quota_degraded` and does NOT schedule a full sync (operator: API logs). ☐

## Flow 3 — At the wall (the acceptance: cache-only, not an error)

1. Latch the 402: `SET solus:intq:onshape:acct:<acct>:402 1 EX 3600`. Reload Home. ☐
2. Expected: the badge stays `DEGRADED`; the note reads "Onshape's call limit is reached, so Solus
   is in cache-only mode: documents already synced stay readable, nothing new is fetched and no
   syncs run until the allowance resets. This is not an error and needs no sign-in." No
   Re-authorize; Revoke present; the row's status is still connected (no red error state). ☐
3. In a project using the account: the Sources page's document picker still lists cached documents;
   **Sync now** is refused (quota exhausted) without marking the account as needing sign-in. ☐
4. `DEL` the latch, reload: back to the approaching note (ledger still at 80%). ☐

## Flow 4 — Token expired (the acceptance: reconnect in place)

1. Make the grant fail: either revoke the token on the Onshape side and trigger a sync so the
   provider rejects it, or (operator) set the `account_connections` row to `status = error` with
   `last_error = {"code": "invalid_credentials", "message": "Onshape rejected the token"}`. Reload
   Home. ☐
2. Expected: badge `TOKEN EXPIRED`; a warning note "Onshape rejected the token. Re-authorize to
   reconnect."; a **Re-authorize** button on the row; the quota line still shown if the ledger is
   reachable. The token state outranks quota in the badge. ☐
3. Click **Re-authorize**. Expected: the account-mode connect wizard opens ("Choose access → Sign
   in"). Complete the sign-in. Expected: the SAME row returns to `HEALTHY` (no duplicate row), the
   note disappears. ☐
4. Variant: with the grant row itself healthy, make a bound source's last sync fail with
   `invalid_credentials` (operator: set `sources.last_error` on a source bound to the connection).
   Reload Home. Expected: the account row reads `TOKEN EXPIRED` with "The provider rejected this
   account's token. Re-authorize to reconnect." and the Re-authorize button. A source failing
   with a different code (e.g. `api_unreachable`) does NOT change the account's badge. ☐

## Flow 5 — Events (operator)

1. Reset: `DEL …:seen`, ledger at 80%, no latch, no rows in `data_events` with
   `event_type LIKE 'integration.quota%'`. Load Home three times. Expected: exactly ONE
   `integration.quota_degraded` row (payload: provider, connection_id, used 1440, allowance 1800,
   estimated true). ☐
2. Set the latch, load Home twice. Expected: exactly ONE `integration.quota_exhausted` row added. ☐
3. Turn consent OFF, `DEL …:seen`, load Home. Expected: no new row (events are consent-gated);
   the card still shows the state. ☐

## Flow 6 — Isolation

1. As a second user on the same team, open Home. Expected: they do not see the first user's
   Onshape account, its badge, or its quota position (grants are owner-only). ☐

## Cross-feature checks

- The H3 "How you engineer" card and the rest of Home are unaffected. ☐
- Revoke on a degraded or exhausted account still works and names the projects it disconnects. ☐
- The Sources page's per-source quota (if shown) and the Home account position agree (same
  ledger, same estimate). ☐
