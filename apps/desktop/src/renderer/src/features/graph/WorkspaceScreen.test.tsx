// Workspace screen: honest empty states (SOLUSDEV-152) plus the entity
// navigator (SOLUSDEV-242) — real entities render as bounded node cards, and
// selecting one drives the shared focus store (one bounded neighbourhood
// fetch re-scopes every mounted widget).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkspaceScreen } from './WorkspaceScreen'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { usePaletteStore } from '../palette/paletteStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import * as workspaceApi from '../../lib/api/workspace'
import * as robotApi from '../../lib/api/physicalRobots'
import * as hardwareApi from '../../lib/api/hardware'
import { clearWorkspaceGraphCache } from './useWorkspaceGraph'
import { emptySections, SECTION_LABELS } from './useSolusConfig'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { reconcileWidgetGraph } from '../../lib/api/widgetGraph'
import * as edgesApi from '../../lib/api/edges'
import * as findingsApi from '../../lib/api/findings'

vi.mock('../../lib/api/widgetGraph', () => ({ reconcileWidgetGraph: vi.fn() }))

vi.mock('../../lib/api/projectEvents', () => ({ streamProjectEvents: vi.fn() }))

vi.mock('../../lib/api/edges', () => ({
  listEdgeCandidates: vi.fn(async () => []),
  confirmEdge: vi.fn(),
  declineEdge: vi.fn()
}))

vi.mock('../../lib/api/findings', () => ({ listFindings: vi.fn() }))

vi.mock('../../lib/api/workspace', () => ({
  listAllRelations: vi.fn(),
  getWorkspaceLayout: vi.fn(),
  saveWorkspaceLayout: vi.fn()
}))

vi.mock('../../lib/api/physicalRobots', () => ({
  createPhysicalRobot: vi.fn(),
  renamePhysicalRobot: vi.fn(),
  deletePhysicalRobot: vi.fn()
}))

vi.mock('../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/hardware')>()),
  listDetectedDevices: vi.fn(),
  listHardwareSuggestions: vi.fn(),
  getHardwareConfig: vi.fn()
}))

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getProject: vi.fn(),
    listAllEntities: vi.fn(),
    getGraphNeighborhood: vi.fn(),
    getSolus: vi.fn(),
    listBenchSessions: vi.fn(),
    listAllSources: vi.fn()
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
  vi.mocked(reconcileWidgetGraph).mockImplementation(() => new Promise<void>(() => undefined))
  // The robot sidebar's per-robot reads: nothing streaming, nothing pending, no config.
  vi.mocked(resources.listBenchSessions).mockResolvedValue([])
  vi.mocked(resources.listAllSources).mockResolvedValue([])
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([])
  vi.mocked(hardwareApi.getHardwareConfig).mockRejectedValue(new Error('no config'))
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    /* no frames by default */
  })
  vi.mocked(hardwareApi.listDetectedDevices).mockResolvedValue([])
  vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([])
  vi.mocked(workspaceApi.getWorkspaceLayout).mockResolvedValue({ version: 0, positions: {} })
  vi.mocked(findingsApi.listFindings).mockResolvedValue([])
  vi.mocked(resources.getSolus).mockResolvedValue({
    entity_id: 'solus-1',
    sections: emptySections()
  })
  clearWorkspaceGraphCache()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
})

describe('WorkspaceScreen — unlinked (dev bypass)', () => {
  it('shows the honest sign-in/connect empty state', () => {
    render(<WorkspaceScreen />)
    expect(screen.getByText('Your workspace will live here')).toBeInTheDocument()
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
  registerRobotDeletionTests()

  registerContainmentFocusTests()
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
    expect(
      screen.getByText(/Solus builds the workspace graph from your connected tools/)
    ).toBeInTheDocument()
  })

  it('shows one real centered .solus root and zooms to seven real section nodes', async () => {
    linkProject()
    const sections = Object.entries(SECTION_LABELS)
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
    expect(screen.queryByRole('button', { name: 'Select Goals' })).not.toBeInTheDocument()
    expect(screen.queryByText(/empty project — on purpose/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Zoom into .solus' }))
    for (const [, name] of sections)
      expect(await screen.findByRole('button', { name: `Select ${name}` })).toBeInTheDocument()
    const navigator = within(screen.getByRole('region', { name: 'Project graph navigator' }))
    // Six: the history node is a view over activities and never says EMPTY (SOLUSDEV-320).
    expect(navigator.getAllByText('EMPTY')).toHaveLength(6)
    // Entering .solus selects it, so its sidebar lists the same seven sections — honest counts twice.
    expect(
      within(screen.getByRole('complementary', { name: 'Sidebar' })).getAllByText('EMPTY')
    ).toHaveLength(7)
    const details = screen.getByRole('button', { name: 'Select Goals' })
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

describe('WorkspaceScreen — live hardware events', () => {
  const device: hardwareApi.DetectedDeviceOut = {
    transport: 'usb_serial',
    device_ref: 'usb_serial:AB12',
    identity: null,
    level: 'board',
    board: null,
    board_class: null,
    mcu_known: true,
    confidence: 0.5,
    evidence: [],
    ambiguous: false,
    last_seen_path: null
  }
  function signIn(): void {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'robot-qa@example.invalid' },
      accessToken: 'robot-qa'
    })
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([entity('e1', 'elbow motor')])
  }

  it("draws no device rail and asks nothing about a plugged-in device (onboarding is SOL's)", async () => {
    signIn()
    vi.mocked(streamProjectEvents).mockImplementation(async function* () {
      yield 'ready' as ProjectEvent
      yield { type: 'hardware.devices_changed', devices: [device] }
    })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select elbow motor' })
    const listCalls = vi.mocked(resources.listAllEntities).mock.calls.length
    await act(async () => undefined)
    expect(document.querySelector('.graph-overlay')).toBeNull()
    expect(screen.queryByRole('textbox', { name: 'Robot name' })).toBeNull()
    expect(hardwareApi.listDetectedDevices).not.toHaveBeenCalled()
    expect(resources.listAllEntities).toHaveBeenCalledTimes(listCalls)
  })
})

describe('WorkspaceScreen — account anchors (SOLUSDEV-250 Phase 5)', () => {
  const source: resources.Source = {
    id: 's1',
    project_id: 'p1',
    type: 'github',
    name: 'octocat/rover',
    status: 'connected',
    config: {},
    account_login: 'octocat',
    connection_id: 'c1',
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: ''
  }
  const repo: resources.Entity = {
    ...entity('repo', 'rover'),
    type: 'code_repo',
    domain: 'code',
    source_id: 's1',
    project_id: 'p1'
  }

  it('clusters a document under its account, opens the account sidebar, and never saves the anchor', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([repo])
    vi.mocked(resources.listAllSources).mockResolvedValue([source])
    vi.mocked(workspaceApi.saveWorkspaceLayout).mockImplementation(async (_p, layout) => layout)
    render(<WorkspaceScreen />)
    // The account is the root; the repo is inside it. No id is printed anywhere.
    const account = await screen.findByRole('button', { name: 'Select octocat' })
    expect(screen.queryByRole('button', { name: 'Select rover' })).not.toBeInTheDocument()
    expect(screen.queryByText(/account:/)).not.toBeInTheDocument()
    await userEvent.click(account)
    const sidebar = within(screen.getByRole('complementary', { name: 'Sidebar' }))
    expect(sidebar.getByRole('heading', { name: 'octocat' })).toBeInTheDocument()
    expect(sidebar.getByRole('button', { name: /rover/ })).toBeInTheDocument()
    expect(useFocusStore.getState().focusedEntityId).toBeNull()
    // Add another → Add › Integrations opens.
    await userEvent.click(sidebar.getByRole('button', { name: 'Add another' }))
    expect(screen.getByRole('dialog', { name: 'Add to graph' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    // A keyboard nudge on the anchor's handle is a session preview only: nothing is saved.
    screen.getByRole('button', { name: 'Move octocat' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    await act(async () => {})
    expect(workspaceApi.saveWorkspaceLayout).not.toHaveBeenCalled()
    // Entering the account shows the document as a card, packed around the account's point.
    await userEvent.click(screen.getByRole('button', { name: 'Zoom into octocat' }))
    expect(await screen.findByRole('button', { name: 'Select rover' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Graph trail' })).toHaveTextContent('octocat')
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
          id: 'goals',
          type: 'solus_section',
          domain: 'project',
          name: 'Goals',
          source_key: '',
          properties: { section: 'goals' }
        }
      ])
      const previousAuth = useAuthStore.getState()
      const { unmount } = render(<WorkspaceScreen />)
      fireEvent.contextMenu(await screen.findByRole('button', { name: 'Select Goals' }))
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

function registerRobotDeletionTests(): void {
  // A legacy category row (SOLUSDEV-326 retired them) is still cleared with its robot.
  it('clears selected legacy categories after deleting their robot from the overview', async () => {
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
    await userEvent.click(screen.getByRole('button', { name: 'Help' }))
    await userEvent.click(screen.getByRole('button', { name: 'Project overview' }))
    expect(useFocusStore.getState().focusedEntityId).toBe('sensors')
    const categoryReads = vi
      .mocked(resources.getGraphNeighborhood)
      .mock.calls.filter((args) => args[1] === 'sensors').length
    // The robot's actions live in its sidebar: select it, then the two-step delete.
    await userEvent.click(await screen.findByRole('button', { name: 'Select Leader' }))
    const sidebar = within(await screen.findByRole('complementary', { name: 'Sidebar' }))
    await userEvent.click(await sidebar.findByRole('button', { name: 'Delete robot…' }))
    expect(
      sidebar.getByText(/Delete Leader\? Its parts and other links are retained/)
    ).toBeInTheDocument()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([solus])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([])
    await userEvent.click(sidebar.getByRole('button', { name: 'Delete robot' }))
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBeNull())
    expect(
      vi.mocked(resources.getGraphNeighborhood).mock.calls.filter((args) => args[1] === 'sensors')
    ).toHaveLength(categoryReads)
    expect(useFocusStore.getState().status).toBe('idle')
  })
}

function registerContainmentFocusTests(): void {
  it('serves a ⌘K jump to a nested node: enters its level and focuses it with its path (SOLUSDEV-317)', async () => {
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
    usePaletteStore.getState().requestJump('p1', 'leaf')
    render(<WorkspaceScreen />)
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('leaf'))
    expect(useFocusStore.getState().path.map((step) => step.entity.entityId)).toEqual(['root'])
    expect(await screen.findByRole('button', { name: 'Select Motor' })).toBeInTheDocument()
    expect(usePaletteStore.getState().jump).toBeNull()
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
}

it('renders registered Live Bench and widgets at overview and opens existing destinations', async () => {
  linkProject()
  const registration = (id: string, type: string, name: string): resources.Entity => ({
    id,
    type,
    name,
    domain: 'workspace',
    origin: 'system',
    project_id: 'p1',
    source_key: null
  })
  const root = registration('workspace-root', 'solus:workspace', 'Workspace')
  const bench = registration('bench-root', 'solus:live_bench', 'Live Bench')
  const widget = {
    ...registration('widget-root', 'solus:widget', 'Parts list'),
    properties: {
      slug: 'parts-list',
      enabled: true,
      blocked: false,
      views: ['page'],
      version: '1.0'
    }
  }
  vi.mocked(resources.getProject).mockResolvedValue(detailWith(3, 2))
  vi.mocked(resources.listAllEntities).mockResolvedValue([root, bench, widget])
  vi.mocked(workspaceApi.listAllRelations).mockResolvedValue(
    [bench, widget].map((child) => ({
      id: `edge-${child.id}`,
      type: 'contains',
      from_entity_id: root.id,
      to_entity_id: child.id
    }))
  )
  const openBench = vi.fn()
  const openWidget = vi.fn()
  render(<WorkspaceScreen onOpenBench={openBench} onOpenWidget={openWidget} />)
  expect(await screen.findByTestId('graph-node-bench-root')).toBeInTheDocument()
  expect(screen.getByTestId('graph-node-widget-root')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-workspace-root')).not.toBeInTheDocument()
  expect(screen.getByTestId('graph-navigator')).toHaveAttribute('data-depth', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Open Live Bench' }))
  fireEvent.click(screen.getByRole('button', { name: 'Open Parts list' }))
  expect(openBench).toHaveBeenCalledOnce()
  expect(openWidget).toHaveBeenCalledWith('parts-list')
})

it("the Add modal's Hardware row opens the Hardware page through the shell", async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
  vi.mocked(resources.listAllEntities).mockResolvedValue([entity('part', 'Existing part')])
  const openHardware = vi.fn()
  render(<WorkspaceScreen onOpenHardware={openHardware} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Hardware' }))
  expect(openHardware).toHaveBeenCalledOnce()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Describe something new' })).toBeNull()
})

it('initializes legacy registrations and renders the persisted Live Bench after refresh', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
  vi.mocked(resources.listAllEntities).mockResolvedValue([entity('part', 'Existing part')])
  let finish!: () => void
  vi.mocked(reconcileWidgetGraph).mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve
    })
  )
  render(<WorkspaceScreen />)
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1))
  expect(screen.queryByTestId('graph-node-persisted-bench')).not.toBeInTheDocument()
  vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 0))
  vi.mocked(resources.listAllEntities).mockResolvedValue([
    entity('part', 'Existing part'),
    {
      id: 'persisted-bench',
      source_key: null,
      project_id: 'p1',
      type: 'solus:live_bench',
      name: 'Live Bench',
      domain: 'workspace',
      origin: 'system'
    }
  ])
  await act(async () => finish())
  expect(await screen.findByTestId('graph-node-persisted-bench')).toBeInTheDocument()
  expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
})

it('explains member-required initialization and exposes a manual retry', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
  vi.mocked(resources.listAllEntities).mockResolvedValue([entity('part', 'Existing part')])
  vi.mocked(reconcileWidgetGraph).mockRejectedValue(new ApiError(403, 'FORBIDDEN', 'private'))
  render(<WorkspaceScreen />)
  expect(await screen.findByText(/project member must initialize widgets/i)).toBeInTheDocument()
  expect(screen.queryByText('private')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry widget initialization' }))
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(2))
})

// SOLUSDEV-320 P4 — clicking a drawn edge opens the EdgePanel; a decision refetches the
// graph and closes it; selecting a card closes it; cards carry open-finding badges.
const OPEN_FINDING: findingsApi.Finding = {
  id: 'f1',
  rule_id: 'i2c.address',
  severity: 'critical',
  source: 'checker',
  status: 'open',
  headline: 'clash',
  explanation: '',
  detail: null,
  subjects: ['a'],
  evidence: {},
  count: 1,
  first_seen: '',
  last_seen: '',
  matrix_cell: null,
  domain: null,
  dismissed_until: null,
  created_at: '',
  updated_at: ''
}

describe('WorkspaceScreen — edges and findings', () => {
  const candidate: resources.Relation = {
    id: 'r1',
    type: 'wires',
    from_entity_id: 'a',
    to_entity_id: 'b',
    origin: 'inferred',
    confidence: 0.6,
    properties: { evidence: [{ kind: 'netlist', ref: 'SDA' }] }
  }
  function seedPair(): void {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 1))
    vi.mocked(resources.listAllEntities).mockResolvedValue([entity('a', 'IMU'), entity('b', 'MCU')])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([candidate])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [],
      edges: [],
      truncated: false
    })
  }

  it('opens the edge panel for a clicked edge, confirms it and returns to the entity', async () => {
    seedPair()
    vi.mocked(edgesApi.confirmEdge).mockResolvedValue({ ...candidate, origin: 'manual' })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select IMU' })
    fireEvent.click(document.querySelector('.graph-cross-edge')!)
    // The edge rail and the entity rail are separate trees: query the sidebar fresh.
    const sidebar = (): ReturnType<typeof within> =>
      within(screen.getByRole('complementary', { name: 'Sidebar' }))
    expect(sidebar().getByRole('heading', { level: 2 })).toHaveTextContent('IMU wires MCU')
    const reads = vi.mocked(resources.getProject).mock.calls.length
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([{ ...candidate, origin: 'manual' }])
    fireEvent.click(sidebar().getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(edgesApi.confirmEdge).toHaveBeenCalledWith('p1', 'r1'))
    // Nothing is selected once the edge is decided, so the panel closes (design template).
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Sidebar' })).toBeNull())
    expect(vi.mocked(resources.getProject).mock.calls.length).toBeGreaterThan(reads)
  })

  it('closes the edge panel when a card is selected', async () => {
    seedPair()
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select IMU' })
    fireEvent.click(document.querySelector('.graph-cross-edge')!)
    expect(screen.getByText('IMU → MCU')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Select IMU' }))
    expect(screen.queryByText('IMU → MCU')).toBeNull()
  })

  it('badges cards with their open findings', async () => {
    seedPair()
    vi.mocked(findingsApi.listFindings).mockResolvedValue([OPEN_FINDING])
    render(<WorkspaceScreen />)
    const card = await screen.findByTestId('graph-node-a')
    await waitFor(() =>
      expect(within(card).getByTitle('1 open finding, worst: critical')).toHaveTextContent('1')
    )
    expect(findingsApi.listFindings).toHaveBeenCalledWith('p1', { status: 'open' })
    expect(screen.getByTestId('graph-node-b').querySelector('.graph-finding-badge')).toBeNull()
  })

  // Design template: the side panel exists only for a selection; ✕ / Escape close it first,
  // a second Escape then zooms out. The neighbourhood cache survives the close.
  it('mounts the panel on selection, closes it on Escape, and keeps the cache warm', async () => {
    seedPair()
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select IMU' })
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Select IMU' }))
    expect(screen.getByRole('complementary', { name: 'Sidebar' })).toBeInTheDocument()
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('a'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).toBeNull()
    expect(useFocusStore.getState().focusedEntityId).toBeNull()
    expect(Object.keys(useFocusStore.getState().cache).length).toBeGreaterThan(0)
    expect(screen.getByTestId('graph-navigator')).toHaveAttribute('data-depth', '0')
  })

  it('the header ✕ closes the panel too', async () => {
    seedPair()
    render(<WorkspaceScreen />)
    await userEvent.click(await screen.findByRole('button', { name: 'Select IMU' }))
    await userEvent.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).toBeNull()
  })
})
