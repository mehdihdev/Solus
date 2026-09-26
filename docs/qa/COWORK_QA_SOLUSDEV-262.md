# Cowork QA — SOLUSDEV-262

**Last updated: 2026-09-14.** This is an independent acceptance checklist for the implemented
brain onboarding, W5, Live Bench and S4 flows. Boxes are deliberately unchecked: previous agent
proof is recorded in COMPLETION_SOLUSDEV-262.md, not substituted for this tester's results.

## Setup and boundaries

- Use branch `SOLUSDEV-262-livebench-robo-sol-initial`, installed workspace dependencies, API,
  Redis/database, native Electron app and local companion. Sign in as a verified project member.
  Browser preview can test web controls but cannot grant native file/folder selection.
- Use a disposable project and separate PostgreSQL test database for mutation/error fixtures.
  Preserve the ignored pre-migration backup. Migration head is `a26200000001`.
- For live readonly checks use leader serial `5B42135040` and follower `5B42134331`; currently
  `/dev/ttyACM0` and `/dev/ttyACM1`. The follower's saved robot is named
  “6 servos on a serial servo bus (ids 1–6, STS3215)”; a different saved “Follower” is not this
  connection. Confirm current CONFIG before starting either. Physical pings do not create mappings.
- Uno is a serialless CH340 connection at `/dev/ttyUSB0`. Select its board profile explicitly.
  Never flash either arm board. This checklist requires no motion. User-authorized experiments
  remain separate from readonly acceptance. USB swap and live SSH are deferred.
- Keep QA approver inactive in default config. Serialless Uno flash requires the actual manual
  central card; prepare/review actions never grant approval. See QA_APPROVALS_SOLUSDEV-262.md.
- Provide an explicitly selected disposable local control folder/file, a bounded URDF or MJCF,
  optional matching STL files, and fixture recorded run artifacts. Model and sensor fixtures are
  not recorded-real evidence. For CAD use an authorized disposable Onshape source or fixture sync.
- Configure API and worker with the same persistent artifact directory before restart testing.
  The session uses ignored `tmp/solus262-artifacts`; temporary capture files are not cloud storage.

## Prior evidence to reproduce

The recorded session verified both read-only baseline runs after API restart (1,860 leader and
2,715 follower packets, zero drops), signal rename/reconnect with the original label restored,
explicit Uno connection acceptance without a session, and probe preparation. Flash review was
blocked by budget 402, so there was no approval card or flash. Two synthetic URDF models retained
independent X positions of 0 and 0.3 m; they are not actual arm geometry. These observations are in
[SOLUSDEV-262-runs-presence-live.json](SOLUSDEV-262-runs-presence-live.json). Repeat checks below
for independent acceptance; do not mark a live CAD attachment passed from current fixture tests.

## Automated helper flows

- [ ] Run `python -m pytest -q scripts/tests/test_qa_approver.py`. Expected: all tests pass;
      non-dev construction raises, missing/ambiguous serials fail and wrong-target/motion cards do
      not send a decide request. Temporary journals contain refusal evidence.
- [ ] Run `packages/api/tests/test_qa_approver_decide.py` with SOLUS_TEST_DATABASE_URL pointing
      to a disposable test DB. Expected: authenticated fixture client uses the real decide endpoint
      and an inert fixture tool; no hardware or external system is touched.
- [ ] Inspect fixture journal ordering. Expected: timestamp and complete card are durably recorded
      before approval POST; an uncertain result is not retried, including across helper instances.
- [ ] Exercise failed journal write and failed attestation tests. Expected: no decide request.
- [ ] Exercise a gate/tool failure returning HTTP 200 with data.ok false. Expected: failure remains
      failure, not an approval-success claim.
- [ ] Run the destructive dispatcher ratchet in `packages/api/tests/test_sol_runtime.py`.
      Expected: no new registry invocation path.
- [ ] Search default startup/config files for QAApprover or qa_approver. Expected: no product
      import, enablement or automatic approving process. Test imports are expected.

## Baseline preservation

1. [ ] On a restored disposable copy, compare robot/part IDs, CONFIG, calibration and saved entries
   before/after migration. Expected: retained identities and the checksum recorded in the
   completion report; active Alembic head `a26200000001`. Never rehearse against populated `solus`.
2. [ ] Inspect the ignored private backup and evidence JSON. Expected: backup mode 0600; historical
   single-board evidence remains historical, while later simultaneous-board evidence identifies
   both serials. No PING/READ observation is described as motion or firmware inspection.
3. [ ] Match each gate to its actual evidence in COMPLETION_SOLUSDEV-262.md. Expected: fixtures,
   read-only recorded baselines, physical experiments and pending checks are distinguished.

## Topology, connection labels and signals

Setup: use the feature branch and its migrated development DB at `a26200000001`, a normal
signed-in account with access to its project, and the app/API/companion running. Do not treat
cached workspace content while the bridge is offline as live-server proof. The migration is
additive; preserve the private pre-migration archive when testing existing data.

1. [ ] Open Workspace with the serialless CH340 Uno connected. Its detection card says
       **Possible Arduino connection**; detail identifies the USB bridge and leaves MCU/firmware
       unknown. Name stays empty and nothing is accepted automatically. Do not approve a flash.
2. [ ] Keep both arms connected. Current mapping is leader serial `5B42135040` and follower
       serial `5B42134331`; path numbers are observational. Read-only interrogation returns 1–6
       from each. This walkthrough uses only read-only operations. If Linux sees only one device, distinguish that
       from a Solus omission; a successful prior check is not proof of current connection.
3. [ ] Open an existing configured robot, then its controller, bus and assigned part. IDs,
       configuration and calibration remain intact. Category chips filter parts while retaining
       their ancestors. An unassigned/unknown part is not silently mapped from its name.
4. [ ] With two robots sharing one endpoint fixture, enter each and verify only its descendants
       appear. From inside one robot reveal a part belonging to the other; the correct root and
       ancestry must be selected. Returning to overview must restore both robots without duplicate
       entity IDs or duplicate-key warnings.
5. [ ] With existing read-only telemetry sessions, open Live Bench with no focused node. Each
       returned signal has a value and chart. API reads must return actual recent samples; no demo
       values count as live proof. One missing device must not erase the other device's values.
6. [ ] For a `rad` signal choose `deg`: pi radians displays 180 degrees; timestamps/raw packets
       stay unchanged. Unknown units have no conversion selector. Incompatible samples break the
       polyline without changing the shared chart scale. Overflow displays no invalid number.
7. [ ] Rename one signal, reconnect/reload, and verify the name/unit preference survives for the
       same account/project/device/signal. Switch project or account while the new request is
       pending: prior values and private preferences disappear immediately. They must not flash
       onscreen while waiting. Clear/blocked local storage yields a visible save failure on edits.
8. [ ] Wrong-project/deleted robot topology reads fail without exposing data. Stale/malformed
       responses produce an honest retry state. Configuration writes with duplicate active part
       mappings or conflicting shared-endpoint channels roll back configuration and derived graph.

## Local host, widget roots, and focused streaming

Use the current desktop build, a verified project member, a matching active companion, and a
local project folder containing control software. A linked remote repository is reference
material and is not an eligible control-software selection. The browser preview cannot exercise
the native folder picker. Use a fixture/disposable project for changes to graph associations.

1. [ ] Open an accepted USB controller's canvas card and choose Connect this computer. If no
       local folder is selected, use the existing native folder picker. Canceling the picker
       must create no association. The software field begins empty.
2. [ ] Select a local folder or discovered Python/Arduino project. Remote repository entries
       must not appear as software choices. With a shared controller, select the intended robot
       explicitly; another robot's ownership must not be silently chosen.
3. [ ] Request a review. Check host → USB → existing endpoint → existing bus/parts, the local
       software name, and evidence. The review alone creates no graph nodes. Cancel and verify
       no change; repeat and confirm to save the reviewed association.
4. [ ] Check retained robot/endpoint/part UUIDs and CONFIG/calibration. Software is a user
       declaration, not a claim that a process or shim is running. Unknown MCU type stays unknown
       unless explicitly declared. Share a host between two robots and check each software label.
5. [ ] Change the local source or disconnect the companion between review and confirmation.
       Confirmation must fail without partial graph/ledger writes. Account/project changes hide
       pending private selections immediately; stale asynchronous responses must not restore them.
6. [ ] Attempt confirmation and replay as a different team and signed out: expect 404 and 401,
       respectively, without graph or operation-ledger changes. Replaying an authorized successful
       request with the same key must not duplicate entities.
7. [ ] Install a supported widget, then return to Workspace: its persisted registration is a
       root node. Open its page from the node; open Live Bench from its registered node. Disable,
       block, unblock, update, and uninstall the widget; graph state must refresh after commit.
       Blocked/disabled entries must not offer a working launch action.
8. [ ] Decline a hardware suggestion and rediscover identical evidence: it stays declined.
       Changed identity evidence may yield a new proposal. Confidence or wording changes alone
       must not resurrect the old proposal. Concurrent accept/decline must remain consistent.
9. [ ] With two read-only streams and no focus, verify both device panels. Select a robot,
       host, controller, bus, then part: only confirmed physical descendants may supply samples.
       Unknown mappings show an explanation, never unrelated devices. Clear focus to restore all.
10. [ ] Check starting and disconnected session states, including one device ending while the
        other continues. From an empty bench choose Add Hardware: Workspace opens Hardware once.
        Returning later or switching project/account must not replay that request.

USB swap and live SSH checks are deferred by user instruction. Hardware identification evidence
does not establish the scene, firmware, run-analysis or Guide gates below.

## Selected local-file evidence review

Setup: run the native desktop app with its local companion and API; sign in as a project member.
The project must contain a saved robot with an accepted controller brain. Use a disposable local
JSON/YAML/TOML config containing named parts/addresses, or a Python file with a Servo/PWM
declaration. The file must contain no credentials. No hardware motion or flashing is involved.

1. [ ] Open Workspace, zoom into the robot, and locate its brain card. Find Local evidence files.
2. [ ] Choose local file through the native picker. Cancel once: no evidence review should appear.
3. [ ] Choose the fixture file, then click its Select button. Choose its evidence type. Shared
   brains require an explicit robot selection. Review stays disabled until all choices exist.
4. [ ] Click Review file evidence. Expected: source declarations with original address/pin
   evidence; unknown fields remain unknown. No rows are selected automatically; review alone does not change graph or hardware.
5. [ ] Review a valid empty file: an honest no-recognized-declarations message appears. Review
   malformed or mismatched-format content: a retry/relink message, no partial topology.
6. [ ] Relink or Verify the selected file. Old evidence clears immediately and Review disables
   until the file is explicitly selected again. Repeat while an extraction response is pending.
7. [ ] Change brain, robot, project and account during a request, including A→B→A. Old results
   must not reappear. Repeat with a slow native picker response.
8. [ ] Browser preview without the native bridge explains local files are unavailable; it must
   not invent a file path or successful extraction.
9. [ ] Select a declaration, provide its name and Confirm evidence. Expected: evidence nodes or
   explicit retained-node annotations appear once; CONFIG, calibration and runtime stay unchanged.
   Retry an uncertain confirmation with the same operation: no duplicate IDs. While uncertain,
   selections remain frozen. Changed source evidence must require fresh review.
10. [ ] Choose an existing retained part explicitly. Expected: its identity remains stable and
   no self-parent edge appears. A remote repository is still a reference, not a local file grant.

## Saved robot telemetry connections

1. [ ] Open Live Bench with no selected part, then Manage connections. Saved robots are listed
   separately from USB bridges. Search by name; only current-project manual robots appear.
2. [ ] Connect a configured robot. The existing accepted protocol/config opens its telemetry;
   duplicate clicks are disabled while starting. Incomplete config shows its setup error.
3. [ ] Connect a second robot. Both status lines and their device-keyed signals appear without
   focus. Inspect packet units and rolling charts; no fabricated signal is shown.
4. [ ] Stop one session in Manage connections. Its pane says disconnected; the other continues.
   Stop the remaining session after the test. No motion commands are part of this walkthrough.

## Bare MCU and central flash gate

1. [ ] In Add → Hardware select the unknown USB connection. Enter a name and choose Add MCU
   connection. Expected: a brain and identity-only configuration appear; no driver/session starts,
   no parts are invented, and firmware stays unknown. Repeat a request: no duplicate robot.
2. [ ] Unplug/change the device after review, or reuse a conflicting existing binding. Expected:
   confirmation refuses without overwriting an operational CONFIG. Another project cannot bind
   an inaccessible entity through its ID.
3. [ ] Open the brain card and select the explicit Uno profile and probe. Prepare it. Expected:
   complete source, target, source/binary digests and erasure warning; raw analog values are not
   described as attached devices. Missing compiler/profile shows unavailable, not success.
4. [ ] Request flash review. With available budget, SOL Build displays the real central confirmation card
   containing all source bytes and exact target. A budget 402 must show failure and create no card
   or upload; restore budget before retrying. Cancel/reject: no upload. Try the same operation
   on a configured actuator board: refused before upload. No driver-board flash is permitted.
5. [ ] Only after the user approves that concrete Uno card, observe verified upload and resulting
   telemetry. Record source/binary digests and timestamp. Do not mark this step passed from compile
   tests. Unknown interrupted upload must not automatically retry.
6. [ ] Repeat preparation/review for heartbeat `uno.alive`; approval is separate. After approved
   upload, verify actual channel samples. A missing/occupied device must fail honestly. Return
   all sessions to stopped state when done.

## Reviewed wiring and existing Arduino sketches

Use a saved transport-only MCU and select its board profile explicitly. Preparation is not a
flash. For the connected serialless Uno, the live review request currently returns budget 402;
restore account budget and use the real confirmation card before any future upload.

1. [ ] Open the MCU brain's Presence firmware card, select Arduino Uno (AVR), then **Tell me**.
   Leave input rows blank and choose **Review wiring**. Expect “No input channels declared” and
   a declaration provenance statement, never a claim that the board is physically unwired.
2. [ ] Choose **Accept wiring**, select **Read accepted input wiring**, then **Prepare firmware**.
   Expect complete source with `uno.alive` and immutable source/binary hashes. No upload occurs.
3. [ ] In a synthetic QA target, declare an analog A0 and digital D2 input with distinct channel
   names. Review and accept. Expect input-only pin setup/readings and bounded status requests.
   Test duplicate pins/channels, output mode, serial pins, Uno A6/A7, and a 65-character channel:
   they must be rejected. Nano A6/A7 are analog-only. Maximum row count is 16.
4. [ ] Choose **From the schematic**, select a connected electrical source, and review its graph
   evidence. No device driver is inferred from a name or I2C address. Declare supported inputs
   explicitly. Change the source after review; acceptance or preparation must refuse stale data.
5. [ ] Choose **Let me look** and a completed probe run for this robot/device. Expect recorded
   observations and origin labeling. Floating analog samples do not become parts. Zero I2C
   responders do not prove empty wiring; responding addresses retain unknown device types.
   A different robot/device run or a run without probe values is refused.
6. [ ] Change account, project, profile or evidence while a request is pending. Old results must
   not attach or prepare hardware in the new context. Another member cannot accept your proposal.
7. [ ] In **Review local file evidence**, use the existing-sketch offer with an explicitly selected
   connected LOCAL folder and exact `.ino` manifest entry. A GitHub/reference source is ineligible.
   Enter existing baud, a unique loop anchor, scalar variable/channel/unit mappings. Preview shows
   include/setup/publish snippets. Function calls and injected expressions are rejected.
8. [ ] Request the firmware file diff. SOL must verify the actual authorized file and anchors,
   preserve existing hardware logic, and show the full before/after central confirmation. Shared
   binary Serial use, missing/ambiguous anchors and inaccessible files refuse the proposal. Merely
   requesting a diff does not install a library, execute code, start a loop or flash the board.

## Provisioned onboard deployment fixture

Live SSH is deferred. Automated coverage runs against synthetic targets and a temporary actual
installer filesystem, using the real API confirmation endpoint with injected SSH. A bare target
is unsupported: a real future target needs pinned host keys, operator-authorized bundle UUID/hash,
pre-enrolled companion identity/service, the fixed helper and private deployment state.

1. [ ] With the default app (no scoped local deployment factory), preparation returns 503 and SOL
   does not advertise a deploy-companion tool. No SSH connection starts.
2. [ ] In the fixture setup, prepare using only scoped target and artifact UUIDs. Confirm preview
   includes target/version, instance, bundle hash, enrollment prerequisites and restart.
3. [ ] Reject the central confirmation: no upload/install/start. Approve once: exact immutable
   bundle installs, restart occurs, and only a new authenticated post-restart session can succeed.
4. [ ] Change target version, pinned host authority, artifact bytes or operator allowlist before
   approval. The action refuses. A different actor/project, viewer or unverified member must not
   prepare or decide another actor's plan. Attempted plans cannot silently retry.
5. [ ] Simulate a lost preflight response: operation-owned cleanup releases its lock. Simulate
   failed install/start/handshake: prior release is restored where possible. Failed rollback
   retains the journal and reports unknown until an explicitly reviewed recovery succeeds.
6. [ ] Simulate a reconnect during upload with no reconnect after restart. It must not satisfy
   the post-restart health check. No fixture result is reported as a live deployment.

## Explicit host mirror offer

1. [ ] Complete reviewed local-host attachment above. Select a loop file inside the authorized
   local source, control-object name, insertion anchor, method, signal mapping, units and loopback
   receiver port. Expected: exact proposed snippet; no running shim claim or automatic file edit.
2. [ ] Request the existing SOL file-diff review. Expected: authorized read and fingerprinted
   before/after change through the central gate. Reject: bytes unchanged. Missing write authority,
   changed file, ambiguous anchor or wrong source must prevent a write.
3. [ ] On a disposable fixture only, approve the exact edit and run its inert control object.
   Expected: method arguments/results/exceptions unchanged, receiver gets selected finite numeric
   fields, no additional hardware calls, bounded queue drops reported, close restores wrappers.
4. [ ] Change account/project/source while preparation is pending. Expected: private file details
   and stale offers disappear. A linked remote repo must never substitute for a selected local file.

## W5 rediscovery and manual evidence

1. [ ] Restore the development snapshot into a disposable database. Record follower robot UUID,
   controller UUID and binding. Remove only its binding in this copy, then rediscover fixture
   identity. Expected: a proposal against the same follower with bus-identity evidence.
2. [ ] Accept via normal API/UI. Expected: one existing robot, no duplicate part/config identity.
   Decline an equivalent proposal and rediscover: it stays declined for identical evidence.
3. [ ] Add a fixture CAD gripper with evidence for one robot. Expected: separate node plus reviewed
   suggestion to the correct robot, not asserted ownership. Right-click Attach to robot, select
   the intended robot and confirm. Check retained source identity and relations after reload.
4. [ ] Reject/decline in the actual UI, reload, change evidence and repeat. Expected: wording-only
   changes do not defeat decline memory; substantive evidence permits fresh review. Capture the
   UI outcome separately from the DB-copy API proof.

## Scene imports, mappings and CAD updates

1. [ ] Open Live Bench → Scene. With no model, check the honest import state. Upload a bounded
   URDF/MJCF through the file control, select a robot and import. For mesh references explicitly
   upload matching STL associations. Expected: no native path/URL fetching from model text.
2. [ ] Import a second model for a different robot. Place/rotate each independently and reload.
   Expected: namespaced IDs, retained separate poses, no shared-state movement.
3. [ ] Confirm a moving joint against an accepted part/device/signal with compatible packet units.
   Start readonly telemetry. Expected: that joint follows actual samples; unconfirmed or stale
   mapping remains static with a reason. Replacing CONFIG invalidates outdated binding authority.
4. [ ] Import a jointless fixture, missing mesh, malformed XML and external-resource reference.
   Expected: jointless static reason, missing geometry warning, and bounded refusal of unsafe
   input respectively. No synthesized moving joint or arbitrary file access.
5. [ ] Link an existing mesh to an explicit CAD leaf and trigger a fixture source microversion
   update with changed geometry. Expected: vertices change even for unchanged bounding box;
   model identity, placement and valid mappings persist. Failed/revoked/ambiguous source keeps
   previous geometry with stale/error status.
6. [ ] Remove CAD links after eligible source list becomes empty. Expected: unlink still works;
   response reports current/unlinked rather than claiming a refresh queued. Concurrent version
   changes preserve draft or request re-review, never overwrite a newer mapping.
7. [ ] Try signed-out, foreign-project model/artifact/source and oversized imports. Expected:
   authorization/refusal with no graph mutation, artifact leakage or refresh job.

## Signals, observers and recorded sensors

1. [ ] Accept an unnamed actuator fixture. Expected: stable RobotName-Motor-N default unless an
   explicit name was supplied. Rename a live signal and reconnect: account/project preference
   persists, while another account/project gets its own values and preferences.
2. [ ] Feed a timestamped fixture with a statistical change and a second unrelated device.
   Expected: marker only on matching device/signal within its plotted time window. Missing event
   service is disclosed; it is not presented as “no anomalies.” A marker is not a stall diagnosis.
3. [ ] Load a recorded fixture with joint sample and camera reference at the same timestamp.
   Scrub and explicitly open the frame. Expected: exact captured timestamp and bounded PNG/JPEG/
   WebP image. Missing/foreign/oversized/unsupported artifact displays failure without fallback data.
4. [ ] Open a fixture LiDAR reference containing finite meter-based XYZ points. Expected: bounded
   XY projection, stated Z range and timestamp. Invalid units, nonfinite or excessive points refuse.
   Change account/project/run during loading: old image/points cannot appear in the new scope.

## Run capture, playback, findings and comparison

1. [ ] Connect a saved robot readonly. Open Runs, name and start a run for that active session.
   Expected: running state and increasing actual packet count; starting capture never commands
   motion or starts another session. Stop and verify completed manifest/artifact with counts.
2. [ ] Scrub the run. Expected: actual captured samples and timestamps; CONFIG, accepted part IDs,
   source/code/CAD snapshot context only where present. Download/reopen and restart API/worker
   using the same artifact root: completed run remains readable with identical counts.
3. [ ] Interrupt a fixture capture process. Expected: interrupted state and last durable count,
   never completed. Exceed a bound: truncated state and explicit dropped/partial evidence. Run
   list is newest-first and cursors cannot reveal another project's runs.
4. [ ] Open clean baseline findings. Expected: no finding or explicit insufficient evidence is
   valid. Load synthetic current/position/command/rating evidence: stall finding names the mapped
   part and exact supplied limits/current. Load-percent must not be treated as amperes; missing
   rating, command or incompatible units must not fabricate a fault.
5. [ ] Request Explain findings. Expected: optional metered cheap-tier narration; deterministic
   cards/numbers unchanged. Budget/provider failure gives a clear deterministic fallback. Guide/
   Expert preference is respected; generated narration cannot call tools or add evidence.
6. [ ] Import two declared synthetic same-robot clamp-difference fixtures and compare. Expected:
   aligned compatible signals and graph-backed configuration attribution. Different robots,
   foreign runs and incomplete evidence refuse or explain insufficiency. Readonly live baselines
   must not be described as a deliberate two-run motion experiment.

## Guide, Build and native shortcuts

1. [ ] In Guide choose the fixture “add a 6 mm hole” task for Onshape. Expected: confidence-bearing
   steps/pointer context and zero provider writes. Unknown control/version says uncertain.
2. [ ] Choose a scriptable task: commands display for copying without execution. Choose native
   surface: explicit overlay handoff or side-panel fallback. Switching account/project/task/mode
   dismisses old guidance. Capture only through the explicit visible capture action.
3. [ ] Switch to Build and request the same fixture change. Expected: actual diff card before any
   mutation. Reject: no provider change. Fixture approval invokes only its inert owned path;
   the QA approver must not approve real Onshape writes.
4. [ ] Focus a separate native application. Press Ctrl+Shift+Space: SOL appears. Press Ctrl+Space:
   Guide/Build toggles and persists. Restore the initial mode. Browser-only key tests do not count
   as this native check.
5. [ ] Separately test overlay pointing at a real external control with explicit user selection.
   Expected: accurate target or honest unavailable/fallback; no invented arrow. Record this result
   separately from shortcut proof and fixture handoff.

## Cleanup and handoff

1. [ ] Stop every session/capture started here; leave hardware unmodified except separately logged,
   manually approved Uno operations. No driver flash, remote push or MR.
2. [ ] Verify QA approver absent from default startup and central dispatcher/vendor ratchets green.
   Keep approval journal exact, including zero approvals when applicable.
3. [ ] Record pass/fail and evidence for each flow, latest test totals and remaining blockers in
   the completion matrix. Leave user-owned SPEC and private backups unstaged.
