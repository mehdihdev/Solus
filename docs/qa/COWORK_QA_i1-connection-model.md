# Cowork QA — I1, the connection model (account-scoped OAuth + shared integration cache)

**Ticket:** SOLUSDEV-241 · **Branch:** `SOLUSDEV-241-corpus-c1-scope-and-licensing`

You have the running application and this file, and nothing else. Mark each numbered step
**PASS** / **FAIL** and record what you actually saw. A step that could not be reached is
**BLOCKED**, not a pass.

---

## 0. What this feature is

Before this change every project ran its own OAuth and held its own token. Now a tool account
is linked **once, on Home** ("Connected accounts"), and each project chooses **what to track**
from that account on its Sources page. Two projects can track the same Onshape document on one
grant, and everything Solus already read for that account is served from a shared cache: the
picker's document list costs the provider nothing after the first time, a teammate's "Sync now"
costs nothing while nothing changed, and a second project tracking a document another project
already synced costs nothing at all.

Hold onto three rules while testing:

- A linked account belongs to the person who authorized it. Teammates never see it on their Home;
  they use it *through the project's source*.
- Revoking an account on Home disconnects it in **every** project that uses it. The confirmation
  must say which projects before you click.
- "Sync now" on an Onshape source that nobody changed is supposed to do nothing and cost nothing.
  That is the feature, not a bug. The hourly sweep and a provider webhook are what notice a change.

---

## 1. Setup

- [ ] API running (`make dev-api`) against a database migrated to head
      (`cd packages/api && uv run alembic upgrade head` — this feature adds
      `account_connections`, `sources.connection_id`, and nullable `oauth_states.source_id`).
- [ ] Desktop app running (`make dev-desktop`). OAuth needs it; there is no web path.
- [ ] **Two Solus accounts** on one collaborative team (Owner "A", Member "B"), with **two
      projects** in that team ("Rover", "Arm").
- [ ] **One Onshape account** A can sign into, with at least one document containing an assembly.
      A GitHub account is useful for §7 but optional.
- [ ] Note whether Redis is up (`make db-up`). Without it the cache is per API process — every
      flow below still works, but restart the API and the cache starts empty.
- [ ] Optional for §8: a way to watch the API log (`packages/api` terminal). Onshape calls log as
      `solus.connectors.onshape` lines; a cache hit makes none.

---

## 2. Flow — link an account on Home (A)

1. [ ] Sign in as A. On **Home**, find the **CONNECTED ACCOUNTS** card in the right column.
       **Expect:** one row per OAuth tool (GitHub, GitLab, Onshape), each "Not connected" with a
       **Connect** button. KiCad/Altium (file exports) and local tools do **not** appear here.
2. [ ] Click **Connect** on Onshape. **Expect:** the connect wizard opens with the rail
       **Choose access → Sign in** and nothing after it — no "Pick documents", no "Build graph".
3. [ ] Choose **Read only**, click **Connect Onshape**, complete the sign-in in the browser.
       **Expect:** the wizard ends on "Onshape connected" with **"Connected as <your Onshape
       login or id>"**. Click Done.
4. [ ] **Expect:** the Onshape row now shows the account (login or opaque id), "Not used by any
       project yet", and a **Revoke** button. No Connect button for Onshape.
5. [ ] Click **Connect** on Onshape again (there is none — this is the check). **Expect:** no way
       to link the same provider twice from this card while it is linked.

## 3. Flow — attach a project without signing in again (A)

6. [ ] Open **Rover → Sources**. Click the **Onshape** tile.
       **Expect:** the wizard rail reads **Pick documents → Build graph** only. Under the
       *Connect Onshape* button: **"Using your linked account · <login>"**.
7. [ ] Click **Connect Onshape**. **Expect:** **no browser opens**. The picker lists your
       Onshape documents. Pick one document with an assembly. Continue.
8. [ ] **Expect:** "Indexing…" then "Connected — N entities indexed" with N > 0. The Sources
       page lists an Onshape source, CONNECTED, with your account label.
9. [ ] Back on **Home**: the Onshape row now reads **"Used in Rover"**.

## 4. Flow — a second project shares the same document (A)

10. [ ] Open **Arm → Sources**, Onshape tile, **Connect Onshape** (linked-account wizard again,
        no browser), pick the **same document** as in step 7.
11. [ ] **Expect:** "Connected — N entities indexed" with the **same N** as step 8, and it
        finishes **noticeably faster** than step 8 (no export translation this time).
12. [ ] Home: Onshape row reads **"Used in Rover and Arm"**.
13. [ ] Open Rover → Graph and Arm → Graph. **Expect:** both projects show the document's
        entities; neither project's graph contains the other project's entities.

## 5. Flow — the teammate (B)

14. [ ] Sign in as B (member of the team). **Home → Connected accounts.** **Expect:** every row
        "Not connected" — A's Onshape account is **not listed** for B.
15. [ ] B opens **Rover → Sources**. **Expect:** the Onshape source connected by A is listed,
        CONNECTED, with A's account label. B can click **documents** and see the account's
        document list (served for B through the project's source).
16. [ ] B clicks **Sync now**. **Expect:** the sync completes quickly with the source still
        showing the same entity count and "Synced just now". (Nothing changed upstream, so
        nothing was re-fetched.)
17. [ ] B clicks the Onshape tile in "Connect a tool". **Expect:** the wizard shows the ordinary
        **Sign in** rail — B has no linked account, so B is offered B's own sign-in, never A's
        account. Close it.

## 6. Flow — change, remove, revoke (A)

18. [ ] In Onshape (browser), make a saved change to the tracked document (move a part). Wait for
        the next hourly sweep, or (if a webhook is registered for the source) a few seconds. Then
        on Rover → Sources click **Sync now**.
        **Expect:** the entity count reflects the change once the sweep/webhook has noticed it.
        Before that, "Sync now" is allowed to report unchanged — record which you observed and
        how long you waited.
19. [ ] Rover → Sources → Onshape source → **documents** → deselect the document → save.
        **Expect:** a sync runs; Rover's Onshape entity count drops toward 0; **Arm is
        untouched** (its count unchanged).
20. [ ] Rover → Sources → **Disconnect** the Onshape source (confirm).
        **Expect:** the source disappears from Rover. **Arm → Sources → Sync now** still
        succeeds — the account grant survived the other project's disconnect. Home: Onshape row
        reads "Used in Arm".
21. [ ] Home → **Revoke** on the Onshape row. **Expect:** a confirmation titled
        "Revoke Onshape (<login>)?" whose text names **Arm** ("…disconnects Onshape in Arm…")
        and says already-synced entities stay. Click **Cancel** first — nothing changes.
22. [ ] Revoke again and confirm. **Expect:** the row returns to "Not connected / Connect".
        Arm → Sources: the Onshape source shows **DISCONNECTED**; **Sync now** is refused
        ("not connected"). Arm's graph still holds the entities it had.

## 7. Flow — GitHub follows the same model (optional)

23. [ ] Home → Connect on **GitHub**, sign in. **Expect:** rail **Sign in** only (GitHub offers
        no access choice), done copy "Connected as <login>".
24. [ ] Rover → Sources → GitHub tile. **Expect:** rail **Pick repositories → Build graph**,
        "Using your linked account · <login>", no browser; pick a repository; it indexes.

## 8. Cost checks (needs the API log)

25. [ ] Rover → Sources → Onshape → **documents**. Close. Open **documents** again.
        **Expect:** the second open makes **no** Onshape request in the API log.
26. [ ] Repeat step 16 as A or B twice. **Expect:** neither "Sync now" makes an Onshape request
        (the log shows the sync skipped as unchanged).
27. [ ] Restart the API without Redis and open **documents** once. **Expect:** exactly one walk of
        `/api/v6/documents` in the log (the cache was empty), then none on the next open.

## 9. Edge cases and failure paths

28. [ ] Home → Connect Onshape → close the wizard while the browser is open.
        **Expect:** the row stays "Not connected"; no account was linked; no error persists after
        reopening the wizard.
29. [ ] Cancel the Onshape sign-in in the browser. **Expect:** the wizard shows an honest error
        with **Retry**.
30. [ ] With the API stopped, open Home. **Expect:** the Connected accounts card is **absent**
        (not a broken card), and the existing "can't reach its API" message shows.
31. [ ] As B, using any HTTP tool with B's token, call `DELETE /api/v1/users/me/connections/<A's
        connection id>` and `GET /api/v1/users/me/connections/<id>/documents`.
        **Expect:** **404** for both — not 403, not the documents.
32. [ ] As B, `POST /api/v1/projects/<Rover>/sources` with
        `{"type":"onshape","name":"cad","connection_id":"<A's connection id>"}`.
        **Expect:** **404** — a teammate cannot bind someone else's grant.
33. [ ] As A, `POST /api/v1/projects/<Rover>/sources/<onshape source>/documents` with
        `{"id":"../etc"}`. **Expect:** **400 `config_invalid`**.
34. [ ] As A, the same route with a document id already tracked. **Expect:** **200** with
        `"status":"unchanged"` and no new sync in the source's history.

## 10. Cross-feature interactions

35. [ ] SOL: in Rover (while Onshape is attached), ask SOL about a part in the tracked document.
        **Expect:** the tool answers as before; ask about a document you did **not** track and
        expect the same refusal as before this change.
36. [ ] FeatureScript add-on (if you have it): enable it on the attached Onshape source in Rover,
        then attach Arm to the same account. **Expect:** Arm's source shows the add-on state
        correctly on its own row; revoking the account on Home removes the add-on grant too
        (the Sources page shows it as not connected afterwards).
37. [ ] Delete account A (Settings → delete) after linking an account. **Expect:** the deletion
        succeeds; a later sign-in as a fresh user with the same Onshape account can link it
        again (the old grant was swept, not orphaned).
