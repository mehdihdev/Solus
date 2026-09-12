// SOLUSDEV-250 P3 — the live list of pending device cards: honest "looking" and
// empty states per SOL mode, one card per pending device, and the confirmed
// robot handed back through onCreated.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfirmOut, HardwareSuggestion, ProposalOut } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { useDetectedDevicesStore } from './detectedDevicesStore'
import { DevicesFound, type DevicesFoundProps } from './DevicesFound'
import type { DeviceCardState } from './deviceCard'
import { useDeviceProposals, type DeviceProposals } from './useDeviceProposals'

vi.mock('./useDeviceProposals', () => ({ useDeviceProposals: vi.fn() }))

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
  evidence: []
}
const card = (ref: string, extra: Partial<DeviceCardState> = {}): DeviceCardState => ({
  ref,
  device: {
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
    last_seen_path: null
  },
  status: 'proposed',
  proposal: { ...proposal, device_ref: ref },
  error: null,
  conflictRobotId: null,
  result: null,
  attempts: 1,
  ...extra
})
const confirmed: ConfirmOut = {
  robot,
  part_ids: [],
  config_entry_id: 'c',
  session_id: 's',
  session_error: null
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
const proposals: DeviceProposals = {
  cards: [],
  confirm: vi.fn(),
  accept: vi.fn(),
  dismiss: vi.fn(),
  retry: vi.fn()
}
const onCreated = vi.fn()
function mount(extra: Partial<DevicesFoundProps> = {}): void {
  render(
    <DevicesFound
      projectId="p1"
      mode="Expert"
      robots={[robot]}
      entities={[]}
      onCreated={onCreated}
      {...extra}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useDetectedDevicesStore.getState().reset()
  vi.mocked(useDeviceProposals).mockReturnValue({ ...proposals, cards: [] })
  vi.mocked(proposals.confirm).mockResolvedValue(confirmed)
  vi.mocked(proposals.accept).mockResolvedValue(true)
})

describe('DevicesFound — states', () => {
  it('says it is looking until the store is seeded', () => {
    mount()
    expect(screen.getByRole('status')).toHaveTextContent('Looking for devices…')
  })

  it('says no devices per SOL mode once seeded and empty', () => {
    useDetectedDevicesStore.getState().setDevices([])
    mount({ mode: 'Guide' })
    expect(
      screen.getByText(/Nothing found yet\. Plug in a USB device, a CAN adapter, or join/)
    ).toBeInTheDocument()
  })

  it('is terse in Expert mode', () => {
    useDetectedDevicesStore.getState().setDevices([])
    mount()
    expect(screen.getByText('Nothing found yet.')).toBeInTheDocument()
  })

  it('renders nothing for the rail when there is nothing to show', () => {
    const { container } = render(
      <DevicesFound
        projectId="p1"
        mode="Expert"
        robots={[]}
        entities={[]}
        onCreated={onCreated}
        compact
      />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('hands the hook the store devices and the graph entities', () => {
    useDetectedDevicesStore.getState().setDevices([card('usb_serial:S1').device])
    mount({ entities: [robot] })
    expect(useDeviceProposals).toHaveBeenLastCalledWith(
      'p1',
      [card('usb_serial:S1').device],
      [robot]
    )
  })
})

describe('DevicesFound — cards', () => {
  it('renders one card per pending device, flagging an ambiguous one without Add', () => {
    useDetectedDevicesStore.getState().setDevices([])
    vi.mocked(useDeviceProposals).mockReturnValue({
      ...proposals,
      cards: [
        card('usb_serial:S1'),
        card('usb_serial:TWIN', {
          device: { ...card('usb_serial:TWIN').device, ambiguous: true },
          status: 'failed',
          proposal: null,
          error: 'no unique identity yet — reconnect it to verify'
        })
      ]
    })
    mount()
    expect(screen.getAllByRole('article')).toHaveLength(2)
    expect(screen.getByText('no unique identity yet — reconnect it to verify')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Add' })).toHaveLength(1)
  })

  it('confirms through the hook and hands the robot to onCreated', async () => {
    useDetectedDevicesStore.getState().setDevices([])
    vi.mocked(useDeviceProposals).mockReturnValue({ ...proposals, cards: [card('usb_serial:S1')] })
    mount()
    await userEvent.type(screen.getByRole('textbox', { name: 'Robot name' }), 'Bench arm')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(proposals.confirm).toHaveBeenCalledExactlyOnceWith('usb_serial:S1', {
      target: { kind: 'new', name: 'Bench arm' }
    })
    await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith(robot))
  })

  it('does not report a robot when confirm failed', async () => {
    useDetectedDevicesStore.getState().setDevices([])
    vi.mocked(proposals.confirm).mockResolvedValue(null)
    vi.mocked(useDeviceProposals).mockReturnValue({ ...proposals, cards: [card('usb_serial:S1')] })
    mount()
    await userEvent.type(screen.getByRole('textbox', { name: 'Robot name' }), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(proposals.confirm).toHaveBeenCalled())
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('accepts a suggestion and reports the named robot; dismiss and retry route by ref', async () => {
    useDetectedDevicesStore.getState().setDevices([])
    vi.mocked(useDeviceProposals).mockReturnValue({
      ...proposals,
      cards: [
        card('usb_serial:S1', {
          proposal: { ...proposal, suggestions: [suggestion] } as ProposalOut
        }),
        card('usb_serial:S2', { status: 'failed', proposal: null, error: 'boom' })
      ]
    })
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'It’s Rover' }))
    expect(proposals.accept).toHaveBeenCalledExactlyOnceWith('usb_serial:S1', 'sug-1')
    await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith(robot))
    // Both cards can be put away; the first Not now belongs to the first card.
    const [first, second] = screen.getAllByRole('button', { name: 'Not now' })
    await userEvent.click(first!)
    expect(proposals.dismiss).toHaveBeenCalledExactlyOnceWith('usb_serial:S1')
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(proposals.retry).toHaveBeenCalledExactlyOnceWith('usb_serial:S2')
    await userEvent.click(second!)
    expect(proposals.dismiss).toHaveBeenLastCalledWith('usb_serial:S2')
  })
})
