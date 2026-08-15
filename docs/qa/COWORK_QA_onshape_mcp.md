# Cowork QA — Onshape MCP server, SOL chat, and the confirmation gate

Test plan for SOLUSDEV-96 (Onshape A1–A5 + ONS-UI-01) and CAD-00b. Written to be self-sufficient:
you need the running application and this file, nothing else.

Mark each step **PASS** / **FAIL**. A FAIL should record what you saw, not what you expected.

---

## 0. Setup

### 0.1 Services

- [ ] Postgres running with migrations applied (`make migrate`); `alembic heads` shows exactly one.
- [ ] API running (`make api` or equivalent) and reachable at the desktop app's configured base URL.
- [ ] Redis + an ARQ worker running (sync jobs are background jobs).
- [ ] Desktop app running (`pnpm --filter @solus/desktop dev`) or a packaged build.

### 0.2 Accounts and data

- [ ] A Solus account, signed in, onboarded, on a team.
- [ ] A project created and selected (the SOL screen needs one; §1.1 covers the case where none is).
- [ ] **An Onshape account you are willing to let Solus edit.** Grants are account-wide — Onshape
      has no per-document scope — so use a personal/scratch account, not a production one.
- [ ] In that Onshape account: a document containing **a part studio with at least one extrude** and
      **a Variable Studio with at least two variables** (e.g. `width = 120 mm`, `count = 4`). Two
      variables matter — one of the tests is that writing one does not delete the other.
- [ ] Onshape OAuth configured server-side (`docs/integrations/onshape-setup.md`).

### 0.3 Baseline to record before you start

Open the Variable Studio in Onshape and write down every variable's name and expression. You will
compare against this later.

---

## 1. SOL chat surface

### 1.1 No project selected

1. Sign in and go to SOL **without** opening a project (from Home, do not enter a project).
   - [ ] The header reads **`NO PROJECT`**.
   - [ ] The body says **"Select a project"**.
   - [ ] There is **no message box** — SOL does not offer to answer something it cannot.

### 1.2 With a project

1. Open a project, go to SOL.
   - [ ] Header reads **`READY`**.
   - [ ] A message box labelled "Ask SOL about this robot…" is present.
   - [ ] **Send is disabled** while the box is empty.
2. Type anything and send.
   - [ ] Your message appears under **`YOU`**.
   - [ ] **"SOL is thinking…"** appears while streaming.
   - [ ] A reply appears under **`SOL`**, streaming in rather than arriving all at once.
3. **Nothing is scripted.** Confirm you never see any of: `247 NODES`, `GROUNDED IN`, `STM32H743`,
   `Apply & flash`, `τ_FL_knee`, or the word `strider`.
   - [ ] None of the above appears.
4. Stop the API, then send a message.
   - [ ] An **error message is shown in the conversation**. It does not hang, and it does not
         silently do nothing.
   - [ ] Restart the API; the next message works.

### 1.3 SOL mode (ADR-016)

1. Toggle **Guide** / **Expert** in the SOL header.
   - [ ] Guide shows "explains and teaches"; Expert shows "terse, direct".
   - [ ] The choice survives navigating away and back.
   - [ ] The choice survives an app restart.

---

## 2. Connecting Onshape — the grant choice

### 2.1 The picker appears

1. Go to **Sources** (or onboarding Connect) and click the **Onshape** tile.
   - [ ] Before any browser window opens, the tile shows **"How much access should Solus have?"**
         with two options.
   - [ ] Each option shows a **description**, not just a label — e.g. "Solus can also change your
         models. Every edit is shown to you for approval before it is applied."
   - [ ] **"Read only" is preselected.** (The default must never be the wider grant.)

### 2.2 Read-only path

1. Leave **Read only** selected and click **Continue**.
   - [ ] A browser window opens on Onshape's authorization page.
   - [ ] The consent screen requests **read** permission only — no edit/write permission.
2. Approve, pick a document, let the sync finish.
   - [ ] The tile reaches **Connected — N entities indexed** with a real, non-zero N.

### 2.3 Cancelling

1. Disconnect the source. Click Onshape again, and at the grant picker **navigate away / close
   without choosing**.
   - [ ] No Onshape authorization window opens.
   - [ ] The tile reports the connect was cancelled. It does **not** silently proceed with either
         grant.

### 2.4 Read+write path

1. Disconnect, reconnect, and this time choose **"Read and edit"** → Continue.
   - [ ] Onshape's consent screen now requests **write** permission as well.
   - [ ] It does **not** request permission to delete documents or workspaces.
2. Approve, pick the document containing your Variable Studio, let the sync finish.
   - [ ] Connected, with entities indexed.

---

## 3. Reading through SOL

With the read+write source connected, ask SOL each of these and confirm the answer matches what you
see in Onshape:

- [ ] "What Onshape documents can you see?" → your real document names.
- [ ] "What tabs are in \<your document\>?" → the real tab names and types.
- [ ] "What's in the feature tree of \<your part studio\>?" → the real, ordered feature list.
- [ ] "What variables are defined in \<your document\>?" → the real names and expressions, matching
      your §0.3 baseline.
- [ ] "What's the mass of \<your part\>?" → a plausible value matching Onshape's own mass properties
      panel.

**Isolation check:**

- [ ] Create a **second project** with **no** Onshape source. Ask SOL there to list Onshape
      documents. It must say no Onshape source is connected — it must **not** answer using the first
      project's connection.

---

## 4. The confirmation gate — the core of this feature

### 4.1 A write parks and shows its diff

1. In your read+write project, ask SOL: **"Change the width variable to 150 mm."**
   - [ ] SOL does **not** apply it immediately.
   - [ ] A card appears **in the conversation** reading **"SOL wants to change your design"**.
   - [ ] It names the tool (e.g. `onshape.set_variable`).
   - [ ] It shows a **diff**: the variable name, its **current** expression, an arrow, and the
         **new** expression. Approving a bare action name is not acceptable — the before value must
         be there and must match what is actually in Onshape right now.
   - [ ] There are **Approve** and **Reject** buttons.
2. **Before deciding**, check Onshape.
   - [ ] The variable is **unchanged**. Nothing happened just because it was proposed.

### 4.2 Reject

1. Click **Reject**.
   - [ ] The card reads **"Rejected. Nothing was changed."**
   - [ ] In Onshape, the variable is still at its original value.
   - [ ] **Every other variable is untouched** (compare to §0.3).

### 4.3 Approve

1. Ask again, and this time click **Approve**.
   - [ ] The card reads **"Approved and applied."**
   - [ ] In Onshape, the variable now reads the new value.
   - [ ] **Every other variable still has its original expression.** This is the data-loss test —
         Onshape's endpoint replaces the whole table, so a bug here silently deletes the others.
   - [ ] Any geometry driven by that variable has updated.

### 4.4 Double-submit and failure

1. Trigger another change. Click **Approve** and immediately try to click **Reject**.
   - [ ] The second button is **disabled** while the decision is in flight. Only one decision lands.
2. Trigger another change, stop the API, then click **Approve**.
   - [ ] The card says the decision **did not go through and the action is still waiting** — it must
         **not** show "Approved and applied."
   - [ ] Restart the API. The action can still be approved, and it applies correctly.

### 4.5 Expiry

1. Trigger a change and leave it undecided for **over 30 minutes**.
   - [ ] Approving it now reports that it has expired.
   - [ ] Onshape is unchanged.

### 4.6 Approval is not transferable

1. Trigger a change and leave it pending.
2. Sign in as a **different user on a different team** and try to approve that confirmation
   (via the API, using the id from the first user's stream).
   - [ ] Refused. The other team's user cannot approve, and cannot even see it.

---

## 5. The read-only grant actually refuses writes

This is the most important security check in this file.

1. Disconnect Onshape. Reconnect choosing **Read only**.
2. Ask SOL: **"Change the width variable to 200 mm."**
   - [ ] SOL reports the source is connected **read-only** and tells you to reconnect choosing
         "Read and edit".
   - [ ] **No confirmation card appears.**
   - [ ] In Onshape, nothing changed.
3. Reads still work:
   - [ ] "What variables are defined?" still answers correctly.

---

## 6. Feature edits and geometry selectors

Reconnect with **Read and edit** before this section.

### 6.1 Editing a feature parameter

1. Ask: **"Change the depth of \<your extrude\> to 30 mm."**
   - [ ] The card's label names **the feature and the parameter** (e.g. `Extrude 1 · depth`).
   - [ ] Before shows the **actual current depth**; after shows `30 mm`.
2. Approve.
   - [ ] Onshape shows the new depth.
   - [ ] **Every other setting on that feature is unchanged** — direction, end condition, the
         faces it was built on. An edit is surgical, not a rewrite.

### 6.2 Geometry by description

1. Ask: **"Which is the largest flat face on \<your part\>?"**
   - [ ] SOL describes it (type, area, position).
   - [ ] The description **contains no Onshape id** — no opaque alphanumeric handle like `JBIG`.
2. Ask something deliberately ambiguous: **"the flat face"** on a part with several.
   - [ ] SOL reports the description matches **several** entities and asks you to narrow it. It does
         **not** silently pick one.
3. Ask: **"Change \<your extrude\> to start from the largest flat face instead."**
   - [ ] The card's after value **describes the face** (type, size, position) rather than showing an
         id.
   - [ ] Approve; Onshape shows the extrude rebuilt on that face.

### 6.3 Refusals are honest

- [ ] Ask SOL to add a feature type your document does not have. It reports the part studio does not
      accept it and points at the feature list — rather than failing with an opaque error.
- [ ] Ask SOL to set a variable named `1bad` (starting with a digit). It reports the naming rule.

---

## 7. Cross-feature interactions

- [ ] After an approved edit, run a **sync** on the Onshape source. It completes, and the graph
      reflects the new geometry (check entity count / mass in the project view).
- [ ] Disconnect the Onshape source, then ask SOL an Onshape question. It says no source is
      connected. It does **not** answer from stale data as if live.
- [ ] Reconnect. Confirm you are asked for the grant again — a reconnect is a fresh consent, not an
      inherited one.
- [ ] Delete the project entirely. Confirm no orphaned confirmations remain approvable.
- [ ] Sign out and back in mid-conversation. Any pending confirmation is still there and still
      decidable by you.

---

## 8. Empty and edge states

- [ ] Connect an Onshape account with **no documents**. The picker reports there is nothing to
      select rather than showing an empty list with a dead Continue button.
- [ ] Ask SOL about a part studio with **no features**. It says so; it does not invent any.
- [ ] Ask SOL to change a variable in a document with **no Variable Studio**. It reports the problem
      clearly.
- [ ] Send a very long message (several thousand characters). It is handled or rejected cleanly —
      no hang, no crash.
- [ ] Let the Onshape access token expire (over 60 minutes idle), then ask a question. It works —
      the token refreshes transparently, with no reconnect prompt.

---

## 9. Companion / vendored MCP servers (CAD-00b)

Only relevant if you are running a **packaged** desktop build.

- [ ] The companion starts without `SOLUS_COMPANION_INTEGRATIONS_ROOT` being set anywhere. It should
      find the `mcp/` tree next to its own binary rather than dying at startup.
- [ ] Companion logs show either discovered servers **or** an explicit warning naming the root it
      searched. Silence with zero servers is a FAIL — a wrong root and a correct-but-empty one must
      be distinguishable.

_(There are no vendored forks yet, so there is nothing further to exercise here.)_

---

## 10. Known-absent — do NOT file these as bugs

These are deliberately not built. They are recorded in `COMPLETION_SOLUSDEV-96-onshape-mcp.md`.

- **Interference / collision detection.** Not in Onshape's REST API at all (verified across all 248
  paths). Solus does not claim it.
- **Sketching on an existing face by dimension** ("20 mm from the left edge"). Blocked on an
  unpublished payload shape; deliberately not guessed.
- **SOL seeing your Onshape screen, or your live selection.** Impossible over REST; needs the
  in-Onshape extension (A7), not built.
- **Fusion / SolidWorks / AutoCAD.** Not started.
- **Per-document Onshape permissions.** Onshape grants are account-wide; there is no such scope.
