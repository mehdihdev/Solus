# UI implementation and Isaac connection — completion evidence

Branch: `SOLUSDEV-262-livebench-robo-sol-initial`. User authority: the September 15
four-phase UI brief. Descriptions are authoritative; `docs/design/screens/` is absent.
Local commits only; no push, merge request, deployment, or self-approval.
Primary phase commits: `b1b0ac34` (Bench), `2929186e` (graph), `5c8b3215` (hardware),
and `9ebd0a88` (Isaac), followed by separately committed review and visual fixes.

## Delivered

1. Live Bench is one view: approximately 300px scene/sensor column, responsive signal windows,
   eight-second filled charts, inline persisted names, scope/reset, unknown-unit flags, live
   reasoning, and inline capture/playback/widgets. Pause freezes presentation, not hardware.
   Stale telemetry and unavailable health remain explicit. Scene settings is an inline disclosure.
2. Graph cards use organic default positions, curved relationship/count labels, actual metadata,
   two-column child previews, and evidence-backed floating proposals. Saved coordinates remain
   intact. Presentation account groups persist locally per account/project without fake UUIDs.
   Proposal reads are stable across dragging/focus and stale account/project results are rejected.
3. Hardware has Devices found, Search, and Describe. Library specs and supplier results are
   inline. Standalone library imports create a part and independent provenance config without a
   container robot. Describe creates an unassigned part when no robot exists. Explicit supplier
   search retains the existing credit gate; typing does not spend credits. Completed creation
   clears its idempotency key; uncertain retries preserve it.
4. Isaac has a generic application-status connection surface. The old platform import offer and
   unused component/client are removed. A project-authorized, rate-limited endpoint projects only
   bounded probe/status evidence. Connection polling invokes no simulation mutation. The vendor
   hygiene ratchet covers connection paths and proves that injected product copy fails.

Review fixes include stale telemetry health, aged-out signal gap findings, account-switch races
in supplier search and Isaac polling, completed-operation idempotency, and compact scene settings.
API schema and generated desktop types are refreshed.

## Governing documents

Read root instructions and locked decisions, architecture `workspace-navigation.md` and
`local-machine-actions.md`, API plans `workspace.md`, `hardware.md`, and `isaac-development.md`,
and wireflows `workspace.md`, `hardware-onboarding.md`, and `widget-canvas.md`.
Tier-1 amendments describe the new presentation, standalone library compatibility extension,
and bounded Isaac status endpoint. No ADR, contract, hook, or environment file was edited.
The execution plan and independent QA walkthrough accompany this report.

## Verification

- Final desktop full suite: 4,092 tests across 412 files passed.
- Repository `pnpm typecheck` and production desktop build passed; the missing `./bench.css`
  import resolves and its stylesheet is bundled.
- Changed Python: Ruff passed; strict mypy passed across all eight changed production/test files.
- Full API suite: 7,192 passed, six skipped, eight warnings. The annotation-only follow-up also
  passed its thirteen focused Isaac tests.
- Standalone library API: 25 tests passed, including replay/conflict, authorization, and tenant isolation.
- Live Bench focused suite: 137 tests passed, including twelve motor channels plus a thirteenth
  unit-less force channel, dynamic windows, pause, naming, scope, and stale evidence.
- Vendor hygiene and destructive-action gate regressions: 29 passed.
- Alembic: exactly one head, `a26200000001`.
- Fresh code/TypeScript and dedicated security/Python reviews passed after their findings were fixed.
- Automatic approval review allowed the necessary local runtime checks and commits. Initial
  sandbox runtime/network restrictions were retried through that review, not bypassed.

Root ESLint across changed TypeScript files has zero errors; function-length warnings remain.
Complexity errors were resolved by extracting cohesive helpers without suppressions. Scoped
bench and scene regressions and navigation zoom tests passed after those changes.
Fresh reviews caught a new await boundary in the scene import helper; `3c9611e0` restores the
generation guard immediately before import and adds a deterministic failing-then-passing
regression. Both reviewers confirmed the correction. An existing picker test now waits for its
initial loading state to finish before clicking; all stale-result assertions remain intact.

## Screenshots and live observations

Screenshots are local artifacts under `tmp/ui-phase-screens/`: `live-bench.png`,
`graph-existing-project.png`, `graph-five-nodes.png`, `hardware-three-devices.png`, `isaac.png`,
and `live-bench-18-live-signals.png`.
They show actual application state, not fabricated telemetry. The CAD QA project contains
explicitly named synthetic QA entities; it is not proof of physical arm geometry.
The local Isaac bridge positively reported Installed and Owned session not running. Monitoring
was disconnected after verification. No simulator or hardware motion was commanded. The saved
Leader telemetry connection succeeded on serial `5B42135040` and automatically displayed
eighteen live windows: position, load, and temperature from six motors, with observed units.
The named Follower entry refused connection because its saved config lacks transport identity
or protocol; the refusal did not disturb the Leader stream or invent a connection.
Leader read-only telemetry was left running for inspection; Manage connections exposes Stop.
The final hardware panel showed all three settled device cards, Close, Search, Describe, and Add.
At the actual 1280×720 viewport its content measured 621px versus 588px available (33px scroll).
The same CSS provides 668px at 1280×800, so the measured content fits with 47px spare; this is a
derived size check, not a screenshot captured at 800px height. The panel is anchored outside the
graph's clipping boundary. Small saved graphs are framed without rewriting stored positions.
The Describe path created `QA UI force sensor` in the existing synthetic QA robot with one Add
action after entering the name; the new part appeared and its draft cleared. These are planned
QA graph entities, not new physical sensor discoveries.
Repeating the path created `QA UI pressure sensor`. The five-part level was captured with organic
positions; Fit and 100% controls let the user alternate between overview and legible card detail
without changing saved coordinates. A floating-proposal interaction is covered by component
tests; no synthetic pending proposal was inserted into the live project for a screenshot.

## Needs you / capability gaps

- Live camera/LiDAR discovery and media are not exposed by the current APIs. The UI states that
  live streams are unavailable and points to existing recorded sensor playback. A live sensor
  appearance gate remains unverified; numeric fixtures do not satisfy it.
- Describe category suggestions use the existing local fallback. It is labelled as a suggestion,
  not a SOL model result. Actual SOL classification remains an unimplemented capability.
- Isaac connects to read-only status monitoring through the owned local bridge. It cannot attach
  to arbitrary independently started Isaac instances or claim a telemetry stream. A negative
  probe is Unknown, because the bridge does not distinguish missing installation from unsupported
  discovery. Those broader connection capabilities remain outside the available status seam.
- Leader live telemetry was verified with eighteen windows. The precise twelve-motor-plus-force
  gate remains covered by component fixtures, not a live paired-arm/force capture. The named
  Follower graph entry needs its missing transport/protocol configuration reconciled before that
  saved entry can stream; physical USB presence alone does not supply that accepted config.
- Existing shared graph coordinates are deliberately preserved, including old matrix layouts.
  New defaults are organic; a deliberate user arrange/reset is needed to replace old placements.
- Human review, push, and MR remain human actions under repository policy.
- The repository's requested Ponytail plugin is unavailable in this environment. Independent
  code/security reviews and scoped dead-code cleanup were used; no Ponytail execution is claimed.

These limitations are not represented as passed acceptance gates. No credentials were written
to source, fixtures, or this report.
