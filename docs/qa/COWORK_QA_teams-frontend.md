# COWORK_QA — Teams & Home Frontend (SOLUSDEV-85)

End-to-end test plan for the Teams/Home frontend completion. This wires four
previously-unbuilt frontend capabilities to existing backend routes in the
Solus desktop app (Electron + React renderer):

1. **Accept an invite** — redeem a one-time invite token to join a team.
2. **Mark all notifications read** — bulk-clear the bell.
3. **Project management** — archive / unarchive / rename / delete projects.
4. **Team switching** — switch which team the Team screen shows.

The tester has the running application and this file, nothing else.

---

## Required setup state

- **Backend running** (`solus-api`) with a Postgres DB, reachable at the URL in
  the renderer's `VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`).
- **Supabase auth configured** (`VITE_SUPABASE_*`). Without it the app runs in
  the **offline/dev-bypass demo** and the live flows below will NOT engage —
  see "Offline fallback" at the end. Live flows require a linked workspace.
- **Two user accounts** you can sign in as, on different emails:
  - **User A** — owner of a non-personal team ("Team Alpha") with ≥1 project.
  - **User B** — a second account whose email you know (to be invited).
- Recommended seed: User A on Team Alpha (owner) plus their auto-created
  personal team; at least one project under Team Alpha named e.g. "Rover".
- To exercise team switching, User A should belong to **two** teams (e.g. also
  a member of "Team Beta"). Accepting an invite in flow 1 creates this state.

Checklist legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Flow 1 — Invite and accept (the full join loop)

### 1A. User A sends an invite (existing, re-verify)

1. Sign in as **User A**. Land on Home.
2. Click the **Team** icon in the left rail.
3. Click **Invite teammate** (top-right; visible only to owner/admin).
4. Enter **User B's email**, click **Send invite**.
   - Expected: success state shows a **one-time join token** string. Copy it.
   - [ ] Token is shown exactly once, in monospace, and is copyable.
5. Close the dialog. A **pending invite row** for User B's email appears in the
   Members card with an "INVITE PENDING" tag.
   - [ ] Pending row visible.

### 1B. User B accepts via paste-token dialog (NEW)

6. Sign out. Sign in as **User B**.
7. On **Home**, in the top-right action row, click **Join team**.
   - [ ] A "Join a team" dialog opens with an **Invite token** field.
8. Paste the token from step 4. Click **Join**.
   - Expected: dialog closes; Home refreshes; **Team Alpha** now appears as one
     of User B's team groups with its project(s).
   - [ ] Team Alpha (and its projects) now listed on User B's Home.
9. Click the **Team** rail icon.
   - [ ] The Team screen resolves to the joined team; User B appears in Members.

### 1C. Invite-accept failure paths (NEW)

10. As User B, open **Join team** again and paste the **same** (now-used) token
    → **Join**.
    - Expected: inline error like _"Couldn't join with that token…"_; dialog
      stays open; no crash.
    - [ ] Error shown, no navigation.
11. Paste a **garbage** token → **Join**. [ ] Same graceful error.
12. Paste a token that was issued to a **different email** (reuse 1A but for a
    third email if available) → **Join**. [ ] Graceful error (backend rejects
    on email mismatch); no team joined.
13. Empty field → **Join** is a no-op (button does nothing / stays). [ ] OK.

---

## Flow 2 — Mark all notifications read (NEW)

Preconditions: User A has unread notifications. The invite acceptance in Flow 1
generates an "X accepted your invite" notification to the inviter (User A), so
signing back in as User A after Flow 1 is a reliable way to have ≥1 unread.

1. Sign in as **User A**. Note the **red count badge** on the bell (top bar).
2. Click the **bell**. The notifications popover opens.
   - [ ] Unread rows show a dot; a **Mark all read** control appears in the
         popover header (only when something is unread).
3. Click **Mark all read**.
   - Expected: all rows immediately lose their unread dot (optimistic); the bell
     badge drops to 0; **Mark all read** disappears (nothing left unread).
   - [ ] Badge → 0, control hidden.
4. Close and reopen the popover (or refresh).
   - [ ] Still all-read (persisted server-side).
5. Single-row read still works: generate a new notification, open the popover,
   click a single unread row → only that row clears, badge decrements by one.
   - [ ] Single mark-read unaffected.

---

## Flow 3 — Project management (NEW)

Sign in as **User A** (owner of Team Alpha). On **Home**, find Team Alpha's card.

### 3A. Rename

1. On a project row, click the **⋯** (actions) button → **Rename**.
   - [ ] A dialog opens **prefilled** with the current name; button reads **Save**.
2. Change the name, click **Save**.
   - [ ] Row shows the new name after refresh; no page reload needed.

### 3B. Archive → Unarchive

3. On a project row, click **⋯ → Archive**.
   - Expected: the project moves out of the active list into an **ARCHIVED**
     subsection of the same team card, dimmed.
   - [ ] Project now under ARCHIVED.
4. In the ARCHIVED row, click **Unarchive**.
   - [ ] Project returns to the active list.

### 3C. Delete (with confirmation)

5. On a project row, click **⋯ → Delete**.
   - Expected: a **confirmation dialog** ("Delete project") naming the project
     and warning it's permanent. The delete has **not** happened yet.
   - [ ] Confirmation required; nothing deleted on menu-click alone.
6. Click **Cancel** → dialog closes, project still present. [ ] OK.
7. Reopen, click **Delete project** (confirm).
   - [ ] Project disappears from the list after the action.

### 3D. Archived-row delete

8. Archive a project, then in the ARCHIVED row click the **✕ / Delete** control
   → confirm.
   - [ ] Archived project can be permanently deleted with the same confirmation.

### 3E. Role gating (authorization is UX + backend)

9. Sign in as a **viewer** of a team (change User B's role to `viewer` via
   User A's Team screen role selector first).
   - [ ] Viewer sees **no ⋯ menu**, **no New project**, **no Unarchive/Delete**
         on that team's projects (management actions hidden).
10. As a **member** (non-admin): ⋯ menu shows **Rename** and **Archive** but
    **not Delete** (delete is admin/owner only).
    - [ ] Member cannot see Delete; can rename/archive.
11. (Boundary) Even if gating were bypassed, the backend rejects unauthorized
    archive/delete — confirm no client-side action leaves the UI in a broken
    state if the server returns 403 (action silently no-ops / stays put).
    - [ ] No crash on server-side denial.

---

## Flow 4 — Team switching (NEW)

Preconditions: User B now belongs to ≥2 teams (their personal team + Team Alpha
from Flow 1). Sign in as **User B**.

1. Click the **Team** rail icon.
   - [ ] Below the team name/subtitle, a **Switch team** dropdown appears
         (only when the user has ≥2 teams).
2. Select a different team in the dropdown.
   - Expected: the Team screen reloads to show that team's roster, activity, and
     pending invites; the header name updates.
   - [ ] Screen reflects the newly-selected team.
3. Switch back.
   - [ ] Returns correctly; personal team is labeled "(personal)".
4. A user on exactly **one** team sees **no** switcher. [ ] Verify with a
   single-team account.

---

## Flow 5 — Create team / create project (existing, re-verify no regression)

1. Home → **New team** → enter a name → **Create**.
   - [ ] New team card appears.
2. On a team card, **New project** → enter a name → **Create**.
   - [ ] Project created and the app navigates into it (graph view).

---

## Cross-feature interactions

- [ ] After **accepting an invite** (Flow 1), the inviter's **activity feed**
      (Team screen) shows a "joined the team" entry, and the inviter gets a
      **notification** (feeds Flow 2).
- [ ] After **creating a project** on a team with the notify setting ON,
      other members receive a notification (bell badge increments).
- [ ] After **archiving/unarchiving**, the team **activity feed** shows
      "archived the project" / "restored the project".
- [ ] **Switching teams** (Flow 4) then opening a project still works; the
      workspace's active team persists across app reloads.

## Empty / edge states

- [ ] A brand-new user with only a personal team and no projects sees a
      friendly "No projects yet" card, and can Create or Join.
- [ ] Team with only archived projects shows an empty active list + the
      ARCHIVED subsection.
- [ ] Notifications popover with nothing shows "You're all caught up."

## Offline fallback (dev bypass — no Supabase/API)

When the workspace is **not linked** to the API, the app shows demo content:

- [ ] Home shows a single demo project card; Team/Settings show the static
      prototype. The NEW live actions (Join team, ⋯ menu, Mark all read live,
      team switcher) rely on a linked workspace and are expected to be
      absent/no-op in this mode. This is intended, not a bug.

---

## Regression sweep

- [ ] Sign in / sign out still work; sign-out returns to landing and clears
      workspace + shell state.
- [ ] Existing invite modal on the Team screen still sends invites and reveals
      the one-time token (Flow 1A).
- [ ] Notifications bell still opens the alert popover when offline (scripted
      demo) and the live popover when online.
