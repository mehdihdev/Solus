# Cowork QA: assigning GitHub org members to Solus teammates (SOLUSDEV-317)

**What this feature does.** On Home → **Team & invites**, a team **owner or admin** whose team has linked a GitHub **organization** sees every member of that org in a new **GITHUB ORG MEMBERS** section, under the GITHUB ORGANIZATION card. They can **assign** each GitHub account to a Solus teammate, **change** it, or **unassign** it, and still **invite** org members who are not on Solus yet. Everyone on the team sees, in the MEMBERS list, which GitHub account each teammate is linked to.

**An assignment is a label, not a permission.** It never gives anyone Solus access, never changes a role, and never lets someone accept an invite. Several checks below confirm this.

Mark each checkbox **PASS** or **FAIL**, and add a note on every FAIL: what you saw, a screenshot, and the time.

---

## 0. Setup (do once)

### 0.1 People

| Who          | GitHub account                                                      | Solus                                                                       |
| ------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **Owner**    | `qa-owner`: **owner** of org `solus-qa-org`                         | Owner of the collaborative team **Strider** (BASIC or PRO plan)             |
| **Verified** | `qa-verified`: member of `solus-qa-org`                             | Member of Strider, and has connected `qa-verified` under Connected accounts |
| **Plain**    | (none of their own)                                                 | Member of Strider, no GitHub connected                                      |
| **Viewer**   | (none)                                                              | **Viewer** of Strider                                                       |
| **Spare**    | (none)                                                              | Member of Strider; removed in §4.3                                          |
| **Outsider** | `qa-outsider`: member of `solus-qa-org`, **not** on Solus           | (none)                                                                      |
| **Extra**    | `qa-extra-1`, `qa-extra-2`: members of `solus-qa-org`, not on Solus | (none)                                                                      |

`solus-qa-org` needs at least 5 members. For the paging check (§6.3) it needs more than 50; if it doesn't, skip that check and note it.

The Owner also belongs to a second collaborative team, **Rover**, with no GitHub organization linked, and has their **personal** workspace.

### 0.2 Server and app

- Backend running with the SOLUSDEV-317 assignment API merged (routes `PUT` / `DELETE /teams/{t}/github/members/{github_id}/assignment`). Both GitHub registrations are already configured in the server `.env`: do not change them.
- Two desktop windows signed in at once: **Window A** as Owner, **Window B** as Plain (a second machine or a second app profile).
- SOL mode starts at **Guide** (Settings → Appearance → SOL mode). Some checks switch to **Expert**.

---

## 1. Link the organization

| #   | Step                                                                                          | Expected                                                                                                                                                                 | ☐   |
| --- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 1.1 | Window A: switch to **Strider**. Sidebar → **Team & invites**.                                | Pane order, top to bottom: MEMBERS, GITHUB ORGANIZATION, (nothing yet), TEAM ACTIVITY.                                                                                   | ☐   |
| 1.2 | Look at the GITHUB ORGANIZATION card (unlinked).                                              | It reads "Link a GitHub organization to **Strider**" (team name bold), then the explainer and **Link organization**.                                                     | ☐   |
| 1.3 | Switch to **Rover**, open Team & invites.                                                     | The card now says "…to **Rover**". Switch back to Strider.                                                                                                               | ☐   |
| 1.4 | Switch to your **personal** workspace, open Team & invites.                                   | No GITHUB ORGANIZATION card and no GITHUB ORG MEMBERS section. The sidebar ACCOUNT nav's "Team & invites" entry looks as it did before.                                  | ☐   |
| 1.5 | Back on Strider: **Link organization**, finish the install for `solus-qa-org` in the browser. | The card shows `solus-qa-org · Organization`. **GITHUB ORG MEMBERS** appears under it and keyboard focus lands on its heading (press Tab: focus moves into the section). | ☐   |
| 1.6 | The card has no "Members on GitHub" button.                                                   | Only **Manage on GitHub ↗** and **⋯**.                                                                                                                                  | ☐   |

## 2. The roster

| #   | Step                                        | Expected                                                                                                                                           | ☐   |
| --- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 2.1 | Read the top of GITHUB ORG MEMBERS (Guide). | A paragraph explaining that an assignment is only a label: it never gives Solus access or changes a role, and people still join through an invite. | ☐   |
| 2.2 | Switch SOL mode to **Expert**, return.      | The explainer is one short line ("…no access, no role change"). The header reads "N org members · M on team". Switch back to Guide.                | ☐   |
| 2.3 | Header (Guide).                             | "N organization members · M on this team", N = the org's member count.                                                                             | ☐   |
| 2.4 | Row for `qa-verified`.                      | Chip **Verified**, the Verified teammate's name, the line "They linked this GitHub account themselves…", and **no** buttons.                       | ☐   |
| 2.5 | Row for `qa-outsider`.                      | Chip **Not on Solus**, buttons **Assign** and **Invite**.                                                                                          | ☐   |
| 2.6 | Avatars.                                    | GitHub avatars show. No broken-image icons.                                                                                                        | ☐   |

## 3. Assign, change, unassign

| #    | Step                                                                                   | Expected                                                                                                                                                                  | ☐   |
| ---- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 3.1  | On `qa-extra-1` click **Assign**.                                                      | A list of teammates opens with the first selectable one focused. **Verified** appears greyed out with "@qa-verified · verified" and cannot be picked.                     | ☐   |
| 3.2  | Use ↓ / ↑ to move, then press **Escape**.                                              | Focus moves between teammates; Escape closes the list and focus returns to **Assign**.                                                                                    | ☐   |
| 3.3  | **Assign** → pick **Plain** (click or Enter).                                          | The row immediately shows **Assigned**, Plain's name, then "assigned by <Owner> …". A green line reads "@qa-extra-1 is now shown as Plain. Their access did not change."  | ☐   |
| 3.4  | Header.                                                                                | "M on this team" went up by one.                                                                                                                                          | ☐   |
| 3.5  | MEMBERS list (top of the pane).                                                        | Plain's row shows the GitHub mark, `@qa-extra-1` and the tag **assigned**. Verified's row shows `@qa-verified` and **verified**.                                          | ☐   |
| 3.6  | On `qa-extra-2` click **Assign**.                                                      | **Plain** is not offered (already assigned to `qa-extra-1`).                                                                                                              | ☐   |
| 3.7  | On `qa-extra-1` click **Change** → pick **Owner** (yourself).                          | The row now shows Owner. In MEMBERS, Plain loses the GitHub badge and Owner gains `@qa-extra-1 assigned`.                                                                 | ☐   |
| 3.8  | On `qa-extra-1` click **Unassign**.                                                    | The row shows an inline question "Remove the label linking @qa-extra-1 to <Owner>? Their Solus access stays the same." with **Unassign** and **Cancel**. No popup dialog. | ☐   |
| 3.9  | Click **Cancel**, then **Unassign** → **Unassign**.                                    | Cancel restores the buttons. Confirming returns the row to **Not on Solus** and announces "@qa-extra-1 is no longer shown as a teammate…".                                | ☐   |
| 3.10 | Check Plain's access after 3.3–3.9 (Window B: open a Strider project, change nothing). | Plain's role and project access are unchanged throughout.                                                                                                                 | ☐   |
| 3.11 | While one row is saving (pick an assignment, then immediately click on another row).   | The other row works normally; only the saving row shows a spinner.                                                                                                        | ☐   |

## 4. Refusals

| #   | Step                                                                                                                                                                                       | Expected                                                                                                                                                                                      | ☐   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 4.1 | Assign `qa-extra-1` → Plain. In Window B (as an admin of Strider — temporarily promote Plain to admin from Window A for this step), assign `qa-extra-2` → Plain before Window A refreshes. | The second assignment is refused on its row: "Plain is already assigned to @qa-extra-1. Unassign them there first…" with a **Find @qa-extra-1** button. The row goes back to how it was.      | ☐   |
| 4.2 | Click **Find @qa-extra-1**.                                                                                                                                                                | The filter switches to **All** and the search box holds `qa-extra-1`; that row is shown.                                                                                                      | ☐   |
| 4.3 | Window B (Plain still admin from 4.1): open the **Assign** list on any row. Window A: remove **Spare** from Strider. Window B, before it refreshes: pick that removed teammate.            | "That person isn't on this team anymore — the member list has been refreshed." The row is unchanged and the removed teammate disappears from MEMBERS. Afterwards demote Plain back to member. | ☐   |
| 4.4 | Disconnect the network, then assign any row.                                                                                                                                               | The row rolls back and shows "Couldn't save that assignment…". Reconnect.                                                                                                                     | ☐   |
| 4.5 | Switch to Expert and repeat 4.4.                                                                                                                                                           | "Assignment failed. Retry."                                                                                                                                                                   | ☐   |

## 5. Invite from the roster

| #   | Step                                                                                                                                                                                           | Expected                                                                                                             | ☐   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | Count the **Invite** buttons.                                                                                                                                                                  | Only on **Not on Solus** rows; never on Assigned, Verified or Invited rows.                                          | ☐   |
| 5.2 | **Invite** on `qa-outsider`.                                                                                                                                                                   | A small dialog "Invite @qa-outsider" shows a one-time token, focused and announced.                                  | ☐   |
| 5.3 | Press **Escape**; click outside the dialog.                                                                                                                                                    | Neither closes it.                                                                                                   | ☐   |
| 5.4 | Click **Done** once without copying.                                                                                                                                                           | A warning "You won't see this token again…". Click **Done** again: the dialog closes. The row now shows **Invited**. | ☐   |
| 5.5 | (Plan at its member limit, if you can arrange it) **Invite** another row.                                                                                                                      | The row shows the plan-limit notice with **Upgrade**; Upgrade opens Billing.                                         | ☐   |
| 5.6 | Assigning never counts as identity proof: assign `qa-outsider` to Plain, then have `qa-outsider` try to accept the 5.2 token with a Solus account **not** signed in with GitHub `qa-outsider`. | Accept is refused (`github_identity_mismatch`). The assignment did not let them in.                                  | ☐   |

## 6. Browsing

| #   | Step                                                                                    | Expected                                                                                                                              | ☐   |
| --- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 6.1 | Filters **On team** then **Not on Solus**.                                              | On team: only Assigned and Verified rows. Not on Solus: only Not on Solus and Invited rows.                                           | ☐   |
| 6.2 | Type part of a login in the search box.                                                 | Only matching loaded rows remain. Clearing it brings all back. A search with no match says "No organization members match this view." | ☐   |
| 6.3 | (Org > 50 members) Scroll to the end, **Load more**.                                    | More rows append; the button disappears once all are loaded.                                                                          | ☐   |
| 6.4 | Filter **Unassigned teammates**.                                                        | Lists teammates with no GitHub link (e.g. Plain, after 3.9), each with **Pick GitHub account**.                                       | ☐   |
| 6.5 | **Pick GitHub account** on Plain → pick `@qa-extra-2`.                                  | Plain disappears from this list (now linked). Back on **All**, `qa-extra-2` shows Assigned → Plain.                                   | ☐   |
| 6.6 | Unassign so Plain has no link. In MEMBERS click **Assign GitHub…** on Plain's row.      | The page scrolls to GITHUB ORG MEMBERS, the filter switches to **Unassigned teammates**, and Plain's account list opens.              | ☐   |
| 6.7 | A team with more than 8 members (add test members if needed): open any **Assign** list. | A search box appears at the top of the list and is focused; typing filters the teammates.                                             | ☐   |
| 6.8 | Turn on macOS **Reduce motion**, reopen the view.                                       | Rows appear without the fade/slide.                                                                                                   | ☐   |

## 7. Who sees what

| #   | Step                                                                                                                              | Expected                                                                                                                         | ☐   |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | --- |
| 7.1 | Window B as **Plain** (member): Strider → Team & invites.                                                                         | The card shows the linked org; **no** GITHUB ORG MEMBERS section; MEMBERS shows everyone's GitHub badges; no **Assign GitHub…**. | ☐   |
| 7.2 | Sign in as **Viewer**, same view.                                                                                                 | Same as 7.1.                                                                                                                     | ☐   |
| 7.3 | Suspend the Solus app on GitHub (`solus-qa-org` settings → Installed GitHub Apps → Suspend). In Window A, refresh Team & invites. | The card shows the yellow "Suspended on GitHub…" row; GITHUB ORG MEMBERS is hidden. Unsuspend afterwards.                        | ☐   |
| 7.4 | Link a **personal** GitHub account (User type) to Rover instead of an org.                                                        | The card shows it; no GITHUB ORG MEMBERS section for a User link.                                                                | ☐   |

## 8. Team switch and live updates

| #   | Step                                                                                                                         | Expected                                                                                                              | ☐   |
| --- | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --- |
| 8.1 | Window A: start an assignment, and immediately switch to **Rover**.                                                          | Rover's Team & invites shows Rover's own state; nothing from Strider's roster appears there.                          | ☐   |
| 8.2 | Back on Strider.                                                                                                             | The roster reloads; the assignment from 8.1 either shows (it saved) or doesn't (it was refused) — never half-applied. | ☐   |
| 8.3 | Window A (Owner) and Window B (Plain promoted to admin) both on Strider → Team & invites. In A, assign `qa-extra-1` → Owner. | Within a few seconds B shows `qa-extra-1` Assigned → Owner in the roster and the badge in MEMBERS, without reloading. | ☐   |
| 8.4 | In A, unassign it.                                                                                                           | B updates the same way.                                                                                               | ☐   |
| 8.5 | In A, remove Plain from Strider while B is open.                                                                             | B leaves the team (existing behaviour) and any Plain assignment disappears from A's roster.                           | ☐   |

## 9. Safety

| #   | Step                                                                                                | Expected                                                                                                                   | ☐   |
| --- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --- |
| 9.1 | Rename a teammate (or a GitHub login, if you control one) to `<img src=x onerror=alert(1)>`.        | Shown as plain text everywhere in this view; no alert, no broken image.                                                    | ☐   |
| 9.2 | Every new sentence in this view, in both Guide and Expert.                                          | Guide explains; Expert is short. Nothing is blank or shows `{placeholders}`.                                               | ☐   |
| 9.3 | Keyboard only: Tab through a row, open its list, pick with Enter, unassign with the inline confirm. | Everything is reachable; focus is always visible; screen reader (VoiceOver) reads the row's status line after each change. | ☐   |
