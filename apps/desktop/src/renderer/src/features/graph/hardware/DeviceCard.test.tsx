// SOLUSDEV-250 P3 — one device, one sentence, one question. Every claim the
// card shows is the wire's (headline, error, session error); nothing auto-adds.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMarks, recordDeviceFrame } from '../../../lib/perf/marks'
import type { HardwareSuggestion, ProposalOut } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { DeviceCard, type DeviceCardProps } from './DeviceCard'
import type { DeviceCardState } from './deviceCard'

const robot: Entity = {
  id: 'robot-1',
  type: 'physical_robot',
  domain: 'project',
  name: 'Rover',
  source_key: ''
}
const proposal: ProposalOut = {
  device_ref: 'usb_serial:S1',
  level: 'protocol',
  summary: '2 devices on usb_serial:S1',
  driver_id: 'serial_bus',
  params: {},
  rows: [],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: [
    {
      modality: 'bus_enumeration',
      source_ref: {},
      confidence: 1,
      state: 'matched',
      evidence: { note: 'pinged ids 1..6, 2 answered' }
    }
  ],
  tone: 'probably'
}
const suggestion: HardwareSuggestion = {
  id: 'sug-1',
  subject_ref: 'usb_serial:S1',
  subject_kind: 'device',
  candidate_robot_id: 'robot-1',
  confidence: 0.8,
  tier: 'high',
  evidence: [],
  reason: null,
  status: 'pending',
  created_at: '',
  decided_at: null
}
const base: DeviceCardState = {
  ref: 'usb_serial:S1',
  device: {
    transport: 'usb_serial',
    device_ref: 'usb_serial:S1',
    identity: null,
    level: 'transport',
    board: null,
    board_class: 'usb_bridge',
    mcu_known: false,
    confidence: 0.4,
    evidence: [],
    ambiguous: false,
    last_seen_path: null
  },
  status: 'proposed',
  proposal,
  error: null,
  conflictRobotId: null,
  result: null,
  attempts: 1
}
const handlers = {
  onConfirm: vi.fn(),
  onAccept: vi.fn(),
  onDismiss: vi.fn(),
  onRetry: vi.fn()
}
function mount(state: Partial<DeviceCardState>, extra: Partial<DeviceCardProps> = {}): void {
  render(
    <DeviceCard
      state={{ ...base, ...state }}
      robots={[robot]}
      mode="Expert"
      {...handlers}
      {...extra}
    />
  )
}
const addButton = (): HTMLElement => screen.getByRole('button', { name: 'Add' })
const nameInput = (): HTMLInputElement => screen.getByRole('textbox', { name: 'Robot name' })

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  resetMarks()
  performance.clearMarks()
  performance.clearMeasures()
})

describe('DeviceCard — perf marks (SOLUSDEV-250 P6)', () => {
  it('measures receipt-to-render once across rail and Add cards', () => {
    recordDeviceFrame(['usb_serial:S1'])
    mount({})
    mount({}, { compact: true })
    expect(performance.getEntriesByName('hw:receipt_to_card:usb_serial:S1')).toHaveLength(1)
    expect(performance.getEntriesByName('hw:plug_in_to_card')).toHaveLength(0)
  })
})

describe('DeviceCard — the sentence', () => {
  it('says it is looking while proposing, with no Add', () => {
    mount({ status: 'proposing', proposal: null })
    expect(screen.getByText('something on USB · looking at what answers…')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
  })

  it('reads the toned headline once proposed and adds evidence notes only in Guide mode', () => {
    mount({})
    expect(screen.getByText('Probably · 2 devices on usb_serial:S1')).toBeInTheDocument()
    expect(screen.queryByText('pinged ids 1..6, 2 answered')).toBeNull()
  })

  it('shows evidence notes verbatim in Guide mode', () => {
    mount({}, { mode: 'Guide' })
    expect(screen.getByText('pinged ids 1..6, 2 answered')).toBeInTheDocument()
  })

  it('flags an ambiguous device with its note, no way to add it, and a way to put it away', async () => {
    mount({
      device: { ...base.device, ambiguous: true },
      status: 'failed',
      proposal: null,
      error: 'no unique identity yet — reconnect it to verify'
    })
    expect(screen.getByText('no unique identity yet — reconnect it to verify')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(handlers.onDismiss).toHaveBeenCalledOnce()
  })
})

describe('DeviceCard — the question', () => {
  registerDeviceNamingTests()

  registerDeviceChoicesTests()
})

describe('DeviceCard — silent, failed, confirming, done', () => {
  registerDeviceFailuresTests()

  registerConnectionStatusTests()
})

function registerDeviceNamingTests(): void {
  it('needs a 1..512-char name for a new robot, trims it, and never sends before Add', async () => {
    mount({})
    expect(screen.getByText('What is this?')).toBeInTheDocument()
    expect(nameInput().placeholder).toBe('Name this robot')
    expect(addButton()).toBeDisabled()
    await userEvent.type(nameInput(), '   ')
    expect(addButton()).toBeDisabled()
    await userEvent.type(nameInput(), 'Bench arm ')
    expect(handlers.onConfirm).not.toHaveBeenCalled()
    await userEvent.click(addButton())
    expect(handlers.onConfirm).toHaveBeenCalledExactlyOnceWith({
      target: { kind: 'new', name: 'Bench arm' }
    })
  })

  it('offers the single repo match label as the placeholder, never the value', () => {
    mount({
      proposal: {
        ...proposal,
        repo_matches: [{ config_id: 'c1', parser_id: 'p', label: 'Arm config', source: 'a.yaml' }]
      }
    })
    expect(nameInput().value).toBe('')
    expect(nameInput().placeholder).toBe('Arm config')
  })

  it('adds to an existing robot without a name', async () => {
    mount({})
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Part of' }), 'robot-1')
    expect(addButton()).toBeEnabled()
    await userEvent.click(addButton())
    expect(handlers.onConfirm).toHaveBeenCalledExactlyOnceWith({
      target: { kind: 'existing', robot_id: 'robot-1' }
    })
  })

  it('hides Part of when there are no robots', () => {
    mount({}, { robots: [] })
    expect(screen.queryByRole('combobox')).toBeNull()
  })
}

function registerDeviceChoicesTests(): void {
  it('asks the disambiguation question verbatim, then the name, sending the chosen config', async () => {
    mount({
      proposal: {
        ...proposal,
        repo_matches: [
          { config_id: 'c1', parser_id: 'p', label: 'Left arm', source: 'a.yaml' },
          { config_id: 'c2', parser_id: 'p', label: 'Right arm', source: 'a.yaml' }
        ],
        disambiguation: { question: 'Which arm is this?', options: ['c1', 'c2'] }
      }
    })
    expect(screen.getByText('Which arm is this?')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Right arm' }))
    expect(screen.getByRole('button', { name: 'Right arm' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    await userEvent.type(nameInput(), 'Bench')
    await userEvent.click(addButton())
    expect(handlers.onConfirm).toHaveBeenCalledExactlyOnceWith({
      target: { kind: 'new', name: 'Bench' },
      repoConfigId: 'c2'
    })
  })

  it('offers "It’s <robot>" for a suggestion beside the name path', async () => {
    mount({ proposal: { ...proposal, suggestions: [suggestion] } as ProposalOut })
    await userEvent.click(screen.getByRole('button', { name: 'It’s Rover' }))
    expect(handlers.onAccept).toHaveBeenCalledExactlyOnceWith(suggestion)
    expect(nameInput()).toBeInTheDocument()
  })

  it('never shows a robot id — an unknown suggestion target is "a robot you imported"', () => {
    mount({ proposal: { ...proposal, suggestions: [suggestion] } as ProposalOut }, { robots: [] })
    expect(screen.getByRole('button', { name: 'It’s a robot you imported' })).toBeInTheDocument()
    expect(screen.queryByText(/robot-1/)).toBeNull()
  })

  it('dismisses with Not now', async () => {
    mount({})
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(handlers.onDismiss).toHaveBeenCalledOnce()
  })
}

function registerDeviceFailuresTests(): void {
  it('says nothing answered and offers Retry', async () => {
    mount({ status: 'silent', proposal: { ...proposal, driver_id: null } })
    expect(screen.getByText('Nothing answered yet — is it powered and free?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(handlers.onRetry).toHaveBeenCalledOnce()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(handlers.onDismiss).toHaveBeenCalledOnce()
  })

  it('shows a propose failure verbatim with Retry and Not now', async () => {
    mount({ status: 'failed', proposal: null, error: 'runner absent: no bench' })
    expect(screen.getByRole('alert')).toHaveTextContent('runner absent: no bench')
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(handlers.onRetry).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(handlers.onDismiss).toHaveBeenCalledOnce()
  })

  it('offers "Add to that robot instead" on a 409 and keeps the question', async () => {
    mount({
      status: 'failed',
      error: 'usb_serial:S1/1 is already part of robot 0f9c2f2a-1111-4222-8333-444455556666',
      conflictRobotId: '0f9c2f2a-1111-4222-8333-444455556666'
    })
    expect(screen.getByRole('alert')).toHaveTextContent('is already part of robot')
    await userEvent.click(screen.getByRole('button', { name: 'Add to that robot instead' }))
    expect(handlers.onConfirm).toHaveBeenCalledExactlyOnceWith({
      target: { kind: 'existing', robot_id: '0f9c2f2a-1111-4222-8333-444455556666' }
    })
    expect(addButton()).toBeInTheDocument()
  })

  it('names the conflicting robot instead of its uuid when it is a known robot', () => {
    const id = '0f9c2f2a-1111-4222-8333-444455556666'
    mount(
      {
        status: 'failed',
        error: `usb_serial:S1/1 is already part of robot ${id}`,
        conflictRobotId: id
      },
      { robots: [{ ...robot, id }] }
    )
    expect(screen.getByRole('alert')).toHaveTextContent('is already part of robot Rover')
    expect(screen.getByRole('alert')).not.toHaveTextContent(id)
  })

  it('spins on Add while confirming', () => {
    mount({ status: 'confirming' })
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
  })

  it('reports an open session without claiming received telemetry', () => {
    const result = {
      robot,
      part_ids: ['a'],
      config_entry_id: 'c',
      session_id: 's',
      session_error: null
    }
    mount({ status: 'done', result })
    expect(screen.getByRole('status')).toHaveTextContent('Added · connected')
  })
}

function registerConnectionStatusTests(): void {
  it('reports the saved asynchronous connection attempt as connecting', () => {
    mount({
      status: 'done',
      result: {
        robot: { ...robot, properties: { connection: { status: 'connecting' } } },
        part_ids: [],
        config_entry_id: 'c',
        session_id: null,
        session_error: null
      }
    })
    expect(screen.getByRole('status')).toHaveTextContent('Added · connecting')
    expect(screen.getByRole('status')).not.toHaveTextContent('no session started')
  })

  it('shows the session error when no session started', () => {
    mount({
      status: 'done',
      result: {
        robot,
        part_ids: ['a'],
        config_entry_id: 'c',
        session_id: null,
        session_error: 'bench session cap reached'
      }
    })
    expect(screen.getByRole('status')).toHaveTextContent('Added · bench session cap reached')
    expect(screen.queryByRole('button')).toBeNull()
  })
}
