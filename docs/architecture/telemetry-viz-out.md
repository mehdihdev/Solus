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
