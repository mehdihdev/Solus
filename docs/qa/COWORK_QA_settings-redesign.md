# Cowork QA — Settings redesign (SOLUSDEV-318)

Test plan for the redesigned desktop Settings screen. It assumes you have the
running Solus desktop app and this file, and nothing else. Mark each box
**pass** or **fail**, and give one line of detail for every fail.

## Setup

- [ ] Solus desktop app is built from branch `SOLUSDEV-318-settings-redesign` and running (`pnpm dev:all`).
- [ ] The API is running and reachable (the Bridge pill is not the issue here, but Settings must not show "can't reach its API").
- [ ] **Account A**: a signed-in user on a **Basic trial ending within 14 days**, with at least one **connected GitHub** account and one **Onshape** account. Owner of a non-personal team named e.g. "QA Robotics" that has ≥2 members.
- [ ] **Account B**: a **member** (not owner/admin) of the same team.
- [ ] On macOS: **System Settings › Privacy & Security › Screen & System Audio Recording**. To test the "blocked" path, Solus must be **off** there.
- [ ] Optional: an Onshape document with the Solus panel open, to produce a pairing code.

---

## 1. Layout and navigation

1. [ ] Open **Settings** from the left rail. **Expect:** title "Settings" with the Solus logo, a sidebar with **Find a setting**, groups **YOU / WORKSPACE / SYSTEM**, and the page on the right.
2. [ ] Click every sidebar entry in turn. **Expect:** the page scrolls so that section's card sits at the top. The app does **not** navigate away, and the URL hash does not change to the section name.
3. [ ] Narrow the window to about 760 px. **Expect:** the sidebar stacks above the page, with nothing clipped and no horizontal scroll.
4. [ ] Look for "Density". **Expect:** it appears nowhere.
5. [ ] Look for a separate "Onshape panel" card, an "Integrations" list showing AVAILABLE, or a note about the Onshape panel. **Expect:** none of them exist.
6. [ ] On a wide window, scroll the page. **Expect:** the sidebar stays pinned in place, and the entry for the section at the top of the view is highlighted, moving as you scroll. On a narrow (stacked) window the sidebar is **not** pinned.
7. [ ] Reopen Settings. **Expect:** the sections ease in, staggered, with no jumps. With macOS **Reduce motion** on, everything appears instantly.

## 2. Find a setting

1. [ ] Type `theme`. **Expect:** only **Appearance** remains, in both the sidebar and the page, and the attention cards are hidden.
2. [ ] Type `terms`. **Expect:** only **About & legal**.
3. [ ] Type `credits`, then `onshape`, then `delete`. **Expect:** Plan & usage, then Connected tools, then Privacy & data.
4. [ ] Type `zzzz`. **Expect:** "No settings match “zzzz”." in the sidebar, and no sections.
5. [ ] Clear the box. **Expect:** everything is back, including the attention cards.

## 3. Needs attention (Account A)

1. [ ] With macOS Screen Recording **off** for Solus and **SOL sees your screen** on, open Settings. **Expect:** the top card reads **"SOL can't see your screen yet"** and shows the platform message, the mono path `System Settings › Privacy & Security › Screen Recording › Solus`, and three buttons. The sidebar's **Needs attention** shows the card count.
2. [ ] Turn **SOL sees your screen** off (the card collapses out smoothly), then on again. **Expect:** the card **expands in** smoothly at the top, and the sidebar's Needs attention entry slides in with it.
3. [ ] Click **Open Screen Recording settings**. **Expect:** macOS System Settings opens on the Screen Recording pane. Nothing opens in a browser.
4. [ ] Turn Solus on in that pane, return to Solus and click **Recheck**. **Expect:** the card disappears and the count drops. (macOS may require relaunching Solus. If so, relaunch and expect the card to be gone.)
5. [ ] Turn the permission off again. In Settings, click **Turn off screen capture**. **Expect:** the card disappears and the _SOL sees your screen_ switch is off.
6. [ ] With the switch **off** and the permission **off**, **expect** no capture card ("off means SOL never captures").
7. [ ] Trial card: **expect** "Your trial ends in N days" (N ≤ 14). Click **Choose a plan**. **Expect:** the Billing page opens.
8. [ ] Make one connected account's token invalid (revoke the OAuth app on the provider side, then trigger a sync), then reopen Settings. **Expect:** a card titled "Reconnect &lt;Provider&gt; (@login)". **Reconnect** opens Home on **Connected accounts**.
9. [ ] On a paid account whose accounts are all healthy and whose permission is granted, **expect** no attention cards and no sidebar Needs attention entry.

## 4. SOL section

1. [ ] **Answer mode**: switch Guide ↔ Expert, then reopen Settings. **Expect:** the choice persists, and SOL replies in that mode.
2. [ ] **Action mode**: Guide ↔ Build. **Expect:** the tray menu reflects it.
3. [ ] Each row shows its explanation **under the label**, with no full-width text under the switch.
4. [ ] With capture blocked and the setting on, **expect** a `PERMISSION NEEDED` tag beside _SOL sees your screen_. **How to fix** scrolls to the attention card.
5. [ ] **Hold-Ctrl gestures** off → double-tap Ctrl does nothing; on → it summons SOL.

## 5. Appearance

1. [ ] Click each theme tile. **Expect:** the whole app re-skins instantly, and the selected tile has an accent border.
2. [ ] Click each accent swatch. **Expect:** the accent colour changes app-wide.
3. [ ] Restart the app. **Expect:** the theme and accent persist.

## 6. Plan & usage

1. [ ] **Expect:** the plan name, a trial line ("Trial ends in N days"), and tiles for **Credits** (a number), **Projects**, **Integrations** and **Teams** ("Up to N" or "Unlimited").
2. [ ] Click **Open Billing →**. **Expect:** the Billing page.
3. [ ] With the credits endpoint failing (stop the API after load, then reopen Settings), **expect** Credits to show "—", never 0.

## 7. Connected tools

1. [ ] **Expect:** one row per linked account (GitHub, Onshape…), each led by the **same logo Home's Connected accounts shows** for that tool, with "@login · used in N projects" and a status word (CONNECTED / RECONNECT / ERROR / DEGRADED / PENDING).
2. [ ] Click **Manage connected accounts →**. **Expect:** Home opens directly on **Connected accounts**, not the project pane.
3. [ ] On an account with **no** linked tools, **expect** "No tool accounts are connected yet…". **Connect a tool** opens Home › Connected accounts.
4. [ ] Revoke an account on Home, then return to Settings. **Expect:** it is gone from the list.

## 8. Onshape panel pairing (moved to Home)

1. [ ] Open Home › Connected accounts, **Mechanical** tab. **Expect:** an **Onshape panel** card under the accounts card, with a **Pairing code** field and **Link panel**.
2. [ ] Switch to the **Software** tab. **Expect:** the pairing card is not shown.
3. [ ] Enter the code from the Onshape panel and click **Link panel**. **Expect:** the panel links and a row appears with "never used" / "last used …" and **Revoke**.
4. [ ] Enter a wrong or expired code. **Expect:** "That code is not valid, or it expired…".
5. [ ] Click **Revoke** on a linked panel. **Expect:** the row disappears.

## 9. Team (Account A = owner, Account B = member)

1. [ ] **Expect** a summary: the team name, "You're an Owner · N members", **Edit team** and **Open team page →**.
2. [ ] **Open team page →**. **Expect:** Home opens on **Members**.
3. [ ] **Edit team** (owner): rename the team and **Save**. **Expect:** the new name everywhere. Toggle **Notify team on new projects**, and expect it to persist.
4. [ ] **Delete team** (owner, non-personal): **expect** the confirm dialog to name the team and "every project in it". **Cancel** leaves the team in place.
5. [ ] As **Account B** (member): **Edit team** shows the name read-only and no **Delete team**.
6. [ ] On a **personal** workspace: the summary reads "Your personal workspace — just you.", with no Delete team.
7. [ ] With 2+ teams, **expect** a **Your teams** list showing every team you belong to, with its role, `PERSONAL` on the personal one, and `CURRENT` on the active one (which has no Switch button).
8. [ ] Click **Switch** on another team. **Expect:** it becomes `CURRENT`, the summary and Edit team now show that team, and Home's team selector agrees. If the open project belonged to the old team it closes.
9. [ ] **Edit team** open/close. **Expect:** it expands and collapses smoothly, with no jump.

## 10. Privacy & data

1. [ ] **Usage data** switch: toggle it and reopen Settings. **Expect:** the state persists.
2. [ ] **Read the Privacy Policy ↗** opens `https://solusforge.com/privacy-policy` in the system browser.
3. [ ] **Delete account**: the first click shows the confirmation text plus Cancel / Delete account. **Cancel** restores it. (Only on a disposable account: confirm, and expect sign-out to the landing page.)
4. [ ] As the sole owner of a shared team, confirm delete. **Expect:** "You solely own 1 shared team. Transfer ownership…", and you stay signed in.

## 11. About & legal

1. [ ] **Terms of Service**, **Privacy Policy** and **Contact support** open `https://solusforge.com/terms-of-service`, `/privacy-policy` and `/contact` in the **system browser**, not inside Solus.
2. [ ] **Expect** `Solus <version>` under the links, matching the app's version.

## 12. Offline / signed-out

1. [ ] Stop the API and reopen Settings. **Expect:** SOL, How you engineer, Appearance, About & legal (and Developer in the desktop app), ending with "You're signed in, but Solus can't reach its API…". Profile, Plan, Connected tools, Team and Privacy are absent, and so are their sidebar entries.
2. [ ] The **Answer mode** toggle still works offline (local only).

## 13. Developer (desktop only)

1. [ ] **Developer** is present in the desktop app and absent in a browser preview. **Load unpacked extension…** works as before.

## Cross-feature checks

- [ ] Billing page rows (Renews, Trial ends, Card, Credits, Seats) still look as before. They share the Settings row component.
- [ ] Home opened normally (from the rail, not from Settings) still opens on the project pane.
- [ ] The tray's _SOL sees your screen_ checkbox and Settings stay in sync both ways.
