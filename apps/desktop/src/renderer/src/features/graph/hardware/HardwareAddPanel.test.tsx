import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { HARDWARE_COPY } from './hardware.constants'
import { HardwareAddPanel } from './HardwareAddPanel'

vi.mock('./DevicesFound', () => ({
  DevicesFound: ({
    projectId,
    mode,
    robots,
    entities
  }: {
    projectId: string
    mode: string
    robots: readonly Entity[]
    entities: readonly Entity[] | null
  }): React.JSX.Element => (
    <div data-testid="devices-found">
      {`${projectId}:${mode}:${robots.length}:${entities === null ? 'null' : entities.length}`}
    </div>
  )
}))
vi.mock('../../sourcing/SourcingModal', () => ({
  SourcingModal: ({
    door,
    projectId,
    onSelected,
    onClose
  }: {
    door: string
    projectId: string
    onSelected?: (entity: unknown) => void
    onClose: () => void
  }): React.JSX.Element => (
    <div role="dialog" aria-label={`sourcing:${door}:${projectId}`}>
      <button type="button" onClick={() => onSelected?.({ id: 'planned-1' })}>
        pick
      </button>
      <button type="button" onClick={onClose}>
        close sourcing
      </button>
    </div>
  )
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listUnassignedParts: vi.fn(),
  searchLibrary: vi.fn()
}))
vi.mock('../../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  listRobotOrphans: vi.fn()
}))

const robot: Entity = {
  id: 'robot-1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  source_id: null,
  origin: 'manual',
  version: 1
}
const onCreated = vi.fn()

function renderPanel(online = true, mode: 'Guide' | 'Expert' = 'Guide'): void {
  render(
    <HardwareAddPanel
      projectId="p1"
      online={online}
      mode={mode}
      robots={[robot]}
      entities={[robot]}
      onCreated={onCreated}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.searchLibrary).mockResolvedValue([])
})

it('renders the sections in order with no card grid, passing the contract props down', () => {
  renderPanel()
  const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
  expect(headings).toEqual(['Devices found', 'Search', 'Describe something new', 'Sourced'])
  expect(screen.getByTestId('devices-found')).toHaveTextContent('p1:Guide:1:1')
  expect(screen.getByText(HARDWARE_COPY.intro.Guide)).toBeInTheDocument()
  expect(screen.getByText(HARDWARE_COPY.search.Guide)).toBeInTheDocument()
  expect(screen.getByRole('searchbox', { name: 'Search parts and platforms' })).toBeEnabled()
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Unassigned parts' })).toHaveAttribute(
    'aria-expanded',
    'false'
  )
  expect(screen.queryByRole('button', { name: 'Detected' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Library' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Authored' })).not.toBeInTheDocument()
})

it('Sourced opens the sourcing panel on the Workspace door and reports the planned part', async () => {
  renderPanel()
  await userEvent.click(screen.getByRole('button', { name: 'Find a part from suppliers' }))
  const dialog = screen.getByRole('dialog', { name: 'sourcing:workspace:p1' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'pick' }))
  expect(onCreated).toHaveBeenCalledWith({ id: 'planned-1' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'close sourcing' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('offline: one honest line, controls disabled, no device list and no reads', async () => {
  renderPanel(false, 'Expert')
  expect(screen.getByText('Connect this project to add hardware.')).toBeInTheDocument()
  expect(screen.queryByTestId('devices-found')).not.toBeInTheDocument()
  expect(screen.getByRole('searchbox')).toBeDisabled()
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Find a part from suppliers' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Unassigned parts' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Find a part from suppliers' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(hardware.listUnassignedParts).not.toHaveBeenCalled()
  expect(screen.getByText(HARDWARE_COPY.intro.Expert)).toBeInTheDocument()
})
