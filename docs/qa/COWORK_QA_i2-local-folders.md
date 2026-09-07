# COWORK QA — INTEGRATIONS I2 · Local folders (SOLUSDEV-249)

Self-sufficient end-to-end test plan. You have the running application and this file only.

## Required setup

- API running on this machine (`packages/api`, `uv run uvicorn --factory solus_api.main:create_app`)
  against a migrated dev database (`alembic upgrade head` — includes `c7d8e9f0a1b2`).
- The desktop app in dev mode with a companion command
  (`SOLUS_COMPANION_DEV_CMD="uv run python -m solus_companion"`), signed in as a verified user who
  owns a team and a project.
- The vendored MCP forks materialised: `make mcp-forks` (on a Mac whose `python3.12` is the
  uv-managed build, run `SOLUS_MCP_FORK_PYTHON=~/.local/share/uv/python/cpython-3.12*/bin/python3.12
scripts/install-mcp-forks.sh`). `integrations/mcp/local/.venv/bin/python3` must exist.
- KiCad installed (`/Applications/KiCad/KiCad.app` on macOS) and VS Code installed.
- A scratch git clone with a KiCad project: e.g. `git clone https://github.com/<any public repo>`
  or `git init` a folder with `hw/main/main.kicad_pro`, `hw/main/main.kicad_sch`,
  `hw/main/main.kicad_pcb`, `fw/blink/blink.ino`, `cad/frame.step`, `tools/x.py`, and a remote:
  `git remote add origin git@github.com:org/repo.git`.
- For the repo-link check (flow 3): the SAME project must have a connected GitHub or GitLab source
  whose repository is `org/repo` (the clone's remote) and that has synced at least once.

## Flow 1 — link a folder; the graph derives the chain

1. Home › LOCAL FOLDER › **Select folder** → pick the clone.
   Expected: the path appears; under it "Scanning…" (shimmer) then "Scanned now". The companion
   respawns (Bridge chip may flicker) — within ~30 s.
2. Expected detected list: one row per tool project — `main` (Ki, `hw/main/main.kicad_pro`),
   `blink` (Ar), `cad` (CA), `<folder> (python)` (Py). Rows fade in staggered.
3. Workspace (rail) › Project overview: a `local clone` node containing the four project nodes
   (`4 inside`). Focus `main`: the inspector says `kicad_project` and shows **OPEN ON THIS
   MACHINE — Open in KiCad / Open in editor / Open**.
4. Connected accounts › **Software** tab: a row "Local folder · <your machine name>" with Sync now
   and Disconnect.
5. `GET /api/v1/projects/{id}/sources`: one source `type: local`, `config` =
   `{machine_id, machine_name, folder_name}` — **no path anywhere** in the response.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5

## Flow 2 — Open in [tool]

1. Card row `main` › **Open in KiCad**. Expected: KiCad launches on `hw/main/main.kicad_pro`
   (its project manager opens that project). Response is immediate; no browser, no dialog.
2. Card › **Open in editor**. Expected: VS Code opens the folder.
3. Row `blink` › **Open**. Expected: the OS default app for `.ino` opens it.
4. Quit the companion (Bridge chip → offline, e.g. stop the API for 10 s or kill
   `python -m solus_companion`). Expected: every Open button is DISABLED with the tooltip/note
   "Solus companion is offline on this machine" — never hidden. Restart: buttons re-enable.
5. On a machine WITHOUT KiCad: the KiCad row shows no "Open in KiCad" button (only editor/Open).

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5

## Flow 3 — the clone links to its repo

1. With the GitHub/GitLab source from setup connected in the same project, link the clone (or
   Sync now on the local source). Expected in Workspace: the cross-links strip lists
   `<folder> clone_of <repo>`; the `code repo` node and the `local clone` node are joined.
2. Change the clone's remote (`git remote set-url origin git@github.com:other/repo.git`), edit any
   `.kicad_sch` (to trigger a re-scan). Expected: the `clone_of` link disappears within ~30 s;
   nothing else in the graph changes.
3. No matching source at all: no link, no error — the clone node's `remote` property still shows
   `org/repo`.

- [ ] 1 · [ ] 2 · [ ] 3

## Flow 4 — the watch: an edit re-syncs exactly once

1. Note the sync count: `GET /api/v1/projects/{id}/sources/{local_source_id}/syncs`.
2. Append a line to `hw/main/main.kicad_sch`; wait 45 s. Expected: exactly ONE new sync
   (`status: succeeded`, `trigger: webhook`); "Scanned <n>s ago" refreshes.
3. Wait another 45 s without editing. Expected: no further sync.
4. Press **Sync now** twice quickly on the Software row. Expected: the second answers
   `409 sync_in_progress` or is a cheap skip (no second scan); the sync list grows by at most one
   `skipped`/`succeeded` entry with zero created/updated.
5. Touch a file that is NOT a design/code file (e.g. `README.md`). Expected: no re-sync (the
   doorbell watches design suffixes only).

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5

## Flow 5 — unlink, relink, second machine

1. Card › **Unlink**. Expected: the card returns to Select folder / Clone a repo; the Software row
   disappears; the graph's local nodes are tombstoned (Workspace no longer shows the clone).
2. Relink the same folder. Expected: the same source row is reused (same id in
   `GET /sources`), status connected, nodes back.
3. Sign in on a SECOND machine (or clear `~/.solus/companion_id` to simulate one) and link a
   folder to the same project. Expected: TWO local sources, each named after its machine; each
   machine's card shows only its own folder; "Open" on machine A never launches on B.
4. As a teammate (another account, same project) press Sync now on YOUR local source.
   Expected: the sync records `api_unreachable` ("this machine's Solus companion is not
   connected") — never their machine's contents.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Edge cases and failure paths

- Link a folder with NO recognisable files: "Nothing Solus recognises in this folder yet (KiCad,
  Altium, CAD, Arduino, Python)." and a `local_folder` node only.
- A folder without `.git`: the root node is `local_folder` (not `local_clone`), no remote.
- A folder with >2000 tool files: scan lands the first 2000; the sync detail carries one error
  "scan truncated at 2000 files"; the root node has `truncated: true`.
- A file whose path segment is ≥40 characters of letters/digits/`._-`: it is skipped and the
  sync detail says "skipped: a path segment looked secret-shaped" — no `[REDACTED]` name in the
  graph.
- Link before the companion is up (fresh app start): the card shows the sync's error text
  "this machine's Solus companion is not connected" briefly, then the companion connects and
  the scan lands without any click.
- `POST /api/v1/projects/{id}/sources` with `{"type":"local", …}` → `400 use_local_folder_route`.
- `POST …/local-folder` with a 31-char `machine_id`, or an extra `path` field → `422`.
- `POST …/local-folder/{source}/open` with `tool: "altium"` on a KiCad row → `400 unsupported_tool`;
  with the companion stopped → `409 bridge_offline`; as a non-member → `404`.

- [ ] all edge cases exercised

## Cross-feature checks

- The KiCad committed-export source (Connect › KiCad) still syncs and still re-syncs on a `change`
  frame; a companion CONNECT alone does not re-run a KiCad export (check its sync list).
- Altium/KiCad forks still advertise and the bridge connects with a linked workspace (the hello
  frame is now allowed up to 128 KiB).
- SOL: ask "open the KiCad project in KiCad" in Do mode. Expected: an approval card for
  `local.open_in_tool` with `path`/`tool` rows; approving launches; Guide mode refuses with the
  switch-to-Do hint.

- [ ] cross-feature checks
