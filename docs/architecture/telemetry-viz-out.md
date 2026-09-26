# Telemetry viz-out — Solus → Foxglove (CON-03, SOLUSDEV-105)

Solus INGESTS robot telemetry through the Foxglove WS bridge and MCAP (Pattern 2,
`LiveConnection`); this note documents the **complementary direction** — how anything
Solus holds as LB-06 packets becomes consumable by Foxglove Studio and the wider MCAP
tool ecosystem.

## The path

```
LB-06 packets (replay, sim run, buffered window source)
  ──▶ livebench.telemetry.mcap_export.write_packets(stream, packets)
  ──▶ .mcap file — one json-encoded channel per device_id,
      payloads in the ratified LB-06 wire form (ts_us et al.),
      log_time = packet timestamp in nanoseconds
  ──▶ open in Foxglove Studio (drag-drop / "Open local file")
```

Round-trip fidelity is tested: an export read back through
`livebench.telemetry.mcap_ingest.read_packets` reproduces the original packets
exactly (`lb_mcap_export_test.py`).

## Choices

- **MCAP file, not a live WS server.** Foxglove reads MCAP natively, and a file is
  the honest first increment — a live Solus→Foxglove WS _server_ (Solus imitating
  `foxglove_bridge`) has no ticket and no consumer yet. When one appears, the frame
  builders in `foxglove_client.py` (`build_subscribe`'s inverse) are the starting
  point.
- **json message encoding.** The LB-06 wire form is already JSON-serializable and
  Foxglove renders json channels without schemas; shipping protobuf/cdr encoders
  would re-import exactly the toolchain weight the LB-06 contract rejected.
- **ROS 2 side door.** `rosbag2_storage_mcap` is installed with ROS Jazzy on the dev
  machine, so ROS-native recordings are already MCAP — they enter Solus through
  `read_packets` with no conversion step.

## SOLUSDEV-262 run capture

An optional bounded capture sink taps the existing graph TelemetryPlumbing ingest stream before
recent-window reduction. Runs snapshot accepted graph/config/source identity at start and retain
completed manifests through the existing .solus artifact filing path. Persistent run records and
checkpoint status expose interrupted/truncated capture. This is capture of a robot session, not
a motion/routine runner or experiment-tracking platform. Deterministic analysis and comparison
consume immutable project-scoped snapshots. Optional narration uses existing metered cheap-tier
routing and cannot add evidence. Sensor frames remain timestamped project artifact references.

The client scene consumes bounded normalized URDF/MJCF from explicitly imported retained graph
artifacts (bench-scene API), renders primitive geometry and link frames with Three.js, and
applies only confirmed numeric joint bindings. It never starts a simulator or commands hardware.
Multiple robot models share one scene. Per-account/project/model display poses are local view
preferences, independent of physical transforms. Source revision changes mark bindings stale;
explicit reimport preserves model identity and user display placement. Missing mesh bytes or
jointless CAD remain visible with a reason rather than guessed geometry or motion.

Source-linked CAD mesh refresh uses the existing authoritative Onshape change-signal spine.
Explicit model mesh-key→CAD graph leaf bindings select exact occurrence provenance. The existing
revision-bracketed STEP acquisition captures only requested export bytes for this sync; after
successful graph sync, the worker tessellates bounded exact occurrences through existing OCCT,
retains triangles via scoped artifact filing, rechecks model/source revisions, then updates only
that mesh. Failed/ambiguous/oversized/racing refresh retains previous geometry and marks stale.
This supersedes manual-reimport-only behavior for explicitly bound CAD meshes; imported URDF
structure and unsupported CAD remain manually reimportable. No extra provider export loop.
