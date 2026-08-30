# Architecture — Local connections & the bench-session seam (SOLUSDEV-72)

How a local stream (simulator, serial robot, replay) is started, owned, and torn down. Companion
docs: `docs/contracts/live-connection.md` (the four-op streaming contract),
`docs/api/API-implementation.md` §15/§15b (routes), `docs/wireflows/local-connections.md` (UX).

## The one telemetry path

```
MuJoCo / Gazebo / MCAP / serial arm            Isaac (direct script, Isaac's python)
        │  PacketSource → LiveConnection pump          │  stdlib HTTP POST
        │  (livebench, in the API process)             ▼
        │  tap: every packet ──────────────►  TelemetryPlumbing.ingest(project_id, packet)
        ▼                                      │        (LNK-06 sink — resolver + buffers)
  windowed summaries (W0-07) → session         ├── resolved → entity buffer → /bench/recent, /bench/summary
  detail's last_summary                        └── unresolved → device ring → /bench/device-recent
```

- `PacketStreamLiveConnection.tap` (SOLUSDEV-72) is the tee: one guarded call at the pump choke
  point covers every provider, including serial post-reconnect. A failing tap never kills the
  pump. Telemetry stays Pattern 2 (ADR-031 §2) — never an MCP tool.
- The resolver is wrapped in a positive-TTL cache (`CachingEntityResolver`): a 50 Hz per-joint
  stream costs ~1 query per device per TTL. Negatives are never cached, so a freshly-linked
  entity attaches on the next packet.

## The runtime-optional provider seam

`solus-api` must not depend on `livebench` (the package arrow points the other way). The session
routes therefore load providers through `solus_api.livebench.sessions.load_local()` — a runtime
`find_spec("livebench")` + import of `livebench.local`, stored on `app.state.bench_local`:

- Installed (dev topology — API runs on the user's machine): honest probes
  (`available_simulators()` never imports mujoco; `list_devices()` keys identity by USB serial
  with `/dev/serial/by-id` resolution) and lazy provider factories.
- Absent (a cloud API image): `GET /bench/sources` reports `runner.available=false`; session
  starts refuse with `503 source_unavailable`. Nothing is faked.

Device exceptions (`DeviceNotFoundError`, `AmbiguousDeviceError`) are defined API-side in
`sessions.py` and imported BY livebench, so the router catches them without any livebench import.

## Session ownership & lifecycle

`SessionManager` (`solus_api/livebench/sessions.py`, on `app.state.bench_sessions`): in-memory,
project-keyed (BenchEventRing posture — lifecycle, not durable history; no migration). Start
reserves the cap slot synchronously, opens the connection (blocking ctors off-loop), installs the
tap (closing over the ctx-derived project id — §7 tenant binding), subscribes (starts the pump),
and retains the last window summary. Stop is idempotent `aclose()` (pump cancelled, partial
window flushed, subprocesses/ports closed). App-lifespan shutdown closes every session.

## Topology honesty (the anticipated evolution)

"Backend starts local processes" is only coherent while the API process runs on the user's
machine — true today (`localhost:8000` dev topology). In cloud deployment the runner belongs on
the customer machine (companion territory; the ARQ worker is the wrong lane — no bridge access).
The seam is cut for that swap: the routes and the LiveConnection/tap contracts stay; only the
host of `livebench.local` + the pump moves. Recorded here so the migration is a decision, not an
archaeology dig.
