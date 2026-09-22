# Wireflow — Local Connections (SOLUSDEV-72)

Documents the local-connections surface exactly as implemented. Authority: this file governs the
flow; visual polish within it is implementer judgment (CLAUDE.md §3). Companion doc:
`docs/api/API-implementation.md` §15b for the routes every step calls.

## Where it lives

The Sources screen is retired (SOLUSDEV-244). Machine-local streams now live in two places, both
rendering what is on THIS machine from live backend claims only — offline / runner-absent degrades
to honest copy with disabled controls, never fabricated availability:

- **Simulators** → Home › Connected accounts › **Simulation** tab
  (`features/workspace/SimulationPanel.tsx`): one row per simulator, `Start` opens
  `SimulatorStartModal` (see `home.md`).
- **Devices** → Live Bench › **Connect a device** (`features/bench/ConnectDeviceModal.tsx`): the
  header's button opens a dialog with the device rows (`DeviceRow`) and the unmatched sessions.
- **Local tools** (Fusion) → Home › Connected accounts (their row's status line is the live bridge
  word; `Connect` opens the wizard's "Connect on this computer" step).

## Flow 1 — start a simulator

1. Home › Connected accounts › **Simulation**. One row per simulator from
   `GET /bench/sources`: MuJoCo, Gazebo, Isaac, MCAP replay.
2. An available simulator's **Start** opens `SimulatorStartModal` (MuJoCo: one click starts the
   built-in demo scene; Gazebo: topics input; MCAP: path input relative to the server's data
   root). An unavailable one shows its reason verbatim ("Gazebo is not installed (no `gz` CLI on
   PATH)") and **cannot be started** — Start is disabled, not hidden.
3. Start → `POST /bench/sessions` → an active **session chip** appears inline on the row: status,
   live link state (`connected`/`streaming`/`disconnected` — derived, never asserted), packet
   counts, Stop.
4. Stop → `POST /bench/sessions/{id}/stop` (idempotent). Sessions whose source row vanished
   (device unplugged mid-session) stay listed and stoppable under an "unmatched sessions" group.
5. Isaac renders its honest state: installed-but-no-live-adapter, pointing at the direct script
   (`livebench/sim/isaac_direct.py`, run under Isaac's python) or an MCAP recording. ROS is never
   required.

## Flow 2 — connect a robot (the identity-safety flow)

1. Live Bench › **Connect a device** lists every enumerated USB-serial device with exactly what
   recognition claims:
   board name or "unknown", `usb_bridge` renders as "USB-serial bridge — MCU unknown" with its
   confidence (the CH343 case), never a guessed board.
2. The **USB serial number is the identity discriminator** and is always shown. User labels
   ("leader" / "follower") are edited inline and persist locally **keyed by serial** —
   so the binding survives replugging into a different port. A device with no serial falls back
   to a `vid:pid:path` key and is marked **unverified after replug**.
3. Connect → `POST /bench/sessions {mode: real, config: {provider: serial, serial_number}}`. The
   backend re-resolves serial → `/dev/serial/by-id` at open, so reconnects reopen the same
   physical arm.
4. **Two identical devices** (same or missing serials) render as `ambiguous`: connect requires an
   explicit per-device pick (`confirmed_device_path`), shown with the device path as the visible
   tiebreaker. Propose, never assert (RBT-03 posture). A `409 device_ambiguous` from the backend
   surfaces its candidates.

## Flow 3 — see the data without a graph entity

1. Live Bench (`features/bench/BenchScreen.tsx`): a focused graph entity behaves as before.
2. **No focused entity but active sessions** → the device-keyed view (`DeviceBenchView`) renders
   one panel per streaming `device_id` (from the sessions' `device_ids`), polling
   `GET /bench/device-recent` — a connected arm is watchable BEFORE RBT-05 reconciles it into the
   graph. When the device later resolves to an entity, the entity view is the home for its data
   and the views converge (`device_id == external_ref`).
3. The empty state stays honest and becomes actionable: "no telemetry yet — connect a device"
   opens the Connect a device dialog in place.

## Flow 4 — bridge-hosted tools (Fusion, and every tool after it)

1. A local tool's Home row merges the static `GET /api/v1/integrations/local-tools` catalog with
   the per-project live bridge status on its status line: companion state, server state
   (`toolStatusText`). A `ready` server with zero allowlisted tools says "connected — no tools
   callable yet"; connected ≠ callable. `Connect` opens the wizard's single step with the launch
   guidance ("Launch Fusion and enable Preferences → General → API → Fusion MCP Server").
2. The onboarding catalog grows the same **generic `local-bridge` tile** derived entirely from
   the same route — clicking opens guidance + bridge state (`LocalBridgeConnectModal`), never a
   fake OAuth or file-picker flow. The next bridge-hosted tool (SolidWorks, AutoCAD) is a backend
   catalog entry; zero frontend edits.

## Empty/failure states (all honest)

- Runner absent (livebench not installed server-side): every control disabled with that reason.
- API unreachable: section renders offline copy; no cached inventions.
- No devices: "no serial devices detected", not an empty void.
- Session start failure: the backend's error verbatim (`too_many_sessions`, `device_ambiguous` +
  candidates, `source_unavailable`, validation text).

## Platform availability (SOLUSDEV-261)

Local-tool rows and catalog tiles compare `supported_platforms` with the native desktop platform. Unsupported tools show “<Tool> is not available on <OS>” in neutral styling, including while the companion is offline, with Connect disabled. Unknown host platforms cannot connect to restricted tools. Invalid metadata displays “Platform availability is unavailable” and disables Connect. The companion reports unsupported servers as `not_launched` with the same human-readable reason, advertises no tools for them, and never launches, calls, or retries them. Compatible-but-missing installations still report ordinary startup failures. This uses the existing bridge state vocabulary; unavailable servers do not make the companion error badge red.

The bridge popover hides Add license and Upgrade required for OS-unavailable servers: a license or plan change cannot make an unsupported desktop application run. Compatible servers retain their existing license guidance.

### SO-101 model setup

Home → Connected accounts → Simulation offers an explicit SO-101 model setup
panel for the open project. Before Add model, show that it creates a simulation
model with eight links, six joints, one jaw contact sensor and a bottle from the
pinned official SO-101 template; the sensor/bottle are example scene additions,
not measured hardware. The setup does not start a simulator. On success show the
returned graph model identity and direct the user to SOL to probe/start/load via
the existing approval flow. Pending/error states remain local; a project change
must discard stale results. The legacy Live Bench Isaac unavailable row is omitted
on this surface because the owned companion path is separate from Live Bench.
