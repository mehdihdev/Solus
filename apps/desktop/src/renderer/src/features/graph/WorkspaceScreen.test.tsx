// Workspace screen: honest empty states (SOLUSDEV-152) plus the entity
// navigator (SOLUSDEV-242) — real entities render as bounded node cards, and
// selecting one drives the shared focus store (one bounded neighbourhood
// fetch re-scopes every mounted widget).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkspaceScreen } from './WorkspaceScreen'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import * as workspaceApi from '../../lib/api/workspace'
import * as robotApi from '../../lib/api/physicalRobots'
import * as hardwareApi from '../../lib/api/hardware'
import { clearWorkspaceGraphCache } from './useWorkspaceGraph'

vi.mock('../../lib/api/workspace', () => ({
  listAllRelations: vi.fn(),
  getWorkspaceLayout: vi.fn(),
  saveWorkspaceLayout: vi.fn()
}))

vi.mock('../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn(),
  listRobotOrphans: vi.fn()
}))

vi.mock('../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/hardware')>()),
  createHardwarePart: vi.fn()
}))

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getProject: vi.fn(),
    listAllEntities: vi.fn(),
    getGraphNeighborhood: vi.fn(),
    getSolus: vi.fn()
  }
})

function detailWith(
  entities: number,
  relations: number,
  sources: unknown[] = []
): resources.ProjectDetail {
  return {
    id: 'p1',
    team_id: 't1',
    name: 'Rover MK2',
    description: null,
    archived_at: null,
    created_at: '',
    updated_at: '',
    stats: { entities, relations },
    sources
  }
}

function entity(id: string, name: string): resources.Entity {
  return { id, type: 'part', domain: 'mechanical', name, source_key: `onshape:${id}` }
}

function linkProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(robotApi.listRobotOrphans).mockResolvedValue({ data: [], meta: { has_next: false } })
  vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([])
  vi.mocked(workspaceApi.getWorkspaceLayout).mockResolvedValue({ version: 0, positions: {} })
  vi.mocked(resources.getSolus).mockResolvedValue({
    entity_id: 'solus-1',
    sections: { hardware: [], details: [], errors: [], docs: [], code: [] }
  })
  clearWorkspaceGraphCache()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
})

describe('WorkspaceScreen — unlinked (dev bypass)', () => {
  it('shows the honest sign-in/connect empty state', () => {
    render(<WorkspaceScreen />)
    expect(screen.getByText('Your context model will live here')).toBeInTheDocument()
    expect(
      screen.getByText(/connect a source to start building your robot's graph/i)
    ).toBeInTheDocument()
  })

  it('contains no fabricated nodes, alerts, or counts', () => {
    const { container } = render(<WorkspaceScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES/)
    expect(text).not.toMatch(/leg_ik\.c|DRV8316C|motor_driver\.c/)
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/SYNCED 2 MIN AGO/)
  })
})

describe('WorkspaceScreen — linked', () => {
  it('clears selected categories after deleting their robot from the overview', async () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'robot-qa@example.invalid' },
      accessToken: 'robot-qa'
    })
    linkProject()
    const robot: resources.Entity = {
      ...entity('robot', 'Leader'),
      type: 'physical_robot',
      domain: 'project',
      project_id: 'p1',
      origin: 'manual',
      source_id: null,
      version: 1
    }
    const category: resources.Entity = {
      ...robot,
      id: 'sensors',
      type: 'robot_category',
      name: 'Sensors',
      properties: { robot_id: 'robot', category: 'sensors' }
    }
    const solus = { ...entity('solus-1', '.solus'), type: 'solus_config', domain: 'project' }
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(3, 1))
    vi.mocked(resources.listAllEntities).mockResolvedValue([solus, robot, category])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([
      { id: 'owned', type: 'contains', from_entity_id: robot.id, to_entity_id: category.id }
    ])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [robot, category],
      edges: [],
      truncated: false
    })
    vi.mocked(robotApi.deletePhysicalRobot).mockResolvedValue({
      deleted_entity_id: robot.id,
      retained_part_ids: []
    })
    render(<WorkspaceScreen />)
    await userEvent.click(await screen.findByRole('button', { name: 'Zoom into Leader' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Select Sensors' }))
    await waitFor(() => expect(useFocusStore.getState().status).toBe('ready'))
    await userEvent.click(screen.getByRole('button', { name: 'Project overview' }))
    expect(useFocusStore.getState().focusedEntityId).toBe('sensors')
    const categoryReads = vi
      .mocked(resources.getGraphNeighborhood)
      .mock.calls.filter((args) => args[1] === 'sensors').length
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([solus])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([])
    await userEvent.click(screen.getByRole('button', { name: 'Delete robot' }))
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBeNull())
    expect(
      vi.mocked(resources.getGraphNeighborhood).mock.calls.filter((args) => args[1] === 'sensors')
    ).toHaveLength(categoryReads)
    expect(useFocusStore.getState().status).toBe('idle')
  })

  it('authors a part under a new robot through Add › Hardware and reveals the robot', async () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'robot-qa@example.invalid' },
      accessToken: 'robot-qa'
    })
    linkProject()
    // Existing authenticated accounts need not retain the old onboarding flag.
    useWorkspaceStore.setState({ linked: false })
    const leader: resources.Entity = {
      ...entity('leader', 'Leader'),
      type: 'physical_robot',
      domain: 'project',
      origin: 'manual',
      source_id: null,
      project_id: 'p1',
      version: 1
    }
    const follower = { ...leader, id: 'follower', name: 'Rover MK2' }
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([leader])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [follower],
      edges: [],
      truncated: false
    })
    vi.mocked(robotApi.createPhysicalRobot).mockResolvedValue(follower)
    vi.mocked(hardwareApi.createHardwarePart).mockResolvedValue({
      entity: { ...entity('cam', 'Wrist camera'), origin: 'manual', project_id: 'p1' },
      config_entry_id: 'entry-1'
    })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select Leader' })
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Hardware' }))
    await userEvent.click(screen.getByRole('button', { name: 'Authored' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Wrist camera')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Robot' }), '__new__')
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([leader, follower])
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByRole('button', { name: 'Select Rover MK2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Select Leader' })).toBeInTheDocument()
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('follower'))
    expect(robotApi.createPhysicalRobot).toHaveBeenCalledTimes(1)
    await waitFor(() =>
      expect(hardwareApi.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', 'follower', {
        name: 'Wrist camera',
        category: 'sensors',
        specs: {},
        lifecycle: 'planned'
      })
    )
    expect(screen.queryByRole('button', { name: 'Create' })).not.toBeInTheDocument()
  })

  it('navigates a containment level and selects a leaf with its shared focus path', async () => {
    linkProject()
    const root = entity('root', 'Assembly')
    const leaf = entity('leaf', 'Motor')
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 1, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([root, leaf])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([
      { id: 'r1', type: 'contains', from_entity_id: 'root', to_entity_id: 'leaf' }
    ])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [root, leaf],
      edges: [],
      truncated: false
    })
    render(<WorkspaceScreen />)
    await userEvent.dblClick(await screen.findByRole('button', { name: 'Select Assembly' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Select Motor' }))
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('leaf'))
    expect(useFocusStore.getState().path).toEqual([
      {
        entity: { projectId: 'p1', entityId: 'root' },
        domain: 'mechanical',
        label: 'Assembly',
        relation: 'contains'
      }
    ])
    expect(resources.getGraphNeighborhood).toHaveBeenLastCalledWith('p1', 'leaf', { depth: 1 })
  })
})

describe('WorkspaceScreen — deliberate empty states', () => {
  it('prompts to connect a source when none are connected', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(
      await screen.findByText("Connect a source to start building your robot's graph")
    ).toBeInTheDocument()
  })

  it('shows one real centered .solus root and zooms to five real section nodes', async () => {
    linkProject()
    const sections = Object.entries({
      hardware: 'Hardware configs',
      details: 'Project details',
      errors: 'Error logging',
      docs: 'Documentation',
      code: 'Code environment'
    })
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(6, 5))
    vi.mocked(resources.listAllEntities).mockResolvedValue([
      { id: 'solus-1', type: 'solus_config', domain: 'project', name: '.solus', source_key: '' },
      ...sections.map(([section, name]) => ({
        id: section,
        type: 'solus_section',
        domain: 'project',
        name,
        source_key: '',
        properties: { section }
      }))
    ])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue(
      sections.map(([id]) => ({
        id: `r-${id}`,
        type: 'contains',
        from_entity_id: 'solus-1',
        to_entity_id: id
      }))
    )
    render(<WorkspaceScreen />)
    expect(await screen.findByRole('button', { name: 'Select .solus' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Select / })).toHaveLength(1)
    expect(screen.getByTestId('graph-node-solus-1')).toHaveAttribute('data-x', '0')
    expect(screen.getByTestId('graph-node-solus-1')).toHaveAttribute('data-y', '0')
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
    expect(screen.queryByText('Hardware configs')).not.toBeInTheDocument()
    expect(screen.queryByText(/empty project — on purpose/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Zoom into .solus' }))
    for (const [, name] of sections)
      expect(await screen.findByRole('button', { name: `Select ${name}` })).toBeInTheDocument()
    expect(screen.getAllByText('EMPTY')).toHaveLength(5)
    const details = screen.getByRole('button', { name: 'Select Project details' })
    fireEvent.contextMenu(details)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.keyDown(details, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByTestId('graph-navigator')).toHaveAttribute('data-depth', '1')
  })

  it('prompts to sync when sources exist but no entities do', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(await screen.findByText('Waiting for your first sync')).toBeInTheDocument()
  })
})

describe('WorkspaceScreen — graph data and failures', () => {
  it('renders nodes in stable identity order with real counts', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 5, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([
      entity('e2', 'wrist servo'),
      entity('e1', 'elbow motor')
    ])
    render(<WorkspaceScreen />)
    await waitFor(() =>
      expect(screen.getByText('2 ENTITIES · 5 RELATIONS · 1 SOURCE')).toBeInTheDocument()
    )
    const rows = await screen.findAllByRole('button', {
      name: /^Select (elbow motor|wrist servo)$/
    })
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('elbow motor'),
      expect.stringContaining('wrist servo')
    ])
    expect(screen.queryByText('Your graph is taking shape')).not.toBeInTheDocument()
  })

  it('selecting a node drives the shared focus store', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([entity('e1', 'elbow motor')])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [entity('e1', 'elbow motor')],
      edges: [],
      truncated: false
    })
    render(<WorkspaceScreen />)
    await userEvent.click(await screen.findByRole('button', { name: 'Select elbow motor' }))
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('e1'))
    expect(vi.mocked(resources.getGraphNeighborhood)).toHaveBeenCalledWith('p1', 'e1', {
      depth: 1
    })
  })

  it('says so honestly when the entity list fails but counts succeeded', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(3, 5, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('boom'))
    render(<WorkspaceScreen />)
    expect(await screen.findByText("Couldn't load this project's entities")).toBeInTheDocument()
    expect(screen.getByText('3 ENTITIES · 5 RELATIONS · 1 SOURCE')).toBeInTheDocument()
  })

  it('renders the refusal state — not "backend unreachable" — on a 403', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockRejectedValue(new ApiError(403, 'forbidden', 'nope'))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(await screen.findByText("You don't have access to this project")).toBeInTheDocument()
    expect(screen.queryByText(/can't reach its API/)).not.toBeInTheDocument()
  })

  it('shows a loading line while the summary fetches', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
    vi.mocked(resources.listAllEntities).mockReturnValue(new Promise(() => undefined))
    render(<WorkspaceScreen />)
    expect(screen.getByText(/LOADING WORKSPACE/)).toBeInTheDocument()
    await waitFor(() => expect(resources.getSolus).toHaveBeenCalled())
  })
})

describe('WorkspaceScreen — transient state boundaries', () => {
  it.each(['project', 'account'])(
    'closes an old composer when the %s changes',
    async (boundary) => {
      linkProject()
      vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
      vi.mocked(resources.listAllEntities).mockResolvedValue([
        {
          id: 'details',
          type: 'solus_section',
          domain: 'project',
          name: 'Project details',
          source_key: '',
          properties: { section: 'details' }
        }
      ])
      const previousAuth = useAuthStore.getState()
      const { unmount } = render(<WorkspaceScreen />)
      fireEvent.contextMenu(await screen.findByRole('button', { name: 'Select Project details' }))
      await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
      await userEvent.type(screen.getByRole('textbox'), 'Private old draft')
      act(() => {
        if (boundary === 'project')
          useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
        else useAuthStore.setState({ user: { email: 'different@example.invalid' } })
      })
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.queryByText('Private old draft')).not.toBeInTheDocument()
      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
      unmount()
      useAuthStore.setState(previousAuth)
    }
  )
})
