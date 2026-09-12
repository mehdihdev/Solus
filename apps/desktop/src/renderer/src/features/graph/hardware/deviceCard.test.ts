// SOLUSDEV-250 P3 — the pure rules behind a device card: which devices are
// still pending, what the one sentence says, which single question to ask,
// what a default Add sends, and where a rail-confirmed robot lands.
import { describe, expect, it } from 'vitest'
import type {
  DetectedDeviceOut,
  HardwareSuggestion,
  ModalityMatch,
  ProposalOut,
  ProposalRowOut
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { CARD_HEIGHT, CARD_WIDTH } from '../navigation/layout'
import {
  boundDeviceRefs,
  cardGlyph,
  cardQuestion,
  cardSentence,
  conflictText,
  defaultAccepted,
  evidenceNotes,
  pendingDevices,
  placementNearRail
} from './deviceCard'

const device = (ref: string | null, extra: Partial<DetectedDeviceOut> = {}): DetectedDeviceOut => ({
  transport: 'usb_serial',
  device_ref: ref,
  identity: null,
  level: 'transport',
  board: null,
  board_class: 'usb_bridge',
  mcu_known: false,
  confidence: 0.4,
  evidence: [],
  ambiguous: false,
  last_seen_path: null,
  ...extra
})
const entity = (id: string, source_key: string): Entity => ({
  id,
  type: 'part',
  domain: 'runtime',
  name: id,
  source_key
})
const row = (address: string, fn: string | null): ProposalRowOut => ({
  id: `usb_serial:S1/${address}`,
  subject: `M1 at ${address}`,
  address,
  model: 'M1',
  proposed_function: fn,
  confidence: 0.9,
  evidence: [],
  provenance: 'bus'
})
const proposal: ProposalOut = {
  device_ref: 'usb_serial:S1',
  level: 'protocol',
  summary: '2 devices on usb_serial:S1',
  driver_id: 'serial_bus',
  params: {},
  rows: [row('1', 'joint_1'), row('2', null)],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: [],
  tone: 'probably'
}
const suggestion: HardwareSuggestion = {
  id: 'sug-1',
  subject_ref: 'usb_serial:S1',
  subject_kind: 'device',
  candidate_robot_id: 'robot-9',
  confidence: 0.8,
  tier: 'high',
  evidence: [],
  reason: null,
  status: 'pending',
  created_at: '',
  decided_at: null
}

describe('boundDeviceRefs / pendingDevices', () => {
  it('takes everything before the FIRST slash of a keyed part', () => {
    const refs = boundDeviceRefs([
      entity('a', 'usb_serial:S1/1'),
      entity('b', 'can:X/0x10/extra'),
      entity('c', 'plain')
    ])
    expect([...refs]).toEqual(['usb_serial:S1', 'can:X'])
  })

  it('survives a manual entity whose source_key is null on the wire', () => {
    const manual = { ...entity('m', 'x'), source_key: null }
    expect([...boundDeviceRefs([manual, entity('a', 'usb_serial:S1/1')])]).toEqual([
      'usb_serial:S1'
    ])
  })

  it('lists unbound, undismissed devices with a ref; ambiguous ones stay listed', () => {
    const bound = device('usb_serial:S1')
    const free = device('usb_serial:S2')
    const twin = device('usb_serial:S3', { ambiguous: true })
    const gone = device('usb_serial:S4')
    const pending = pendingDevices(
      [bound, free, device(null), twin, gone],
      [entity('a', 'usb_serial:S1/1')],
      new Set(['usb_serial:S4'])
    )
    expect(pending).toEqual([free, twin])
  })

  it('treats a null entity list as nothing bound', () => {
    expect(pendingDevices([device('usb_serial:S1')], null, new Set())).toHaveLength(1)
  })
})

describe('cardSentence / cardGlyph / evidenceNotes', () => {
  it('reads the toned headline once a proposal exists', () => {
    expect(cardSentence(device('usb_serial:S1'), proposal, 'proposed')).toBe(
      'Probably · 2 devices on usb_serial:S1'
    )
  })

  it('says it is looking while proposing, else the title with its identity note', () => {
    const d = device('usb_serial:S1', { identity_basis: 'port_position' })
    expect(cardSentence(d, null, 'proposing')).toBe('something on USB · looking at what answers…')
    expect(cardSentence(d, null, 'failed')).toBe(
      'something on USB · identity from the USB port — keep it in this port'
    )
    expect(cardSentence(device('usb_serial:S1'), null, 'failed')).toBe('something on USB')
  })

  it('picks the glyph per driver family', () => {
    expect(cardGlyph(null)).toBe('?')
    expect(cardGlyph({ ...proposal, driver_id: null })).toBe('?')
    expect(cardGlyph(proposal)).toBe('⛓')
    expect(
      cardGlyph({
        ...proposal,
        stream: {
          framing: 'csv',
          channel_count: 4,
          update_hz: 50,
          channel_names: null,
          declared_hz: null
        }
      })
    ).toBe('⌇')
  })

  it('joins at most two verbatim evidence notes', () => {
    const match = (note: unknown): ModalityMatch => ({
      modality: 'bus_enumeration' as const,
      source_ref: {},
      confidence: 1,
      state: 'matched' as const,
      evidence: { note }
    })
    expect(
      evidenceNotes({ ...proposal, evidence: [match('pinged 1..6'), match(''), match(7)] })
    ).toBe('pinged 1..6')
    expect(evidenceNotes({ ...proposal, evidence: [match('a'), match('b'), match('c')] })).toBe(
      'a · b'
    )
    // Six servos answering the same register yield six identical notes — say it once.
    expect(evidenceNotes({ ...proposal, evidence: [match('a'), match('a'), match('b')] })).toBe(
      'a · b'
    )
  })
})

describe('cardQuestion', () => {
  it('asks for a name by default', () => {
    expect(cardQuestion(proposal)).toEqual({ kind: 'name' })
  })

  it('asks to choose when exactly two configs are offered, labels verbatim', () => {
    const matches = [
      { config_id: 'c1', parser_id: 'p', label: 'Left arm', source: 'a.yaml' },
      { config_id: 'c2', parser_id: 'p', label: 'Right arm', source: 'a.yaml' },
      { config_id: 'c3', parser_id: 'p', label: 'Spare', source: 'a.yaml' }
    ]
    expect(
      cardQuestion({
        ...proposal,
        repo_matches: matches,
        disambiguation: { question: 'Which arm is this?', options: ['c1', 'c2'] }
      })
    ).toEqual({
      kind: 'choose',
      question: 'Which arm is this?',
      options: [
        { configId: 'c1', label: 'Left arm' },
        { configId: 'c2', label: 'Right arm' }
      ]
    })
    expect(
      cardQuestion({
        ...proposal,
        repo_matches: matches,
        disambiguation: { question: 'Which?', options: ['c1', 'c2', 'c3'] }
      })
    ).toEqual({ kind: 'name' })
  })

  it('offers the first pending suggestion', () => {
    expect(cardQuestion({ ...proposal, suggestions: [suggestion] } as ProposalOut)).toEqual({
      kind: 'suggest',
      suggestion
    })
  })
})

describe('conflictText', () => {
  const message = 'usb_serial:S1/1 is already part of robot 0f9c2f2a-1111-4222-8333-444455556666'
  const rover = { ...entity('0f9c2f2a-1111-4222-8333-444455556666', ''), name: 'Rover' }

  it('replaces the uuid a 409 names with the robot’s name', () => {
    expect(conflictText(message, [rover])).toBe('usb_serial:S1/1 is already part of robot Rover')
  })

  it('keeps the backend sentence verbatim when the robot is unknown or no uuid is named', () => {
    expect(conflictText(message, [])).toBe(message)
    expect(conflictText('something else failed', [rover])).toBe('something else failed')
  })
})

describe('defaultAccepted / placementNearRail', () => {
  it('accepts every row, naming unnamed channels by address, actuators for a bus', () => {
    expect(defaultAccepted(proposal)).toEqual([
      { row_id: 'usb_serial:S1/1', function_name: 'joint_1', category: 'actuators' },
      { row_id: 'usb_serial:S1/2', function_name: 'channel 2', category: 'actuators' }
    ])
  })

  it('files a line stream’s channels as sensors', () => {
    const streamed: ProposalOut = {
      ...proposal,
      stream: {
        framing: 'csv',
        channel_count: 1,
        update_hz: 50,
        channel_names: null,
        declared_hz: null
      }
    }
    expect(defaultAccepted(streamed).map((r) => r.category)).toEqual(['sensors', 'sensors'])
  })

  it('lands a rail-confirmed robot two columns right, one row up', () => {
    expect(placementNearRail()).toEqual({ x: 2 * (CARD_WIDTH + 72), y: -(CARD_HEIGHT + 64) })
  })
})
