# Cowork QA: assigning GitHub org members to Solus teammates (SOLUSDEV-317)

**What this feature does.** Home → **Team & invites** is one **People** table (design A, "one roster"): teammates, pending invites and — for a team **owner or admin** whose team has linked a GitHub **organization** — the org's members who are not on the team. Admins **link** each teammate to their GitHub account (from the teammate's row or the org member's row), **unlink** it, and **invite** org members who are not on Solus. Everyone sees which GitHub account each teammate is linked to. A team with only its owner starts with two **setup steps** instead.

**An assignment is a label, not a permission.** It never gives anyone Solus access, never changes a role, and never lets someone accept an invite. Several checks below confirm this.

Mark each checkbox **PASS** or **FAIL**, and add a note on every FAIL: what you saw, a screenshot, and the time.

---

## 0. Setup (do once)

### 0.1 People

| Who          | GitHub account                                                      | Solus                                                                                                                 |
| ------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Owner**    | `qa-owner`: **owner** of org `solus-qa-org`                         | Owner of the collaborative team **Strider** (BASIC or PRO plan), and of a second team **Solo** with nobody else in it |
| **Verified** | `qa-verified`: member of `solus-qa-org`                             | Member of Strider, and has connected `qa-verified` under Connected accounts                                           |
| **Plain**    | (none of their own)                                                 | Member of Strider, no GitHub connected                                                                                |
| **Viewer**   | (none)                                                              | **Viewer** of Strider                                                                                                 |
| **Spare**    | (none)                                                              | Member of Strider; removed in §4.3                                                                                    |
| **Outsider** | `qa-outsider`: member of `solus-qa-org`, **not** on Solus           | (none)                                                                                                                |
| **Extra**    | `qa-extra-1`, `qa-extra-2`: members of `solus-qa-org`, not on Solus | (none)                                                                                                                |

`solus-qa-org` needs at least 5 members. For the paging check (§6.3) it needs more than 50; if it doesn't, skip that check and note it.

The Owner also belongs to a second collaborative team, **Rover**, with no GitHub organization linked, and has their **personal** workspace.

### 0.2 Server and app

- Backend running with the SOLUSDEV-317 assignment API merged (routes `PUT` / `DELETE /teams/{t}/github/members/{github_id}/assignment`). Both GitHub registrations are already configured in the server `.env`: do not change them.
- Two desktop windows signed in at once: **Window A** as Owner, **Window B** as Plain (a second machine or a second app profile).
- SOL mode starts at **Guide** (Settings → Appearance → SOL mode). Some checks switch to **Expert**.

---

## 1. Solo team setup

| #   | Step                                                                                                                                    | Expected                                                                                                                                                                                                                                                                                                                            | ☐   |
| --- | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 1.1 | Window A: switch to **Solo** (only you, no invites). Sidebar → **Team & invites**.                                                      | Header "Solo" and "Just you so far. Two optional steps make this a working team." Two cards: **① Invite a teammate** (email field + **Send invite**) and **② Link a GitHub organization to Solo** (**Link organization**). Below: PEOPLE · 1 with you, and TEAM ACTIVITY beside it. No search box, no **+ Invite teammate** button. | ☐   |
| 1.2 | Type `nope` and **Send invite**.                                                                                                        | "Enter a valid email address." under the field. Nothing is sent.                                                                                                                                                                                                                                                                    | ☐   |
| 1.3 | Type a real email, **Send invite**.                                                                                                     | A dialog "Invite <email>" shows a one-time token and "…They paste it under Join team." Escape and click-out do nothing; **Done** asks twice while uncopied. After it closes the steps are gone (there is now a pending invite) and the normal header + table show, with the invite row. Revoke it to get back to 1.1.               | ☐   |
| 1.4 | Switch SOL mode to **Expert**, return.                                                                                                  | The intro reads "Just you. Optional setup:" and the step text is one short line. Back to Guide.                                                                                                                                                                                                                                     | ☐   |
| 1.5 | **Link organization** on step ② and finish the install for `solus-qa-org` in the browser (then unlink it again from ⋯ to restore Solo). | Step ② disappears and the GitHub strip shows `solus-qa-org`; step ① stays. Focus moves to the PEOPLE heading.                                                                                                                                                                                                                       | ☐   |
| 1.6 | Switch to your **personal** workspace → Team & invites.                                                                                 | No steps, no GitHub strip. PEOPLE shows just you.                                                                                                                                                                                                                                                                                   | ☐   |

## 2. The People table (Strider, org linked)

| #   | Step                                                                                              | Expected                                                                                                                                                                                                                                                | ☐   |
| --- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 2.1 | Window A: switch to **Strider** → Team & invites. Link `solus-qa-org` from the strip if it isn't. | Header: "Strider", "N members · M pending invites · K more people in solus-qa-org", a search box, **+ Invite teammate**. Under it, one strip: avatar, `solus-qa-org · Organization · N repos`, "Linked by …", **● ACTIVE**, **Manage on GitHub ↗**, ⋯. | ☐   |
| 2.2 | The table.                                                                                        | Columns PERSON · ROLE · GITHUB · ACTIONS. Teammates first, then pending invites, then a band "IN SOLUS-QA-ORG, NOT ON THIS TEAM · K" with org members. TEAM ACTIVITY sits to the right (under the table on a narrow window).                            | ☐   |
| 2.3 | Verified's row.                                                                                   | GITHUB: `@qa-verified` **VERIFIED**, no Unlink. Hovering the tag says they linked it themselves.                                                                                                                                                        | ☐   |
| 2.4 | Plain's row.                                                                                      | "No GitHub linked" and **Link GitHub…**. A role select and ✕ remove. The Owner row has neither.                                                                                                                                                         | ☐   |
| 2.5 | A teammate with no display name.                                                                  | Their email appears once (not twice).                                                                                                                                                                                                                   | ☐   |
| 2.6 | `qa-outsider`'s org row.                                                                          | Avatar (a real GitHub avatar, not a broken image), `@qa-outsider`, **NOT ON SOLUS**, **Link to teammate…** and **Invite**.                                                                                                                              | ☐   |
| 2.7 | Footnote (Guide, then Expert).                                                                    | Guide: the paragraph saying a link is only a label, never access or a role change. Expert: one short line.                                                                                                                                              | ☐   |

## 3. Link and unlink

| #   | Step                                                      | Expected                                                                                                                                                                                     | ☐   |
| --- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 3.1 | Plain's row → **Link GitHub…**.                           | A list of org members nobody is linked to opens ABOVE every row (nothing paints over it), first option focused. ↓/↑ move; Escape closes and focus returns to the button.                     | ☐   |
| 3.2 | Pick `qa-extra-1`.                                        | Plain's GITHUB shows `@qa-extra-1` **ASSIGNED** "by <Owner> …" at once, and a green line "@qa-extra-1 is now shown as Plain. Their access did not change." `qa-extra-1` leaves the org band. | ☐   |
| 3.3 | `qa-extra-2`'s org row → **Link to teammate…**.           | Plain is not offered (already linked). Verified is listed greyed out with "@qa-verified · verified".                                                                                         | ☐   |
| 3.4 | Pick **Owner** (you).                                     | Your row shows `@qa-extra-2` ASSIGNED; `qa-extra-2` leaves the band.                                                                                                                         | ☐   |
| 3.5 | Plain's row → **Unlink**.                                 | An inline question "Remove the label linking @qa-extra-1 to Plain? Their Solus access stays the same." with **Unlink** (focused) and **Cancel**. No dialog.                                  | ☐   |
| 3.6 | **Cancel**, then **Unlink** → **Unlink**.                 | Cancel restores the row. Confirming shows "No GitHub linked" again and `qa-extra-1` returns to the org band.                                                                                 | ☐   |
| 3.7 | Window B (Plain): check access during 3.2–3.6.            | Plain's role and project access never change.                                                                                                                                                | ☐   |
| 3.8 | Open a picker, then scroll the page or resize the window. | The list closes (it never floats away from its button). Opening one near the bottom of the window shows it above the button.                                                                 | ☐   |
| 3.9 | While one row is saving, act on another row.              | The other row works; only the saving row shows a spinner.                                                                                                                                    | ☐   |

## 4. Refusals

| #   | Step                                                                                                                                         | Expected                                                                                                                             | ☐   |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 4.1 | Promote Plain to admin. In Window B link `qa-extra-1` → Plain; in Window A, before it refreshes, link `qa-extra-2` → Plain from the org row. | Window A's row rolls back and says "Plain is already assigned to @qa-extra-1. Unassign them there first…" with **Find @qa-extra-1**. | ☐   |
| 4.2 | Click **Find @qa-extra-1**.                                                                                                                  | The filter goes to **Everyone** and the search holds `qa-extra-1`.                                                                   | ☐   |
| 4.3 | Window B: open **Link to teammate…** on an org row. Window A: remove **Spare**. Window B, before refreshing: pick Spare.                     | "That person isn't on this team anymore — the member list has been refreshed." Spare disappears. Demote Plain back to member.        | ☐   |
| 4.4 | Disconnect the network, then link any row; then Expert mode, again.                                                                          | The row rolls back. Guide: "Couldn't save that assignment…"; Expert: "Assignment failed. Retry."                                     | ☐   |

## 5. Invites

| #   | Step                                                                                                                                | Expected                                                                                                                                        | ☐   |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | **Invite** on `qa-outsider`'s org row.                                                                                              | Dialog "Invite @qa-outsider" with the one-time token, focused and announced. Escape / click-out do nothing; **Done** asks twice while uncopied. | ☐   |
| 5.2 | After Done.                                                                                                                         | `qa-outsider` now appears as an invite row (`@qa-outsider INVITED`, "Invite sent now · expires in 7d") and is NOT also listed in the org band.  | ☐   |
| 5.3 | **Revoke** on that invite row.                                                                                                      | A confirm naming it; confirming removes the row and `qa-outsider` returns to the org band.                                                      | ☐   |
| 5.4 | **+ Invite teammate** in the header.                                                                                                | The email invite dialog opens (unchanged flow).                                                                                                 | ☐   |
| 5.5 | (Plan at its member limit) **Invite** an org row.                                                                                   | The plan-limit notice with **Upgrade** on that row; Upgrade opens Billing.                                                                      | ☐   |
| 5.6 | Link `qa-outsider` to Plain, then have `qa-outsider` accept a 5.1 token with a Solus account NOT signed in as GitHub `qa-outsider`. | Accept is refused (`github_identity_mismatch`). The link let nobody in.                                                                         | ☐   |

## 6. Filters and search

| #   | Step                                                            | Expected                                                                                                             | ☐   |
| --- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --- |
| 6.1 | Filters **Team**, **Invites**, **Not on Solus**, **No GitHub**. | Team: teammates only. Invites: pending invites only. Not on Solus: org band only. No GitHub: teammates with no link. | ☐   |
| 6.2 | Search a name, an email, then an `@login`.                      | Each narrows every group at once. No match: "No organization members match this view."                               | ☐   |
| 6.3 | (Org > 50 members) **Load more** in the table footer.           | More org rows append; the button goes away when all are loaded.                                                      | ☐   |
| 6.4 | 9+ teammates: open **Link to teammate…**.                       | A search box at the top of the list, focused.                                                                        | ☐   |
| 6.5 | macOS **Reduce motion** on, reopen the view.                    | Rows appear without the fade/slide.                                                                                  | ☐   |

## 7. Who sees what

| #   | Step                                                                                                    | Expected                                                                                                                                             | ☐   |
| --- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 7.1 | Window B as **Plain** (member): Strider → Team & invites.                                               | The strip; the table with teammates and their GitHub badges; no org band, no **Not on Solus** filter, no Link/Unlink, no role selects, no ✕.         | ☐   |
| 7.2 | Sign in as **Viewer**.                                                                                  | As 7.1, and the footnote says "You have view access to this team…".                                                                                  | ☐   |
| 7.3 | Suspend the Solus app on GitHub (`solus-qa-org` → Installed GitHub Apps → Suspend); Window A refreshes. | Strip shows **● SUSPENDED** and the yellow "Suspended on GitHub…" line; the org band and the **Not on Solus** filter are gone. Unsuspend afterwards. | ☐   |
| 7.4 | Link a personal (User) GitHub account to Rover.                                                         | The strip shows it; no org band for a User link.                                                                                                     | ☐   |

## 8. Team switch and live updates

| #   | Step                                                                                  | Expected                                                                                                | ☐   |
| --- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --- |
| 8.1 | Window A: start a link, immediately switch to **Rover**.                              | Rover's view shows only Rover; nothing from Strider leaks in.                                           | ☐   |
| 8.2 | Back to Strider.                                                                      | The link either shows (saved) or not (refused) — never half-applied.                                    | ☐   |
| 8.3 | Windows A (Owner) and B (Plain as admin) on Strider. In A, link `qa-extra-1` → Owner. | Within a few seconds B shows it in Owner's row and `qa-extra-1` leaves B's org band, without reloading. | ☐   |
| 8.4 | In A, unlink it.                                                                      | B updates the same way.                                                                                 | ☐   |
| 8.5 | In A, remove Plain while B is open.                                                   | B leaves the team; any Plain link disappears from A.                                                    | ☐   |

## 9. Safety

| #   | Step                                                                                  | Expected                                                                                                                        | ☐   |
| --- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --- |
| 9.1 | Rename a teammate (or a login you control) to `<img src=x onerror=alert(1)>`.         | Plain text everywhere in this view; no alert, no broken image.                                                                  | ☐   |
| 9.2 | Every sentence in this view, in Guide and Expert.                                     | Guide explains; Expert is short. Nothing blank, no `{placeholders}`.                                                            | ☐   |
| 9.3 | Keyboard only: Tab to a row's **Link GitHub…**, pick with Enter; Tab inside the list. | Everything reachable; Tab inside the list closes it back onto its button; VoiceOver reads the row's status line after a change. | ☐   |
