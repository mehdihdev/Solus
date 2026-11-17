import { beforeEach, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../../../lib/api/physicalRobots'
import * as hardwareApi from '../../../lib/api/hardware'
import * as resources from '../../../lib/api/resources'
import type { Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { usePhysicalRobots } from './usePhysicalRobots'

vi.mock('../../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn()
}))
vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  listHardwareSuggestions: vi.fn(),
  getHardwareConfig: vi.fn()
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
  const nodes = usePhysicalRobots(projectId, changed, reveal, entities)
  probe(nodes.renderContent)
  const focused = entities.find((entity) => entity.id === selected)
  return (
    <>
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
beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'robot@example.invalid' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([])
  vi.mocked(hardwareApi.getHardwareConfig).mockRejectedValue(new Error('none'))
  vi.mocked(resources.listBenchSessions).mockResolvedValue([])
  vi.mocked(api.createPhysicalRobot).mockResolvedValue(robot)
  vi.mocked(api.renamePhysicalRobot).mockResolvedValue({ ...robot, name: 'Scout', version: 2 })
  vi.mocked(api.deletePhysicalRobot).mockResolvedValue({
    deleted_entity_id: robot.id,
    retained_part_ids: [part.id]
  })
})
it.each(['project', 'account'])(
  'never publishes a write after an A → B → A %s switch',
  async (boundary) => {
    let resolve!: (value: Entity) => void
    vi.mocked(api.renamePhysicalRobot).mockReturnValue(
      new Promise<Entity>((done) => {
        resolve = done
      })
    )
    render(<Harness selected={robot.id} />)
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Robot name' }), ' 2')
    await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
    expect(api.renamePhysicalRobot).toHaveBeenCalledOnce()
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
      resolve({ ...robot, name: 'Rover 2', version: 2 })
    })
    expect(changed).not.toHaveBeenCalled()
    expect(reveal).not.toHaveBeenCalled()
  }
)
it.each(['signed out', 'missing project'])('never writes when %s', async (state) => {
  if (state === 'signed out') useAuthStore.setState({ status: 'unauthenticated' })
  else useWorkspaceStore.setState({ project: null })
  render(<Harness selected={robot.id} />)
  expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete robot…' })).not.toBeInTheDocument()
  await act(async () => {})
  expect(api.renamePhysicalRobot).not.toHaveBeenCalled()
  expect(api.deletePhysicalRobot).not.toHaveBeenCalled()
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
})

it('closes a stale rename editor when the workspace changes', async () => {
  render(<Harness selected={robot.id} />)
  await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
  expect(screen.getByRole('textbox', { name: 'Robot name' })).toBeInTheDocument()
  act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } }))
  expect(screen.queryByRole('textbox', { name: 'Robot name' })).not.toBeInTheDocument()
})

it("offers no Add › Hardware panel: onboarding is SOL's (SOLUSDEV-326)", () => {
  render(<Harness entities={[]} />)
  expect(screen.queryByRole('textbox', { name: 'What is it?' })).toBeNull()
  expect(screen.queryByRole('searchbox', { name: 'Search parts and platforms' })).toBeNull()
})

it('keeps a legacy category row’s guidance and puts no actions on the robot card', () => {
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
