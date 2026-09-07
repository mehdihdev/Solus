import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { FromFileModal } from './FromFileModal'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listUnassignedParts: vi.fn(),
  attachParts: vi.fn()
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
const part = (id: string, name: string): Entity => ({
  id,
  project_id: 'p1',
  name,
  type: 'cad_part',
  domain: 'mechanical',
  source_key: 'onshape:doc1',
  origin: 'connector'
})
const bracket = part('e1', 'Bracket')
const plate = part('e2', 'Base plate')
const onClose = vi.fn()

function renderModal(robots: Entity[] = [robot]): void {
  render(<FromFileModal projectId="p1" mode="Guide" robots={robots} onClose={onClose} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.listUnassignedParts).mockResolvedValue({
    data: [bracket, plate],
    meta: { has_next: false, next_cursor: null }
  })
})

it('lists unassigned parts with their graph identity and the empty state honestly', async () => {
  renderModal()
  const list = within(await screen.findByRole('list', { name: 'Unassigned parts' }))
  expect(list.getByRole('checkbox', { name: /Bracket/ })).not.toBeChecked()
  expect(list.getAllByText('cad_part · onshape:doc1')).toHaveLength(2)
  expect(hardware.listUnassignedParts).toHaveBeenCalledExactlyOnceWith('p1', null)
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

it('shows the empty state and read failures', async () => {
  vi.mocked(hardware.listUnassignedParts).mockResolvedValueOnce({ data: [], meta: {} })
  const view = render(
    <FromFileModal projectId="p1" mode="Expert" robots={[robot]} onClose={onClose} />
  )
  expect(
    await screen.findByText('No unassigned parts from connected sources yet.')
  ).toBeInTheDocument()
  view.unmount()
  vi.mocked(hardware.listUnassignedParts).mockRejectedValueOnce(new Error('API unreachable'))
  renderModal()
  expect(await screen.findByRole('alert')).toHaveTextContent('API unreachable')
})

it('loads the next page on demand', async () => {
  vi.mocked(hardware.listUnassignedParts)
    .mockResolvedValueOnce({ data: [bracket], meta: { has_next: true, next_cursor: 'c2' } })
    .mockResolvedValueOnce({ data: [plate], meta: { has_next: false, next_cursor: null } })
  renderModal()
  await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
  expect(hardware.listUnassignedParts).toHaveBeenLastCalledWith('p1', 'c2')
  expect(await screen.findByRole('checkbox', { name: /Base plate/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

it('attaches the selected parts under the chosen robot and category, reporting skips', async () => {
  vi.mocked(hardware.attachParts).mockResolvedValue({
    attached: ['e1'],
    skipped: ['e2'],
    config_entry_id: 'entry-1'
  })
  renderModal()
  const attach = await screen.findByRole('button', { name: 'Add to robot' })
  expect(attach).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox', { name: /Bracket/ }))
  await userEvent.click(screen.getByRole('checkbox', { name: /Base plate/ }))
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'structure')
  expect(screen.getByRole('combobox', { name: 'Robot' })).toHaveValue('robot-1')
  await userEvent.click(attach)
  expect(hardware.attachParts).toHaveBeenCalledExactlyOnceWith('p1', 'robot-1', {
    entity_ids: ['e1', 'e2'],
    category: 'structure'
  })
  expect(await screen.findByRole('status')).toHaveTextContent('1 attached, 1 already there')
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
})

it('shows an attach failure verbatim and keeps the selection', async () => {
  vi.mocked(hardware.attachParts).mockRejectedValue(
    new ApiError(409, 'conflict', 'e1 is already under another robot')
  )
  renderModal()
  await userEvent.click(await screen.findByRole('checkbox', { name: /Bracket/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Add to robot' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('e1 is already under another robot')
  expect(screen.getByRole('checkbox', { name: /Bracket/ })).toBeChecked()
})

it('cannot attach without a robot and says why', async () => {
  renderModal([])
  await userEvent.click(await screen.findByRole('checkbox', { name: /Bracket/ }))
  expect(screen.getByRole('button', { name: 'Add to robot' })).toBeDisabled()
  expect(screen.getByText(/Create a Physical Robot first/)).toBeInTheDocument()
})
