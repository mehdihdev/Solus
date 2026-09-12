import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import * as robotsApi from '../../../lib/api/physicalRobots'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { UnassignedParts } from './UnassignedParts'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listUnassignedParts: vi.fn(),
  attachParts: vi.fn()
}))
vi.mock('../../../lib/api/physicalRobots', () => ({ listRobotOrphans: vi.fn() }))

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
const gantry: Entity = { ...robot, id: 'robot-2', name: 'Gantry' }
const part = (id: string, name: string, type = 'cad_part'): Entity => ({
  id,
  project_id: 'p1',
  name,
  type,
  domain: 'mechanical',
  source_key: 'doc1',
  origin: 'connector'
})
const bracket = part('e1', 'Bracket')
const plate = part('e2', 'Base plate')
const orphan = part('e3', 'Drive motor', 'motor')
const page = (data: Entity[], next: string | null = null): { data: Entity[]; meta: object } => ({
  data,
  meta: { has_next: next !== null, next_cursor: next }
})

function renderParts(robots: Entity[] = [robot], mode: 'Guide' | 'Expert' = 'Guide'): void {
  render(<UnassignedParts projectId="p1" mode={mode} robots={robots} disabled={false} />)
}
const open = (): Promise<void> =>
  userEvent.click(screen.getByRole('button', { name: 'Unassigned parts' }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.listUnassignedParts).mockResolvedValue(page([bracket, plate, orphan]))
  vi.mocked(robotsApi.listRobotOrphans).mockResolvedValue(page([orphan]))
  vi.mocked(hardware.attachParts).mockResolvedValue({
    attached: ['e1'],
    skipped: [],
    config_entry_id: 'entry'
  })
})

it('stays collapsed and reads nothing until opened', async () => {
  renderParts()
  expect(screen.getByRole('button', { name: 'Unassigned parts' })).toHaveAttribute(
    'aria-expanded',
    'false'
  )
  expect(hardware.listUnassignedParts).not.toHaveBeenCalled()
  expect(robotsApi.listRobotOrphans).not.toHaveBeenCalled()
  await open()
  expect(hardware.listUnassignedParts).toHaveBeenCalledExactlyOnceWith('p1', null)
  expect(robotsApi.listRobotOrphans).not.toHaveBeenCalled()
  expect(await screen.findByRole('listitem', { name: 'Bracket' })).toBeInTheDocument()
  expect(
    within(screen.getByRole('listitem', { name: 'Drive motor' })).getByText('motor')
  ).toBeInTheDocument()
  expect(screen.queryByText(/e1|e3/)).not.toBeInTheDocument()
})

it('attaches one part to the chosen robot in the chosen category and drops the row', async () => {
  renderParts([robot, gantry])
  await open()
  const row = within(await screen.findByRole('listitem', { name: 'Bracket' }))
  expect(row.getByRole('combobox', { name: 'Part of' })).toHaveValue('robot-1')
  expect(row.getByRole('combobox', { name: 'Category' })).toHaveValue('structure')
  await userEvent.selectOptions(row.getByRole('combobox', { name: 'Part of' }), 'robot-2')
  await userEvent.selectOptions(row.getByRole('combobox', { name: 'Category' }), 'wiring')
  await userEvent.click(row.getByRole('button', { name: 'Add' }))
  expect(hardware.attachParts).toHaveBeenCalledExactlyOnceWith('p1', 'robot-2', {
    entity_ids: ['e1'],
    category: 'wiring'
  })
  await waitFor(() =>
    expect(screen.queryByRole('listitem', { name: 'Bracket' })).not.toBeInTheDocument()
  )
  expect(screen.getByRole('listitem', { name: 'Base plate' })).toBeInTheDocument()
})

it('pages one source and deduplicates overlapping entity ids', async () => {
  vi.mocked(hardware.listUnassignedParts)
    .mockResolvedValueOnce(page([bracket], 'c2'))
    .mockResolvedValueOnce(page([bracket, plate]))
  renderParts()
  await open()
  await screen.findByRole('listitem', { name: 'Bracket' })
  await userEvent.click(screen.getByRole('button', { name: 'Load more from unassigned parts' }))
  expect(hardware.listUnassignedParts).toHaveBeenLastCalledWith('p1', 'c2')
  expect(await screen.findByRole('listitem', { name: 'Base plate' })).toBeInTheDocument()
  expect(screen.getAllByRole('listitem', { name: 'Bracket' })).toHaveLength(1)
  expect(screen.queryByRole('button', { name: /Load more/ })).not.toBeInTheDocument()
})

it('is honest when nothing is unassigned', async () => {
  vi.mocked(hardware.listUnassignedParts).mockResolvedValueOnce(page([]))
  vi.mocked(robotsApi.listRobotOrphans).mockResolvedValueOnce(page([]))
  renderParts()
  await open()
  expect(await screen.findByText('Nothing unassigned.')).toBeInTheDocument()
})

it('shows a read failure verbatim and never claims emptiness over it', async () => {
  vi.mocked(hardware.listUnassignedParts).mockRejectedValueOnce(
    new ApiError(403, 'forbidden', 'Member access required')
  )
  renderParts()
  await open()
  expect(await screen.findByRole('alert')).toHaveTextContent('Member access required')
  expect(screen.queryByText('Nothing unassigned.')).not.toBeInTheDocument()
})

it('shows an attach failure verbatim and keeps the row', async () => {
  vi.mocked(hardware.attachParts).mockRejectedValueOnce(new Error('Robot is not editable'))
  renderParts()
  await open()
  const row = within(await screen.findByRole('listitem', { name: 'Bracket' }))
  await userEvent.click(row.getByRole('button', { name: 'Add' }))
  expect(await row.findByRole('alert')).toHaveTextContent('Robot is not editable')
  expect(screen.getByRole('listitem', { name: 'Bracket' })).toBeInTheDocument()
})

it('without a robot it lists the parts but offers no target', async () => {
  renderParts([], 'Expert')
  await open()
  await screen.findByRole('listitem', { name: 'Bracket' })
  expect(screen.getByText('No robot to add these to yet.')).toBeInTheDocument()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
})

it('preserves skipped parts and offers private local sources in the active flow', async () => {
  vi.mocked(hardware.attachParts).mockResolvedValueOnce({
    attached: [],
    skipped: ['e1'],
    config_entry_id: 'entry'
  })
  renderParts()
  await open()
  const row = within(await screen.findByRole('listitem', { name: 'Bracket' }))
  await userEvent.click(row.getByRole('button', { name: 'Add' }))
  expect(await row.findByRole('alert')).toHaveTextContent('was not attached')
  expect(screen.getByRole('listitem', { name: 'Bracket' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Local calibration sources' })).toBeInTheDocument()
})
