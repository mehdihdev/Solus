# Cowork QA — SOLUSDEV-114: Sources page crash on structured sync errors

Bugfix QA plan. The Sources page previously **white-screened the entire desktop app** whenever the open project had a source whose last sync/connect attempt failed (the API returns `last_error` as a `{code, message}` object; the renderer rendered the raw object as a React child). This pass verifies the page now renders error'd sources correctly and never crashes.

## Required setup state

- [ ] Full stack running: `pnpm dev:all` (Postgres in Docker, API on `127.0.0.1:8000`, Electron desktop app) with real Supabase auth configured (`apps/desktop/.env` has `VITE_SUPABASE_*`).
- [ ] A signed-in account that owns a team and at least one project.
- [ ] The open project has **at least one source in `error` status with a non-null `last_error`**. Easiest real path (post-SOLUSDEV-252 — the S-expression `.net` is now accepted and the app blocks `.kicad_sch` picks client-side): `POST /api/v1/projects/{id}/sources` with `{"type":"kicad","name":"Arduino_hat","config":{"export":"(kicad_sch (version 20250114))"}}` then trigger a sync — the connector rejects it and records `{code: "export_format_unsupported", message: "kicad: a .kicad_sch schematic can't be read directly yet …"}`.
- [ ] Also have one healthy source (e.g. a connected GitHub repo) to verify mixed lists.

## Flow 1 — Sources page renders with an error'd source (the regression)

1. Sign in, open the project (Home → project card). **Expected:** project hub Overview loads.
2. Click **Sources** in the left icon rail. **Expected:** the Sources page renders — no white screen, no blank app, no dev-tools console error `Objects are not valid as a React child`.
3. Find the error'd source row (e.g. `Arduino_hat`). **Expected:** red status dot, status text `ERROR`, and the human-readable error **message** in red under the source name (e.g. "kicad: a .kicad_sch schematic can't be read directly yet (no pin-level connectivity without KiCad's own netlister). Export a netlist from KiCad … or provide the .kicad_pcb board file."). It must be the message text, **not** `[object Object]` and not JSON like `{"code": …}`.
4. Verify the healthy source row still shows its type, "Synced … ago" time, and entity count.
5. Navigate away (Overview, Context Model) and back to Sources. **Expected:** stable every time.

## Flow 2 — Error'd source actions still work

1. On the error'd source row click **Sync now**. **Expected:** no crash; row refreshes (stays `ERROR` with the same message if the stored export is still bad).
2. Click **Disconnect** on the error'd source. **Expected:** confirm modal appears stating synced data is kept; confirming removes the row; app stays up.

## Flow 3 — Regression sweep around the page

1. With the error'd source present, check every other surface that lists project data: project **Overview**, **Home**, notifications bell. **Expected:** none of them crash or show `[object Object]`.
2. Offline path: stop the API (`Ctrl+C` uvicorn), reload the app, open Sources. **Expected:** honest offline note ("Solus can't reach its API right now…"), connect catalog still renders.
3. Empty path: open a project with no sources. **Expected:** "No tools connected yet." card + connect catalog.

## Edge cases

- [ ] Source with `last_error` present but status back to `connected` after a later successful sync — message should be gone (API clears `last_error` on success).
- [ ] Very long error message — row should wrap/contain it without breaking layout; page scrolls, app remains responsive.
- [ ] Two error'd sources at once — both rows render their own messages.

## Pass/fail checklist

- [ ] Flow 1 (crash regression) — PASS / FAIL
- [ ] Flow 2 (actions on error'd source) — PASS / FAIL
- [ ] Flow 3 (surrounding surfaces + offline/empty) — PASS / FAIL
- [ ] Edge cases — PASS / FAIL
