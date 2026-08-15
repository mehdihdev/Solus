# Completion report — SOLUS-LB-03 Device deployment (SOLUSDEV-123)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified against scripted
runners and captured arg lists; **no real device was flashed** — the CH343-fronted board is the
only hardware on this bench and flashing it without explicit human OK is off the table. The
real-robot flash gate is honestly unmet.

## What was built — `livebench/deploy/`

- `flash.py` — `flash(target, artifact, runner=…, on_progress=…)`: progress phases
  (preparing→erasing→writing→verifying→done/failed) and an honest tri-state result.
  **Mid-flash failure is the loud UNKNOWN state**: a failure during write/verify returns
  `device_state="unknown"` ("treat as unbootable until re-flashed"), never folded into a
  generic error; pre-write failures return `unchanged`; artifact problems (unreadable,
  >32 MiB) fail before touching the device. Artifact sha256 recorded (ties to PRB-01
  flash-status). `ArduinoCliRunner`: pinned binary, argument lists only, constructor fails
  fast when arduino-cli is absent.
- `fs.py` — `SshFilesystem.push/pull` over scp for Jetson/Pi targets: `BatchMode=yes`,
  `--` operand separator (a hostile filename can never become a flag), host/user regex
  validation, remote paths may not look like flags, injectable exec seam (tests assert the
  exact argv with no network).
- `check.py` — `await_post_deploy_telemetry(source, expected_devices, max_packets)`: watches
  any `PacketSource` until every expected `device_id` (the `external_ref` seam) has spoken or
  the budget runs out, and NAMES the missing devices. Graph attachment itself is LNK-06's at
  ingest (LB-05 route), already wired.

## Acceptance vs. delivered

- flash with progress + success/failure status ✅ (scripted-runner verified; real-device gate
  NOT RUN — needs sanctioned hardware).
- fs read/write ✅ (arg-list verified; live scp NOT RUN — no SSH robot on the bench).
- post-deploy telemetry → right entities ✅ mechanism (check helper + LB-05 ingest seam).
- mid-flash failure safe and reported ✅ — the UNKNOWN tri-state, tested.

## Verification

163 livebench tests green (this ticket: 15). mypy strict clean; ruff clean. TDD RED→GREEN.
