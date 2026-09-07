import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../../../lib/api/physicalRobots'
import * as hardwareApi from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { Page } from '../../../lib/api/client'
import { ApiError } from '../../../lib/api/envelope.types'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { usePhysicalRobots } from './usePhysicalRobots'

vi.mock('../../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn(),
  listRobotOrphans: vi.fn()
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  createHardwarePart: vi.fn()
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
const second: Entity = { ...robot, id: 'robot-2', name: 'Spare' }
const part: Entity = {
  ...robot,
  id: 'part-1',
  name: 'Drive motor',
  type: 'motor',
  domain: 'mechanical',
  origin: 'connector',
  source_id: 'cad-source'
}
const changed = vi.fn()
const reveal = vi.fn()
function Harness({
  entities = [robot, second],
  revision = 0
}: {
  entities?: Entity[]
  revision?: number
}): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const nodes = usePhysicalRobots(projectId, revision, changed, reveal, entities)
  return (
    <>
      {nodes.hardware}
      {entities.map((entity) => (
        <article key={entity.id} aria-label={entity.name}>
          {nodes.renderContent(entity)}
        </article>
      ))}
      {nodes.overlays}
      {nodes.prompt}
    </>
  )
}
/** Add › Hardware › Authored with a new Physical Robot as the target; returns Create. */
async function openAuthoredForNewRobot(): Promise<HTMLElement> {
  await userEvent.click(screen.getByRole('button', { name: 'Authored' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Wrist IMU')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Robot' }), '__new__')
  return screen.getByRole('button', { name: 'Create' })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'robot@example.invalid' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.mocked(api.listRobotOrphans).mockResolvedValue({ data: [], meta: { has_next: false } })
  vi.mocked(api.createPhysicalRobot).mockResolvedValue(robot)
  vi.mocked(hardwareApi.createHardwarePart).mockResolvedValue({
    entity: { ...part, id: 'part-new', name: 'Wrist IMU', origin: 'manual', source_id: null },
    config_entry_id: 'entry-1'
  })
  vi.mocked(api.renamePhysicalRobot).mockResolvedValue({ ...robot, name: 'Scout', version: 2 })
  vi.mocked(api.deletePhysicalRobot).mockResolvedValue({
    deleted_entity_id: robot.id,
    retained_part_ids: [part.id]
  })
})
it('creates a default-named robot once, reveals its real ID, then authors the part under it', async () => {
  const pending = deferred<Entity>()
  vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
  render(<Harness />)
  const create = await openAuthoredForNewRobot()
  fireEvent.click(create)
  fireEvent.click(create)
  expect(api.createPhysicalRobot).toHaveBeenCalledOnce()
  expect(api.createPhysicalRobot).toHaveBeenCalledWith('p1', expect.anything())
  expect(screen.getByText('Creating part…')).toBeInTheDocument()
  await act(async () => {
    pending.resolve(robot)
  })
  expect(reveal).toHaveBeenCalledWith(robot.id)
  await waitFor(() =>
    expect(hardwareApi.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', robot.id, {
      name: 'Wrist IMU',
      category: 'sensors',
      specs: {},
      lifecycle: 'planned'
    })
  )
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2))
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument()
})

it('lists only editable robots as Authored targets and posts the part to the chosen one', async () => {
  render(<Harness entities={[robot, second, { ...robot, id: 'robot-3', origin: 'connector' }]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Authored' }))
  const target = screen.getByRole('combobox', { name: 'Robot' })
  expect(Array.from(target.querySelectorAll('option')).map((o) => o.textContent)).toEqual([
    'Rover',
    'Spare',
    'New Physical Robot'
  ])
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Bus driver')
  await userEvent.selectOptions(target, 'robot-2')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
  expect(api.createPhysicalRobot).not.toHaveBeenCalled()
  expect(hardwareApi.createHardwarePart).toHaveBeenCalledWith(
    'p1',
    'robot-2',
    expect.objectContaining({ name: 'Bus driver' })
  )
})
it('keeps inline names independent and trims a valid submitted name', async () => {
  render(<Harness />)
  const firstCard = within(screen.getByRole('article', { name: 'Rover' }))
  const secondCard = within(screen.getByRole('article', { name: 'Spare' }))
  await userEvent.click(firstCard.getByRole('button', { name: 'Rename' }))
  await userEvent.click(secondCard.getByRole('button', { name: 'Rename' }))
  await userEvent.clear(firstCard.getByRole('textbox', { name: 'Robot name' }))
  await userEvent.type(firstCard.getByRole('textbox', { name: 'Robot name' }), '  Scout  ')
  expect(secondCard.getByRole('textbox', { name: 'Robot name' })).toHaveValue('Spare')
  await userEvent.click(firstCard.getByRole('button', { name: 'Save name' }))
  expect(api.renamePhysicalRobot).toHaveBeenCalledWith('p1', robot, 'Scout', expect.anything())
  expect(changed).toHaveBeenCalledOnce()
})
it('keeps failed rename drafts, refreshes conflicts, and does not retry automatically', async () => {
  vi.mocked(api.renamePhysicalRobot).mockRejectedValue(new ApiError(409, 'conflict', 'Changed'))
  const view = render(<Harness />)
  const firstCard = within(screen.getByRole('article', { name: 'Rover' }))
  await userEvent.click(firstCard.getByRole('button', { name: 'Rename' }))
  const input = firstCard.getByRole('textbox', { name: 'Robot name' })
  await userEvent.clear(input)
  await userEvent.type(input, 'Scout')
  await userEvent.click(firstCard.getByRole('button', { name: 'Save name' }))
  expect(await firstCard.findByRole('alert')).toHaveTextContent(/changed.*review/i)
  expect(input).toHaveValue('Scout')
  expect(changed).toHaveBeenCalledOnce()
  expect(api.renamePhysicalRobot).toHaveBeenCalledOnce()
  view.rerender(<Harness entities={[{ ...robot, name: 'Teammate name', version: 2 }, second]} />)
  expect(screen.getByRole('textbox', { name: 'Robot name' })).toHaveValue('Scout')
})
it('rejects blank names and enforces the 512 character input boundary', async () => {
  render(<Harness />)
  const card = within(screen.getByRole('article', { name: 'Rover' }))
  await userEvent.click(card.getByRole('button', { name: 'Rename' }))
  const input = card.getByRole('textbox', { name: 'Robot name' })
  expect(input).toHaveAttribute('maxlength', '512')
  await userEvent.clear(input)
  await userEvent.type(input, '   ')
  expect(card.getByRole('button', { name: 'Save name' })).toBeDisabled()
  expect(api.renamePhysicalRobot).not.toHaveBeenCalled()
  await userEvent.click(card.getByRole('button', { name: 'Cancel rename' }))
  expect(card.queryByRole('textbox')).not.toBeInTheDocument()
})
it('requires concrete deletion confirmation, then lists retained parts after reload', async () => {
  const view = render(<Harness />)
  await userEvent.click(
    within(screen.getByRole('article', { name: 'Rover' })).getByRole('button', { name: 'Delete' })
  )
  expect(screen.getByText(/parts.*retained/i)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(api.deletePhysicalRobot).not.toHaveBeenCalled()
  await userEvent.click(
    within(screen.getByRole('article', { name: 'Rover' })).getByRole('button', { name: 'Delete' })
  )
  vi.mocked(api.listRobotOrphans).mockResolvedValue({ data: [part], meta: { has_next: false } })
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot' }))
  expect(api.deletePhysicalRobot).toHaveBeenCalledWith('p1', robot, expect.anything())
  expect(changed).toHaveBeenCalledWith(robot.id)
  await userEvent.click(await screen.findByRole('button', { name: 'Reveal Drive motor' }))
  expect(reveal).toHaveBeenCalledWith(part.id)
  view.unmount()
  render(<Harness entities={[second]} />)
  expect(await screen.findByRole('button', { name: 'Reveal Drive motor' })).toBeInTheDocument()
  expect(screen.getByText(/attach.*another robot/i)).toBeInTheDocument()
})
it('blocks duplicate confirmation writes while deletion is pending', async () => {
  const pending = deferred<{ deleted_entity_id: string; retained_part_ids: string[] }>()
  vi.mocked(api.deletePhysicalRobot).mockReturnValue(pending.promise)
  render(<Harness />)
  await userEvent.click(
    within(screen.getByRole('article', { name: 'Rover' })).getByRole('button', { name: 'Delete' })
  )
  const confirm = screen.getByRole('button', { name: 'Delete robot' })
  fireEvent.click(confirm)
  fireEvent.click(confirm)
  expect(api.deletePhysicalRobot).toHaveBeenCalledOnce()
  await act(async () => {
    pending.resolve({ deleted_entity_id: robot.id, retained_part_ids: [] })
  })
  expect(changed).toHaveBeenCalledOnce()
})
it('shows deletion access errors without claiming parts were unassigned', async () => {
  vi.mocked(api.deletePhysicalRobot).mockRejectedValue(
    new ApiError(403, 'forbidden', 'Member access required')
  )
  render(<Harness />)
  await userEvent.click(
    within(screen.getByRole('article', { name: 'Rover' })).getByRole('button', { name: 'Delete' })
  )
  await userEvent.click(screen.getByRole('button', { name: 'Delete robot' }))
  expect(await screen.findByText(/Member access required/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete robot' })).toBeInTheDocument()
  expect(changed).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: 'Reveal Drive motor' })).not.toBeInTheDocument()
})
it('pages orphan parts without rendering more than 24 and reveals a service-owned part', async () => {
  const parts = Array.from({ length: 24 }, (_, i) => ({
    ...part,
    id: `part-${i}`,
    name: `Motor ${i}`
  }))
  vi.mocked(api.listRobotOrphans)
    .mockResolvedValueOnce({ data: parts, meta: { has_next: true, next_cursor: 'next' } })
    .mockResolvedValueOnce({ data: [{ ...part, name: 'Final motor' }], meta: { has_next: false } })
    .mockResolvedValue({ data: parts, meta: { has_next: true, next_cursor: 'next' } })
  render(<Harness />)
  await screen.findByRole('button', { name: 'Reveal Motor 0' })
  expect(screen.getAllByRole('button', { name: /^Reveal/ })).toHaveLength(24)
  await userEvent.click(screen.getByRole('button', { name: 'Next unassigned parts' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Reveal Final motor' }))
  expect(screen.queryByRole('button', { name: 'Reveal Motor 0' })).not.toBeInTheDocument()
  expect(reveal).toHaveBeenCalledWith(part.id)
  expect(api.listRobotOrphans).toHaveBeenLastCalledWith('p1', 'next', expect.anything())
  await userEvent.click(screen.getByRole('button', { name: 'Previous unassigned parts' }))
  expect(await screen.findByRole('button', { name: 'Reveal Motor 0' })).toBeInTheDocument()
})
it('shows orphan read errors with explicit retry and respects SOL mode', async () => {
  vi.mocked(api.listRobotOrphans)
    .mockRejectedValueOnce(new Error('Network unavailable'))
    .mockResolvedValue({ data: [part], meta: { has_next: false } })
  render(<Harness />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable')
  await userEvent.click(screen.getByRole('button', { name: 'Retry unassigned parts' }))
  await screen.findByRole('button', { name: 'Reveal Drive motor' })
  const guide = screen.getByText(/attach.*another robot/i).textContent
  act(() => useSettingsStore.setState({ solMode: 'Expert' }))
  expect(screen.getByText(/attach.*another robot/i).textContent).not.toEqual(guide)
})
it.each(['project', 'account'])(
  'never publishes a write after an A → B → A %s switch',
  async (boundary) => {
    const pending = deferred<Entity>()
    vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
    render(<Harness />)
    await userEvent.click(await openAuthoredForNewRobot())
    act(() => {
      if (boundary === 'project') {
        useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
        useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
      } else {
        useAuthStore.setState({ status: 'unauthenticated' })
        useAuthStore.setState({ status: 'authenticated' })
      }
    })
    await act(async () => {
      pending.resolve(robot)
    })
    expect(changed).not.toHaveBeenCalled()
    expect(reveal).not.toHaveBeenCalled()
    expect(hardwareApi.createHardwarePart).not.toHaveBeenCalled()
  }
)
it('discards older orphan reads after a graph refresh and uses a fresh read client', async () => {
  const pending = deferred<Page<Entity[]>>()
  vi.mocked(api.listRobotOrphans)
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue({ data: [part], meta: { has_next: false } })
  const view = render(<Harness />)
  view.rerender(<Harness revision={1} />)
  await screen.findByRole('button', { name: 'Reveal Drive motor' })
  await act(async () => {
    pending.resolve({ data: [{ ...part, name: 'Old part' }], meta: {} })
  })
  expect(screen.queryByRole('button', { name: 'Reveal Old part' })).not.toBeInTheDocument()
  expect(vi.mocked(api.listRobotOrphans).mock.calls[0]?.[2]).not.toBe(
    vi.mocked(api.listRobotOrphans).mock.calls[1]?.[2]
  )
})
it.each(['signed out', 'missing project'])('never writes when %s', async (state) => {
  if (state === 'signed out') useAuthStore.setState({ status: 'unauthenticated' })
  else useWorkspaceStore.setState({ project: null })
  render(<Harness />)
  expect(screen.getByRole('button', { name: 'Authored' })).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Authored' }))
  expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument()
  expect(
    within(screen.getByRole('article', { name: 'Rover' })).queryByRole('button', {
      name: 'Rename'
    })
  ).not.toBeInTheDocument()
  expect(api.createPhysicalRobot).not.toHaveBeenCalled()
  expect(api.listRobotOrphans).not.toHaveBeenCalled()
})

it('allows authenticated hardware creation and orphan reads with a stale onboarding linked flag', async () => {
  useWorkspaceStore.setState({ linked: false })
  render(<Harness />)
  expect(screen.getByRole('button', { name: 'Authored' })).not.toHaveAttribute('aria-disabled')
  await userEvent.click(await openAuthoredForNewRobot())
  expect(api.createPhysicalRobot).toHaveBeenCalledWith('p1', expect.anything())
  expect(api.listRobotOrphans).toHaveBeenCalledWith('p1', null, expect.anything())
  await waitFor(() => expect(reveal).toHaveBeenCalledWith(robot.id))
})
it.each([
  { origin: 'connector' },
  { origin: 'fingerprint' },
  { source_id: 'source' },
  { version: undefined },
  { version: 1.5 },
  { project_id: 'p2' }
])('refuses editing roots without manual ownership and a safe version: %j', async (override) => {
  render(<Harness entities={[{ ...robot, ...override }]} />)
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
})

it('keeps creation failures visible without publishing success', async () => {
  vi.mocked(api.createPhysicalRobot).mockRejectedValue(new Error('Cannot create robot'))
  render(<Harness />)
  await userEvent.click(await openAuthoredForNewRobot())
  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot create robot')
  expect(changed).not.toHaveBeenCalled()
  expect(reveal).not.toHaveBeenCalled()
  expect(hardwareApi.createHardwarePart).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Wrist IMU')
})

it('does not revive a pending write after unmounting', async () => {
  const pending = deferred<Entity>()
  vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
  const view = render(<Harness />)
  await userEvent.click(await openAuthoredForNewRobot())
  view.unmount()
  await act(async () => {
    pending.resolve(robot)
  })
  expect(changed).not.toHaveBeenCalled()
  expect(reveal).not.toHaveBeenCalled()
})

it('closes stale editors and refuses token lookup from an expired workspace', async () => {
  const pending = deferred<Entity>()
  vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
  render(<Harness />)
  await userEvent.click(
    within(screen.getByRole('article', { name: 'Rover' })).getByRole('button', { name: 'Rename' })
  )
  await userEvent.click(await openAuthoredForNewRobot())
  const client = vi.mocked(api.createPhysicalRobot).mock.calls[0]?.[1]
  act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } }))
  expect(screen.queryByRole('textbox', { name: 'Robot name' })).not.toBeInTheDocument()
  await act(async () => {
    await expect(client?.request('/projects/p1/entities')).rejects.toThrow(
      'workspace session has changed'
    )
  })
  await act(async () => {
    pending.resolve(robot)
  })
  expect(changed).not.toHaveBeenCalled()
})

it('discards orphan results when the account changes', async () => {
  const pending = deferred<Page<Entity[]>>()
  vi.mocked(api.listRobotOrphans).mockReturnValueOnce(pending.promise)
  render(<Harness />)
  act(() => useAuthStore.setState({ user: { email: 'other@example.invalid' } }))
  await act(async () => {
    pending.resolve({ data: [part], meta: {} })
  })
  expect(screen.queryByRole('button', { name: 'Reveal Drive motor' })).not.toBeInTheDocument()
})

it.each([
  { data: [{ ...part, project_id: 'p2' }], meta: {} },
  { data: Array.from({ length: 25 }, () => part), meta: {} },
  { data: [part], meta: { has_next: true } }
])('rejects out-of-scope, oversized, or incomplete orphan pages', async (page) => {
  vi.mocked(api.listRobotOrphans).mockResolvedValue(page)
  render(<Harness />)
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be/)
  expect(screen.queryByRole('button', { name: 'Reveal Drive motor' })).not.toBeInTheDocument()
})

it('stops repeated pagination cursors and leaves the last valid parts visible', async () => {
  vi.mocked(api.listRobotOrphans).mockResolvedValue({
    data: [part],
    meta: { has_next: true, next_cursor: 'same' }
  })
  render(<Harness />)
  await userEvent.click(await screen.findByRole('button', { name: 'Next unassigned parts' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('next page')
  expect(screen.getAllByRole('button', { name: /^Reveal/ })).toHaveLength(1)
})

it('waits for a refreshed version before explicitly retrying a rename conflict', async () => {
  vi.mocked(api.renamePhysicalRobot)
    .mockRejectedValueOnce(new ApiError(409, 'conflict', 'Changed'))
    .mockResolvedValue({ ...robot, name: 'Scout', version: 3 })
  const view = render(<Harness entities={[robot]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Robot name' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Robot name' }), 'Scout')
  await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
  expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled()
  const refreshed = { ...robot, name: 'Updated by teammate', version: 2 }
  view.rerender(<Harness entities={[refreshed]} revision={1} />)
  expect(screen.getByRole('textbox', { name: 'Robot name' })).toHaveValue('Scout')
  expect(screen.getByText('Current name: Updated by teammate')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
  expect(api.renamePhysicalRobot).toHaveBeenLastCalledWith(
    'p1',
    refreshed,
    'Scout',
    expect.anything()
  )
})

it('offers honest category guidance and Escape cancels only the inline editor', async () => {
  render(
    <Harness
      entities={[robot, { ...robot, id: 'category', name: 'Sensors', type: 'robot_category' }]}
    />
  )
  expect(screen.getByText('Parts assigned to this category appear inside.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(api.renamePhysicalRobot).not.toHaveBeenCalled()
  act(() => useSettingsStore.setState({ solMode: 'Expert' }))
  expect(screen.getByText('Assigned parts inside.')).toBeInTheDocument()
})
