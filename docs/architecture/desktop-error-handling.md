# Desktop error handling (SOLUSDEV-311)

**Goal:** one bad component must never blank the whole app. A render error is contained to the
panel (or window) it happened in; every error — render, event-handler, async, main-process, a
renderer that dies — is reported once, scrubbed, to the local log and (when configured) Sentry,
and counted as a `client.error` data event. Scope: the Electron renderer and main process. The
companion has its own supervision.

## Flow

```
renderer                                   main                                  off-box
────────                                   ────                                  ───────
ErrorBoundary (render)  ─┐
window 'error'          ─┼─► errorReporter ──diag:report──► reportInput (validate)
'unhandledrejection'    ─┘   (1× per error      (sender-      → scrub → fingerprint
                              object; dev also   gated)         → dedupe + session cap
                              console.error)                    → errorLog  (stdout + solus-errors.log)
                                  ▲                             → Sentry sink (first sighting, if DSN) ──► Sentry
                                  │ ack {fingerprint, first, appVersion}
                                  └── first ⇒ client.error ─────────────────────────────► POST /api/v1/events

process 'uncaughtException' ─► crashHandlers: report → crash marker → flush → relaunch (≤1 / 60 s) or dialog + quit
process 'unhandledRejection' ─► report only
app 'render-process-gone'    ─► report → crash marker
next main renderer, signed in ── diag:take-crash-marker ──► one client.error for the prior crash
```

## Boundaries

| Where                         | Surface                                                                                            | Scope    | Fallback                                                                    |
| ----------------------------- | -------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------- |
| `main.tsx` root, every window | `root` / `sol_window` / `ext_window` (from the hash)                                               | `app`    | Reload app · Copy details                                                   |
| `main.tsx` root, `#/overlay`  | `overlay`                                                                                          | `silent` | nothing drawn (click-through window over the user's screen); still reported |
| `WorkspaceShell` `ScreenView` | the shell route: `home` `workspace` `bench` `sol` `store` `billing` `settings` `alert` `extension` | `panel`  | Reload panel · Reload app · Copy details                                    |

The panel boundary sits inside the route-keyed wrapper, so the nav rail is outside it and
navigating away and back also starts the screen fresh. **Reload panel** clears the boundary and
remounts the children; **Reload app** reloads the window.

Boundaries catch render errors only. Event-handler, timer and promise errors reach the same
reporter through the window's `error` / `unhandledrejection` events — not through try/catch.

## Wording (ADR-016)

The fallback reads `settingsStore.solMode`. **Guide** names the panel, says what happened and that
the rest of Solus (and the user's projects and tools) are unaffected, and what each button does.
**Expert** is a terse title plus the error line in mono. The log is mentioned only when the
desktop bridge exists (Empty beats invented).

## Privacy

- `scrub.ts` runs on every report before it is logged or sent — **before** any final
  truncation, so a token cut at a length limit cannot slip past as a fragment (transport
  limits are 4× the final ones). It redacts: JWTs (including partial ones), `Bearer` / `Basic`
  credentials, Stripe (`sk_`/`pk_`/`rk_`/`whsec_`), Supabase (`sb_secret_`/`sb_publishable_`),
  GitHub (`gh*_`, `github_pat_`), GitLab (`glpat-`, `gldt-`, `glrt-`, …), `sk-ant-`/`sk-proj-`
  and AWS access keys; credential-named values (`refresh_token`, `password`, `api_key`, …);
  emails (also `%40`); absolute **and relative** URL query strings and non-route fragments; and
  home paths (`/Users/*`, `/home/*`, `/root`, `C:\Users\*`, percent-encoded and JSON-escaped).
  "Copy details" uses the same scrubber. The console line additionally strips control
  characters and indents stacks, so a renderer cannot forge log lines.
- **Sentry is consent-gated** (human decision): main sends nothing until the main window tells
  it the signed-in user has data-collection consent (`diag:set-consent`, after sign-in and on
  every Settings change; `false` on sign-out). It starts closed, so errors before sign-in — and
  early-boot main crashes — stay local.
- Sentry runs **in main only** (the renderer CSP is unchanged), loaded lazily and only with a
  DSN: `sendDefaultPii: false`, breadcrumbs dropped, integrations allowlisted
  (`ElectronContext`, `EventFilters`, `FunctionToString`, `LinkedErrors`, `NormalizePaths`) —
  no minidumps (raw memory can hold tokens), local variables, console/net capture, screenshots
  or sessions. `beforeSend` strips `user`/`request`/`server_name` and re-scrubs. The SDK's own
  renderer-facing `ipcMain` channels (which check no sender, and the preload exposes raw
  `ipcRenderer`) are **removed right after init**, under a per-launch random namespace — no
  window can feed Sentry except through `diag:report`.
- The `client.error` event carries only closed categories and a hash — never the message or
  stack (API.md §2.13). Consent-gated server-side like every client event.

## Bounds

- Main: one full log entry and one Sentry event per fingerprint per session; repeats log one
  line with a count; 200 log entries and 50 Sentry events per session; at most 1,000
  fingerprints remembered (past that, new errors count as repeats).
- Renderer: `client.error` at most 10 per minute; best-effort, never retried.
- Log file: 1 MB, one rotation (`solus-errors.log.1`).
- `diag:report` admits only Solus app windows from their top frame (renderer URL match, never
  the checkout window); a secondary window's own surface overrides the one it claims.
  `diag:take-crash-marker` and `diag:set-consent` admit only the main window.
- Relaunch loop guard fails closed: if the relaunch time cannot be saved (read-only or full
  disk) Solus shows the dialog and quits instead of relaunching. The marker is written
  atomically (temp + rename).

## Configuration

| Key                            | Where                                                                 | Meaning                                                                 |
| ------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `MAIN_VITE_SENTRY_DSN`         | root `.env` (via `.env.mega`) — inlined into the main bundle at build | Sentry DSN; absent = no Sentry                                          |
| `SENTRY_DSN`                   | process env at runtime                                                | overrides the above in **development only** (a packaged app ignores it) |
| `MAIN_VITE_SENTRY_ENVIRONMENT` | root `.env`                                                           | environment tag; default `development` / `production` by build mode     |

Files: log in `app.getPath('logs')` (macOS `~/Library/Logs/<app>/solus-errors.log`); crash
marker in `app.getPath('userData')/solus-crash.json` (mode 0600).

## Known gaps

- A renderer that dies (`render-process-gone`) is reported but not auto-reloaded; the window
  stays blank until the user quits and reopens Solus (production builds ignore Cmd/Ctrl+R).
- Main-process `unhandledRejection` is reported only; it neither relaunches nor produces a
  `client.error` event (no marker), since main keeps running.
