# Cowork QA — Onshape FeatureScript (hosted MCP add-on)

**Ticket:** SOLUSDEV-168 · **Branch:** `SOLUSDEV-168-featurescript-mcp`

You have the running application and this file, and nothing else. Everything you need is
here. Mark each numbered step **PASS** / **FAIL** and record what you actually saw — a step
that could not be reached is **BLOCKED**, not a pass.

---

## 0. What this feature is

Onshape Labs hosts a FeatureScript MCP server. This feature lets a Solus user connect
**their own Onshape account's** server so SOL can read and author FeatureScript **as them**,
using their own sign-in and their own Onshape API allowance. Solus never uses a developer
key.

Three things to hold onto while testing, because most of the interesting failures are here:

- FeatureScript is **not a separate tile**. It appears under the already-connected Onshape
  source on the Sources page.
- Subscribing to the Onshape Labs app **cannot** be done by Solus. The app can only send you
  to the Onshape App Store and then re-check. Onshape's own docs say a redirect back does not
  prove a purchase, so "check again" asks the server, never the browser.
- Disconnecting Solus **must not** unsubscribe you — but it **must** revoke Solus's ability
  to act as you.

---

## 1. Setup

Required before any flow below:

- [ ] The API is running (`make dev-api`) against a database migrated to head
      (`cd packages/api && uv run alembic upgrade head` — this feature adds
      `oauth_states.code_verifier`).
- [ ] Redis is up (`make db-up`). **Optional**: without it the quota meter fails open by
      design, and §6 will not be exercisable.
- [ ] The desktop app is running (`make dev-desktop`). The OAuth legs need it — there is no
      web path.
- [ ] A Solus account, signed in, with a team and a project.
- [ ] **An Onshape account you can sign into in a browser.** Two accounts are ideal: one
      subscribed to the Onshape Labs FeatureScript app, one NOT (see §4).
- [ ] An Onshape document with at least one Feature Studio you are willing to have modified.

If `SOLUS_SECRETS_KEY` is unset the API logs a warning and uses an in-memory secret store —
acceptable for QA, but grants are lost on restart. Note it if you see it.

---

## 2. Flow — connect Onshape and see the disclosure

1. [ ] Open the project → **Sources**. Click the **Onshape** tile.
       **Expect:** the connect wizard opens on step 1.
2. [ ] Read the step. **Expect:** somewhere before you sign in, a notice stating that
       connecting Onshape **also enables FeatureScript authoring** through the Onshape Labs
       app, that it runs as you using your own sign-in, that it consumes your account's API
       allocation, and that **disconnecting Solus leaves the app enabled**.
       **This copy must appear before the browser opens, not after.**
3. [ ] Choose **Read and edit** when offered the access choice, then complete the sign-in in
       your browser.
       **Expect:** the wizard proceeds to pick documents, syncs, and finishes on
       "Connected — N entities indexed".
4. [ ] **Expect:** the wizard did NOT ask you anything about FeatureScript, and did not stall
       or error because of it. Onshape connect succeeding is independent of FeatureScript.

**Edge cases**
5. [ ] Close the wizard mid-flow (X or backdrop). **Expect:** the attempt cancels, and the
       source is NOT deleted.
6. [ ] Stop the API, then click the Onshape tile. **Expect:** an honest error, no flow start.

---

## 3. Flow — enable FeatureScript on the connected source

7. [ ] On **Sources**, look at the connected Onshape row.
       **Expect:** beneath it, an add-on block with the disclosure and an
       **Enable FeatureScript** button. **Expect: NO separate FeatureScript tile anywhere.**
8. [ ] Click **Enable FeatureScript**.
       **Expect:** the button reads "Waiting for your browser…" and your system browser opens
       an `fs-mcp.labs.onshape.app` authorize page (it will bounce through Onshape sign-in).
9. [ ] Look at the authorize URL before approving. **Expect:** it requests
       `OAuth2Read OAuth2Write` and **NOTHING ELSE** — in particular **not** `OAuth2Delete`
       and **not** `OAuth2ReadPII`. **If either appears, this is a FAIL, stop, and report it.**
10. [ ] Approve.
        **Expect (subscribed account):** the row updates to **FEATURESCRIPT ON**.
        **Expect (unsubscribed account):** see §4.
11. [ ] **Expect:** there is no "disable FeatureScript" button. Removal happens in the Onshape
        App Store, and the disclosure says so.
12. [ ] Navigate away (Graph, then back to Sources). **Expect:** the state persists — it is
        stored on the source, not in the screen.

**Edge cases**
13. [ ] Start an Onshape connect in the wizard and, while it is waiting for the browser, click
        **Enable FeatureScript** on another source. **Expect:** "A sign-in is already in
        progress." and no second browser window. Nothing hangs.
14. [ ] Click **Enable FeatureScript** and then close the browser tab without approving.
        **Expect:** it settles within ~5 minutes with a cancelled/failed message — it must not
        park forever.

---

## 4. Flow — the account is NOT subscribed

Use an Onshape account without the Onshape Labs FeatureScript app.

15. [ ] Enable FeatureScript as in §3 and approve the sign-in.
        **Expect:** the row shows a **subscription needed** state, NOT "on" and NOT a generic
        error.
16. [ ] Read the message. **Expect:** it names **both** remedies — an Onshape subscription to
        the app, **and** that on a company account an administrator may have to permit it
        first. **Expect:** it is specific and actionable, never "something went wrong".
17. [ ] Click **Open Onshape App Store**. **Expect:** your system browser opens the Onshape
        App Store page for the Onshape Labs app.
18. [ ] Without subscribing, come back and click **I've subscribed — check again**.
        **Expect:** it re-checks and stays in the subscription state. It must NOT flip to "on"
        just because you clicked.
19. [ ] Now actually subscribe in the browser, return, and click **check again**.
        **Expect:** the row flips to **FEATURESCRIPT ON**.

---

## 5. Flow — SOL uses FeatureScript, and the approval card

20. [ ] Open SOL in a project with FeatureScript ON. Make sure the action mode is **Do**
        (in **Guide** mode every mutating tool is refused before the gate — that is existing
        behaviour, but note which mode you are in).
21. [ ] Ask SOL to READ something, e.g. "list the Feature Studios in my Onshape document"
        or "show me the FeatureScript in <studio>".
        **Expect:** it answers without asking for approval. Reads are not gated.
22. [ ] Ask SOL to CHANGE FeatureScript, e.g. "add a comment at the top of the FeatureScript
        in <studio>".
        **Expect:** the turn ENDS with an approval card rather than applying the change.
23. [ ] Read the card carefully. **Expect all of:**
        - a sentence in Solus's own words naming the concrete effect — for a whole-studio
          overwrite something like *"Replace the whole contents of a Feature Studio in your
          Onshape document"*. **It must NOT be a bare tool name.**
        - a **diff**: a checksum row, plus one row per changed hunk showing before → after.
        - the rows are readable — **not** one long glued-together line of code.
24. [ ] Click **Reject**. **Expect:** the card reports you rejected it, and **nothing changed
        in Onshape** (verify in Onshape itself).
25. [ ] Ask again, and this time click **Approve**. **Expect:** the change appears in Onshape,
        and it is exactly what the card showed.

**The important failure paths**
26. [ ] Ask SOL to change a Feature Studio so a card appears. **Before approving**, edit that
        same Feature Studio in Onshape yourself and save. Now click **Approve**.
        **Expect:** it REFUSES with something like "What this action would do has changed
        since it was shown to you. Nothing was applied." **Expect: the card stays visible,
        says the approval cannot be retried, and both buttons are disabled.**
        **Expect: your Onshape edit is intact.** *(A silently-vanishing card here is the
        single worst outcome this feature can produce — fail it loudly.)*
27. [ ] Get a card, wait **over 30 minutes**, then approve.
        **Expect:** refused as expired, card stays with a terminal message, nothing applied.
28. [ ] Get a card and approve it twice quickly (double-click).
        **Expect:** it runs at most ONCE.
29. [ ] Get a card, then stop the API, then approve.
        **Expect:** a transport error, the card STAYS, and **Approve is still enabled** — the
        action really is still parked. (Contrast with 26/27, where it is terminal.)

---

## 6. Flow — the API allowance (needs Redis)

30. [ ] Ask SOL to make several FeatureScript calls in a row.
        **Expect:** they work. FeatureScript calls spend **your Onshape account's** allowance
        (about 2,500/year on a free/standard plan) — not Solus credits.
31. [ ] Ask SOL "what is my FeatureScript API usage?".
        **Expect:** it can answer via the read-only usage tool.

---

## 7. Flow — disconnect and revocation

32. [ ] With FeatureScript ON, disconnect the Onshape source (confirm the modal).
        **Expect:** the source disconnects.
33. [ ] Check your Onshape account's authorized apps / App Store.
        **Expect: the Onshape Labs FeatureScript app is STILL SUBSCRIBED.** Solus must not
        have unsubscribed you. **If it did, this is a FAIL.**
34. [ ] Reconnect Onshape.
        **Expect:** the add-on block is back at **Enable FeatureScript** — the old grant was
        revoked, so it must ask again rather than silently resuming.
35. [ ] In a project where FeatureScript was never enabled, ask SOL to change FeatureScript.
        **Expect:** it says FeatureScript is not enabled and tells you where to enable it —
        never a generic "unavailable, try again".

---

## 8. Cross-feature interactions

36. [ ] **Teammate.** Have a second team member open the same project's Sources page.
        **Expect:** they see the same Onshape source and the same FeatureScript state — it is
        stored on the source, not per-person.
37. [ ] **Tenant isolation.** From a DIFFERENT team's account, try to reach the add-on for
        this source (if you can craft the URL).
        **Expect:** 404 — never 403, and never any data.
38. [ ] **Other connectors are unaffected.** Connect GitHub. **Expect:** its tile and wizard
        behave exactly as before and show NO FeatureScript block.
39. [ ] **Other SOL tools still work.** Ask SOL a graph question unrelated to Onshape.
        **Expect:** normal behaviour; nothing about this feature slowed or broke the turn.
40. [ ] **Offline.** Kill the API and open Sources.
        **Expect:** an honest offline message. No crash, no fabricated FeatureScript state.

---

## 9. Things that must NEVER be true

Report any of these as a **CRITICAL** failure:

- [ ] A FeatureScript change applied **without** an approval card.
- [ ] An approval card that vanished leaving you unsure whether the change ran.
- [ ] An approval card showing only a tool name, or an unreadable single-line blob of code.
- [ ] An authorize URL requesting `OAuth2Delete` or `OAuth2ReadPII`.
- [ ] Disconnecting Solus unsubscribing you from the Onshape Labs app.
- [ ] Any screen, log line or API response containing an access token, refresh token or
      client secret.
- [ ] A separate FeatureScript tile in the connect catalog.
- [ ] Another team's data reachable through any hosted add-on route.

---

## 10. Result

| Section | Pass | Fail | Blocked | Notes |
| ------- | ---- | ---- | ------- | ----- |
| 2 Connect + disclosure | | | | |
| 3 Enable | | | | |
| 4 Not subscribed | | | | |
| 5 SOL + approval card | | | | |
| 6 API allowance | | | | |
| 7 Disconnect | | | | |
| 8 Cross-feature | | | | |
| 9 Never-true list | | | | |
