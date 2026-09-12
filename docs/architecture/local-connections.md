# Architecture — Local connections and the bench-session seam

**Last updated:** 2026-09-07. SOLUSDEV-72 foundation; approved SOLUSDEV-251/253
hardware configuration/discovery/recovery amendments below specify target behavior.

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
  entity attaches on the next packet. Binding/config/ownership/deletion changes invalidate
  affected positive caches after their database transaction commits.

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

## Approved hardware lifecycle extension (SOLUSDEV-251/253)

A saved connection owner may be a robot, controller or gateway part. The additive real-mode
hardware provider selects its entity UUID; legacy robot provider remains an adapter. Resolve the
project-scoped owner CONFIG and its referenced component configs before constructing the existing
driver input. Drivers retain current Channel/PacketSource/LiveConnection contracts. Saving or
reviewed configuration changes commit before connection starts; a failed start leaves saved IDs
available for retry. A session ID/ping is not evidence of receiving actual packets.

One runner-owned machine-wide endpoint lease covers probes, raw serial, sessions and reconnect.
Reserve it before any open; active sessions keep ownership, enumeration does not open their port,
and cross-project contention reports generic busy state. Release on cooperative cancellation,
failed start, stop and shutdown. Overall probing has a deadline; HTTP cancellation alone cannot
safely release a port while its worker still uses it. Reconnect re-resolves identity and opens
inside retry/error handling. Serial-less/duplicate-device observation choices expire after
attachment generation changes; an old path is never identity or durable consent.

Enumeration remains independent of selected-device interrogation. OS watchers where supported
or bounded polling while Hardware is open publish early observations and invalidate vanished
attachments. Typed busy, permission, ambiguous, missing-runner, unsupported and disconnected
errors remain distinguishable. Old project/account/generation results cannot start a session.

Desktop MAIN is the only writer of the approved private hardware source/hint file. The local
reader resolves authenticated project/account source refs, verifies picker authority/canonical
path/digest and treats changed content as a revised proposal. Shared configuration and model
context receive portable references/verified values, never private paths. A cloud process has no
local reader; `repo_root` in a remote request is not permission to open arbitrary files. See
[local-state.md](../contracts/local-state.md), [hardware routes](../api/hardware.md) and
[hardware architecture](hardware-onboarding.md). Local I/O never moves to cloud ARQ or the
companion MCP telemetry channel as an incidental scheduling fix.
