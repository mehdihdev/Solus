# COWORK QA — SOLUSDEV-311: desktop error boundaries

What changed: when part of the Solus desktop app breaks, only that part shows an explanation
card ("fallback"); the navigation rail and every other screen keep working. Errors are written
to a local log, sent to Sentry when a DSN is configured, and counted as a `client.error` data
event. Mark each check **PASS / FAIL** and note what you saw on FAIL.

## Setup

1. A checkout of branch `SOLUSDEV-311-desktop-error-boundaries`, dependencies installed
   (`pnpm install`), root `.env` present (Supabase keys set).
2. API running: `pnpm dev:api` (http://127.0.0.1:8000). Desktop running: `pnpm dev:desktop`.
   Keep the terminal running `dev:desktop` visible — it is where main-process logs print.
3. Signed in to the desktop app with a project open (any project; an empty one is fine).
4. DevTools: in the dev build press **F12** in the Solus window to open them (Console tab).
5. Log file location (macOS dev build): `~/Library/Logs/@solus/desktop/solus-errors.log`.
   Open a second terminal and run `tail -f ~/Library/Logs/@solus/desktop/solus-errors.log`.
6. Settings → SOL mode starts on **Guide** unless changed.

**Inducing a render error** (needed for sections A–C). Edit
`apps/desktop/src/renderer/src/features/bench/BenchScreen.tsx`: as the first line inside
`export function BenchScreen(...) {`, add

```ts
throw new TypeError("QA: temporary Bench throw");
```

and save. Remove that line again when a step says so, and **always before you finish**.

## A. A broken panel is contained (Guide mode)

| #   | Step                                                             | Expected                                                                                                                                                                                                                                                                                  | P/F |
| --- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| A1  | With the throw added, click **Live Bench** on the left rail.     | The Bench area shows a card titled **"Live Bench hit a problem"** with plain-language text saying only this panel stopped and the rest still works, ending "The error has been saved to Solus's error log." Buttons: **Reload panel**, **Reload app**, **Copy details**. No blank window. |     |
| A2  | Look at the left rail and the top bar.                           | Both are fully drawn and clickable.                                                                                                                                                                                                                                                       |     |
| A3  | Click **Workspace** on the rail.                                 | The Workspace screen renders normally (the `.solus` sections / graph).                                                                                                                                                                                                                    |     |
| A4  | Click **Home**, then **SOL**, then **Settings**.                 | Each renders normally.                                                                                                                                                                                                                                                                    |     |
| A5  | Click **Live Bench** again.                                      | The same fallback card appears again (still broken).                                                                                                                                                                                                                                      |     |
| A6  | Check the `dev:desktop` terminal.                                | A block starting `[solus:error] render bench TypeError: QA: temporary Bench throw (` followed by a 16-hex id, then a stack and a component stack.                                                                                                                                         |     |
| A7  | Check the `tail -f` log terminal.                                | A JSON line with `"origin":"render","surface":"bench"` and the same message. Revisiting Bench adds a short line with `"repeat":2` (no second full stack).                                                                                                                                 |     |
| A8  | In the log line, look for your macOS username or `/Users/<you>`. | Not present — paths show as `~/…`.                                                                                                                                                                                                                                                        |     |

## B. Recovery

| #   | Step                                                           | Expected                                                                                                                           | P/F |
| --- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | --- |
| B1  | While the fallback is showing, remove the throw line and save. | The fallback stays (it does not silently vanish).                                                                                  |     |
| B2  | Click **Reload panel**.                                        | The real Live Bench screen appears (title "Live Bench", Pause / Manage connections / Add hardware).                                |     |
| B3  | Re-add the throw, open Bench, click **Reload app**.            | The whole window reloads; you land back in the app signed in. Opening Bench shows the fallback again. Remove the throw afterwards. |     |

## C. Copy details and Expert mode

| #   | Step                                                                           | Expected                                                                                                                                                                                                        | P/F |
| --- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| C1  | With the fallback showing, click **Copy details**, paste into any text editor. | The button changes to **Copied**. Pasted text starts `Solus error report`, with `Where: Live Bench (bench)`, `When:` an ISO time, `Error: TypeError: QA: temporary Bench throw`, a stack and a component stack. |     |
| C2  | In the pasted text, look for your username / email.                            | Not present (`~` and `[email]` instead).                                                                                                                                                                        |     |
| C3  | Settings → switch SOL mode to **Expert**. Open Bench (throw still in place).   | Card title **"Live Bench crashed"**, one short line, and the error `TypeError: QA: temporary Bench throw` in red monospace. Same three buttons.                                                                 |     |
| C4  | Switch back to **Guide**. Remove the throw.                                    | Guide wording returns.                                                                                                                                                                                          |     |

## D. Errors a boundary cannot see

| #   | Step                                                                                                   | Expected                                                                                             | P/F |
| --- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | --- |
| D1  | No throw in Bench. In DevTools Console run `setTimeout(() => { throw new RangeError('QA timer') }, 0)` | App keeps working (no fallback, nothing blank). Log shows `"origin":"window_error"` with `QA timer`. |     |
| D2  | Run `Promise.reject(new Error('QA rejection'))`                                                        | App keeps working. Log shows `"origin":"unhandled_rejection"` with `QA rejection`.                   |     |
| D3  | Note the `"surface"` on D1/D2 lines.                                                                   | It is the last rail screen you opened (e.g. `bench`, `workspace`).                                   |     |
| D4  | DevTools Console (dev build).                                                                          | The errors also appear in the console — nothing is swallowed in development.                         |     |

## E. Data event (API)

| #   | Step                                                                                   | Expected                                                                                                  | P/F |
| --- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | --- |
| E1  | Watch the `dev:api` output while doing A1 on a fresh app start.                        | A line `event=client.error user=… team=… project=… consented=…` and `POST /api/v1/events … 202`.          |     |
| E2  | The API output / event payload.                                                        | Contains no error message or stack — only origin, surface, error name category, fingerprint, app version. |     |
| E3  | Trigger 25 different errors quickly (e.g. run D1 with 25 distinct messages in a loop). | At most 10 `client.error` events per minute reach the API; the app stays responsive.                      |     |
| E4  | Sign out, go to the login screen, and run D1.                                          | Logged locally; no event is accepted (no signed-in user).                                                 |     |

## F. Sentry (only if a DSN is configured)

Add `MAIN_VITE_SENTRY_DSN=<dsn>` to the repo-root `.env`, then restart `dev:desktop`.
Sentry only receives errors from a signed-in user who has **data-collection consent on**
(Settings → privacy / data collection toggle).

| #   | Step                         | Expected                                                                                                                                         | P/F |
| --- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| F1  | Do A1.                       | One issue appears in the Sentry project within ~1 min, tagged `origin: render`, `surface: bench`, with the React component stack under Contexts. |     |
| F2  | Open the issue.              | No user, no IP, no machine name, no breadcrumbs; paths show `~`.                                                                                 |     |
| F3  | Revisit Bench several times. | Still one event for this error in this session (repeats are not re-sent).                                                                        |     |
| F4  | Without a DSN.               | Everything in A–E still works; nothing about Sentry in the logs.                                                                                 |     |

## G. Other windows and edge cases

| #   | Step                                                                              | Expected                                                                                   | P/F |
| --- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --- |
| G1  | Open the SOL window (double-tap Ctrl, or Settings → hotkeys on). Use it normally. | Works as before.                                                                           |     |
| G2  | Use the Guide overlay (SOL Guide pointing at an external tool) if available.      | Works as before; the overlay never shows an error card over your screen.                   |     |
| G3  | Open Store and an installed extension page (e.g. BOM).                            | Render normally.                                                                           |     |
| G4  | Run the full flow A–D with the API stopped.                                       | Fallback, recovery and local logs all work; only the data event is missing.                |     |
| G5  | Delete `~/Library/Logs/@solus/desktop` while the app runs, then trigger D1.       | App keeps working; the terminal may print `could not write error log` but nothing crashes. |     |

## Cleanup

- [ ] The temporary throw in `BenchScreen.tsx` is removed (`git status` shows no change there).
- [ ] SOL mode set back to what it was.
