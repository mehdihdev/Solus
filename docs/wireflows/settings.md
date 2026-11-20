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
4. **Local tools need setup** (desktop app only, SOLUSDEV-329): one card when any
   fork the companion reports `needs_setup:*` (`docs/architecture/mcp-fork-runtime.md`
   §5) and setup is not running. Lists the affected tools by display name (KiCad,
   Code, …). `Set up local tools` scrolls to _Python for local tools_ and starts
   Install/Repair; it never starts silently.

## Sections

| Section                | Shown when                       | Content                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ---------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Profile                | online                           | Avatar, display name (save), email.                                                                                                                                                                                                                                                                                                                                                                                              |
| SOL                    | always                           | Answer mode (ADR-016, backend-persisted; local-only when offline). In the desktop app it also has Action mode, _SOL sees your screen_ (with a `PERMISSION NEEDED` tag + `How to fix` while blocked) and Hold-Ctrl gestures. Every row carries its description under the label. In the browser: "Available in the desktop app".                                                                                                   |
| How you engineer       | always                           | The HOME H3 document card (unchanged).                                                                                                                                                                                                                                                                                                                                                                                           |
| Appearance             | always                           | Theme tiles drawn in each preset's own tokens, plus accent swatches. **Density removed**: nothing read it.                                                                                                                                                                                                                                                                                                                       |
| Plan & usage           | online                           | Plan, trial/status, credit balance (`—` if unknown, `Unlimited`), each plan limit. `Open Billing →`. Card, invoices, packs and plan changes stay on Billing.                                                                                                                                                                                                                                                                     |
| Connected tools        | online and connections reachable | Each live account grant with the **same brand logo as Home › Connected accounts** (`ProviderMark`, letter-mark fallback), its real status (Connected / Reconnect / Error / Degraded / Pending) and the projects using it. `Manage connected accounts →` (or `Connect a tool` when there are none) goes to Home › Connected accounts.                                                                                             |
| Team                   | team ready                       | Summary of the current team: name, your role, member count. `Open team page →` goes to Home › Members. `Edit team` discloses rename (owner/admin), notify-on-new-project, and the owner danger zone (non-personal only). With more than one team, **Your teams** lists every team you belong to (role, `PERSONAL`, `CURRENT`), and `Switch` makes another team current through the shared team-switch path (surface `settings`). |
| Privacy & data         | online                           | Usage-data consent switch (ADR-011) with the Privacy Policy link, plus the delete-account danger row (two-step confirm; 409 ownership block surfaced).                                                                                                                                                                                                                                                                           |
| Python for local tools | desktop app only                 | The interpreter the local tools (KiCad, Code, Local, Altium, Gazebo, Isaac) run on, and their setup state. Flow below.                                                                                                                                                                                                                                                                                                           |
| Developer              | desktop app only                 | Unchanged (SOLUSDEV-235).                                                                                                                                                                                                                                                                                                                                                                                                        |
| About & legal          | always                           | Terms of Service, Privacy Policy and Contact support on solusforge.com (`/terms-of-service`, `/privacy-policy`, `/contact`), opened in the system browser. Shows the app version in the desktop app.                                                                                                                                                                                                                             |

When the page is offline it ends with the sign-in / API-unreachable notice.

### Python for local tools (SOLUSDEV-329)

Governing doc: `docs/architecture/mcp-fork-runtime.md` (CLI §6, IPC §9, events §10).
Works offline except Install/Repair and the managed download, which need PyPI / GitHub.

```
┌ Python for local tools ─────────────────────────────────────────┐
│ Python   ● /opt/homebrew/bin/python3.12   3.12.7  [Choose…]     │
│          ○ /usr/local/bin/python3.13      3.13.1                │
│          ○ Solus-managed Python 3.12                            │
│ Tools    KiCad ✓  Code ✓  Local ✓  Altium — (Windows only)     │
│          [Repair]                                               │
└─────────────────────────────────────────────────────────────────┘
```

| State            | Shows                                                                                                                                                                                                                                                            |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Detecting        | Skeleton row while `mcpRuntime:detect` and `mcpRuntime:status` run.                                                                                                                                                                                              |
| None found       | "No Python 3.12 or 3.13 found." Managed offer: what it is (Python 3.12 from python-build-standalone, ~30 MB, stored in Solus's app-data folder), `Install Python for Solus` (consent) and `Not now`. Also `Choose…`.                                             |
| Candidates       | Radio list of detected interpreters (supported first, path in mono, version) plus the managed option. Unsupported ones are listed dimmed with the reason (e.g. "3.11 — Solus needs 3.12 or 3.13"). `Choose…` opens a file picker; the pick is re-probed in main. |
| Unsupported pick | Inline error under the row with the reason code's message; the choice is not saved.                                                                                                                                                                              |
| Installing       | Per-tool progress (step + count from `mcpRuntime:progress`), `Cancel`. Other rows disabled.                                                                                                                                                                      |
| Partial / failed | Each failed tool shows its message (redacted, no paths) and a fix hint for its code (`network_unreachable` → check connection; `venv_copies_unhealthy` → offer the managed Python). `Repair` re-runs only the failed tools.                                      |
| Ready            | Each tool ✓, with the base version. Tools not for this OS read "— (Windows only)" etc.                                                                                                                                                                           |

- Choosing an interpreter saves `mcp_runtime` and then offers `Set up now`; a changed
  choice marks every tool `needs setup` until it is rebuilt.
- Copy follows the SOL mode setting (ADR-016). **Guide**: one plain sentence per
  state on what Python is for here and why the step is needed, plus a "Learn more"
  control that expands in-app text in place (no docs URL yet). **Expert**: the state, the code and the action only.
- Events: `python_tools.interpreter_chosen`, `python_tools.managed_consent`,
  `python_tools.setup_finished` (API.md §2.13).

## Moved out

- **Onshape panel pairing** moved to Home › Connected accounts (SOLUSDEV-318) and was then
  removed from the desktop app entirely (SOLUSDEV-325, `docs/wireflows/home.md`).
- **Integrations catalog** (the "AVAILABLE" rows) has been replaced by Connected tools.
- **Account** is no longer its own card. Delete account is a row in Privacy & data.
