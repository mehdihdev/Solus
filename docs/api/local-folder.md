# Local folders — a working copy on THIS machine as a graph source (SOLUSDEV-249 / INTEGRATIONS I2)

Route plan + wire shapes. Tier-1 (ADR-032): agent-editable, reviewed at the MR. Companion docs:
`docs/architecture/local-folders.md` (why the scan runs on the machine, the per-machine source,
the change signal), `docs/architecture/change-signal-spine.md` (the bridge `change` frame → re-sync
path this reuses), `docs/contracts/bridge-protocol.md` (the tool_call/tool_result frames the scan
rides), `docs/wireflows/home.md` (the LOCAL FOLDER card), ADR-031 (the `local` server is a
Solus-authored Pattern-1 server), ADR-034 (the folder link lives in `~/.solus/projects.json`).

## 1. What it is

A folder the user linked to a project on this computer (Home › LOCAL FOLDER) becomes a `local`
**Source** — one per `(project, machine)`, named after the machine — whose sync DERIVES what the
folder is without the user saying so:

- `.git/config` → the remote → normalised to `owner/name` → a `clone_of` edge to the matching
  GitHub/GitLab `code_repo` node already in the project's graph (same host, same `owner/name`);
  nothing is linked when no such source exists — empty beats invented.
- file extensions → tool projects: `.kicad_pro/.kicad_sch/.kicad_pcb` → `kicad_project`,
  `.PrjPcb/.SchDoc/.PcbDoc` → `altium_project`, `.step/.stp/.sldprt/.sldasm/.iges/.igs/.f3d` →
  `cad_folder` (one per directory), `.ino` → `arduino_sketch` (one per sketch directory),
  `.py` → one `python_code` node at the root; dependency declarations (`requirements*.txt`,
  `pyproject.toml`, `environment.yml`, walked as `python` files so an edit moves the digest) →
  one `python_requirement` node per (file, package) — SOLUSDEV-250. The chain in the graph is
  `code_repo ←clone_of— local_clone —contains→ kicad_project`.
- **Open in [tool]** launches the tool on the right file through the companion bridge (the
  Solus-authored `local` server's `open_in_tool`), never from the cloud and never from the
  renderer directly. Bridge offline → the control is disabled with that reason.
- The folder is watched: the companion's existing stat fingerprint is the doorbell (`change`
  frame), a CONTENT digest over the tool-relevant files is the evidence (`local.folder_digest`
  compared to the source cursor), so an edit re-syncs once and an unchanged folder never
  re-ingests.

**The path never reaches the API.** The companion scans its own `SOLUS_MCP_WORKSPACE` (derived
from the machine registry at spawn); the source carries only `machine_id` (the companion instance
id), `machine_name` (hostname) and `folder_name` (basename). Every dispatch checks that the live
bridge session's `companion_instance_id` equals the source's `machine_id`, so machine A's scan can
never land on machine B's source.

## 2. Source shape

`Source.type = "local"`, `auth_kind = none` (connected on creation, like the export connectors).

```json
{
  "config": {
    "machine_id": "<32 hex>",
    "machine_name": "mehdi-mbp",
    "folder_name": "rover-fw"
  },
  "cursor": {
    "digest": "<hex>",
    "remote": "org/rover-fw",
    "host": "github",
    "branch": "main",
    "tools_installed": { "kicad": true, "altium": false, "vscode": true },
    "detected": [
      {
        "entity_key": "kicad:hw/main",
        "tool": "kicad",
        "name": "main",
        "path": "hw/main/main.kicad_pro"
      }
    ]
  }
}
```

`machine_id` is validated `^[0-9a-f]{32}$`; `machine_name`/`folder_name` ≤ 255 chars, non-blank.
The generic `POST /projects/{id}/sources` REFUSES `type: "local"` (`400 use_local_folder_route`)
— the dedicated route below is the only creator, so idempotency by machine holds.

## 3. Routes

All resolve through `ProjectCtx` (non-member → **404**). MEMBER+ for writes.

| Method | Path                                                          | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Success                                    |
| ------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| POST   | `/api/v1/projects/{project_id}/local-folder`                  | Link THIS machine's folder: body `{machine_id, machine_name, folder_name}`. Creates the `(project, machine_id)` source or updates the existing one's name/folder, connects it, and queues a sync **inline in the API process** (the bridge lives there; the ARQ worker has no bridge — `docs/architecture/local-connections.md` "Topology honesty").                                                                                                                                                                                                                | `201 {source, job_id}` (`200` when reused) |
| GET    | `/api/v1/projects/{project_id}/local-folder?machine_id=…`     | This machine's local source for the project, or `{source: null}`: `{source, bridge: {connected, tools_installed}, detected: [{entity_id, entity_key, tool, name, path, open_targets: ["kicad","vscode","system"]}]}`. `detected` is read from the source's live `local_*` entities; `open_targets` = the tool the project belongs to when installed on the machine, plus `vscode` when installed, plus `system` (OS default app) always. `tools_installed` comes from the last scan; `connected` from the caller's live bridge session with a matching instance id. | `200`                                      |
| POST   | `/api/v1/projects/{project_id}/local-folder/{source_id}/open` | Launch: body `{entity_id, tool}`; `tool ∈ {kicad, altium, vscode, system}`. Dispatches `local.open_in_tool {path, tool}` over the caller's bridge session. `409 bridge_offline` when no session with the source's machine id; `404` unknown/foreign entity; `400 unsupported_tool` when the entity's `open_targets` lacks it. The tool's own answer is returned verbatim — `launched: false` with the reason is a **200**.                                                                                                                                          | `200 {launched, tool, reason}`             |

Existing routes that already serve local sources unchanged: `GET /sources` (lists it),
`DELETE /sources/{id}` (unlink — the desktop calls it when the folder is unlinked),
`POST /sources/{id}/sync` (routes a `local` source inline, never to ARQ),
`GET /sources/{id}/syncs`.

Manual-sync dispatch preserves the same API-process acquisition boundary for
KiCad and Altium sources: only the API registry owns their live desktop export
acquirers. With normal asynchronous sync enabled, these three providers run as
API background tasks after the 202 response, retaining the requesting actor's
bridge scope; they are not sent to an ARQ process without that bridge. Remote
provider syncs, including Onshape, continue through the configured ARQ worker.
The explicit test/bare-development inline override remains available.

Events: `local_folder.linked {machine_name, folder_name}` · `local_folder.opened
{tool, entity_kind, launched}` · the sync's own `source.synced`.

## 4. The `local` server's tools (companion side, `integrations/mcp/local/allowlist.yaml`)

All three are workspace-confined: the workspace IS the linked folder; no tool takes an absolute
path. Composed names: `local.scan_folder`, `local.folder_digest`, `local.open_in_tool`.

`scan_folder {}` → (structuredContent)

```json
{
  "schema_version": 1,
  "root_name": "rover-fw",
  "git": {
    "remote_url": "git@github.com:org/rover-fw.git",
    "branch": "main",
    "head": "<12-char short sha>"
  },
  "files": [
    {
      "parts": ["hw", "main", "main.kicad_pro"],
      "size": 1234,
      "hash": "<32 hex blake2b-128>|null",
      "tool": "kicad"
    }
  ],
  "digest": "<hex blake2b-128>",
  "truncated": false,
  "tools_installed": { "kicad": true, "altium": false, "vscode": true }
}
```

- `files`: relative POSIX paths as SEGMENT LISTS (`parts`, never a joined string — see the
  redaction note below), sorted, ONLY tool-relevant suffixes (the table in §1 plus
  `.kicad_pro`; matched case-insensitively), ≤ **2000** entries (then `truncated: true`),
  directories `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `build`, `dist`,
  `solus-artifacts` skipped. `hash` is blake2b-128 (32 hex) over the bytes, null for files over
  **32 MiB** (size still reported) — the digest then uses the size.
- `git` is null when there is no `.git` (directory OR the worktree `gitdir:` file form), when
  `config` is unreadable, over 64 KiB, or has no `[remote "origin"]` url. `head` is the 12-char
  short sha of the resolved commit when HEAD is readable, else null.
- `digest` includes the ordered relative file paths/hashes and sanitized Git identity
  (remote, branch, HEAD). Both `scan_folder` and `folder_digest` use the same
  algorithm, so metadata-only changes invalidate the probe.
- **Why segments, 32-hex hashes and a short head (found in the live run):** every bridge result
  passes the cloud's ingress redaction (`agent/tools/untrusted.py`, a §7 invariant that is never
  weakened) which masks any string ≥ 40 chars of `[A-Za-z0-9+/=_.-]` with ≥ 16 distinct
  characters — a 64-hex sha256, a 40-hex commit id, and a joined path like
  `firmware/src/controllers/motor_controller.py` all qualify. Segments keep each string short; a
  single segment that still trips the filter arrives as `[REDACTED]`, and the connector DROPS
  that file and records one sync error ("skipped: a path segment looked secret-shaped") rather
  than landing a masked name.
- `tools_installed` is probed, never assumed: macOS `/Applications/<App>.app` (KiCad, Visual
  Studio Code), Linux `shutil.which` on `kicad`/`code`, Windows the documented install roots.
  Altium is Windows-only and reports false elsewhere. Missing = false.

`folder_digest {}` → `{ "digest": "<hex>", "truncated": false }`.

`open_in_tool { "path": "hw/main/main.kicad_pro", "tool": "kicad" }` → `{ "launched": bool,
"tool": "kicad", "reason": null | "KiCad is not installed on this machine" }`. Argument-list
launches only: macOS `/usr/bin/open -a <App> -- <path>` (or bare `/usr/bin/open -- <path>` for
`system`), Linux the resolved binary or `/usr/bin/xdg-open`, Windows `os.startfile`. Never
`shell=True`; the path must resolve inside the workspace or the answer is
`launched: false, reason: "path is outside the linked folder"`. `requires_confirmation: true`
in the allowlist — when SOL proposes a launch it goes through the approval card; the desktop
button's click is the user's own action and dispatches through the route above.

Every tool answers a dict, never raises: a failure is `{launched:false, reason}` /
`{files: [], truncated: false, git: null, …}` with a `reason` field only where the shape above
carries one.

## 5. Entities the connector lands (`connectors/local_folder.py`, pure mapping)

| kind                                          | domain     | key                    | name                        | properties                                                                                                                                |
| --------------------------------------------- | ---------- | ---------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `local_clone` (git) / `local_folder` (no git) | code       | `clone:`               | `root_name`                 | `machine_name, branch, head, remote (owner/name), host (github/gitlab/other), file_count, truncated`                                      |
| `kicad_project`                               | electrical | `kicad:<dir>`          | project basename            | `path, project_file, schematics[], boards[]` (dir grouping: the `.kicad_pro`'s directory; sch/pcb without a pro still group by directory) |
| `altium_project`                              | electrical | `altium:<PrjPcb path>` | file stem                   | `path, schematics[], boards[]` (same directory)                                                                                           |
| `cad_folder`                                  | mechanical | `cad:<dir>`            | dir basename (or root_name) | `path, files[] (≤100 listed), file_count`                                                                                                 |
| `arduino_sketch`                              | code       | `arduino:<dir>`        | dir basename                | `path, sketch_file`                                                                                                                       |
| `python_code`                                 | code       | `python:`              | `root_name (python)`        | `file_count, top_dirs[] (≤50)`                                                                                                            |

Relations: `clone: —contains→ <every project node>` (intra-source). The `clone_of` edge to the
sibling code-host repo node is landed by `services/local_links.py` after the sync applies
(cross-source; `origin="connector"`, `source_id` = the local source, relation `clone_of`,
`domain_pair code<->code`) and removed when the remote changes or the sibling source goes.
Paths in properties are folder-relative; absolute paths never enter the graph.

## 6. Errors

| HTTP | `error.code`             | Where                                                                             |
| ---- | ------------------------ | --------------------------------------------------------------------------------- |
| 400  | `validation_error`       | bad `machine_id` shape, blank names, unknown fields                               |
| 400  | `use_local_folder_route` | `POST /sources` with `type: local`                                                |
| 400  | `unsupported_tool`       | `open` with a tool the entity cannot open in                                      |
| 404  | `not_found`              | non-member project; unknown/foreign source or entity; entity not from this source |
| 409  | `bridge_offline`         | `open` with no live session whose instance id matches the source                  |
| 409  | `sync_in_progress`       | the existing sync debounce                                                        |

A sync with no matching live bridge session does not fail the source: the connector raises
`ConnectorError("api_unreachable")` (a no-signal code), the run records the skip, and the next
`change` frame or manual sync tries again.

## SOLUSDEV-260 Git identity freshness follow-up

A local clone remains a real named folder root (for example ForgeTS); dependency
packages are children in presentation while their semantic requires edges remain.
Git discovery supports directory/worktree metadata, branch tracking remotes and
origin fallback. Remote identity is normalized without credentials, and ambiguous
matches are not guessed. Branch, HEAD and normalized remote changes participate in
the scan digest. The companion change sensor observes bounded source and Git
metadata changes so branch-only changes can trigger a fresh scan. Saved local files
are the working-copy content; editor buffers are not claimed readable.

## Static Arduino observations — SOLUSDEV-261 completion

The optional `arduino` scan list contains at most 128 records, one per observed
`.ino` file: `{parts, pins, buses, libraries, incomplete}`. Pin records carry
`{operation, pin, line}`; pin is a literal digital number or `A<n>`, or null when
an expression cannot be resolved. Recognized calls are pinMode, digitalRead,
digitalWrite, analogRead and analogWrite. Only literal assignments to immutable
`const` variables or object-like defines can resolve aliases; ambiguous/conditional
source is reported incomplete. Buses report explicit Wire/SPI/Serial begin usage;
library includes are declarations, not proof of installation. Comments and string
contents are never treated as calls. No code executes during extraction.

Reads are confined, bounded to 64 KiB per file and 128 pin observations; skipped,
malformed, oversized or unsupported source is incomplete, never a fabricated empty
complete result. Cloud validation rechecks paths, closed call/bus vocabularies,
lengths and counts. Records attach to the corresponding `arduino_sketch` graph
entity as source-file observations. They do not establish physical board bindings
or electrical connections. A projection marker invalidates old unchanged local
cursors once so existing sketches receive these observations.
