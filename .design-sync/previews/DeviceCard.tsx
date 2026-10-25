import { DeviceCard } from '@solus/desktop'

// Fixtures mirror DeviceCard.test.tsx: every string the card shows is the wire's.
const noop = (): void => {}
const handlers = { onConfirm: noop, onAccept: noop, onDismiss: noop, onRetry: noop }
const frame = { width: 440 } as const

const ROVER = { id: 'robot-1', type: 'physical_robot', domain: 'project', name: 'Rover', source_key: '' }
const ARM = { id: 'robot-2', type: 'physical_robot', domain: 'project', name: 'SO-101 follower', source_key: '' }
const ROBOTS = [ROVER, ARM]

const DEVICE = {
  transport: 'usb_serial',
  device_ref: 'usb_serial:5A3F01',
  identity: { kind: 'usb_serial', binding: '5A3F01' },
  identity_basis: 'serial_number',
  level: 'transport',
  board: null,
  board_class: 'usb_bridge',
  mcu_known: false,
  confidence: 0.4,
  evidence: [],
  ambiguous: false,
  last_seen_path: '/dev/ttyACM0'
}

const PROPOSAL = {
  device_ref: 'usb_serial:5A3F01',
  level: 'protocol',
  summary: '6 Feetech STS3215 servos on usb_serial:5A3F01',
  driver_id: 'serial_bus',
  params: { baud: 1000000 },
  rows: [],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: [
    { modality: 'bus_enumeration', source_ref: {}, confidence: 1, state: 'matched', evidence: { note: 'pinged ids 1..6, 6 answered' } },
    { modality: 'usb_descriptor', source_ref: {}, confidence: 0.8, state: 'matched', evidence: { note: 'VID 1a86 PID 55d3 — CH343 bridge' } }
  ],
  tone: 'probably'
}

const base = {
  ref: DEVICE.device_ref,
  device: DEVICE,
  status: 'proposed',
  proposal: PROPOSAL,
  error: null,
  conflictRobotId: null,
  result: null,
  attempts: 1
}

/** The canonical card: one sentence, one question, nothing auto-added. */
export function Proposed() {
  return (
    <div style={frame}>
      <DeviceCard state={base} robots={ROBOTS} mode="Expert" {...handlers} />
    </div>
  )
}

/** Guide mode adds the proposal's evidence notes, verbatim, under the sentence. */
export function GuideMode() {
  return (
    <div style={frame}>
      <DeviceCard state={base} robots={ROBOTS} mode="Guide" {...handlers} />
    </div>
  )
}

/** Two repo configs match: the card asks which, before it asks for a name. */
export function ChooseBetweenConfigs() {
  const proposal = {
    ...PROPOSAL,
    summary: 'a Feetech bus on usb_serial:5A3F01',
    repo_matches: [
      { config_id: 'cfg-leader', parser_id: 'lerobot', label: 'so101_leader', source: 'lerobot/configs' },
      { config_id: 'cfg-follower', parser_id: 'lerobot', label: 'so101_follower', source: 'lerobot/configs' }
    ],
    disambiguation: { question: 'Leader or follower arm?', options: ['cfg-leader', 'cfg-follower'] }
  }
  return (
    <div style={frame}>
      <DeviceCard state={{ ...base, proposal }} robots={[]} mode="Expert" {...handlers} />
    </div>
  )
}

/** A pending link suggestion names an imported robot — one button accepts it. */
export function SuggestedRobot() {
  const proposal = {
    ...PROPOSAL,
    suggestions: [
      { id: 'sug-1', subject_ref: DEVICE.device_ref, subject_kind: 'device', candidate_robot_id: ARM.id, confidence: 0.8, tier: 'high', evidence: [], reason: null, status: 'pending', created_at: '', decided_at: null }
    ]
  }
  return (
    <div style={frame}>
      <DeviceCard state={{ ...base, proposal }} robots={ROBOTS} mode="Expert" {...handlers} />
    </div>
  )
}

/** Nothing answered on the wire: the honest title plus Retry / Not now. */
export function SilentDevice() {
  return (
    <div style={frame}>
      <DeviceCard
        state={{ ...base, status: 'silent', proposal: null, attempts: 2 }}
        robots={ROBOTS}
        mode="Expert"
        {...handlers}
      />
    </div>
  )
}

/** After Add: the robot exists and a session started. Compact is the rail variant. */
export function AddedCompact() {
  const result = { robot: ROVER, part_ids: ['p-1'], config_entry_id: 'c-1', session_id: 's-1', session_error: null }
  return (
    <div style={frame}>
      <DeviceCard state={{ ...base, status: 'done', result }} robots={ROBOTS} mode="Expert" compact {...handlers} />
    </div>
  )
}
