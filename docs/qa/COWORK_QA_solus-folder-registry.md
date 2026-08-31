# Cowork QA — ~/.solus Project Registry (SOLUSDEV-166, Ticket A)

Feature under test: the machine-local `~/.solus/projects.json` registry. Linking a project to a
local folder in the desktop app now (a) persists the link in `~/.solus/projects.json` where the
Electron main process can read it, and (b) feeds `SOLUS_COMPANION_WORKSPACE` to the local bridge
companion at spawn, which unblocks workspace-gated MCP forks (Altium). The renderer's old
localStorage copy still exists but is now only a display cache.

## Required setup

1. The Solus desktop app running in dev (`pnpm dev` in `apps/desktop`) on macOS or Linux, with:
   - `SOLUS_COMPANION_DEV_CMD` set (so the companion spawns), e.g.
     `uv run python -m solus_companion`, and the API running locally.
   - A signed-in user with at least one project.
2. A second project (for cross-project checks).
3. A local git repo URL you can clone (any small public repo works).
4. A terminal for inspecting `~/.solus` (`ls -la ~/.solus`, `cat ~/.solus/projects.json`).

## Flow 1 — link a folder, registry persists

| #   | Step                                                       | Expected                                                                                                            | Pass/Fail |
| --- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | --------- |
| 1   | Open a project's Overview page; find the local folder card | Card offers "Select folder" and "Clone a repo"                                                                      |           |
| 2   | Click Select folder; choose an existing directory          | Card shows the chosen path                                                                                          |           |
| 3   | In a terminal: `cat ~/.solus/projects.json`                | JSON with `"schema_version": 1` and an entry for this project id: `path` = chosen dir, `lastOpenedAt` ISO timestamp |           |
| 4   | `ls -ld ~/.solus`                                          | Permissions `drwx------` (0700)                                                                                     |           |
| 5   | `ls -l ~/.solus/projects.json`                             | Mode `-rw-------` (0600)                                                                                            |           |

## Flow 2 — the registry survives what localStorage doesn't

| #   | Step                                                                                                                         | Expected                                                                                 | Pass/Fail |
| --- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------- |
| 1   | With a folder linked (Flow 1), quit the app                                                                                  | —                                                                                        |           |
| 2   | Clear the renderer's localStorage (DevTools → Application → Local Storage → clear, or delete the app's userData web storage) | —                                                                                        |           |
| 3   | Relaunch the app; open the same project                                                                                      | The folder card shows the linked path again (hydrated from `~/.solus`, not localStorage) |           |

## Flow 3 — unlink removes the entry

| #   | Step                                  | Expected                                                             | Pass/Fail |
| --- | ------------------------------------- | -------------------------------------------------------------------- | --------- |
| 1   | On the folder card, unlink the folder | Card returns to "Select folder / Clone a repo"                       |           |
| 2   | `cat ~/.solus/projects.json`          | The project's entry is gone; other projects' entries (if any) remain |           |

## Flow 4 — clone path records the repo URL

| #   | Step                                                        | Expected                                                | Pass/Fail |
| --- | ----------------------------------------------------------- | ------------------------------------------------------- | --------- |
| 1   | Click "Clone a repo", paste the repo URL, pick a parent dir | Clone succeeds; card shows the new path                 |           |
| 2   | `cat ~/.solus/projects.json`                                | Entry has `path` AND `repoUrl` equal to what you pasted |           |

## Flow 5 — companion picks up the workspace (the Altium unblock)

| #   | Step                                                                                                                                         | Expected                                                                                                                                                         | Pass/Fail |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 1   | With the companion running and a project OPEN but NO folder linked, check the companion's environment (`ps eww <companion pid>` or its logs) | `SOLUS_COMPANION_WORKSPACE` absent; workspace-gated forks (altium) refuse to start with the "SOLUS_MCP_WORKSPACE is not set" message — failing closed is correct |           |
| 2   | Link a folder to the OPEN project (Flow 1)                                                                                                   | The companion process is REPLACED (new pid) shortly after                                                                                                        |           |
| 3   | Check the new companion's environment                                                                                                        | `SOLUS_COMPANION_WORKSPACE` = the linked path                                                                                                                    |           |
| 4   | If the Altium fork is installed with its `.venv` materialized                                                                                | The altium fork launches instead of refusing (it may still fail later for unrelated reasons — the refusal message disappearing is the pass condition)            |           |
| 5   | Unlink the folder                                                                                                                            | Companion replaced again; `SOLUS_COMPANION_WORKSPACE` absent in the new process                                                                                  |           |
| 6   | Link a folder to a DIFFERENT (not open) project                                                                                              | The running companion is NOT restarted (link of an inactive project is irrelevant to it)                                                                         |           |

## Flow 6 — cross-project and edge cases

| #   | Step                                                                                              | Expected                                                                                                          | Pass/Fail |
| --- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | --------- |
| 1   | Link folders in two different projects                                                            | Both entries present in `projects.json`, independently correct                                                    |           |
| 2   | Hand-edit `projects.json` to invalid JSON (`echo garbage > ~/.solus/projects.json`), relaunch app | App starts normally; folder cards show unlinked; next link REWRITES the file cleanly                              |           |
| 3   | Hand-edit `projects.json` to `{"schema_version": 99, "projects": {}}`, relaunch, link a folder    | UI updates (cache), but the FILE is left untouched (a newer schema version is read-only for this build); no crash |           |
| 4   | Not running under Electron (browser preview of the renderer)                                      | Folder card degrades to the "desktop app required" note; no errors from registry calls                            |           |
| 5   | `~/.solus/companion_id`                                                                           | Still present and unchanged by all of the above                                                                   |           |

## Cross-feature interactions

- **Bridge/companion (SOLUSDEV-154)**: token relay and project switching must still work after
  link/unlink respawns — switch projects while linked; the companion respawns and reconnects.
- **Sources connect wizard (SOLUSDEV-165)**: connecting sources is unaffected by folder linking.
- **Existing folder actions (SOLUSDEV-164)**: Reveal in file manager and Open in VSCode still work
  on a linked folder.

## Security spot-checks

- `~/.solus/projects.json` must never contain tokens, secrets, or anything beyond
  `schema_version`/`projects` with `path`/`repoUrl`/`lastOpenedAt`.
- The registry directory is `0700`; the file `0600`.
- Linking with a project id containing `/` or `..` is impossible through the UI; if exercised via
  devtools (`window.solus.folder.link('../x', {path:'/tmp'})`), it must return `{ok:false}` and
  write nothing.
