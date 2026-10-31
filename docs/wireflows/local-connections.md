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

## Findings pane (SOLUSDEV-321)

Live Bench › right column, directly under LIVE REASONING (widget-canvas.md, 2026-09-15: "Findings
follow under LIVE REASONING"). `features/bench/findings/FindingsPane.tsx`, mounted once by
`BenchScreen` inside `DeviceBenchView`. It shows the durable findings the robot session's window
evaluator raises (docs/api/findings.md §5); LIVE REASONING above it keeps the raw observer events.

**Layout.**

- A `FINDINGS · <n> OPEN` heading; in Guide mode, one sentence on what a finding is.
- One group per connected robot: each bench session that has not ended and names a
  `robot_entity_id` (a robot, or a part bound on its own), headed by the session's label and its
  open count. Sim and serial sessions observe no root and get no group. With no connected robot
  and no opened finding the pane is absent.
- Data: `GET /findings?status=open&robot=<id>` per robot. The pane mounts the Bench's one project
  stream; its `finding.*` and `graph.changed` frames bump the findings live key and the reads run
  again. Nothing polls. A failed stream shows its status line ("Live updates unavailable…").

**Grouping.** Within a robot: critical, then warning, then info. Each block is headed
`<SEVERITY> · <count> · last seen <relative>` (the newest `last_seen`). Info findings, checker
infos among them, start collapsed in a disclosure, so however many there are they never push an
observer finding off the pane.

**A finding card.** The headline, then `<severity> · ×<count> · last seen`. Guide mode shows the
explanation under the headline; Expert keeps it inside the card. Clicking the headline opens:

- the explanation (Expert);
- `detail` as its lines (`suggested headline: …`, `not grounded: …`);
- the evidence: the top-level keys of `evidence`, which are the latest raise's values (never the
  `items` history);
- the likely causes, in the narration's `causes_ranked` order, each with what speaks for and
  against it;
- the code site (`path:line`) and the folded rules (`Also seen: …`).

Every string is server text and renders as text. Nothing is interpreted as markup.

**The six actions.** Each action uses exactly one route. A status line under the card reports the
outcome, or the API's error verbatim.

1. **Explain more**: opens the SOL window and sends a Guide turn with `finding_id` and
   Solus-authored text. The headline is never typed into the message; SOL reads the finding through
   the anchor.
2. **Propose a fix**: the same turn in Build (`action_mode: do`), keeping the chat's own
   confirm-every-change choice.
3. **Open the tool**: offered only when `evidence.code_site` names the code entity and that
   entity's source. `POST /local-folder/{source_id}/open {entity_id, tool: system}`; a
   `launched: false` shows the tool's reason.
4. **File**: one `.solus` errors entry,
   `POST /solus/errors/entries {kind: text, text: "<headline>\nfinding: <id>"}`.
5. **Dismiss**: `POST /findings/{id}/dismiss` (24 h). It writes nothing else, and the card leaves
   the open list.
6. **Resolve with note**: a required note (≤ 4000 characters) and, when the finding has a code
   site, an opt-in "Fixed in `<path>:<line>`" box that sends the code entity as `fix_ref`.
   `POST /findings/{id}/resolve`; the route files the one errors entry and the desktop files none.

**Markers.** A signal chart draws dashed markers from `GET /bench/events`. A marker the window
evaluator placed carries its finding's id (attached server-side only; a malformed id makes the
response invalid). That marker is a button over its line, "Open finding: `<kind>` at `<time>`".
Clicking it reads `GET /findings/{id}` and shows that finding expanded at the top of the pane
("Opened finding", with Close), whatever its status, read again when the findings live key moves.
Two findings marking one instant stay two markers. A marker without an id stays a line.

**Empty and could-not-check states.**

- A connected robot with no open finding: `✓ Nothing out of range` (the copy LIVE REASONING
  uses) and "No open findings for `<robot>`".
- A failed read: "Findings are unavailable for `<robot>`; what it shows is unknown". Never the
  all-clear.
- **Could not check** (per robot, a disclosure): opened, it reads the robot's
  `attrs.missing_signals` (`GET /entities/{robot}` → `properties.missing_signals`) and lists each
  `<part>: <need>`. It is read on request only, never on render. An absent attr reads "Not
  assessed yet"; an empty one, "Every signal and fact the rules need was there".

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

### Simulation model setup

Simulation models must be explicitly registered from existing graph bindings and
schema-v2 local asset manifests. No vendor-specific template is created from the
connection panel. Registration does not start a simulator; SOL uses the existing
probe/start/load approval flow with the selected graph model identity. Pending
results remain scoped to the originating project and are discarded on change.

### External telemetry producers (SOLUSDEV-262)

Live Bench also discovers devices from authenticated external telemetry ingestion
through `GET /bench/telemetry-devices`, polling every five seconds while online.
Their IDs merge with session IDs without duplicates and use the existing signal
panels, even before graph binding. No synthetic session or serial connection is
created. External IDs expire after 15 seconds without packets; failed discovery
clears its results. Account/project/workspace-generation changes immediately hide
old results and discard late responses. Session controls still refer only to real
Solus-owned sessions.

### Isaac model selection after generic-model cleanup

Select an explicit schema-v2 graph simulation model and authorized workspace asset
closure. Missing or legacy model bindings show an actionable refusal; no default
robot, bottle, joint mapping or grasp routine is substituted. Review the complete
load or bounded joint-trajectory preview before execution. Result cards report
observed joint tracking only. Existing confirmation and stale-state flows remain.
