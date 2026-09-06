# Cowork QA — HOME H5: The team layer in Home (SOLUSDEV-244)

Home now carries the whole team layer: the active team is always named at the top; the switcher
appears only when you belong to more than one team; members with roles, one-time invites, join by
token, and the team's activity feed live on Home; the separate Team screen is gone. Switching
teams swaps the project grid and closes any open project from the previous team. Plan limits on
collaborative teams (BASIC: 2; the personal team never counts) are stated with the upgrade path,
never as a silent failure. This plan assumes the running application and nothing else.

## Required setup

- API and desktop running. Two signed-in, email-verified users: **A** on the **BASIC** plan
  (Settings → Billing shows Teams 2), and **B** (any plan) with no collaborative teams.
- A has no collaborative teams at the start (leave or delete any; the personal team stays).

Mark each step ☐ pass / ✗ fail. Note the screen and the exact text on failure.

## Flow 1 — The strip and the switcher

1. As A, open **Home**. Expected at the top: the personal team's name, "personal workspace ·
   1 member", **no** switcher (one team), `Join team`, `New team`, `Invite teammate`; below:
   "0 of 2 collaborative teams on your plan · your personal team never counts". ☐
2. `New team` → "Rover Lab" → Create. Expected: Home switches to Rover Lab (strip name), the
   switcher now appears (two teams), the limit line reads "1 of 2". Create a project "Rover MK2". ☐
3. `New team` → "Arm Lab"; create a project "Arm v1". Expected: strip Arm Lab, "2 of 2 …" and a
   warning note "You're at your plan's collaborative-team limit. Leave a team, or upgrade for
   unlimited teams." with an **Upgrade** button. ☐
4. Switch to Rover Lab in the switcher. Expected: the grid shows only Rover MK2; TEAM ACTIVITY
   lists Rover Lab's events; MEMBERS lists A as OWNER. Switch back: only Arm v1. ☐
5. No rail item or menu entry named Team exists; Settings → Team still offers rename, the
   notify toggle, and (owner) the danger zone; Settings has no Members section. ☐

## Flow 2 — Team switch is a full swap (the acceptance)

1. On Rover Lab, click **Open** on Rover MK2 (the project pill shows Rover MK2). Return to Home
   via the rail. ☐
2. Switch the strip's selector to Arm Lab. Expected: the project pill reads "No project"; the
   grid shows Arm v1 only; opening SOL shows a fresh chat for no project (nothing from Rover MK2);
   the Store's detail selection and any toast are gone. ☐
3. Open Arm v1, then switch the selector back to Rover Lab. Expected: the pill drops to "No
   project" again (a project of another team never survives). Open Rover MK2, then select Rover
   Lab again in the selector. Expected: Rover MK2 stays open (same team is not a switch). ☐

## Flow 3 — Plan limit, honestly (the acceptance)

1. As A (2 of 2), `New team` → "Third" → Create. Expected: the dialog stays open showing the
   server's sentence ("You're at your collaborative-team limit…") with an **Upgrade** button —
   never "Couldn't create the team. Please try again." ☐
2. Click Upgrade. Expected: the Billing screen. ☐
3. Have B create a team and invite A; as A paste the token in `Join team`. Expected: the join is
   refused with the same limit sentence and Upgrade (the invitee's OWN plan blocks, ADR-023). ☐
4. Leave Arm Lab (⋯ → Leave team → confirm). Expected: Home moves to the personal workspace; the
   limit line reads "1 of 2"; joining B's team now succeeds. ☐
5. Switch A to PRO (Settings → Billing). Expected: the limit line disappears (unlimited). ☐

## Flow 4 — Invite, one-time token, later joiner (the acceptance)

1. As A on Rover Lab, `Invite teammate` → B's email → Send. Expected: "Invite sent. Share this
   one-time join token — it's shown only now:" with the token and **Copy token** / **Done**. ☐
2. Click Done without copying. Expected: a warning "You won't see this token again…"; the dialog
   stays open. Click **Copy token** ("Copied"), then Done. Expected: MEMBERS shows B's email as
   "INVITE PENDING · MEMBER" with a revoke ✕. ☐
3. The token appears nowhere else: not in the members card, not in TEAM ACTIVITY (which says
   "invited <email> as member"), not in Settings. ☐
4. As B on their personal Home, `Join team` → paste the token → Join. Expected: Home switches to
   Rover Lab; the grid shows **Rover MK2** (created before B joined) with **Open** working — no one
   shared the project with B; MEMBERS shows B as MEMBER; TEAM ACTIVITY shows "joined the team". ☐
5. As B, paste the same token again. Expected: "That token isn't valid. It may have been revoked
   or already used." ☐
6. As A, invite an email, then revoke it (✕) before it is used; as that user, try the token.
   Expected: the same invalid-token message. Wait past the 7-day expiry or (operator) set
   `invites.expires_at` in the past: "This invite has expired. Ask for a new one." ☐
7. As B, try a token issued to a different email. Expected: "This invite was issued to a
   different email address." ☐

## Flow 5 — Roles, remove, leave, rename, delete

1. As A (owner) on Rover Lab: B's row has a role select (admin / member / viewer) and ✕; A's own
   owner row has neither. Change B to admin. Expected: the row updates; TEAM ACTIVITY logs it. ☐
2. As B (now admin): `Invite teammate` and the role selects appear; the ⋯ menu offers Rename team
   and Leave team, **not** Delete team. ☐
3. As A, set B to viewer. As B: no invite button, no role controls, the members footer reads
   "You have view access to this team."; the New project tile is hidden. ☐
4. As A, ⋯ → Rename team → "Rover Racing". Expected: the strip, the switcher and the project
   pill's team naming update; Settings → Team shows the new name. ☐
5. As A, ⋯ → Leave team. Expected: "A team must keep at least one owner. Make someone else an
   owner first." (A is the sole owner). ☐
6. As A, ⋯ → Delete team. Expected: the confirm names the team "and every project in it";
   confirm → Home moves to the personal workspace; B's Home (reload) shows "This team is no longer
   available — it was deleted, or you were removed from it." with **Go to my personal workspace**
   — never "can't reach its API". ☐
7. On the personal team, the ⋯ menu offers Rename only — never Leave or Delete. ☐

## Flow 6 — Invite from the personal team

1. As A on the personal workspace, `Invite teammate` → an email → Send. Expected: the token
   dialog says "Invite sent from your new team — Home has switched to it." and Home's strip now
   names "<A>'s Team" (a new collaborative team; the personal team stays solo); the limit line
   counts it. ☐

## Flow 7 — Activity feed

1. On a team with more than six events: TEAM ACTIVITY shows six rows with actor names and
   relative times, and `View all activity (N) →` with the server total. Click it: the dialog lists
   every loaded row, `Load more` while more exist, ✕ closes. ☐
2. A project card's `All activity →` still shows that project's own rows only. ☐

## Cross-feature checks

- Connected accounts (H2/H4) and How you engineer (H3) cards are unchanged beneath MEMBERS. ☐
- Offline / signed-out Home still shows the honest card and the preferences card; no team strip. ☐
- Data collection (consent on): `team.switched` events carry team ids and the closed project id
  only — never a token, an email, or a name. ☐
