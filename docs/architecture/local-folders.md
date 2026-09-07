# Architecture — Local folders as a source (SOLUSDEV-249 / INTEGRATIONS I2)

How a working copy on ONE machine becomes a graph source that derives what it is — the repo it
clones, the tool projects it holds — without the user saying so, and how "Open in KiCad" and the
folder watch ride the bridge that already exists. Companion docs: `docs/api/local-folder.md`
(routes + wire shapes, authoritative), `docs/architecture/change-signal-spine.md` (the `change`
frame → re-sync path reused here), `docs/contracts/bridge-protocol.md` (frames and caps),
`docs/architecture/solus-folder.md` §3 (where the folder link lives), ADR-031 (Pattern 1),
ADR-034 (the machine registry).

## The one path

```
desktop (Home › LOCAL FOLDER)                       companion (this machine)
  link folder ──► ~/.solus/projects.json ──spawn──► SOLUS_COMPANION_WORKSPACE = the folder
  POST /local-folder {machine_id, machine_name,        │  integrations/mcp/local  (Solus-authored,
        folder_name}   ──► Source(type=local)          │  Pattern 1: scan_folder · folder_digest ·
                              │                        │  open_in_tool — all workspace-confined)
             run_sync ◄── bridge bind (on connect) ◄───┘  hello (inventory) ──► cloud allowlist gate
                │         bridge `change` frame (stat fingerprint = the doorbell)
        LocalFolderConnector.detect_changes ── local.folder_digest ── cursor.digest  (the evidence)
        LocalFolderConnector.sync           ── local.scan_folder   ── FolderScan (validated, untrusted)
                │
        derive_local_graph (pure): local_clone —contains→ kicad_project | altium_project | cad_folder |
                                   arduino_sketch | python_code
        services/local_links.reconcile_local_links: local_clone —clone_of→ code_repo (sibling GitHub/
                                   GitLab source whose config.repo == the normalised remote)
```

## Why the scan runs on the machine, not in the cloud

The connector contract (`SyncContext = {credentials, config, cursor}`) has no filesystem and no
bridge handle by design, and the ARQ worker has no bridge registry at all. So the connector never
reads a disk: a `FolderAcquirer` — `connectors/local_acquire.py::BridgeFolderAcquirer`, the twin of
the EDA family's `BridgeExportAcquirer` — dispatches the `local` server's tools over the caller's
live bridge session and hands back a validated `FolderScan`. No live session, or a session on a
different machine, is a **no-signal** outcome (`ConnectorError("api_unreachable")`): the source
keeps its graph and records the reason; nothing is invented, nothing is tombstoned.

Consequences that follow, all mechanical:

- **A `local` source syncs in the API process only.** `routers/sources.enqueue_sync(inline_only=True)`
  never hands it to ARQ; the on-connect and `change`-frame re-syncs already run in-process
  (`routers/bridge._resync_local_sources`). This is the same topology honesty
  `docs/architecture/local-connections.md` records for bench runners: in a cloud deployment the
  runner belongs on the customer machine, and the seam is cut so only the host moves.
- **The path never crosses the API.** The companion scans its own workspace; the source carries
  `machine_id` (the companion instance id, `~/.solus/companion_id`), `machine_name`, `folder_name`.
  Paths in the graph are folder-relative; the scan model refuses absolute and `..` segments at the
  boundary.

## One source per (project, machine)

A working copy is per machine, a Source is per project — so the source is keyed by BOTH. The
desktop reads (or creates, companion-style) `~/.solus/companion_id` and sends it as `machine_id`;
`POST /local-folder` reuses the row for that machine or creates it; every dispatch and every
re-sync compares the live session's `companion_instance_id` to the source's `machine_id`. Two
teammates on one project get two `local_clone` nodes, both `clone_of` the same repo — which is
the truth. A teammate's manual "Sync now" on MY local source declines (their session is another
machine) and says so.

## The change signal: doorbell vs evidence

The companion's existing `change` frame is a stat-fingerprint doorbell over `DESIGN_SUFFIXES`
(SOLUSDEV-167) — payload-free, coalesced, rate-limited, and hint-only. On a hint the API runs the
freshness gate: `LocalFolderConnector.cheap_probe = True` opts an auth-none connector into
`run_sync`'s probe (read duck-typed, like the registry reads `selection`), and the probe is one
`local.folder_digest` compared to `cursor.digest`. Equal → `_commit_skipped`, no scan paid for;
different → one `scan_folder` → idempotent upsert. "Editing the file re-syncs once" is therefore a
property of the gate, not of the sensor's timing.

## Derived links are not connector edges

`apply_sync_result` reconciles only `origin="connector"` edges for a source. The `clone_of` edge
is `origin="derived"`, filed under the local source's id (so it dies with the source), and owned by
`services/local_links.py`, which reconciles the whole project after any local, GitHub or GitLab
sync — so the link appears whichever side syncs first, and is withdrawn when the remote changes
or the sibling source disconnects. Matching is deterministic (`host` + case-folded `owner/name`),
never a fingerprint: a clone knows its remote.

## Two things the live run found (and fixed here)

- **The hello inventory overflowed the control-frame cap.** With a workspace, Altium + KiCad +
  `local` advertise ≈ 19 KB of tool schemas; the 16 KiB control cap closed every such companion as
  `4400 update required` — on any machine with a linked folder, before this ticket. The `hello`
  now has its own bounded cap (`bridge_hello_frame_max_bytes`, 128 KiB);
  every other control frame keeps 16 KiB. Contract §6 amended.
- **Ingress redaction masks secret-shaped strings — and long paths are secret-shaped.** The scan
  therefore carries paths as segment lists, 32-hex hashes and a 12-char head (`docs/api/local-folder.md`
  §4). The redaction gate is untouched; a segment it still masks drops that file with a recorded
  sync error.

## What this does NOT do

- It does not parse design files. A KiCad project node is "this directory holds a KiCad project";
  its schematic content still comes from the KiCad connector/export path (ADR-030).
- It does not watch the folder from the cloud, and never lets the cloud name a path.
- It does not launch tools from the renderer or the cloud: the desktop button calls
  `POST …/open`, which dispatches `local.open_in_tool` to the caller's own companion. When SOL
  proposes a launch, `requires_confirmation: true` in the allowlist routes it through the
  approval card.
