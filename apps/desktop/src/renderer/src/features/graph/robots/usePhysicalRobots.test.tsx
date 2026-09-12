import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../../../lib/api/physicalRobots'
import * as hardwareApi from '../../../lib/api/hardware'
import * as resources from '../../../lib/api/resources'
import type { Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { usePhysicalRobots } from './usePhysicalRobots'

vi.mock('../hardware/DevicesFound', () => ({
  DevicesFound: (): React.JSX.Element => <div data-testid="devices-found" />
}))
vi.mock('../../sourcing/SourcingModal', () => ({
  SourcingModal: ({ door, projectId }: { door: string; projectId: string }): React.JSX.Element => (
    <div role="dialog" aria-label={`sourcing:${door}:${projectId}`} />
  )
}))
vi.mock('../../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn(),
  listRobotOrphans: vi.fn()
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  createHardwarePart: vi.fn(),
  searchLibrary: vi.fn(),
  listUnassignedParts: vi.fn(),
  listHardwareSuggestions: vi.fn(),
  getHardwareConfig: vi.fn(),
  attachParts: vi.fn()
}))
vi.mock('../../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/resources')>()),
  listBenchSessions: vi.fn()
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
const optimistic = vi.fn()
// Stable like the real snapshot: the sidebar keys its per-robot reads on this identity.
const DEFAULT_ENTITIES = [robot, second]
function Harness({
  entities = DEFAULT_ENTITIES,
  selected
}: {
  entities?: Entity[]
  /** Kept so callers can bump a revision prop the hook must now ignore. */
  revision?: number
  /** The entity whose sidebar is mounted, as WorkspaceScreen mounts the focused one. */
  selected?: string
}): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const nodes = usePhysicalRobots(projectId, changed, reveal, entities, undefined, optimistic)
  probe(nodes.renderContent)
  const focused = entities.find((entity) => entity.id === selected)
  return (
    <>
      {nodes.hardware}
      {entities.map((entity) => (
        <article key={entity.id} aria-label={entity.name}>
          {nodes.renderContent(entity)}
        </article>
      ))}
      <aside aria-label="Sidebar">{focused && nodes.renderSidebar(focused)}</aside>
    </>
  )
}
const probe = vi.fn()
/** Add › Hardware › Describe something new; returns Add. */
async function describe(name = 'Wrist IMU'): Promise<HTMLElement> {
  await userEvent.type(screen.getByRole('textbox', { name: 'What is it?' }), name)
  return screen.getByRole('button', { name: 'Add' })
}
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
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
  vi.mocked(hardwareApi.listUnassignedParts).mockResolvedValue({
    data: [],
    meta: { has_next: false }
  })
  vi.mocked(hardwareApi.searchLibrary).mockResolvedValue([])
  vi.mocked(hardwareApi.listUnassignedParts).mockResolvedValue({ data: [], meta: {} })
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([])
  vi.mocked(hardwareApi.getHardwareConfig).mockRejectedValue(new Error('none'))
  vi.mocked(resources.listBenchSessions).mockResolvedValue([])
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
it('describes a part under the first robot, refreshes once, and never shows a part early', async () => {
  render(<Harness />)
  fireEvent.click(await describe())
  await waitFor(() =>
    expect(hardwareApi.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', robot.id, {
      name: 'Wrist IMU',
      category: 'sensors',
      specs: {},
      lifecycle: 'planned'
    })
  )
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
  // A part has no containment edge until the snapshot lands: showing it at the
  // root for that interval would be an invented placement. Only robots go early.
  expect(optimistic).not.toHaveBeenCalled()
  // P6: the card renderer keeps one identity across the publishes above.
  expect(new Set(probe.mock.calls.map(([fn]) => fn)).size).toBe(1)
  expect(api.createPhysicalRobot).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toHaveValue('')
})

it('lists only editable robots as targets and posts the part to the chosen one', async () => {
  render(<Harness entities={[robot, second, { ...robot, id: 'robot-3', origin: 'connector' }]} />)
  const target = screen.getByRole('combobox', { name: 'Part of' })
  expect(Array.from(target.querySelectorAll('option')).map((o) => o.textContent)).toEqual([
    'Rover',
    'Spare'
  ])
  await userEvent.selectOptions(target, 'robot-2')
  await userEvent.click(await describe('Bus driver'))
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
  expect(api.createPhysicalRobot).not.toHaveBeenCalled()
  expect(hardwareApi.createHardwarePart).toHaveBeenCalledWith(
    'p1',
    'robot-2',
    expect.objectContaining({ name: 'Bus driver' })
  )
})
it.each(['project', 'account'])(
  'never publishes a write after an A → B → A %s switch',
  async (boundary) => {
    const pending = deferred<Entity>()
    vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
    render(<Harness entities={[]} />)
    await userEvent.click(await describe())
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
it.each(['signed out', 'missing project'])('never writes when %s', async (state) => {
  if (state === 'signed out') useAuthStore.setState({ status: 'unauthenticated' })
  else useWorkspaceStore.setState({ project: null })
  render(<Harness selected={robot.id} />)
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Unassigned parts' }))
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete robot…' })).not.toBeInTheDocument()
  expect(api.createPhysicalRobot).not.toHaveBeenCalled()
  expect(hardwareApi.listUnassignedParts).not.toHaveBeenCalled()
})

it('allows authenticated hardware creation with a stale onboarding linked flag', async () => {
  useWorkspaceStore.setState({ linked: false })
  render(<Harness entities={[]} />)
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toBeEnabled()
  await userEvent.click(await describe())
  expect(api.createPhysicalRobot).toHaveBeenCalledWith('p1', undefined, 'Wrist IMU')
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
})

it('never reads unassigned parts on mount or on a graph revision bump', async () => {
  const view = render(<Harness />)
  view.rerender(<Harness revision={1} />)
  await act(async () => {})
  expect(hardwareApi.listUnassignedParts).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Unassigned parts' })).toHaveAttribute(
    'aria-expanded',
    'false'
  )
})
it.each([
  { origin: 'connector' },
  { origin: 'fingerprint' },
  { source_id: 'source' },
  { version: undefined },
  { version: 1.5 },
  { project_id: 'p2' }
])('refuses editing roots without manual ownership and a safe version: %j', async (override) => {
  render(<Harness entities={[{ ...robot, ...override }]} selected={robot.id} />)
  expect(screen.getByRole('heading', { name: 'Rover' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete robot…' })).not.toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText(/Loading unassigned/)).not.toBeInTheDocument())
})

it('keeps creation failures visible without publishing success', async () => {
  vi.mocked(api.createPhysicalRobot).mockRejectedValue(new Error('Cannot create robot'))
  render(<Harness entities={[]} />)
  await userEvent.click(await describe())
  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot create robot')
  expect(changed).not.toHaveBeenCalled()
  expect(reveal).not.toHaveBeenCalled()
  expect(hardwareApi.createHardwarePart).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toHaveValue('Wrist IMU')
})

it('does not revive a pending write after unmounting', async () => {
  const pending = deferred<Entity>()
  vi.mocked(api.createPhysicalRobot).mockReturnValue(pending.promise)
  const view = render(<Harness entities={[]} />)
  await userEvent.click(await describe())
  view.unmount()
  await act(async () => {
    pending.resolve(robot)
  })
  expect(changed).not.toHaveBeenCalled()
  expect(reveal).not.toHaveBeenCalled()
})

it('closes stale editors and never publishes a write from an expired workspace', async () => {
  const pending = deferred<{ entity: Entity; config_entry_id: string }>()
  vi.mocked(hardwareApi.createHardwarePart).mockReturnValue(pending.promise)
  render(<Harness selected={robot.id} />)
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  await userEvent.click(await describe())
  act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } }))
  expect(screen.queryByRole('textbox', { name: 'Robot name' })).not.toBeInTheDocument()
  await act(async () => {
    pending.resolve({ entity: part, config_entry_id: 'entry' })
  })
  expect(changed).not.toHaveBeenCalled()
})

it('offers honest category guidance on the card and no actions on the robot card', () => {
  render(
    <Harness
      entities={[robot, { ...robot, id: 'category', name: 'Sensors', type: 'robot_category' }]}
    />
  )
  expect(screen.getByText('Parts assigned to this category appear inside.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
  act(() => useSettingsStore.setState({ solMode: 'Expert' }))
  expect(screen.getByText('Assigned parts inside.')).toBeInTheDocument()
})

it('mounts the robot sidebar for a selected robot and never a modal', () => {
  render(<Harness selected={robot.id} />)
  expect(screen.getByRole('heading', { name: 'Rover' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Delete robot…' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('Sourced opens the same sourcing panel as the BOM, on the Workspace door', async () => {
  render(<Harness entities={[]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Find a part from suppliers' }))
  expect(screen.getByRole('dialog', { name: 'sourcing:workspace:p1' })).toBeInTheDocument()
})

it('cannot source a part while the project is offline', async () => {
  useAuthStore.setState({ status: 'unauthenticated', user: null })
  render(<Harness entities={[]} />)
  const sourced = screen.getByRole('button', { name: 'Find a part from suppliers' })
  expect(sourced).toBeDisabled()
  await userEvent.click(sourced)
  expect(screen.queryByRole('dialog')).toBeNull()
})
