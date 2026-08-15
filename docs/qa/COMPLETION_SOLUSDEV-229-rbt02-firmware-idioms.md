# Completion report — SOLUS-RBT-02 Firmware-source idiom extraction (SOLUSDEV-229)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** extraction half built and verified; the
CTR-05 pattern-emission half is deliberately NOT built — blocked on a LANE 0 contract
amendment, with the boundary structurally closed and tested in the meantime.

## What was built — `livebench/recognition/firmware.py`

tree-sitter (cpp + python grammars, aarch64 wheels verified) extraction over a repo checkout:

- **Attach calls** — `servo_elbow.attach(9)` (C++ field-expression calls),
  `servo_wrist = PWM(Pin(12))` / `Servo(4)` (MicroPython). **A symbolic argument
  (`gripper.attach(WRIST_PIN)`) records the attachment WITHOUT a pin** — resolving symbols
  across a build is inference this layer refuses to fake.
- **Pin constants** — `#define WRIST_PIN 5`, `const int basePin = 3`, `ELBOW_PIN = 7`.
- **Motor constants** — `const float MOTOR_KV = 920.0`.
- Every finding carries exact `file:line` provenance, a `name_hint` (the `servo_<joint>`
  CONVENTION, surfaced as a hint, never an identification), and CTR-08 `firmware_symbol`
  evidence at **0.55 / LOW_CONFIDENCE** with the fixture's honesty note (code intent only —
  may be stale relative to the physical build).
- Degradation: no recognizable firmware → `[]`; malformed sources skipped per-file; files
  > 1 MiB skipped; scan capped at 2000 files; vendor dirs (.git/.pio/node_modules/venv)
  > excluded. Works with no hardware connected by construction.

## The tenancy boundary (the ticket's ⚠)

**Flag, restated from the Phase 0 Jira comment:** CTR-05's `ToolKnowledge` cannot express a
firmware idiom today — `ToolFamily` is a closed CAD/EDA enum (fusion…spice) and `UiSurface`
is UI-control-only. Per WORKTREES §5 a lane never edits a contract to unblock itself, so:

- **Not built:** any emission of library idioms to the knowledge store.
- **Built and tested** (`TestTenancyBoundary`): (1) `ToolFamily` cannot name a firmware
  family — constructing one raises; (2) this module imports nothing from the
  knowledge-store boundary, so no code path exists that could carry "pin 9 is the elbow"
  out of the tenant; (3) findings are instance-shaped (concrete repo paths) — exactly what
  CTR-05's vendor-text rules reject.
- **LANE 0 proposal (for the human to raise):** additively extend CTR-05 with a firmware
  library surface — e.g. `ToolFamily.ARDUINO_SERVO` / `MICROPYTHON_MACHINE`, a
  `UiSurface.API` value, and `ControlEffect` entries for bind/actuate — so the IDIOM
  ("`Servo.attach(pin)` binds a PWM channel", "`servo_<joint>` conventionally encodes the
  joint") can compound across users while the closed-column/vendor-text machinery keeps
  instances out. The rejection test for TU-06's ingestion should reuse this module's
  fixtures.

## Verification

148 tests green (this ticket: 12 — extraction 9 incl. symbolic-pin honesty, oversize/malformed
degradation; boundary 3). `mypy -p livebench` strict clean (24 files); ruff clean.
TDD: RED commit → GREEN.
