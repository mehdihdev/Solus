# Settings (SOLUSDEV-318, design A)

The desktop Settings screen: a sidebar beside one scrolling page. It replaces the
SOLUSDEV-86 single column of cards. Settings changes the user's own preferences
and summarises the things that are managed elsewhere (Billing, the team, tool
accounts), each with one way out.

Design source: the "Solus Settings Redesign" canvas, direction A.

## Layout

```
┌───────────────────┬───────────────────────────────────────────────┐
│ [logo] Settings   │ ┌ Needs attention ─────────────────────────┐ │
│ [ Find a setting ]│ │ ⚠ SOL can't see your screen yet          │ │
│ [Needs attention 2]│ │   message · System Settings › … (mono)  │ │
│ YOU               │ │   [Open Screen Recording settings]       │ │
│   Profile         │ │   [Recheck]  [Turn off screen capture]   │ │
│   SOL             │ └──────────────────────────────────────────┘ │
│   How you engineer│ Profile · SOL · How you engineer · Appearance │
│   Appearance      │ Plan & usage · Connected tools · Team         │
│ WORKSPACE         │ Privacy & data · Developer · About & legal    │
│   Plan & usage …  │                                               │
│ SYSTEM            │                                               │
│   Privacy & data …│                                               │
└───────────────────┴───────────────────────────────────────────────┘
```

- The sidebar wraps above the page when the window is narrow. When it sits beside
  the page it is **pinned** (sticky) while the page scrolls, and the entry for the
  section in view is highlighted (scroll-spy).
- Sidebar entries are buttons that scroll the page to the section. They are never
  `#hash` links, because the HashRouter would treat the hash as a route.
- **Find a setting** filters the sidebar and the page together, matching on titles
  and keywords (`settingsSections.constants.ts`). While a query is active the
  attention cards are hidden. No match reads "No settings match “…”."
- The sidebar lists only the sections the page shows right now.

## Motion

Motion follows Home's house rules (`settings.css`): it is short and eased, and it is
switched off entirely under `prefers-reduced-motion`.

- **Attention cards expand in** when a problem appears, for example turning on _SOL
  sees your screen_ without the permission. They **collapse out** once it is fixed.
  The sidebar's Needs-attention entry does the same.
- Sections ease in on first paint (staggered), and again when they come back from a
  filter.
- The `Edit team` disclosure expands and collapses.
- Team and tool rows ease in, staggered.
- Theme tiles and swatches ease their selection and give slightly on press.
- The `PERMISSION NEEDED` tag fades in.

## Needs attention

These cards sit at the top of the page, and the sidebar entry shows their count.
They are derived in `attention.ts`, in this order:

1. **Capture blocked**: shown only while _SOL sees your screen_ is on and capture is
   unavailable. The card shows the platform message. On macOS it also shows the
   System Settings path and `Open Screen Recording settings`, which runs over IPC.
   Main opens only its own capability URL, allowlisted. `Recheck` re-reads the SOL
   state, and capture is re-probed on every read. `Turn off screen capture` sets the
   setting off.
2. **Trial ending**: shown when 14 days or fewer are left, or once the trial has
   ended. `Choose a plan` goes to Billing.
3. **Reconnect**: one card per account grant with `needs_reauth` or
   `health: token_expired`. Revoked grants are skipped. `Reconnect` goes to Home ›
   Connected accounts.

## Sections

| Section          | Shown when                       | Content                                                                                                                                                                                                                                                                                                                        |
| ---------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Profile          | online                           | Avatar, display name (save), email.                                                                                                                                                                                                                                                                                            |
| SOL              | always                           | Answer mode (ADR-016, backend-persisted; local-only when offline). In the desktop app it also has Action mode, _SOL sees your screen_ (with a `PERMISSION NEEDED` tag + `How to fix` while blocked) and Hold-Ctrl gestures. Every row carries its description under the label. In the browser: "Available in the desktop app". |
| How you engineer | always                           | The HOME H3 document card (unchanged).                                                                                                                                                                                                                                                                                         |
| Appearance       | always                           | Theme tiles drawn in each preset's own tokens, plus accent swatches. **Density removed**: nothing read it.                                                                                                                                                                                                                     |
| Plan & usage     | online                           | Plan, trial/status, credit balance (`—` if unknown, `Unlimited`), each plan limit. `Open Billing →`. Card, invoices, packs and plan changes stay on Billing.                                                                                                                                                                   |
| Connected tools  | online and connections reachable | Each live account grant with the **same brand logo as Home › Connected accounts** (`ProviderMark`, letter-mark fallback), its real status (Connected / Reconnect / Error / Degraded / Pending) and the projects using it. `Manage connected accounts →` (or `Connect a tool` when there are none) goes to Home › Connected accounts.                                |
| Team             | team ready                       | Summary of the current team: name, your role, member count. `Open team page →` goes to Home › Members. `Edit team` discloses rename (owner/admin), notify-on-new-project, and the owner danger zone (non-personal only). With more than one team, **Your teams** lists every team you belong to (role, `PERSONAL`, `CURRENT`), and `Switch` makes another team current through the shared team-switch path (surface `settings`).                                                                                                                           |
| Privacy & data   | online                           | Usage-data consent switch (ADR-011) with the Privacy Policy link, plus the delete-account danger row (two-step confirm; 409 ownership block surfaced).                                                                                                                                                                         |
| Developer        | desktop app only                 | Unchanged (SOLUSDEV-235).                                                                                                                                                                                                                                                                                                      |
| About & legal    | always                           | Terms of Service, Privacy Policy and Contact support on solusforge.com (`/terms-of-service`, `/privacy-policy`, `/contact`), opened in the system browser. Shows the app version in the desktop app.                                                                                                                           |

When the page is offline it ends with the sign-in / API-unreachable notice.

## Moved out

- **Onshape panel pairing** now lives in Home › Connected accounts, on the Mechanical
  tab (`docs/wireflows/home.md`).
- **Integrations catalog** (the "AVAILABLE" rows) has been replaced by Connected tools.
- **Account** is no longer its own card. Delete account is a row in Privacy & data.
