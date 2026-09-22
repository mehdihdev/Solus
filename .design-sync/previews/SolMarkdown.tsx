import { SolMarkdown } from '@solus/desktop'

const box = { width: 520 } as const

const DIAGNOSIS = [
  '## I²C address collision on the sensor bus',
  '',
  'The IMU and the new time-of-flight sensor both answer at `0x68`, so the',
  'bus arbitration you are seeing in `imu_node` is two devices replying to the',
  'same read.',
  '',
  '1. `BNO085` (U7, main-board.kicad_pcb) — strapped to `0x68`',
  '2. `VL53L5CX` (U11, added in the v4 schematic) — default `0x68`',
  '3. `camera_node` is unaffected; it is on CSI-2, not I²C',
  '',
  'Pull `ADDR` on U11 high to move it to `0x29`, then update the driver:',
  '',
  '```cpp',
  'static constexpr uint8_t TOF_ADDR = 0x29;  // was 0x68 — collided with the IMU',
  'Wire.beginTransmission(TOF_ADDR);',
  '```',
  '',
  'I checked this against the KiCad netlist synced 4 minutes ago.'
].join('\n')

const TABLE = [
  '### Power budget — Ari-02, 24 V rail',
  '',
  '| Entity | Domain | Draw |',
  '| --- | --- | --- |',
  '| `knee_motor` | mechanical | 6.4 A |',
  '| `DRV8301` | electrical | 0.2 A |',
  '| Jetson Orin Nano | runtime | 2.1 A |',
  '',
  '> Headroom is 1.3 A. Adding the second arm motor overruns the budget.'
].join('\n')

const STREAMING = [
  '## Why the deploy failed',
  '',
  'The package you flashed needs CUDA 12, and the Jetson target reports',
  '`11.8`. The deployment step that failed is'
].join('\n')

export function Diagnosis() {
  return (
    <div style={box}>
      <SolMarkdown content={DIAGNOSIS} />
    </div>
  )
}

export function TableAnswer() {
  return (
    <div style={box}>
      <SolMarkdown content={TABLE} />
    </div>
  )
}

export function MidStream() {
  return (
    <div style={box}>
      <SolMarkdown content={STREAMING} />
    </div>
  )
}
