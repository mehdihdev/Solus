# Completion report — SOLUS-LB-01 Sim connections (SOLUSDEV-121)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** MuJoCo fully verified; Gazebo and Isaac
built + fixture-verified, live smokes pending the human's installs. **Ticket stays open** until
the Isaac live smoke actually runs (per the recorded decision).

## What was built

- `livebench/telemetry/stream_live.py` — `PacketStreamLiveConnection`, the generic
  packets→windows→LiveConnection machinery extracted from the CON-03 Foxglove connection (which
  is now a thin subclass). Every sim/robot provider is a `PacketSource` + a subclass; the
  review-hardened behavior (teardown flush, pump supervision, honest status) is inherited, not
  re-implemented.
- `livebench/sim/mujoco_source.py` + `MuJoCoSimConnection` (`provider="mujoco"`) — steps real
  MuJoCo physics (3.11.0, aarch64) in sim time; per-joint topics (`<scene>/<joint>`: qpos/qvel)
  and per-sensor topics, deterministic timestamps (`start_time + sim_time`), duration bounds,
  clean early teardown. **Smoke-tested against a real pendulum scene: gravity moves the joint,
  windows deliver through the conformance-checked contract.**
- `livebench/sim/gazebo_source.py` + `GazeboSimConnection` (`provider="gazebo"`) — streams via
  the pinned `gz topic -e --json-output` CLI (argument lists, `shutil.which`, no shell,
  flag-safe topic validation; §7). The JSON-lines parser is the tested core; the connection
  accepts an injected source, so windowing is proven without the binary.
  `GazeboNotAvailableError` at construction when `gz` is absent.
- `livebench/sim/mcap_replay.py` + `McapReplaySimConnection` (`provider="mcap-replay"`) — the
  **Isaac Sim path**: Isaac logs to MCAP, the same container CON-03 reads, so its telemetry
  replays through the identical windowing/contract machinery. Topic filter, mid-stream aclose,
  file handle always released.

SimConnector lifecycle mapping (delegated judgment): _start_ ≡ construct + `subscribe`,
_stream_ ≡ `on_batch` windows, _stop_ ≡ `aclose`. Signal→entity mapping rides
`device_id == graph_entity.external_ref` (per-joint topics chosen because graph entities from
CAD are per part).

## Acceptance vs. delivered

- MuJoCo connect/start/stop/stream + smoke test: ✅ verified for real.
- Gazebo: ✅ built + fixture-verified; **live `gz sim` smoke NOT RUN** (simulator not installed;
  human installing `ros-jazzy-ros-gz`). Will run post-install.
- Isaac Sim: connector built over the MCAP path and conformance-verified against recorded files.
  **Isaac itself is NOT INSTALLED on this machine** (audited: no pip/Omniverse/container) — the
  lane brief's claim that it runs here was wrong. On install (human, container path on aarch64),
  the native-API-vs-ROS2-bridge choice gets confirmed and the live smoke runs. Until then this
  acceptance line is honestly **unmet**.
- Telemetry in LB-06 format into the telemetry path: ✅ (packets → windows → LiveConnection).
- Graph mapping via LNK-06: the resolver seam is honored by construction (`device_id` ==
  `external_ref`); actual DB attachment happens when the transport route lands (LB-05).

## Verification

34 LB-01 tests (MuJoCo source 6, Gazebo source 5, MCAP replay 3, stream-live base 1, sim
connections 5, plus the CON-03 suite they share) — 108 total in `livebench/tests/`, all green.
`mypy -p livebench` strict clean; `ruff check` clean. TDD: RED commits precede GREEN throughout.
