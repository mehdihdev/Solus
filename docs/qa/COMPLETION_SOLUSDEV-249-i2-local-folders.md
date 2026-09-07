# Completion report — SOLUSDEV-249 · INTEGRATIONS I2 — Local folders

Branch `SOLUSDEV-249-local-folders` (from `main` @ `02590af`). Not pushed; no MR opened.

## What was built

A folder linked on THIS machine (Home › LOCAL FOLDER) becomes a `local` graph source that derives
what it is, without the user saying so:

- **Graph chain** `code_repo ←clone_of— local_clone —contains→ kicad_project | altium_project |
cad_folder | arduino_sketch | python_code`. The remote in `.git/config` is normalised to
  `host + owner/name` and deterministically linked to the sibling GitHub/GitLab source's repo node
  in the same project (`services/local_links.py`, `origin="derived"`); no sibling → no edge.
- **Scan on the machine, never in the cloud**: a Solus-authored Pattern-1 MCP server
  `integrations/mcp/local` (`scan_folder`, `folder_digest`, `open_in_tool`; workspace-confined,
  never raises, `env -i` launcher, hash-pinned lockfile derived from the Altium lock's `mcp`
  closure). The API reaches it through `BridgeFolderAcquirer` (the twin of the EDA family's
  bridge acquirer), keyed to the caller's live session AND the source's `machine_id`.
- **One source per (project, machine)**: `POST /projects/{id}/local-folder` with
  `{machine_id, machine_name, folder_name}` — the path never crosses the API. The generic
  `POST /sources` refuses `type: local`.
- **Open in [tool]** through the companion only: `POST …/local-folder/{source}/open` → the caller's
  own bridge session → `local.open_in_tool` (`/usr/bin/open -a KiCad -- <file>` on macOS). SOL's
  path to the same tool is `requires_confirmation: true` in the allowlist.
- **Watch**: the companion's stat fingerprint (`change` frame) is the doorbell; the cheap content
  digest (`local.folder_digest`, via the new `cheap_probe` opt-in to `run_sync`'s gate) is the
  evidence, so an edit re-syncs exactly once. A companion connect re-scans this machine's local
  sources (`only_local`), never the KiCad/Altium exports.
- **Desktop**: machine identity IPC (`~/.solus/companion_id`, created companion-style when
  absent), the card's scan state + detected list with staggered row animation and honest
  disabled states, "Open in editor" replacing "Open with VSCode", the Workspace inspector's
  "Open on this machine" panel, a "Local folder · <machine>" row under Connected accounts ›
  Software.

## Governing docs

DECISIONS.md ADR-021/030/031/034; `docs/architecture/{change-signal-spine,local-connections,
solus-folder}.md`; `docs/contracts/{bridge-protocol,connector-interface,action-gate}.md`;
`docs/wireflows/{home,local-connections}.md`; `docs/api/{API,solus}.md`. **`docs/design/SPEC.md`
exists but is a copy of `.gitlab-ci.yml`, and `docs/design/screens/` does not exist** — noted once;
the docs above governed.

New / amended (tier-1, ADR-032): `docs/api/local-folder.md` (new route plan + wire shapes),
`docs/architecture/local-folders.md` (new), `docs/api/API.md` (3 rows), `docs/wireflows/home.md`
(LOCAL FOLDER card), `docs/contracts/bridge-protocol.md` §6 (the `hello` cap — see below).

## Decisions taken at the design gate (answered in-session by Mehdi)

Tickets 249–252 for I2–I5 · launcher via the companion bridge only · a Solus-authored `code`
server for I3 · flag-gated client path for I5's MCAP picker · one local source per project per
machine · Isaac/Fusion honestly deferred · Onshape live via a desktop sign-in for I4 · "Code
environment" row for I3.

## Delegated-judgment decisions

- Entities per tool PROJECT (KiCad per directory, Altium per `.PrjPcb`, CAD per directory, Arduino
  per sketch dir, one Python node) — never per file; folder-relative paths only.
- `local` syncs run in the API process (bridge lives there); `enqueue_sync(inline_only=True)`.
- Derived `clone_of` edges are `origin="derived"` and `apply_sync_result` now reconciles only
  `origin="connector"` edges (so the sync that owns the endpoints cannot churn the link).
- No-signal semantics: bridge offline / other machine → `ConnectorError("api_unreachable")`; the
  source keeps its graph, records the reason, and the next connect or `change` frame retries.
- The on-connect re-scan also picks up local sources in `error` (their error IS "companion
  offline"); export connectors stay `connected`-only on connect.

## Found in the live run (and fixed here)

1. **The bridge hello overflowed the 16 KiB control cap** once a workspace was linked: Altium +
   KiCad + `local` advertise ≈ 19 KB of schemas → the cloud closed every such companion as `4400
update required`. Pre-existing (Altium + KiCad alone = 17.7 KB) — any machine with a linked
   folder and the forks materialised was affected. Fix: `bridge_hello_frame_max_bytes` (128 KiB) applied to
   the first frame only; contract §6 amended;
   `tests/test_bridge_hello_cap.py`.
2. **Ingress redaction masks long paths and hashes.** `redact_value` (a §7 invariant, untouched)
   masks ≥40-char base64-ish strings — every sha256, the 40-hex head, and joined paths like
   `firmware/src/controllers/motor_controller.py`. The wire shape became segment lists + 32-hex
   hashes + a 12-char head; a still-masked segment drops that file with a recorded sync error.
3. **Nothing re-scanned on companion (re)connect** — linking a folder respawns the companion with
   the workspace, so the first scan always raced it. Added the on-connect `only_local` re-scan.
4. **Card overflow**: the detected rows widened Home's right column; fixed with wrap + `minWidth:0`
   down the chain (pinned by a test).

## Verified live (real API on :8001, real Electron app over CDP, real companion, real forks)

- Linked the scratch clone `rover-fw` (git remote `git@github.com:solus-test/rover-fw.git`, a KiCad
  project, an Arduino sketch, a CAD folder, Python files). The companion respawned with the
  workspace, connected (hello under the new cap), the on-connect scan landed; the card shows
  "Scanned now" and the detected list.
- Graph (DB + Workspace screenshot): `local_clone:rover-fw —clone_of(derived)→ code_repo:rover-fw`
  and four `contains` edges; Workspace lists the cross-link `rover-fw clone_of rover-fw` and the
  inspector shows "Open on this machine" on the KiCad node.
- **Open in KiCad**: real click → `POST …/open` 200 → KiCad 9 launched and holds
  `rover-fw/hw/main` (the `.kicad_pro`'s directory) open.
- **Edit re-syncs once**: 4 syncs → appended to the schematic → 5 syncs after 50 s (succeeded,
  bridge-triggered) → still 5 after another 45 s.
- Scaffolding, stated honestly: the GitHub sibling source and its `:repo` node were SEEDED in the
  dev DB (no GitHub OAuth in this run) — the remote derivation and the edge reconciliation were
  exercised live, a GitHub sync was not. The native folder dialog cannot be driven over CDP, so
  the link went through the app's own store + API client (the pick→link glue is unit-tested).
- The fork venvs were materialised with `SOLUS_MCP_FORK_PYTHON=<uv cpython 3.12>
scripts/install-mcp-forks.sh` on this Mac (none existed before).

## Tests

- API: `tests/test_local_folder.py` (32), `test_local_acquire.py` (10), `test_local_links.py` (7),
  `test_local_folder_routes.py` (12, incl. cross-team, bridge-offline, wrong-machine, foreign
  entity, unsupported tool, no-signal, unchanged-digest skip, resync filtering),
  `test_bridge_hello_cap.py` (5). Full API suite (`-m 'not live'`): 4482 passed, 1 skipped,
  22 min on this Mac (after the three fixes above).
- Fork: 151 tests (`uv run pytest integrations/mcp/local`); whole `integrations/mcp` suite green.
- Desktop: full suite green (2986 → +layout test), typecheck clean.

## Values a human must set

None new for dev. `SOLUS_BRIDGE_HELLO_FRAME_MAX_BYTES` has a default (131072).

## Humans must sign / decide

- `integrations/mcp/local/PROVENANCE.md` reviewer sign-offs (blank), `SECURITY_REVIEW.md` (DRAFT),
  `allowlist.yaml` (draft; `open_in_tool` is `requires_confirmation: true`).
- No Windows `bin/launch.cmd` for the `local` server (as for Altium) — companion fails closed there.

## Phase 4 review findings (all fixed before handoff)

Code review (1 HIGH): rows were disabled with the VS Code reason even when their own tool was
installed → `rowsDisabledReason` now carries only bridge/scan reasons. Security review
(1 CRITICAL, 3 HIGH, 5 MEDIUM, 5 LOW): the on-connect re-scan now honours `may_write` (a viewer's
companion never writes the graph); a local source is bound to the user who linked it
(`created_by` + server-set `config.user_id`) on the re-sync, the acquirer, the GET and the open
route — a teammate declaring my machine id reaches nothing of mine; the hello's identity fields
are bounded; credential-bearing remote URLs are stripped on the machine and refused in the cloud;
`gitdir:` pointers are confined to the folder or `$HOME`; launch failures report a fixed reason;
`PATCH /sources` cannot rebind a local source; path segments and joined paths are bounded with
over-long files dropped and reported; the `companion_id` file is written atomically and never
through a symlink; the walk caps during traversal and the hash loop has a byte budget. (`_unchanged` was
kept: it is pinned by `test_sync_write_path.py`.) Tests added for each (`test_local_folder_routes.py` C1/H1/M3,
`test_local_acquire.py`, `test_local_folder.py`, `test_bridge_hello_cap.py`, fork tests).

## Open concerns / deferred

- A single path SEGMENT ≥40 chars with ≥16 distinct chars is still masked by the ingress gate
  (the file is dropped and reported). Relaxing the gate for `parts` is a §7 call, not taken.
- Pre-existing, seen again: two `## ADR-035` headings in DECISIONS.md; the KiCad allowlist header
  still says `set_symbol_property` is unregistered (it is registered).
- The MCP catalog (`agent/tools/mcp_servers.py`) does not list `local`; it is not needed for
  bridge-hosted servers (the allowlist root is the gate) — flagged, not added.
