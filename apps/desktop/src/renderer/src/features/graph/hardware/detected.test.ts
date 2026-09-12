// SOLUSDEV-250 P2 — the Detected copy rules: the backend's headline wins, a
// bare bridge is "something on USB" (never an "MCU unknown" verdict), tone is
// a label not a number, and a port-position identity says so.
import { describe, expect, it } from 'vitest'
import type { DetectedDeviceOut, ProposalOut } from '../../../lib/api/hardware'
import { detectedTitle, identityNote, proposalHeadline, toneLabel } from './detected'

const bridge: DetectedDeviceOut = {
  transport: 'usb_serial',
  device_ref: 'usb_serial:S1',
  identity: { kind: 'usb_serial', binding: 'S1' },
  level: 'transport',
  board: null,
  board_class: 'usb_bridge',
  mcu_known: false,
  confidence: 0.4,
  evidence: [],
  ambiguous: false,
  last_seen_path: '/dev/serial0'
}
const proposal: ProposalOut = {
  device_ref: 'usb_serial:S1',
  level: 'protocol',
  summary: '3 servos on usb_serial:S1',
  driver_id: 'serial_bus',
  params: {},
  rows: [],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: []
}

describe('detectedTitle', () => {
  it('uses the backend headline when present', () => {
    expect(detectedTitle({ ...bridge, headline: 'something on USB streaming 4 channels' })).toBe(
      'something on USB streaming 4 channels'
    )
  })

  it('says "something on USB" for a bare bridge — never "MCU unknown"', () => {
    expect(detectedTitle(bridge)).toBe('something on USB')
    expect(detectedTitle({ ...bridge, headline: '' })).toBe('something on USB')
  })

  it('keeps the board name and the non-USB fallback', () => {
    expect(detectedTitle({ ...bridge, level: 'board', board: 'Dev board' })).toBe('Dev board')
    expect(detectedTitle({ ...bridge, transport: 'can' })).toBe('can device — unknown')
  })
})

describe('toneLabel / proposalHeadline', () => {
  it('maps each tone to its label', () => {
    expect(toneLabel('looks_like')).toBe('Looks like')
    expect(toneLabel('probably')).toBe('Probably')
    expect(toneLabel('something')).toBe('Something on USB')
  })

  it('prefixes the summary with the tone, defaulting to "something"', () => {
    expect(proposalHeadline({ ...proposal, tone: 'probably' })).toBe(
      'Probably · 3 servos on usb_serial:S1'
    )
    expect(proposalHeadline(proposal)).toBe('Something on USB · 3 servos on usb_serial:S1')
  })

  it('does not repeat a tone the summary already starts with', () => {
    expect(
      proposalHeadline({ ...proposal, tone: 'something', summary: 'something on USB, 4 channels' })
    ).toBe('something on USB, 4 channels')
    expect(
      proposalHeadline({ ...proposal, tone: 'probably', summary: 'Probably a servo bus' })
    ).toBe('Probably a servo bus')
  })

  it('never doubles a headline the summary already leads with', () => {
    const led = { ...proposal, headline: 'Arduino-class board on USB' }
    expect(
      proposalHeadline({
        ...led,
        tone: 'something',
        summary: 'Arduino-class board on USB · 4 channels'
      })
    ).toBe('Arduino-class board on USB · 4 channels')
    expect(
      proposalHeadline({
        ...led,
        tone: 'probably',
        summary: 'Arduino-class board on USB · 4 channels'
      })
    ).toBe('Probably Arduino-class board on USB · 4 channels')
    expect(
      proposalHeadline({
        ...proposal,
        headline: 'an ESP32',
        tone: 'looks_like',
        summary: 'an ESP32 · 2 channels'
      })
    ).toBe('Looks like an ESP32 · 2 channels')
  })
})

describe('identityNote', () => {
  it('notes a port-position identity and nothing else', () => {
    const note = 'identity from the USB port — keep it in this port'
    expect(identityNote({ ...bridge, identity_basis: 'port_position' })).toBe(note)
    expect(identityNote(bridge)).toBe('')
    expect(identityNote({ ...bridge, identity_basis: 'serial' })).toBe('')
  })
})

it('distinguishes deleted hardware from a stale saved version without hiding the draft', async () => {
  const { ApiError } = await import('../../../lib/api/envelope.types')
  const { hardwareErrorText } = await import('./detected')
  expect(hardwareErrorText(new ApiError(404, 'not_found', 'Part not found'))).toContain(
    'no longer available'
  )
  expect(hardwareErrorText(new ApiError(409, 'version_conflict', 'Version changed'))).toContain(
    'Reload'
  )
})
