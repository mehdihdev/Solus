// SOLUSDEV-72 — pure presentation rules for the Local Connections section.
// The honesty contract lives here: render EXACTLY what the backend claims,
// never a guessed board, never an implied capability.
import { describe, it, expect } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import type { BenchDevice, BenchSession, BridgeStatus, LocalTool } from '../../../lib/api/resources'
import {
  platformUnavailableReason,
  connectErrorText,
  deviceTitle,
  simulatorName,
  sessionsForSimulator,
  sessionsForDevice,
  toolStatusText,
  unmatchedSessions
} from './presentation'

function device(overrides: Partial<BenchDevice> = {}): BenchDevice {
  return {
    device_path: '/dev/ttyACM0',
    by_id_path: null,
    serial_number: '5B42135040',
    vid: '1a86',
    pid: '55d3',
    board: 'Arduino Uno R3',
    board_class: 'arduino',
    mcu_known: true,
    confidence: 0.9,
    ambiguous: false,
    note: null,
    ...overrides
  }
}

/** The REAL session.device echo — 3 fields, never a full BenchDevice. */
function sessionDevice(serial: string | null, path: string | null = null): BenchSession['device'] {
  return { serial_number: serial, device_path: path, baud: 115200 }
}

function session(overrides: Partial<BenchSession> = {}): BenchSession {
  return {
    id: 's1',
    mode: 'sim',
    provider: 'mujoco',
    status: 'active',
    link: 'streaming',
    label: 'MuJoCo demo scene',
    created_at: '2026-08-16T00:00:00Z',
    ended_at: null,
    device: null,
    device_ids: ['demo/rod'],
    counts: { ingested: 10, unresolved: 0 },
    last_summary: null,
    ...overrides
  }
}

const TOOL: LocalTool = {
  type: 'fusion',
  display_name: 'Fusion',
  hosting: 'vendor-run',
  url_host: '127.0.0.1:27182',
  connect_notice: 'Launch Fusion and enable Preferences → General → API → Fusion MCP Server',
  requires: 'companion'
}

function bridge(overrides: Partial<BridgeStatus> = {}): BridgeStatus {
  return { connected: true, companion_version: '0.1.0', servers: [], ...overrides }
}

describe('deviceTitle', () => {
  it('shows the claimed board name', () => {
    expect(deviceTitle(device())).toBe('Arduino Uno R3')
  })

  it('says "Unknown device" when the backend claims no board', () => {
    expect(deviceTitle(device({ board: null, board_class: 'unknown' }))).toBe('Unknown device')
  })

  it('never guesses a board behind a USB-serial bridge — "something on USB", not a verdict', () => {
    const bridged = device({
      board: 'WCH CH343/CH9102 USB-serial bridge',
      board_class: 'usb_bridge',
      mcu_known: false
    })
    expect(deviceTitle(bridged)).toBe('something on USB')
    expect(deviceTitle(bridged)).not.toMatch(/MCU unknown/)
  })
})

describe('simulatorName', () => {
  it('maps known kinds to display names', () => {
    expect(simulatorName('mujoco')).toBe('MuJoCo')
    expect(simulatorName('gazebo')).toBe('Gazebo')
    expect(simulatorName('isaac')).toBe('Isaac Sim')
    expect(simulatorName('mcap-replay')).toBe('MCAP replay')
  })
})

describe('session matching', () => {
  it('matches sim sessions to their simulator kind', () => {
    const sessions = [session(), session({ id: 's2', provider: 'gazebo' })]
    expect(sessionsForSimulator(sessions, 'mujoco').map((s) => s.id)).toEqual(['s1'])
  })

  it('a starting session already belongs to its row (visible and stoppable)', () => {
    const starting = session({ id: 'st', status: 'starting' })
    expect(sessionsForSimulator([starting], 'mujoco').map((s) => s.id)).toEqual(['st'])
    const real = session({
      id: 'sr',
      mode: 'real',
      provider: 'serial',
      status: 'starting',
      device: sessionDevice('5B42135040')
    })
    expect(sessionsForDevice([real], device()).map((s) => s.id)).toEqual(['sr'])
  })

  it('matches real sessions to a device by serial number when no path was picked', () => {
    const real = session({
      id: 's3',
      mode: 'real',
      provider: 'serial',
      device: sessionDevice('5B42135040')
    })
    expect(sessionsForDevice([real, session()], device()).map((s) => s.id)).toEqual(['s3'])
    expect(sessionsForDevice([real], device({ serial_number: 'OTHER' }))).toEqual([])
  })

  it('an explicit device_path pick wins, even when rows share a serial', () => {
    const picked = session({
      id: 's4',
      mode: 'real',
      provider: 'serial',
      device: sessionDevice('SHARED', '/dev/ttyACM1')
    })
    const rowA = device({ serial_number: 'SHARED', device_path: '/dev/ttyACM0' })
    const rowB = device({ serial_number: 'SHARED', device_path: '/dev/ttyACM1' })
    expect(sessionsForDevice([picked], rowA)).toEqual([])
    expect(sessionsForDevice([picked], rowB).map((s) => s.id)).toEqual(['s4'])
  })

  it('a picked path also matches a row via its stable by_id_path', () => {
    const picked = session({
      id: 's5',
      mode: 'real',
      provider: 'serial',
      device: sessionDevice(null, '/dev/serial/by-id/usb-x-if00')
    })
    const row = device({ serial_number: null, by_id_path: '/dev/serial/by-id/usb-x-if00' })
    expect(sessionsForDevice([picked], row).map((s) => s.id)).toEqual(['s5'])
  })

  it('never matches a session with neither serial nor picked path', () => {
    const anonymous = session({
      id: 's6',
      mode: 'real',
      provider: 'serial',
      device: sessionDevice(null)
    })
    expect(sessionsForDevice([anonymous], device({ serial_number: null }))).toEqual([])
  })
})

describe('unmatchedSessions', () => {
  it('lists active sessions no simulator or device row will show, so they stay stoppable', () => {
    const simulators = [{ kind: 'mujoco' as const, available: true, reason: null }]
    const orphan = session({
      id: 'orphan',
      mode: 'real',
      provider: 'serial',
      device: sessionDevice('GONE')
    })
    const matched = session()
    const result = unmatchedSessions([matched, orphan], simulators, [device()])
    expect(result.map((s) => s.id)).toEqual(['orphan'])
  })

  it('a starting orphan is listed too — never invisible', () => {
    const orphan = session({
      id: 'starting-orphan',
      mode: 'real',
      provider: 'serial',
      status: 'starting',
      device: sessionDevice('GONE')
    })
    expect(unmatchedSessions([orphan], [], []).map((s) => s.id)).toEqual(['starting-orphan'])
  })
})

describe('toolStatusText', () => {
  it('reports the companion offline when the bridge is down or unknown', () => {
    expect(toolStatusText(TOOL, null)).toBe('Companion offline')
    expect(toolStatusText(TOOL, { connected: false, companion_version: null, servers: [] })).toBe(
      'Companion offline'
    )
  })

  it('never implies function from a bare connection: zero tools reads as such', () => {
    expect(toolStatusText(TOOL, bridge())).toBe('Connected — no tools callable yet')
  })

  it('reports a ready server as ready', () => {
    const status = bridge({
      servers: [{ name: 'fusion', state: 'ready', detail: null, updated_at: 'x' }]
    })
    expect(toolStatusText(TOOL, status)).toBe('Server ready')
  })

  it('a ready server can still need a license — say so', () => {
    const status = bridge({
      servers: [
        {
          name: 'fusion',
          state: 'ready',
          detail: null,
          updated_at: 'x',
          license_state: 'bring_your_license'
        }
      ]
    })
    expect(toolStatusText(TOOL, status)).toBe('Server ready — license key required')
  })

  it('carries a non-ready state and its detail verbatim', () => {
    const status = bridge({
      servers: [{ name: 'fusion', state: 'error', detail: 'port busy', updated_at: 'x' }]
    })
    expect(toolStatusText(TOOL, status)).toBe('Server error — port busy')
  })
})

describe('connectErrorText', () => {
  it('explains the session cap', () => {
    expect(connectErrorText(new ApiError(409, 'too_many_sessions', 'cap'))).toBe(
      'Session limit reached — stop an active session first.'
    )
  })

  it('asks for an explicit pick on device ambiguity', () => {
    expect(connectErrorText(new ApiError(409, 'device_ambiguous', 'several match'))).toBe(
      'Several devices match — confirm the exact port and try again.'
    )
  })

  it('lists the candidate discriminators when the 409 carries them', () => {
    const details = [
      { device_path: '/dev/ttyACM0', serial_number: 'SHARED' },
      { device_path: '/dev/ttyACM1', serial_number: 'SHARED' }
    ]
    expect(connectErrorText(new ApiError(409, 'device_ambiguous', 'several match', details))).toBe(
      'Several devices match — confirm the exact port and try again. Candidates: /dev/ttyACM0, /dev/ttyACM1.'
    )
  })

  it('passes the server reason through for unavailable sources', () => {
    expect(connectErrorText(new ApiError(503, 'source_unavailable', 'gz CLI not on PATH'))).toBe(
      'gz CLI not on PATH'
    )
  })

  it('surfaces other API errors by their message and network failures honestly', () => {
    expect(connectErrorText(new ApiError(422, 'validation_error', 'mcap_path required'))).toBe(
      'mcap_path required'
    )
    expect(connectErrorText(new Error('fetch failed'))).toBe(
      "Couldn't reach the Solus API — try again once you're back online."
    )
  })
})

describe('platform availability', () => {
  const tool: LocalTool = {
    type: 'vendor',
    display_name: 'Test CAD',
    hosting: 'vendor-run',
    url_host: 'localhost',
    connect_notice: '',
    requires: 'companion',
    supported_platforms: ['darwin', 'win32']
  }
  it('reports the native host restriction before companion offline', () => {
    expect(toolStatusText(tool, null, 'linux')).toBe('Test CAD is not available on Linux')
    expect(toolStatusText(tool, null, 'darwin')).toBe('Companion offline')
  })
  it('fails closed for unknown host and invalid metadata', () => {
    expect(platformUnavailableReason(tool, null)).toBe(
      'Open the desktop app to check platform availability'
    )
    expect(platformUnavailableReason({ ...tool, supported_platforms: [] }, 'linux')).toBe(
      'Platform availability is unavailable'
    )
  })
})
