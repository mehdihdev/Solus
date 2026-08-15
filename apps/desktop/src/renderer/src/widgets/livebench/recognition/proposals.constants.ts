// RBT-03: fixtures for the four recognition tiers. Every tier must produce a
// USABLE screen — and the product must be good at tier 3, not just tier 1.
import type { MappingProposal } from './proposals.types'

/** Tier 1 — self-describing bus + firmware + repo: near-automatic, high confidence. */
export const TIER1_BUS_FIRMWARE_REPO: readonly MappingProposal[] = [
  {
    id: 'ttyUSB0/id:3',
    subject: 'Dynamixel XM430-W350 (id 3)',
    proposedFunction: 'elbow',
    confidence: 0.92,
    evidence: [
      {
        kind: 'bus_enumeration',
        value: 'model register 1020',
        note: 'the device asserts its own identity; identifies the part, not the joint',
        provenance: 'ttyUSB0 broadcast ping'
      },
      {
        kind: 'firmware_symbol',
        value: 'servo_elbow.attach(9)',
        note: 'code intent only — may be stale relative to the physical build',
        provenance: 'src/arm.ino:11'
      }
    ]
  },
  {
    id: 'ttyUSB0/id:7',
    subject: 'Dynamixel XL330-M288 (id 7)',
    proposedFunction: 'wrist',
    confidence: 0.92,
    evidence: [
      {
        kind: 'bus_enumeration',
        value: 'model register 1190',
        note: 'the device asserts its own identity; identifies the part, not the joint',
        provenance: 'ttyUSB0 broadcast ping'
      }
    ]
  }
]

/** Tier 2 — firmware only: inferred, the user confirms. */
export const TIER2_FIRMWARE_ONLY: readonly MappingProposal[] = [
  {
    id: 'pin:9',
    subject: 'PWM channel on pin 9',
    proposedFunction: 'elbow',
    confidence: 0.55,
    evidence: [
      {
        kind: 'firmware_symbol',
        value: 'servo_elbow.attach(9)',
        note: 'code intent only — may be stale relative to the physical build',
        provenance: 'src/arm.ino:11'
      }
    ]
  },
  {
    id: 'pin:5',
    subject: 'PWM channel on pin 5 (WRIST_PIN)',
    proposedFunction: 'wrist',
    confidence: 0.55,
    evidence: [
      {
        kind: 'firmware_symbol',
        value: '#define WRIST_PIN 5',
        note: 'code intent only — may be stale relative to the physical build',
        provenance: 'src/arm.ino:3'
      }
    ]
  }
]

/** Tier 3 — bare serial, no repo: channel shape only. The user NAMES the channels. */
export const TIER3_BARE_SERIAL: readonly MappingProposal[] = [0, 1, 2, 3, 4, 5].map((i) => ({
  id: `serial:/dev/ttyACM0/ch${i}`,
  subject: `channel ${i} (float, ~100 Hz)`,
  proposedFunction: null,
  confidence: null,
  evidence: [
    {
      kind: 'telemetry_channel',
      value: '6ch@100Hz/json-lines',
      note: 'channel shape constrains, it does not identify — stays unlinked pending confirmation',
      provenance: 'serial:/dev/ttyACM0'
    }
  ]
}))

/** Tier 4 — ROS/URDF present: a bonus that adds names, never the foundation. */
export const TIER4_ROS_BONUS: readonly MappingProposal[] = [
  {
    id: '/joint_states/wrist_pitch',
    subject: 'ROS 2 joint_states channel',
    proposedFunction: 'wrist_pitch',
    confidence: 0.75,
    evidence: [
      {
        kind: 'telemetry_channel',
        value: '/joint_states/wrist_pitch',
        note: 'named by the URDF when present — a bonus, never assumed',
        provenance: 'ros2 topic list'
      }
    ]
  }
]
