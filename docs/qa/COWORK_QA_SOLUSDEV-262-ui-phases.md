# UI phases — independent application QA

Use the desktop build from `SOLUSDEV-262-livebench-robo-sol-initial`, a running API and local
companion, and an authenticated project member. Never use production data for mutation checks.
Have a second account outside the test project and a viewer account for authorization checks.
Use a project with five or six real top-level graph nodes, a curated library, and saved robot
models if testing scene geometry. A model fixture is not proof of physical robot geometry.

## Live Bench

- [ ] Open Live Bench. One view contains Scene, Signals, Live reasoning, Runs and widgets; there
  are no view tabs. Scene settings is a closed inline disclosure; expanding it exposes placement
  and mapping without hiding the other panes.
- [ ] With no live telemetry, verify NO STREAM and Waiting for signal evidence. No nominal,
  live, linked-CAD or installed-sensor claim may appear without its supporting observation.
- [ ] Publish twelve motor channels and a thirteenth force channel through a test telemetry
  source. Verify thirteen responsive windows with large values and filled eight-second charts.
  Omit the force unit; verify amber underlined `no unit`, with no guessed engineering unit.
- [ ] Add and remove a channel at the source. Windows appear and disappear without refresh.
  Click a window to scope it; show all to restore the grid. Click its name, rename, reload and
  verify the name persists only for the same account/project/device/channel.
- [ ] Pause. Values and scene freeze while hardware sessions and recording continue. Resume
  catches up. Switch account/project while paused; no previous scope's readings may appear.
- [ ] Interrupt the telemetry request after successful streaming. Retained data is labelled
  stale and health unknown. A recent gap finding remains visible when that channel has aged
  out of the eight-second window and a sibling continues reporting.
- [ ] Inspect real model joint markers and confirmed channel chips. Unmapped joints are never
  assigned synthetic channel names. CAD-linked caption requires actual CAD bindings.
- [ ] Follow the placeholder banner to Hardware. It opens the existing identity review area;
  no device is silently confirmed. Recorded camera/depth playback remains under Runs.

Current limitation: the available APIs provide numeric live telemetry and recorded sensor
frames, not live camera/LiDAR inventory and media. Stream-unavailable copy is intentional;
do not mark a live sensor appearance gate passed using a numeric or recorded fixture.

## Graph

- [ ] Open the five/six-node project. New defaults use organic, non-aligned positions on a dark
  dot-grid; real saved positions are retained. Inspect rounded domain-bordered cards, actual
  type labels, child previews/counts and metadata. Unknown metadata must remain absent.
- [ ] Drag a real node; reload and verify its project-shared position. Add a node and verify
  none of the existing coordinates move. Repeat for a presentation account group: its position
  survives locally, remains account/project scoped, and is never sent as a graph UUID.
- [ ] Inspect curved edges. Labels count actual projected relationships, with cross-domain
  edges visually distinct. Enter/exit a parent and inspect labels and child pagination.
- [ ] With a genuine pending hardware proposal, inspect the floating dashed suggestion and its
  evidence. Reject it and verify it disappears after refresh; accept a separate proposal and
  verify only the reviewed target is linked. Missing proposals must not produce demo cards.
- [ ] Switch accounts/projects during pending reads/decisions. No prior-scope result is applied.
  Preserve explicit conflict recovery when another member moves nodes concurrently.

## Hardware

- [ ] At 1280×800, open Add → Hardware. Devices found is first, Search second, Describe third.
  There is no Sourced card or hardware library/supplier preview modal. Secondary settings and
  unassigned parts are inline disclosures; ordinary empty/typical content fits the panel.
- [ ] For a detected test device, inspect its actual identity/evidence, supply the required
  answer/name, and Add. Count action clicks from the open Hardware panel; creation requires at
  most two. Verify the same device card disappears from the canvas edge and Hardware panel.
- [ ] Search for a library part. Expand specs inline, enter its name, and Add without a robot.
  Verify exactly one standalone part and independent library-provenance config, no container
  robot. Retry a transport-uncertain request with the same operation key: no duplicate part.
- [ ] Import a part into an existing robot and a platform as a new robot. Verify existing config
  and definition facts are retained and no physical connection or motion is inferred.
- [ ] Describe a new part with one field and Add. With no robot, verify an unassigned part;
  with a selected robot, verify the intended category. Optional category suggestions are a
  local fallback, not evidence of a SOL model call. No specs are required.
- [ ] Type a supplier query: no credits are spent by typing alone. Explicitly start the labelled
  supplier search; inspect inline progress/results/specs, then select a candidate. Failures keep
  the draft. The separate BOM sourcing flow continues to work.
- [ ] Disconnect API/companion, unplug a device during review, and test invalid names and viewer
  access. Show honest errors, retain drafts, and never claim successful creation on refusal.

## Isaac application connection

- [ ] Open Home → Simulation. No product/platform import offer is present. Existing explicit
  model operations elsewhere remain separate from the connection surface.
- [ ] Connect status monitoring. The authenticated local bridge may invoke only read-only probe
  and status. No simulation starts, no graph model is created, no scene is seeded.
- [ ] Verify installed only after positive probe evidence; otherwise unknown with the reason.
  Owned-session running status is distinct from arbitrary independently launched applications.
  No telemetry streaming is claimed when the bridge only exposes status.
- [ ] Disconnect monitoring. Requests cease and late responses cannot revive connection state.
  The simulator itself is not stopped. Switching project/account clears the old observation.
- [ ] Test absent bridge, absent capability, malformed status, timeout and rate limit. Render
  bounded honest state, never raw local paths, logs, session details or other tenants' data.
- [ ] Run vendor-hygiene tests including deliberate product-name injection and the existing
  destructive-action gate suite. Injection must fail; mutation confirmation must remain required.

## Final evidence

- [ ] Save screenshots of all four surfaces and compare them with the user's UI brief.
- [ ] Record desktop types/tests/build, changed Python Ruff/strict mypy/API tests, hygiene and
  destructive-gate results, and exactly one Alembic head. Label fixtures separately from live
  hardware evidence; record remaining limitations in the completion report.
