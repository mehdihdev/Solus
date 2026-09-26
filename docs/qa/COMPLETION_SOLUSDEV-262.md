# SOLUSDEV-262 — implementation and verification report

**Last updated: 2026-09-14. Status: implementation and scoped verification complete; live prerequisites remain.**
The branch implements brain topology, reviewed local evidence, presence preparation, W5 roots
and suggestion memory, L1–L5, and S4. The gate matrix separates verified software from physical
checks that remain unperformed; this is not a claim that every live acceptance gate passes.

## Implemented behavior

- Brain → bus → device → part projection preserves accepted ownership, CONFIG, calibration and
  part IDs. Categories are filters. Reviewed host attachment uses an explicitly selected local
  source on the matching companion; linked remote repositories remain references. Firmware,
  host-config, schematic and onboard extractors share bounded evidence structures. Selected
  firmware/config file review and explicit acceptance retain provenance without changing runtime
  CONFIG or claiming a detected physical device from a declaration.
- Transport-only USB devices can be explicitly added as MCU connections without starting a
  session. The CH340 Uno remains **Possible Arduino connection**, with firmware unknown and
  identity tied to its USB port. Explicit profile selection prepares retained heartbeat/probe
  source and compiled artifacts. The registered flash tool uses the existing central gate,
  complete source preview, target/digest revalidation, port ownership and verified upload.
  A serialless device is ineligible for the dev QA autoapprover.
- Typed inputs, scoped schematic graph evidence and retained device-scoped probe recordings
  now have separate proposal and acceptance steps. Accepted wiring drives bounded analog/digital
  input firmware; empty declarations generate heartbeat only. Evidence is revalidated during
  compilation and immediately before upload. Unknown devices remain unresolved. Existing local
  Arduino sketches have an explicit scalar-telemetry snippet offer with a forced complete file diff.
- The Python telemetry mirror preserves explicitly configured synchronous method results and
  exceptions, sending bounded numeric dictionaries over loopback through a background queue.
  It makes no extra robot calls. The explicit local-file offer routes the reviewed snippet
  through the existing file tool with forced central confirmation. No control source has been
  edited and no running shim is claimed.
- Persisted Live Bench/widget registrations appear as roots. Declined suggestions are remembered
  by evidence set. Reviewed attachments preserve identity and scoped projections.
- L1 connects saved configurations and streams device-keyed signals with no focus. L2 imports
  bounded URDF/MJCF and explicitly associated STL artifacts into a client kinematic scene,
  with namespaced models, independent persisted poses and confirmed live joint mappings.
  Bound CAD meshes refresh from the exact successful source-sync STEP export, preserving model
  identity and showing stale/error state on failure. This is not a physics simulation.
- L3 preserves packet units, supports compatible display conversion and scoped persisted names,
  uses stable unnamed motor defaults, and renders timestamped observer markers. Session observers
  describe statistical changes, not an inferred physical fault. Recorded camera/LiDAR references
  have explicit bounded previews at their captured timestamps.
- L4 produces deterministic graph-grounded findings from recorded evidence and reports missing
  current/rating/command context honestly. Optional narration batches through the existing metered
  cheap-tier gateway; generated prose cannot replace numeric findings. L5 captures bounded runs,
  snapshots configuration/identities/source context, retains artifacts, supports playback and
  same-robot comparison, and marks interrupted/truncated evidence explicitly.
- S4 offers confidence-bearing, surface-aware Guide steps and explicit native-overlay handoff
  with fallback. Guide does not execute. Build retains the real approval gate. The existing
  native shortcuts summon SOL and switch Guide/Build while another application has focus.

## Live and compiled evidence

Both boards simultaneously returned six STS3215 addresses (1–6). The user-confirmed leader is
serial `5B42135040` at `/dev/ttyACM0`; follower is `5B42134331` at `/dev/ttyACM1`.
The Uno is CH340 `1a86:7523`, `/dev/ttyUSB0`, no serial, observed USB location `3-1.2.3`.
Paths are current observations, not durable board identity. Evidence files include
[SOLUSDEV-262-both-arms-live.json](SOLUSDEV-262-both-arms-live.json) and
[SOLUSDEV-262-arduino-label-live.json](SOLUSDEV-262-arduino-label-live.json).

Both arms streamed simultaneously without workspace focus. A saved leader baseline captured
**1,860 packets, zero drops, 10.347 seconds**, and playback scrubbed successfully. A follower
baseline captured **2,715 packets, zero drops** and was saved. These are read-only baselines,
not a stall or a deliberate clamp-change experiment. Both sessions were stopped afterward.
Persistent artifact storage is configured under ignored `tmp/solus262-artifacts`; both saved
runs remained readable after restart. Live signal rename/reconnect passed and the original label
was restored. The Uno was explicitly accepted without starting a session, and its probe source
preview prepared in the running app. Requesting central review returned **402 from the Solus
budget gate**: no confirmation card was created and no flash occurred.

Two synthetic jointless/hinge URDF fixtures were imported in the UI; their independent X poses
(0 and 0.3 m) persisted. The jointless explanation appeared. These are not actual arm geometry,
and no live joint mapping was invented. See
[SOLUSDEV-262-runs-presence-live.json](SOLUSDEV-262-runs-presence-live.json).

Actual Uno heartbeat and probe sketches compiled using official Arduino CLI **1.5.1** and
AVR core **1.8.8** in a task-local toolchain. Heartbeat source/binary SHA256:
`16fd00853c275818a39df8c1fee8c4b31d23a6269b152f891db7d575503b3387` /
`a9dd6fd85bfa3ad74be24526e95733bd09f9988b28d0a0cab57c4405d7fdd7cf`.
Probe source/binary SHA256:
`864c648d1e1fd77c9e31accc7366c1eb435ba69f5881e73016cb487563503ef7` /
`b1f4e5fb409caf25f6dca271960c780cb9a0d187d0f5e22f095e8d1a2163be97`.
Compilation does not prove flashed firmware or pin observations. No flash or motion occurred.

The running Uno card also reviewed and accepted an empty input declaration, then compiled the
same heartbeat source/binary above from that accepted plan. This is no claim of physically empty
wiring. Uno and Nano empty/mixed/maximum topology sketches compiled with the actual AVR toolchain.
The maximum 16-input plan uses 8,088 flash bytes and 618 static SRAM bytes, leaving 1,430 bytes;
channel names are copied from flash into one reusable buffer. Exact compiler records are in
[SOLUSDEV-262-topology-avr-compile.json](SOLUSDEV-262-topology-avr-compile.json).

The separate **SOLUSDEV-262 CAD QA** project contains clearly labeled synthetic CAD evidence.
Browser checks passed for Accept (existing part attached), Decline followed by rescan (remembered),
and manual Structure attachment. No original arm mapping was changed. See
[SOLUSDEV-262-cad-ui-proof.json](SOLUSDEV-262-cad-ui-proof.json).

With an external X11 xmessage window focused, **Ctrl+Shift+Space** summoned SOL and
**Ctrl+Space** switched Guide ↔ Build. Temporary cropped evidence is at
`/tmp/solus262-native-sol-before.png` and `/tmp/solus262-native-sol-after.png`.
This proves native shortcut handling, not overlay pointing at a real application control.

## Database evidence

Private backups are mode 0600, ignored under `tmp/backups/`; no dump is committed.

- Resume archive SHA256: `2700c9094a7f924018e8b96bc885e1f0ea2212a0e5e1695fe76b310ac6389a0b`.
- Immediate pre-live archive: `SOLUSDEV-262-pre-live-topology.dump`, 838452 bytes,
  SHA256 `605669e0f704a8bdd65565a785cbe54d96c97812de032b69be9ff347d6cf1715`.
- Restored rehearsal: `solus_262_rehearsal_reviewed`; upgrade to `a26200000001` succeeded.
- Live upgrade to `a26200000001` succeeded. Entity count 2640 → 2672; edge count 2682 → 2805.
- All `solus_entries` row checksum before and after, both rehearsal and live:
  `f3db0b066a76966547b8b92d2ab2ea32`. This is an equality check, not a security hash.
- Later review added a preflight rejecting cross-owner Wi-Fi/Ethernet conflicts and runtime
  refresh/rejection tests. That additional preflight did not require another live data rewrite.

## Gate matrix

“None” means no such evidence was collected; fixture evidence never establishes live behavior.

| Gate | Live bench/app | Recorded real | Fixtures/tests | Remaining work or human action |
| --- | --- | --- | --- | --- |
| P0 env/ports/snapshot/runtime inventory | App/API/companion checked | Private backup | Restored rehearsal | No additional human action |
| P0 Uno enumeration | CH340 observed; tentative label | Enumeration JSON | Identity/hint regressions | Exact MCU profile is an explicit selection; firmware unknown |
| P0 two boards, six responders each | Both simultaneous | Ping/calibration JSON | Driver tests | USB swap skipped by user |
| P0 host/control source | Machine and selection card checked | None | Host authorization/replay | Actual control folder not confirmed |
| P0 baseline/fault inventory | Read-only baseline capture | Leader/follower runs | Synthetic fault data | No recorded-real stall or clamp pair |
| P0 QA approver/refusals | Inactive; zero approvals | Approval log | Wrong device/motion/non-dev/serialless refusal | Serialless Uno needs manual central approval |
| P1 host brain/local software/shim | No accepted local attachment | None | Host API, mirror receiver and forced file-confirmation tests | Local folder/file selection for actual attachment |
| P1 nested boards/six parts/repo roles | Serial roles confirmed; saved mappings preserved | Physical addresses | Host nesting and extraction acceptance | Full live six-part follower mapping/local provenance not established |
| P1 bare MCU/unknown firmware | Explicit Uno connection accepted; no session | Enumeration | Connection-only acceptance | Firmware remains unknown |
| P1 probe erasure card/pin result | Probe prepared; review request blocked by budget 402 | None | Compiler/provider/central gate | Budget availability, then manual card approval and pin observation |
| P1 heartbeat flash/uno.alive | Not flashed | None | Real compile plus gated provider tests | Budget availability, then manual card approval and live channel |
| P1 firmware/config/schematic/onboard extraction | Browser unavailable-picker state checked | None | Four adapters, authorized review and acceptance | Native selected-file proof pending |
| P1 reviewed wiring/generated sketch | Empty declaration accepted and compiled in app | No probe recording | Typed/schematic/probe, stale evidence, scoped acceptance; real Uno/Nano compilation | Actual probe telemetry still needs budget and flash approval |
| P1 existing firmware integration | Local-folder prerequisite displayed | None | Scoped manifest selection, scalar snippets, forced complete file-diff gate | Select actual local sketch to review its diff |
| P1 onboard companion deployment | Skipped live | None | Central API confirmation → provisioned-target runner/helper install, fresh handshake, rollback/recovery; 48 tests | Live SSH deferred; initial enrollment unsupported; local factory disabled by default |
| P1 MAVLink/CAN/onboard twins/vendor proof | Not live machines | Existing transport recordings | Extended three-machine proof: 10 passing tests | No live substitute claimed |
| P1 preservation migration | Upgrade successful | Snapshot/checksums below | Idempotence/rollback/auth/ambiguity | No additional human action |
| P2 widget roots/lifecycle | Live Bench root opened | None | Registration/projection/lifecycle regressions | Complete live extension lifecycle pending |
| P2 removed-binding rediscovery/no duplicate | Live DB unchanged | None | DB-copy rediscovery preserves partial/full binding IDs without duplication | No additional human action for copy proof |
| P2 CAD suggestion/manual attach/decline | Accept, decline/rescan and manual attachment pass in synthetic QA project | None | Scoped evidence, stale review and attachment tests | No additional human action |
| P3 no-focus streaming/accepted ingest/disconnect | Both streaming; stopped/disconnected | Saved runs | Session/ABA/isolation tests | No additional human action |
| P3 two scenes/live joints/independent poses | Two synthetic UI models; independent persisted poses | None | URDF/MJCF/STL/mapping/pose tests | Actual arm geometry and confirmed live mappings unverified |
| P3 jointless reason/CAD microversion refresh | Jointless explanation displayed; no real CAD edit | None | Changed STEP geometry with same bounds | Real Onshape edit optional live follow-up |
| P3 widgets/default names/rename/units/markers | Streaming and rename/reconnect passed; label restored | Packet units in runs | Conversion/persistence/defaults/observer tests | Live marker proof not claimed |
| P3 camera/LiDAR/joint timestamps | No connected camera/LiDAR | No real sensor capture | Timestamped sensor UI alignment and bounded preview tests pass | No live camera/LiDAR proof claimed |
| P4 stall/rating/command/code/CAD attribution | No induced stall | No recorded-real stall | Deterministic synthetic analysis | Live stall experiment not performed |
| P4 cheap narration/no finding | Live narration pending | None | Metered batch/fallback/no-invented-finding tests | No additional permission for software checks |
| P4 two-run clamp comparison | No deliberate motion pair | Clean baselines only | Synthetic clamp/config comparison | Real paired experiment not performed |
| P4 retained manifest/config/code/IDs/playback | Playback scrub and both runs readable after restart | Both baseline runs | Durability/interruption/pagination/isolation tests | No additional human action for retention proof |
| P5 Build label/Guide confidence/no execution | Native Guide/Build displayed | Screenshot crops | Surface-aware steps and no-write tests | No additional human action for fixtures |
| P5 Build diff/approval/Onshape refusal | No provider write | None | 6 mm hole Guide vs gated Build fixture | No automatic Onshape approval |
| P5 external shortcut/overlay | Both native shortcuts pass | Screenshot crops | Native handoff/fallback tests | Real external-control pointing unverified |
| P6 tests/types/lint/reviews | Scoped checks pass | None | Final integrated totals below | Repository-wide lint baseline unresolved |
| P6 single migration head | a26200000001 | Backup | Single-head recheck passed | No additional human action |
| P6 inactive QA config/ratchets/log | No QA approver enabled | Zero approval journal | Seven destructive/vendor ratchets pass | No additional human action |

## Verification status

The integrated desktop suite passed **4,045 tests across 405 files**. One prior full run had a
transient file-import menu failure; its isolated 18 tests and subsequent full suites passed.
The final integrated Python suite passed **1,259 tests** in 594.42 seconds, including the corrected
provider/route/vendor checks, wiring evidence and onboard deployment paths. Counts from focused
runs overlap these totals and must not be added. Desktop typechecks and production build pass.
Scoped Python lint and types pass (12 and 11 files respectively); scoped frontend lint passes
with function-length warnings. Repository-wide desktop lint has an existing baseline of
**100 errors and 41 warnings**, so this is not a full lint-green claim. Frontend coverage was not
measured because the workspace lacks the Vitest coverage provider.

Focused verification includes 197 CAD/source tests (one skip), actual revised-geometry fixtures,
CAD mutation tenant/refused-grant tests, presence full-preview/central-decision tests, mirror
queue/receiver tests, bounded sensor transport/UI alignment tests, and session-observer failure
isolation. The forced host-file confirmation path passed 42 tests. CAD suggestion service tests
passed 13 tests at 90% coverage, followed by 24 backend and 11 UI tests for integrated suggestion
behavior. The extended three-machine proof passed 10 tests. Counts overlap and must not be summed.
Reviewed wiring and presence passed 38 tests at 92% coverage before two additional relation-change
regressions; topology generation passed 55 tests at 100% statement coverage. Onboard API/runner
integration passed 48 tests at 82% aggregate focused coverage, and dedicated security review
independently passed 77 runner/generator/presence tests. Fresh code, security, Python and TypeScript reviews passed after their findings were fixed.
Review fixes include prismatic tolerances, MJCF rotation composition, complete flash preview,
verified upload, stale mapping/CAD updates, run pagination, scope changes and uncertain retries.
Tests use disposable databases, never the populated development database. Historical checkpoint
suite totals remain in Git history and are not current integrated-suite evidence.

## Governing documents and delegated decisions

Read the supplied brief, SPEC §§2–5, hardware architecture/API/wireflow, 251 review, 260 report,
and the current bench-scene/bench-runs API plans and SOL-window wireflow. Tier-1 amendments
record extraction acceptance, transport-only MCU acceptance, presence preparation, scene CAD
refresh, run APIs and Guide tasks. Contracts, ADRs, AGENTS, hooks and `.env*` are unchanged;
the user-owned restored SPEC remains unstaged. Local implementation commits stay on
`SOLUSDEV-262-livebench-robo-sol-initial`; no push or MR is performed.

The user authorized autonomous continuation and later permitted arm control. No motion was
needed for the completed read-only proofs. Driver boards are never flashed. No source folder
is inferred from a connected remote repo. A discovered `/home/beeboss/lerobot` directory remains
unselected until the user confirms it or selects it through the native picker.

## Remaining live prerequisites and deferred checks

- Select/confirm the local arm-control folder and loop file to prove the host attachment and
  review the actual mirror insertion. The explicit offer must be prepared before approval.
- Restore Solus budget availability before requesting Uno flash review: the actual request
  returned 402, so there is no card to approve yet. Then approve each concrete card manually.
  This Uno has no USB serial and cannot satisfy the brief's serial-only QA allowlist. No automatic
  approval is substituted. An empty pin result requires actual probe telemetry.
- Real stall/clamp-pair experiments, real Onshape dimension change, and external-control overlay
  pointing remain unverified live. Fixture checks do not establish those physical/UI results.
- USB swap and live SSH deployment are explicitly deferred by the user. Driver firmware must
  not be flashed as part of this work; any future firmware integration requires its own review.


The inactive approver and its log are documented in
[QA_APPROVALS_SOLUSDEV-262.md](QA_APPROVALS_SOLUSDEV-262.md). Follow
[COWORK_QA_SOLUSDEV-262.md](COWORK_QA_SOLUSDEV-262.md) for independent application acceptance.
