# Completion report — SOLUS-RBT-01 Passive robot identification (SOLUSDEV-228)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built; USB enumeration **verified on real
hardware** (the bench's CH343); Dynamixel/CAN probes verified against protocol-exact fixtures
(no such hardware attached — stated plainly, not claimed).

## What was built — `livebench/recognition/passive.py`

Three independent probes, each degrading gracefully, every finding a real CTR-08
`ModalityMatch` (so RBT-05 persists them with zero translation):

1. **USB/serial enumeration** — `enumerate_usb_serial()` / `identify_port()` against a curated
   `BOARD_TABLE`. Three honest outcomes: a known MCU board (Teensy, Uno, ESP32-S3 native…)
   matches at 0.85 with the part-not-joint note; a known **bridge** (CH343/CH340/CP210x/FTDI/
   PL2303) identifies the bridge only — `mcu_known=False`, LOW_CONFIDENCE, note says the MCU is
   unknown; an unknown VID/PID reports unknown at 0.05, **never a guess**. Enumeration opens no
   port (side-effect free).
2. **Self-describing buses** — `dynamixel_broadcast_ping()`: Protocol 2.0 framing implemented
   directly (~40 lines + CRC-16) instead of importing the vendor SDK for one ping; **the
   broadcast frame is pinned byte-for-byte to the ROBOTIS spec's golden bytes** (`…31 42`),
   which proves the CRC. Responders map model registers (1020=XM430-W350 …) at 0.92 MATCHED,
   mirroring the `hardware_modalities.json` worked example. Silent or garbage-spewing buses
   return `[]`, never raise. `identify_odrive_heartbeats()`: ODrive CAN nodes (heartbeat cmd
   0x01) at 0.92 — protocol-shaped over `(arbitration_id, data)` frames so python-can plugs in
   live without a hard dependency today.
3. **Stream shape** — `characterize_stream()`: framing (json-lines/csv/text/binary/silent),
   channel count, per-channel ranges, update rate (median inter-arrival) at a stated baud.
   Emits `TELEMETRY_CHANNEL` evidence capped at 0.25 LOW_CONFIDENCE with the fixture's exact
   rule in the note: _shape constrains, it does not identify_. A silent or binary stream is a
   valid result, not an error.

## Acceptance vs. delivered

- VID/PID vs maintained table, unknown→unknown: ✅ **including live on the real CH343**
  (`test_live_enumeration_…` runs against actual hardware, auto-skips benches with none).
- Dynamixel broadcast-ping enumerates IDs+models: ✅ protocol-exact, golden-pinned;
  **live bus NOT RUN** (no U2D2/servos on the bench — stated, not claimed).
- One CAN family (ODrive): ✅ heartbeat identification; **live CAN NOT RUN** (no CAN interface).
- Stream-shape report (baud/framing/channels/ranges/rate): ✅.
- CTR-08 evidence kind + honest confidence on every finding: ✅ (0.92 bus / 0.85 usb-board /
  0.30 bridge / 0.25 shape / 0.05 unknown).
- Bare serial with no self-description → valid useful result: ✅ (bridge + shape path; the
  CH343 is exactly this case).

## Verification

136 tests green (this ticket: 14 — enumeration 4, DXL 4 incl. golden frame, ODrive 2, shape 3,
live hardware 1). `mypy -p livebench` strict clean (23 files); ruff clean. TDD: RED → GREEN
(one real parser bug caught by the fixture test: buffer- vs packet-relative offsets).

## Delegated judgments

1. No `dynamixel-sdk`/`python-can` dependencies: both probes speak the protocol over injectable
   port/frame interfaces — testable today, and live hardware later plugs pyserial / python-can
   into the same seams. The SDKs can be adopted when active control (RBT-04 on Dynamixel)
   needs more than a ping.
2. Baud detection is out of scope: characterization is AT a given baud (auto-baud is a
   hardware-level trial loop that belongs with RBT-04's gated interaction, if ever).
