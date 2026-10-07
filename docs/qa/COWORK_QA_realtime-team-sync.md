# Cowork QA — Real-time team sync (SOLUSDEV-312)

Tests that one teammate's changes appear in another teammate's Solus desktop app
**without clicking refresh, switching screens or restarting the app**. Every
change arrives as a small "something changed" message; the receiving app then
re-reads the data itself. Nothing should ever show a toast — updates are quiet.

Mark each step **PASS / FAIL** and note what you saw on failure.

---

## 0. Setup

| #   | Requirement                                                                              | How to check                                                           | ☐   |
| --- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | --- |
| 0.1 | API, worker and Redis running (`pnpm dev:all`, Redis on)                                 | `GET http://localhost:8000/readyz` → `checks.live_fanout` is `"redis"` | ☐   |
| 0.2 | Two desktop app windows signed in as **two different accounts**: **A** (owner) and **B** | Each window shows its own name in the account menu                     | ☐   |
| 0.3 | A third account **C** that is NOT in A's team                                            | Can sign in                                                            | ☐   |
| 0.4 | A owns a collaborative team **"QA Live"** with B as a **member** (not admin)             | Settings → Team shows both                                             | ☐   |
| 0.5 | "QA Live" has one project **"Live Bench"** with at least one connected source            | Project opens, Sources list non-empty                                  | ☐   |
| 0.6 | Place the two windows side by side so both are visible                                   | —                                                                      | ☐   |

"Within a few seconds" below means **≤ 5 s**. Write down actual times for anything slower.

---

## 1. Team membership

| #   | Step (actor)                                                                                   | Expected (other window)                                                                                    | ☐   |
| --- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --- |
| 1.1 | B opens **Home** and leaves it open. A opens Settings → Team and changes B's role to **admin** | B's Home team panel shows B as admin within a few seconds                                                  | ☐   |
| 1.2 | A changes B back to **member**                                                                 | B's role reverts within a few seconds                                                                      | ☐   |
| 1.3 | A invites **C** by email                                                                       | A's own invite list shows C. B (member) sees **no** invite list and **no** error                           | ☐   |
| 1.4 | C accepts the invite (sign in as C in a third window or reuse B's window after the test)       | A's and B's member lists show C within a few seconds; C's team switcher shows "QA Live" without restarting | ☐   |
| 1.5 | A removes C from the team                                                                      | A/B member lists drop C; in C's window "QA Live" disappears from the team switcher within a few seconds    | ☐   |
| 1.6 | A revokes a pending invite (create one first)                                                  | A's invite list updates; nothing changes for B                                                             | ☐   |

## 2. Projects and activity

| #   | Step (actor)                                                                                            | Expected (other window)                                                                         | ☐   |
| --- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --- |
| 2.1 | B on Home. A creates project **"Live 2"**                                                               | B's project grid shows "Live 2" within a few seconds; B's Team Activity panel shows the new row | ☐   |
| 2.2 | A renames "Live 2" → **"Live 2b"**                                                                      | B's grid shows the new name                                                                     | ☐   |
| 2.3 | A archives "Live 2b"                                                                                    | It leaves B's active grid                                                                       | ☐   |
| 2.4 | A unarchives it                                                                                         | It returns                                                                                      | ☐   |
| 2.5 | B opens **View all activity**, clicks **Load more** once, keeps the dialog open. A makes another change | New row appears at the top; already-loaded older rows are still there (no silent truncation)    | ☐   |

## 3. Notifications

| #   | Step                                                                                       | Expected                                                         | ☐   |
| --- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | --- |
| 3.1 | B's bell shows N unread. A creates a project (team setting "notify on project created" on) | B's unread badge increases by 1 within a few seconds, no restart | ☐   |
| 3.2 | B opens the bell and marks all read                                                        | Badge clears; stays cleared                                      | ☐   |
| 3.3 | A does NOT receive their own "project created" notification                                | A's badge unchanged                                              | ☐   |

## 4. Workspace (project open)

Both A and B open project **"Live Bench"** in the Workspace (graph) screen.

| #   | Step                                                                                                   | Expected                                                                                                                  | ☐   |
| --- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- | --- |
| 4.1 | A drags a node and lets it save. B has made **no** moves                                               | B's canvas moves that node to A's position within a few seconds                                                           | ☐   |
| 4.2 | B drags node X (does not wait), then A drags a **different** node Y and saves, then B's save completes | Both X (B's move) and Y (A's move) end up in their new positions in both windows. **No** "Layout changed elsewhere" error | ☐   |
| 4.3 | A clicks **Sync now** on a source                                                                      | B's source list shows syncing → synced state change without waiting a minute                                              | ☐   |
| 4.4 | A edits a part or syncs a change that alters the graph                                                 | B's graph updates (existing behaviour — regression check)                                                                 | ☐   |
| 4.5 | A renames the project                                                                                  | B's project title updates                                                                                                 | ☐   |

## 5. Losing access mid-session

| #   | Step                                                                         | Expected                                                                                                                          | ☐   |
| --- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | B has "Live Bench" open in Workspace. A removes B from the team              | Within **30 s**, B's workspace shows "Live updates unavailable…" and receives no more updates; B's Home no longer lists "QA Live" | ☐   |
| 5.2 | Re-add B (invite + accept). B reopens the project                            | Live updates work again                                                                                                           | ☐   |
| 5.3 | A deletes project "Live 2b" while B has it open                              | B's live updates for it stop with the unavailable state                                                                           | ☐   |
| 5.4 | A deletes the whole team "QA Live" (use a throwaway team) while B is on Home | The team disappears from B's switcher within a few seconds                                                                        | ☐   |

## 6. Isolation (must never leak)

| #   | Step                                                                                              | Expected                                                                                                           | ☐   |
| --- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --- |
| 6.1 | C (not in "QA Live") on Home. A renames a project, changes roles, invites someone                 | **Nothing** changes in C's window, ever                                                                            | ☐   |
| 6.2 | In C's window DevTools → Network, open `users/me/events` and watch the event stream while A works | No frames mentioning A's team id appear                                                                            | ☐   |
| 6.3 | Inspect any frame in B's stream                                                                   | Frames contain only ids, counts, versions and timestamps — **no** names, emails, invite links or notification text | ☐   |

## 7. Connection resilience

| #   | Step                                                                             | Expected                                                                                                                | ☐   |
| --- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --- |
| 7.1 | Stop the API for ~20 s, then start it                                            | Both apps keep working; within ~30 s of restart, live updates resume without user action; everything shown is refreshed | ☐   |
| 7.2 | Turn Wi-Fi off on B for 30 s, make changes on A, turn Wi-Fi back on              | B catches up to A's changes after reconnecting                                                                          | ☐   |
| 7.3 | Leave both apps idle and live for **over one hour** (token refresh)              | Live updates still work afterwards; workspace does **not** show "Live updates unavailable…" (see Known risks)           | ☐   |
| 7.4 | Sign B out, sign in as C in the same window                                      | No events from B's teams appear for C                                                                                   | ☐   |
| 7.5 | Open 9+ windows/tabs for the same account (or ask an engineer to open 9 streams) | The 9th stream is refused (429); the app backs off rather than retrying in a tight loop                                 | ☐   |

## 8. Without Redis (single process)

| #   | Step                                         | Expected                                                    | ☐   |
| --- | -------------------------------------------- | ----------------------------------------------------------- | --- |
| 8.1 | Restart the API with `SOLUS_REDIS_URL` empty | `/readyz` → `live_fanout: "local_only"`; API logs a warning | ☐   |
| 8.2 | Repeat 1.1 and 4.1                           | Still works (single API process)                            | ☐   |

## Cross-feature regressions

| #   | Check                                                                       | ☐   |
| --- | --------------------------------------------------------------------------- | --- |
| X.1 | Bench / hardware "devices changed" detection still updates in the Workspace | ☐   |
| X.2 | SOL chat responses still stream normally                                    | ☐   |
| X.3 | Billing screen still refreshes the notification bell after checkout         | ☐   |
| X.4 | No toasts appear for any teammate change anywhere                           | ☐   |

## Known risks to watch

- **7.3 hourly token refresh:** the server ends a stream when its token expires.
  If the app hasn't already reconnected with a refreshed token, the workspace may
  show "Live updates unavailable…" until the project is reopened. Record exactly
  what happens and the time.
- Updates for the sources list when **no project is open** rely on a 60 s
  background refresh, not instant push.
