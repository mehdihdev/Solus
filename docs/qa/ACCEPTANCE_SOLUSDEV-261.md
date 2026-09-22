# Integration acceptance checkpoint — 2026-09-13

Project: Workspace W242 Service QA (`01a074e0-3bb4-7317-ba53-7b653bb1f6a8`).
Checkout: SOLUSDEV-261-integration-check. Hardware, XIAO and Live Bench excluded by user.

| Integration | Live product evidence | Still required |
| --- | --- | --- |
| Onshape | Draw Piece imported; circle and pocket created automatically; pocket depth 0.5 → 0.6 → 0.5 mm verified; automatic persisted geometry delta and observed microversion proved; Variable Studio 2 → 1 → 2 mm full-table readback and graph sync passed | Assembly insertion/mates and full hosted FeatureScript operations |
| KiCad | Bound project imported 34 entities/35 relations; label and automatic R1.Value 10k → 10000 edits verified; unchanged divider geometry/topology; ERC 0 errors/0 warnings and automatic graph sync passed | Other drawing operations through product; complete rail-current analysis |
| Isaac | Real 17-entity/30-relation model; full bounded start/load six joints/limits/sensor/routine/stop passed automatically; three Guide questions passed | No grasp observed; arbitrary models/scripts and Onshape FSR-pocket provenance not accepted |
| Local code | Automatic 59-byte creation and 67-byte existing-file edit passed with readback; setup/loop preserved | Full build/test round trip, streamed output and sketch pin/bus/library topology |
| GitHub / GitLab | Real read-only GitHub sync imported 157 entities and SOL remote read_code_file passed | GitHub writes prohibited; GitLab excluded; real local-clone reconciliation not yet established |

Native developer evidence is separate: latest KiCad property/publisher checkpoint
427 tests passed, one optional skip and one existing expected failure; Isaac86pass,
36cloud tests,16template database tests. Peer reviews passed. These tests do not
substitute for user approval and live product round trips.

## Exact persisted setup

- KiCad source: `01a098b1-aa10-763c-9c7c-27712ea0ccc8`.
- Companion workspace: `/home/beeboss/Solus/tmp/integration-check-kicad`.
- Bound project: `verified-divider-final/uno_fsr_divider.kicad_pro`.
- Isaac graph model: `01a098b2-7479-7ca5-9807-773e7ff58350`.
- Draw Piece did/wid/PartStudio: `8282d38e5a53b2eabab497d9` /
  `9cf5cb67e246fb6b9cdf4e84` / `b1b3d31704c9161794c584e1`.
- Current owned stack session: `45051`. Earlier stack/log references below are historical.

## Current authorization and pending work

Credits were unblocked through the approved development allowlist. The user
approved the KiCad label and Isaac start, then explicitly superseded routine
Build approval cards with automatic execution. No additional approval is needed
for those already authorized routine actions. Destructive and unclassified
operations still require an individual decision; remote pushes and hardware are
outside this acceptance scope. Remaining integration proof is listed below.

## Development credit unblock (2026-09-12/13)

User approved the ADR-024 development-only allowlist exception. Enabled the current
account in the checkout-local ignored configuration. Billing and SOL both show
Unlimited (development); a real fresh SOL smoke turn returned “SOL is ready.”
without tools. Credit exhaustion no longer blocks this development account.
Real usage accounting, production credit enforcement and tool approvals remain.
See COWORK_QA_development-credits.md for verification and revocation. This credit smoke test does not complete integration acceptance. The subsequent
Build policy amendment below governs routine writes.

## Live acceptance follow-up and policy change — 2026-09-13

- User approved Isaac start. SOL status readback reported running session
  `755f9ab6-8135-4291-860a-1759658f58a7`, loaded=false.
- User approved KiCad label. Saved file contains SENSE_A0 at R1.1 position
  (114.3,80.01)mm. Automatic KiCad source sync
  `01a09a83-06e9-701d-8601-fd1ef334611f` succeeded as webhook trigger at
  2026-09-13T11:24:33Z: 4 entities updated, zero errors. SOL invoked geometry,
  export and ERC successfully but an overbroad follow-up hit its tool loop guard;
  the narrowed product call `kicad.check_erc` subsequently returned Passed,
  errors=0, warnings=0. Independent native ERC agreed; four configured ignored
  checks remain explicitly reported by the tool.
- Onshape circle approval falsely went stale: live reads had identical source
  microversion080524ab6c33b2c5f3acfb5b but regenerated constraint nodeIds and
  serializationVersion1.2.0/1.2.21. Fixed comparison to ignore only generated
  metadata; semantic state and microversion remain bound, fresh write envelope
  retained. Consecutive live previews now match. No circle was applied at that checkpoint; the successful automatic circle below supersedes it.
- User explicitly changed Build policy: routine edits execute automatically,
  compact prompts only for drastic/unclassified actions; ambiguous intent gets
  clarification. This supersedes the earlier all-writes-card acceptance rule for
  routine Build operations (ADR016 action amendment9ad24ef1). The central trusted execution policy was subsequently implemented and the
  automatic live writes below passed.
- Compact approval UI complete (21tests); CAD preview/variable safety192tests
  passed. Isaac advertisement now includes load_model/run_routine (88native
  tests); the subsequent restart and full bounded product round trip below supersede
  the earlier pending state.

## Automatic Build live proof — 2026-09-13

After restarting the owned development stack, SOL invoked create_circle_sketch
exactly once and created `SOL acceptance circle`, feature `FGJZMs4hAhROhbN_1`,
center (0,0) mm and radius 6.35 mm on the authorized Draw Piece face. No card was
shown. The tool verified vendor readback and queued the shared source-sync hook.
Sync `01a09aa5-3ea8-7526-9097-a1d52cf8f1a5` completed at 12:02:09Z with zero
errors and zero part updates (sketch-only change). The sync record uses the
existing `manual` trigger enum even though the tool hook queued it automatically;
no refresh button was clicked. Current stack session6368, log
`/tmp/solus261-build-policy-live.log`.

KiCad persisted graph readback additionally confirms /SENSE_A0 connected_to
A1 pin9 (Uno A0), R1 pin1 and RFSR1 pin2, preserving the divider topology.

Live cut also passed: `SOL acceptance pocket`, feature `FRrBskvCj5sNzwW_1`,
depth0.5mm, opposite_direction=true. Sync history
`01a09aa8-ba4b-789a-9b7b-a12421bdadac` corresponds to returned job ID
`01a09aa8-b914-7676-84a3-5b685fe617bb`; both identify the same successful job.
Zero graph updates exposed a projection gap: the current STEP graph retains
names/hierarchy/placement but no geometry or observed microversion. The shared-parser geometry projection fix has since landed and persisted
measured geometry with observed microversion, as recorded below. The initial cut
sync alone did not prove a numerical geometry change.

## Isaac automatic Build round trip

Session `ec94412e-7bad-43b1-b8b9-05682994d518` started and loaded graph model
`01a098b2-7479-7ca5-9807-773e7ff58350` with six verified joints and jaw sensor.
Shoulder-pan limits changed to [-1,1]rad (generation2); sensor translation changed
to [0.001,0,0]m, WXYZ [1,0,0,0] (generation3). Named finite routine completed
360steps at generation4, contact valid=true, force0N, grasp_observed=false,
targets_reached=false, max final joint error0.01874488rad. All actions executed
through SOL automatically with native readback. No hardware or Live Bench used.

The same bounded Isaac acceptance also completed stop successfully. Three live
Guide questions passed for lifecycle, model/joints and safe sensor/limit edits.
No observed grasp is claimed.

## Latest live property, geometry and code checkpoint

- KiCad `R1.Value` changed automatically from `10k` to `10000`. Saved schematic
  fingerprint: `f9971d6e407364d5:775e258e95e826d8:b759fd0db2fcde87:7f378a7e18ae3eae`.
  Geometry, wires and labels stayed unchanged; ERC returned zero errors and zero
  warnings. Webhook sync `01a09ac4-58e8-7499-942b-8cac864df741` succeeded at
  2026-09-13T12:35:54Z with four entity updates and zero errors. This proves
  automatic property execution, saved-file readback and persisted graph refresh.
- Onshape feature `FRrBskvCj5sNzwW_1` depth changed automatically from 0.5 to
  0.6 mm with verified readback; returned sync job
  `01a09ac5-40b5-7a6e-8de0-1616614d8ad9`. Persisted microversion
  `eee8cce89814e294a5aafc9e` now contains volume `13568.091301492 mm³` and
  dimensions `[146.05, 2.0000001, 57.15] mm`. No before-volume was captured
  for that first edit. The subsequent automatic restoration from 0.6 to 0.5 mm
  established the numerical delta: job `01a09ac6-b10a-7199-9d24-e68203c62760`
  changed persisted volume `13568.091301492 → 13580.758988469 mm³`, an increase
  of `12.667686977 mm³` (π × 6.35² × 0.1). Surface area changed
  `15863.060938058 → 15859.071115388 mm²`; bounds/dimensions stayed unchanged.
  Microversion changed to `004f36210573b501e3a29d29`. The other Part Studio's
  `51959.096169737 mm³` volume stayed unchanged. Pocket depth is now restored
  to 0.5 mm. Automatic execution plus persisted numerical geometry refresh is
  proved. Older unchanged-source cursor upgrades are now implemented and independently
  reviewed, with 147 connector/call-budget/session-cost/empty-element tests passed.
  The exact `cad-geometry-v1` marker is persisted only after successful ingestion;
  missing/old markers trigger reingestion after normal successful probes.
- Local `machine.write_file` created a 59-byte fixture, then edited that existing
  file in one automatic call with verified readback. The saved result is 67 bytes
  with three real newlines and zero literal backslash-n sequences. Its comment is
  `// Solus acceptance fixture updated`; setup/loop stayed unchanged. No compile,
  package install, streamed execution or hardware result is implied.
- Real authenticated GitHub read-only sync imported 157 entities; SOL's remote
  `read_code_file` succeeded. The user clarified that GitHub repositories remain
  read-only while Solus fixes may continue. GitLab is excluded from this pass.

Remaining acceptance is explicit: assembly
insertion/mates, full hosted FeatureScript operations, other KiCad drawing writes,
rail-current analysis, incremental code execution output, and sketch pin/bus/library
topology. This is not an all-phases-complete report.

## Unverified assembly attempt and Variable Studio discovery

The latest live assembly insertion returned `mutation_unverified` after the vendor
POST returned HTTP 503 Service Temporarily Unavailable. Subsequent read-only SOL
`get_assembly` returned `instances: []`, `occurrences: []`, and `features: []`.
No inserted instance remained observable and no retry was attempted. The uncertain
result was intentional; this is vendor-transient blocked acceptance, not evidence
of a code defect. Assembly insertion/mates remain incomplete.

Variable Studio `b08e606a014ca1b1a9716c08` is now found. It contained one
`sol_acceptance_length` LENGTH variable with expression `1 mm`. The automatic
request to set `2 mm` returned vendor HTTP 204 No Content, but the generic JSON
decoder failed before the required readback and reported `mutation_unverified`.
Independent read-only SOL `get_variables` confirmed the complete table contains
only that variable with expression `2 mm` and an empty description. The write
applied; no retry occurred. Endpoint-specific 204 handling then passed 122 tests
and independent review. A fresh automatic edit from 2 to 1 mm passed live with
mandatory internal full-table GET/readback and successful `set_variable` result;
sync job `01a09ace-366c-7f02-a57c-feee5e51b703` was queued. Final restoration to
2 mm subsequently passed, as recorded below. An extra model read during source
synchronization initially falsely reported “No Onshape source connected”; the
status-filter defect is now fixed and independently reviewed with 47 tests passing.
Account grant, project and tracked-document checks remain enforced. No reconnect
was required. The initial 204 bug and URL/discovery blocker are resolved.

Post-sync live full-table read independently confirmed `1 mm`. Persisted sync
`01a09ace-37e9-7106-aee6-62af4c3a117c` succeeded at 2026-09-13T12:46:54Z
with three entity updates and zero errors. This was followed by the successful restoration below; no reconnect action was needed.

## Final Variable Studio acceptance — restored to 2 mm

SOL freshly read `1 mm`, automatically set `sol_acceptance_length` to `2 mm`,
and verified the complete table internally. An additional `get_variables` also
succeeded without the false connection error. The table contains only that
LENGTH variable, expression `2 mm`, with an empty description. Returned job:
`01a09ad0-e42f-76d0-9f98-4394474f6586`. Persisted sync
`01a09ad0-e548-7706-a919-59f77a45a7fe` succeeded at 2026-09-13T12:49:53Z
with three entity updates and zero errors. This completes the bounded Variable
Studio edit/readback/automatic graph-sync acceptance and restores the final target
to 2 mm. The SYNCING-status fix passed 47 tests and independent security/code review.
Assembly insertion/mates and the other explicitly listed gaps remain incomplete.

## Non-Onshape completion pass — September13

Onshape acceptance is paused at the user's request because their API credits are
exhausted. GitHub remains read-only; GitLab, hardware/XIAO and Live Bench are out
of this acceptance scope.

New schematic `tmp/integration-check-kicad/verified-divider-product/uno_fsr_divider.kicad_sch`
was drawn through SOL Build: real Arduino Uno library symbol, generic FSR resistive
symbol,10k resistor, explicit supply-ground flag,3 wires,7 net labels and26 unused
pin markers. SOL check_erc returned checked/passed true,0 errors,0 warnings,
not degraded and no truncation. It disclosed4 ignored rules: single_global_label,
four_way_junction, simulation_model_issue and footprint_filter. Native full
geometry independently confirmed4 symbols/3 wires/7 labels/26 markers at
fingerprint `0ea1521a3664f993:f09ed8dbe818d15a:eee5fa74623eb9f7:af3af2bd280e5151`.
The installed KiCad SVG export was visually inspected in the browser. It shows the
sensor divider's SENSE_A0 label and Uno A0 label, correctly named power/ground,
and real unused-pin marks. Output: the fixture's `render/uno_fsr_divider.svg`.
No fabricated FSR footprint or XIAO driver was introduced.

The first wire preview refused without mutation; supplying the documented nested
pin-anchor shape succeeded. The tool descriptions now include those exact shapes;
42 registration tests and unchanged input-schema fingerprints were verified. A
separate project-metadata write uncovered a relative-path redaction false positive:
the native preview succeeded but the cloud masked the long filename. The complete
preview gate correctly refused it; its narrow redaction fix is being verified.

Real ForgeTS read-only recognition: origin
`https://github.com/PotosnakW/ForgeTS_internal.git`, branch `vlfh_tsfm`, observed
HEAD `0a3eae0beec8723e4ece07eae721b2bab516cd73`. Native scan found84 recognized
files without file truncation; dependency observations reached the500 cap across3
manifests and correctly reported truncation. Existing scoped repository matching
selected connected GitHub entity `01a09ab9-3dd1-7b3a-9b54-092e346e7bc5` on source
`01a09ab6-ab2b-71bb-9c3f-cf335ebf3a09`. GitHub tracks main: this proves repository
identity, not branch/revision equality. No ForgeTS files or GitHub state changed.
Durable folder-picker linkage is a separate product-UI check.

### Saved files, graph observations and Guide follow-up

The scoped filename fix (`1e2ad936`) passed 83 tests and independent security
review. SOL then saved the exact original `.kicad_pro` path above: three bytes,
verified readback. Home's **Edit project link** saved that path on KiCad source
`01a098b1-aa10-763c-9c7c-27712ea0ccc8`; a read-only scoped query confirmed it.
SOL changed only R1 Value from `10k` to `10k (1%)` using fresh geometry, verified
saved bytes, and passed ERC again with the same four ignored rules. Automatic
source sync completed at `2026-09-13T14:31:26.821459Z` with no error; persisted
R1 entity `01a098b1-aa4d-7100-b4d5-4fda0fa0fd82` contains the new value.
The tool response did not expose that sync status; the database read is separate
evidence. The same read-only proof found 34 live entities and 35 relations;
`verified-divider-product/graph-proof.json` records the actual connected_to edges:
SENSE_A0 contains A1.9/R1.1/RFSR1.2; +5V contains A1.5/RFSR1.1; GND contains
A1.29/A1.6/A1.7/FLG1.1/R1.2. Legacy netlist read handlers still required correction: their regex
parser reported incomplete topology, although official native XML confirmed the
three intended nets. A complete bounded SOL readback remains pending that fix.

SOL wrote `test_acceptance_math.py`, `acceptance_math.py`, `acceptance_build.py`
and `sensor_acceptance.ino` inside the scratch folder with verified readbacks.
Independent review found the planned Python execution effects confined to the
fixture directory. Automatic graph projection on entity
`01a09ab2-c0d5-7d50-907f-0db7300d4c7d` recorded A0 pinMode at line 4 and analogRead
at line 9, I2C/UART buses and Wire.h, with `observations_incomplete:false`.
The older Blink macro-based pins remain null with incomplete=true, as intended.

The user approved the intentional `acceptance_build.py --fail` execution;
the UI records actual exit 2 and both the initial build output and intentional
failure text. Original build/test approvals remain pending. Reopening the chat
hid pending cards, and a typed acceptance produced a duplicate failure card;
these UX defects must be corrected without self-approval or duplicate execution.
Automatic Error logging was also verified read-only: entry
`01a09b2d-ac1a-709e-bbb7-ecce17badd40` at `2026-09-13T14:30:56Z` records the exact
`.venv/bin/python acceptance_build.py --fail` argv, exit 2 and output text.

All nine live Guide questions completed: three each for KiCad, safe Git
inspection, and Isaac collision/drives/sensor evidence. Answers cited official
references and disclosed version/measurement limits. This proves the sampled
workflows, not exhaustive vendor-manual retrieval or every published note.

The live `analyze_rail_current` call on `/+5V` entity
`01a098b1-aa4f-742d-9f9c-79b221935c0a` returned unknown total demand and capacity.
Its zero declared subtotal had no qualified contributions; A1 and RFSR1 lacked
rail attribution. SOL explicitly distinguished this empty subtotal from zero
demand or safe capacity. Result incomplete, not truncated; no measurements or
graph writes were claimed.

Calibrated Isaac product session `79c65788-5950-4e49-888c-b5c091fa3aaf` started
through SOL, loaded the existing model, and read back all six joints/eight links.
Sensor pose readback matched `[-0.007,-0.073,0.019]` metres within float precision
and WXYZ `[1,0,0,0]`, scene generation 2. Its complete clearance routine preview
was refused before execution: native 40 rows plus the cloud binding row exceeded
the unchanged 40-row limit. Grouping timing facts without removing values is
being verified against the actual native-to-cloud boundary before retrying.

### Final repaired product reads and approval recovery

After the reviewed native restart, SOL `kicad.extract_project_netlist` using the
actual `.kicad_pro` path returned `complete:true`, `basis:official_kicadxml`, four
components, 30 nets, R1=`10k (1%)`, and all three exact pin memberships recorded
above. A preceding call with a `.kicad_sch` in the project-path argument correctly
refused with `expected_project_path`; it returned no misleading topology.
The native fix is `398ae4dd`: 447 tests passed, one optional skip and one existing
expected failure; new module coverage 99%, independent security/Python review pass.

Approval recovery `ce652b2e` passed 113 API and 113 frontend tests plus four
dedicated restoration cases, types/lint and independent security/code review.
Actual browser reload restored the original pending build, test and redundant
failure cards. The redundant failure card was rejected without execution at
`2026-09-13T14:44:05Z`; its separate user-approved execution already provided the
expected exit-2 evidence. Original build/test IDs and expiry stayed unchanged.

The new Isaac session `d186a720-69b7-4ccd-8add-2f4ff78581cf` loaded the graph model
and verified the calibrated sensor pose through SOL. The fixed complete preview
then executed the 30-second/1,800-step clearance routine: targets_reached=true,
grasp_observed=false, no bottle contact, zero bottle force, 0/120 retained steps,
and approximately 0.26 micrometres of lift. Scene generation 3 saved successfully;
graph digest `c504ae38cf550d52:9a783f89ef76fd94:c541451879caa2c5:5eddefad12e4c2b6`.
The deliberately negative grasp result is correct for the clearance trajectory.

The single subsequent calibrated approach/close/lift also executed through SOL:
37.5209 mm lift, 8.29553 N final bottle-specific contact force and 120/120 retained
hold steps. Final shoulder-pan error 0.01533077 rad and elbow error 0.01310253 rad
exceed the unchanged 0.01-rad tracking threshold, so targets_reached=false and
grasp_observed=false correctly remain a partial physical result. Scene generation
4 saved; artifact digest
`72ee0c6f9eff8c39:42e85db54b04a195:d1dcb58f20224498:0c927fec09d1724f`.
No thresholds, waypoints or physical attachments were altered to force success.
SOL then stopped that exact owned session and read back stopped/session_id=null.
The final integrated desktop build passed. Dedicated final security review passed;
a final code review's uncertain-execution wording finding was corrected with
neutral approval-status text and a regression, then re-reviewed successfully.

The original unexecuted build/test cards reached their normal 30-minute expiry.
Fresh complete previews were created through exactly one code.run and one
code.test call, without execution or expiry changes. Pending build:
`01a09b45-a649-7b43-9f2a-9cad4a4f4b5b` (expires 15:27:08Z); pending pytest:
`01a09b45-b1d5-79a8-9225-73226d8dd10a` (expires 15:27:11Z), both September 13.
The two visible cards are in the same local saved-code acceptance conversation.


### September 13, 17:37 UTC — user-approved build and pytest complete

The previously recorded 15:27-expiry cards expired normally. Fresh previews were
subsequently requested and approved by the user, without changing expiry or
self-approving commands:

- Build approval `01a09bd7-e091-7d29-aa88-ac19a1ea5d28`, approved at
  17:36:57 UTC; result `01a09bd8-17c3-77f1-a44d-1953e63a7bdc` at 17:37:05 UTC.
  Argv `[".venv/bin/python", "acceptance_build.py"]`, scratch cwd `.`, exit 0,
  no timeout, duration 8027 ms, empty stderr. Output confirms saved-module
  compilation started and `Build finished successfully`.
- Pytest approval `01a09bd7-f3e9-78c4-bb8e-f506c9f73a86`, approved at
  17:36:58 UTC; result `01a09bd8-196a-77b7-89d3-af5204b7b7fb` at 17:37:05 UTC.
  Argv `[".venv/bin/python", "-m", "pytest", "-q", "--", "test_acceptance_math.py"]`,
  scratch cwd `.`, exit 0, no timeout, duration 3391 ms, empty stderr.
  Result: `3 passed, 3 warnings in 3.20s`. The warnings concern inherited
  `asyncio_mode`, `timeout` and `timeout_method` configuration options whose
  plugins are absent from the isolated fixture environment; no tests failed.

Project/conversation-scoped read-only approval and turn queries verified these
actual outcomes. No command was rerun, no failure check repeated, and no GitHub
or ForgeTS files were changed. These results close the remaining successful
build/test execution checks. Live incremental UI output was not directly watched
for these already-completed commands; existing native streaming proof and UI/API
regressions remain separate evidence. The Cowork live reopen check remains open.
