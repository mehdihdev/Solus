import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import { ApiError } from '../../../lib/api/envelope.types'
import { HardwareAddPanel } from './HardwareAddPanel'

vi.mock('../../sourcing/SourcingModal', () => ({
  SourcingModal: ({
    door,
    projectId,
    onSelected
  }: {
    door: string
    projectId: string
    onSelected?: (entity: unknown) => void
  }): React.JSX.Element => (
    <div role="dialog" aria-label={`sourcing:${door}:${projectId}`}>
      <button type="button" onClick={() => onSelected?.({ id: 'planned-1' })}>
        pick
      </button>
    </div>
  )
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listDetectedDevices: vi.fn(),
  listUnassignedParts: vi.fn(),
  searchLibrary: vi.fn()
}))

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
const createRobot = vi.fn<() => Promise<string>>()
const onCreated = vi.fn()

function renderPanel(online = true): void {
  render(
    <HardwareAddPanel
      projectId="p1"
      online={online}
      mode="Guide"
      robots={[]}
      createRobot={createRobot}
      onCreated={onCreated}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.listDetectedDevices).mockResolvedValue([bridge])
  vi.mocked(hardware.listUnassignedParts).mockResolvedValue({ data: [], meta: {} })
  vi.mocked(hardware.searchLibrary).mockResolvedValue([
    {
      kind: 'platform',
      id: 'demo-arm',
      name: 'Demo arm',
      manufacturer: null,
      machine_class: 'arm',
      summary: 'arm · usb_serial · 3 parts'
    }
  ])
})

it('renders the five cards, every one live', () => {
  renderPanel()
  const names = screen.getAllByRole('button').map((card) => card.getAttribute('aria-labelledby'))
  expect(names).toHaveLength(5)
  for (const title of ['Detected', 'From a file', 'Library', 'Sourced', 'Authored'])
    expect(screen.getByRole('button', { name: title })).not.toHaveAttribute('aria-disabled')
  expect(screen.getByRole('button', { name: 'Sourced' })).toHaveAccessibleDescription('Find a part')
})

it('Sourced opens the sourcing panel on the Workspace door and reports the planned part', async () => {
  renderPanel()
  await userEvent.click(screen.getByRole('button', { name: 'Sourced' }))
  const dialog = screen.getByRole('dialog', { name: 'sourcing:workspace:p1' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'pick' }))
  expect(onCreated).toHaveBeenCalledWith({ id: 'planned-1' })
})

it('disables every card offline and never reads devices', async () => {
  renderPanel(false)
  for (const card of screen.getAllByRole('button'))
    expect(card).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Detected' }))
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  expect(hardware.listDetectedDevices).not.toHaveBeenCalled()
  expect(screen.getByText('Connect this project to add hardware.')).toBeInTheDocument()
})

it('lists a detected bridge honestly with a live Propose', async () => {
  renderPanel()
  await userEvent.click(screen.getByRole('button', { name: 'Detected' }))
  const list = within(await screen.findByRole('list', { name: 'Detected devices' }))
  expect(list.getByText('USB-serial bridge — MCU unknown')).toBeInTheDocument()
  expect(list.getByText('usb_serial:5B42134331 · 1a86:55d3 · /dev/ttyACM0')).toBeInTheDocument()
  expect(
    list.getByRole('button', { name: 'Propose USB-serial bridge — MCU unknown' })
  ).toBeEnabled()
  expect(hardware.listDetectedDevices).toHaveBeenCalledExactlyOnceWith('p1')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

it('shows the runner reason verbatim, the empty hint, and read failures', async () => {
  vi.mocked(hardware.listDetectedDevices).mockRejectedValueOnce(
    new ApiError(503, 'source_unavailable', 'livebench is not installed on this server')
  )
  const view = render(
    <HardwareAddPanel
      projectId="p1"
      online
      mode="Expert"
      robots={[]}
      createRobot={createRobot}
      onCreated={onCreated}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: 'Detected' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('livebench is not installed')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  vi.mocked(hardware.listDetectedDevices).mockResolvedValueOnce([])
  await userEvent.click(screen.getByRole('button', { name: 'Detected' }))
  expect(await screen.findByText(/^No devices detected\./)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  vi.mocked(hardware.listDetectedDevices).mockRejectedValueOnce(new Error('API unreachable'))
  await userEvent.click(screen.getByRole('button', { name: 'Detected' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('API unreachable')
  view.unmount()
})

it('opens the real From a file flow and the Library search', async () => {
  renderPanel()
  await userEvent.click(screen.getByRole('button', { name: 'From a file' }))
  expect(
    await screen.findByText('No unassigned parts from connected sources yet.')
  ).toBeInTheDocument()
  expect(hardware.listUnassignedParts).toHaveBeenCalledExactlyOnceWith('p1', null)
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  await userEvent.keyboard('{Enter}')
  expect(screen.getByRole('button', { name: 'Library' })).toHaveAccessibleDescription(
    'Search and import'
  )
  await userEvent.click(screen.getByRole('button', { name: 'Library' }))
  expect(screen.getByRole('searchbox', { name: 'Search the library' })).toBeInTheDocument()
  expect(
    within(await screen.findByRole('list', { name: 'Platforms' })).getByRole('button', {
      name: /Demo arm/
    })
  ).toBeInTheDocument()
  expect(hardware.searchLibrary).toHaveBeenCalledExactlyOnceWith('p1', '')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
})

it('opens the Authored form from the keyboard', async () => {
  renderPanel()
  screen.getByRole('button', { name: 'Authored' }).focus()
  await userEvent.keyboard('{Enter}')
  expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument()
})
