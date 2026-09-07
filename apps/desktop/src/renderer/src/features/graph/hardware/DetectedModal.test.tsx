import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { DetectedModal } from './DetectedModal'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listDetectedDevices: vi.fn(),
  proposeDetected: vi.fn(),
  confirmDetected: vi.fn()
}))

const robot: Entity = {
  id: 'robot-1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  origin: 'manual',
  version: 1
}
const bridge: hardware.DetectedDeviceOut = {
  transport: 'usb_serial',
  device_ref: 'usb_serial:5B42134331',
  identity: { kind: 'usb_serial', binding: '5B42134331', vid: 6790, pid: 21971 },
  level: 'transport',
  board: null,
  board_class: 'usb_bridge',
  mcu_known: false,
  confidence: 0.4,
  evidence: [],
  ambiguous: false,
  last_seen_path: '/dev/ttyACM0',
  vid: 6790,
  pid: 21971
}
const board: hardware.DetectedDeviceOut = {
  ...bridge,
  device_ref: 'usb_serial:AB12',
  identity: { kind: 'usb_serial', binding: 'AB12' },
  level: 'board',
  board: 'Dev board rev C',
  board_class: 'mcu',
  mcu_known: true,
  last_seen_path: null,
  vid: null,
  pid: null
}
const twin: hardware.DetectedDeviceOut = {
  ...board,
  device_ref: 'usb_serial:TWIN',
  ambiguous: true
}
const evidence: hardware.ModalityMatch = {
  modality: 'bus_enumeration',
  source_ref: { external_ref: 'usb_serial:5B42134331/1' },
  confidence: 0.9,
  state: 'matched',
  evidence: { value: 'model 777', note: 'answered a ping' }
}
const row = (address: string, fn: string | null): hardware.ProposalRowOut => ({
  id: `usb_serial:5B42134331/${address}`,
  subject: `servo at address ${address}`,
  address,
  model: '777',
  proposed_function: fn,
  confidence: fn ? 0.9 : null,
  evidence: [evidence],
  provenance: 'bus'
})
const proposal: hardware.ProposalOut = {
  device_ref: 'usb_serial:5B42134331',
  level: 'protocol',
  summary: '3 servos on usb_serial:5B42134331',
  driver_id: 'serial_bus',
  params: { baud: 1000000 },
  rows: [row('1', 'shoulder'), row('2', 'elbow'), row('3', null)],
  repo_matches: [],
  disambiguation: null,
  confidence: 0.9,
  evidence: []
}
const ambiguousProposal: hardware.ProposalOut = {
  ...proposal,
  repo_matches: [
    { config_id: 'cfg-leader', parser_id: 'p', label: 'leader', source: 'configs/leader.yaml' },
    {
      config_id: 'cfg-follower',
      parser_id: 'p',
      label: 'follower',
      source: 'configs/follower.yaml'
    }
  ],
  disambiguation: { question: 'Which arm is this?', options: ['cfg-leader', 'cfg-follower'] }
}
const confirmed: hardware.ConfirmOut = {
  robot: { ...robot, id: 'robot-new', name: 'Arm' },
  part_ids: ['a', 'b'],
  config_entry_id: 'entry-1',
  session_id: 'sess-1',
  session_error: null
}
const onCreated = vi.fn()
const onClose = vi.fn()

function renderModal(robots: Entity[] = [robot]): void {
  render(
    <DetectedModal
      projectId="p1"
      mode="Guide"
      robots={robots}
      onCreated={onCreated}
      onClose={onClose}
    />
  )
}

async function openProposal(next = proposal, robots: Entity[] = [robot]): Promise<void> {
  vi.mocked(hardware.proposeDetected).mockResolvedValue(next)
  renderModal(robots)
  await userEvent.click(
    await screen.findByRole('button', { name: 'Propose USB-serial bridge — MCU unknown' })
  )
  await screen.findByTestId('recognition-panel')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.listDetectedDevices).mockResolvedValue([bridge, board, twin])
})

it('lists devices at the level known, with the binding shown and ambiguity honest', async () => {
  renderModal()
  expect(screen.getByRole('status')).toHaveTextContent('Looking for devices…')
  const list = within(await screen.findByRole('list', { name: 'Detected devices' }))
  expect(list.getByText('USB-serial bridge — MCU unknown')).toBeInTheDocument()
  expect(list.getByText('usb_serial:5B42134331 · 1a86:55d3 · /dev/ttyACM0')).toBeInTheDocument()
  expect(list.getAllByText('Dev board rev C')).toHaveLength(2)
  expect(list.getByText('usb_serial:AB12')).toBeInTheDocument()
  expect(list.getByText('pick this device explicitly on the Sources screen')).toBeInTheDocument()
  expect(list.getAllByRole('button', { name: /^Propose / })).toHaveLength(2)
  expect(hardware.listDetectedDevices).toHaveBeenCalledExactlyOnceWith('p1')
})

it('shows the runner-absent reason and the empty state honestly', async () => {
  vi.mocked(hardware.listDetectedDevices).mockRejectedValueOnce(
    new ApiError(503, 'source_unavailable', 'livebench is not installed on this server')
  )
  const view = render(
    <DetectedModal
      projectId="p1"
      mode="Expert"
      robots={[]}
      onCreated={onCreated}
      onClose={onClose}
    />
  )
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'livebench is not installed on this server'
  )
  view.unmount()
  vi.mocked(hardware.listDetectedDevices).mockResolvedValueOnce([])
  renderModal()
  expect(await screen.findByText(/^No devices detected\./)).toBeInTheDocument()
})

it('proposes a device and renders the summary, driver line, hint and rows', async () => {
  await openProposal()
  expect(hardware.proposeDetected).toHaveBeenCalledExactlyOnceWith('p1', 'usb_serial:5B42134331')
  expect(screen.getByText('3 servos on usb_serial:5B42134331')).toBeInTheDocument()
  expect(screen.getByText('serial_bus · {"baud":1000000}')).toBeInTheDocument()
  expect(
    screen.getByText("Link this project's folder on this machine to read your repo config")
  ).toBeInTheDocument()
  expect(screen.getByTestId('proposal-usb_serial:5B42134331/1')).toBeInTheDocument()
  expect(screen.getByTestId('proposal-usb_serial:5B42134331/3')).toHaveTextContent('unknown')
  expect(screen.getByRole('combobox', { name: 'Category for servo at address 1' })).toHaveValue(
    'actuators'
  )
  expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
  expect(hardware.confirmDetected).not.toHaveBeenCalled()
})

it('surfaces a propose failure verbatim and keeps the list', async () => {
  vi.mocked(hardware.proposeDetected).mockRejectedValue(
    new ApiError(404, 'device_not_found', 'usb_serial:5B42134331 is not connected to this machine')
  )
  renderModal()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Propose USB-serial bridge — MCU unknown' })
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('is not connected to this machine')
  expect(screen.getByRole('list', { name: 'Detected devices' })).toBeInTheDocument()
})

it('confirms only accepted and edited rows, with categories and the chosen robot', async () => {
  vi.mocked(hardware.confirmDetected).mockResolvedValue(confirmed)
  await openProposal()
  const rows = (address: string): ReturnType<typeof within> =>
    within(screen.getByTestId(`proposal-usb_serial:5B42134331/${address}`))
  await userEvent.click(rows('1').getByRole('button', { name: 'Accept' }))
  await userEvent.click(rows('2').getByRole('button', { name: 'Reject' }))
  await userEvent.type(rows('3').getByRole('textbox'), 'gripper')
  await userEvent.click(rows('3').getByRole('button', { name: 'Save' }))
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: 'Category for servo at address 3' }),
    'end_effectors'
  )
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Target' }), 'robot-1')
  expect(screen.queryByRole('textbox', { name: 'Robot name' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  expect(hardware.confirmDetected).toHaveBeenCalledExactlyOnceWith('p1', 'usb_serial:5B42134331', {
    target: { kind: 'existing', robot_id: 'robot-1' },
    accepted: [
      { row_id: 'usb_serial:5B42134331/1', function_name: 'shoulder', category: 'actuators' },
      { row_id: 'usb_serial:5B42134331/3', function_name: 'gripper', category: 'end_effectors' }
    ],
    start_session: true,
    window_seconds: 1
  })
  expect(await screen.findByRole('status')).toHaveTextContent('Arm — 2 parts, streaming')
  expect(onCreated).toHaveBeenCalledExactlyOnceWith(confirmed.robot)
})

it('adds as a new robot named from the summary by default and reports a session error', async () => {
  vi.mocked(hardware.confirmDetected).mockResolvedValue({
    ...confirmed,
    session_id: null,
    session_error: 'RuntimeError: the session did not start'
  })
  await openProposal(proposal, [])
  expect(screen.getByRole('combobox', { name: 'Target' }).querySelectorAll('option')).toHaveLength(
    1
  )
  const name = screen.getByRole('textbox', { name: 'Robot name' })
  expect(name).toHaveValue('3 servos on usb_serial:5B42134331')
  await userEvent.clear(name)
  await userEvent.type(name, ' Left arm ')
  await userEvent.click(screen.getByRole('button', { name: 'Accept all' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  expect(hardware.confirmDetected).toHaveBeenCalledWith(
    'p1',
    'usb_serial:5B42134331',
    expect.objectContaining({ target: { kind: 'new', name: 'Left arm' } })
  )
  expect(vi.mocked(hardware.confirmDetected).mock.calls[0]?.[2].accepted).toHaveLength(2)
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Arm — 2 parts, RuntimeError: the session did not start'
  )
})

it('gates Confirm on the disambiguation answer and sends the chosen config', async () => {
  vi.mocked(hardware.confirmDetected).mockResolvedValue(confirmed)
  await openProposal(ambiguousProposal)
  await userEvent.click(screen.getByRole('button', { name: 'Accept all' }))
  const confirm = screen.getByRole('button', { name: 'Confirm' })
  expect(confirm).toBeDisabled()
  const group = within(screen.getByRole('radiogroup', { name: 'Which arm is this?' }))
  expect(group.getAllByRole('radio')).toHaveLength(2)
  await userEvent.click(group.getByRole('radio', { name: 'follower — configs/follower.yaml' }))
  expect(confirm).toBeEnabled()
  await userEvent.click(confirm)
  expect(hardware.confirmDetected).toHaveBeenCalledWith(
    'p1',
    'usb_serial:5B42134331',
    expect.objectContaining({ repo_config_id: 'cfg-follower' })
  )
})

it('shows a 422 verbatim and keeps the proposal', async () => {
  vi.mocked(hardware.confirmDetected).mockRejectedValue(
    new ApiError(422, 'validation_error', 'unknown proposal rows: x')
  )
  await openProposal()
  await userEvent.click(screen.getByRole('button', { name: 'Accept all' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('unknown proposal rows: x')
  expect(screen.getByTestId('recognition-panel')).toBeInTheDocument()
  expect(onCreated).not.toHaveBeenCalled()
})

it('offers to add to the owning robot on 409 and re-submits with that target', async () => {
  const owner = '11111111-2222-4333-8444-555555555555'
  vi.mocked(hardware.confirmDetected)
    .mockRejectedValueOnce(
      new ApiError(
        409,
        'conflict',
        `usb_serial:5B42134331/1 is already part of robot ${owner} — reconnecting a known machine needs no second robot`
      )
    )
    .mockResolvedValueOnce(confirmed)
  await openProposal()
  await userEvent.click(screen.getByRole('button', { name: 'Accept all' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('is already part of robot')
  await userEvent.click(screen.getByRole('button', { name: 'Add to that robot instead' }))
  expect(hardware.confirmDetected).toHaveBeenCalledTimes(2)
  expect(vi.mocked(hardware.confirmDetected).mock.calls[1]?.[2].target).toEqual({
    kind: 'existing',
    robot_id: owner
  })
  expect(await screen.findByRole('status')).toHaveTextContent('Arm — 2 parts, streaming')
})

it('asks the user to pick a robot when the 409 names none', async () => {
  vi.mocked(hardware.confirmDetected).mockRejectedValueOnce(
    new ApiError(409, 'conflict', 'already part of another robot')
  )
  await openProposal()
  await userEvent.click(screen.getByRole('button', { name: 'Accept all' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Add to that robot instead' }))
  expect(hardware.confirmDetected).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('combobox', { name: 'Target' })).toHaveValue('robot-1')
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Pick the robot to add to, then Confirm again.'
  )
})
