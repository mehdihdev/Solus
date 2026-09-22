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
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import * as workspaceApi from '../../lib/api/workspace'
import * as robotApi from '../../lib/api/physicalRobots'
import * as hardwareApi from '../../lib/api/hardware'
import { clearWorkspaceGraphCache } from './useWorkspaceGraph'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { useDetectedDevicesStore } from './hardware/detectedDevicesStore'
import { placementNearRail } from './hardware/deviceCardRules'
import { resetDeviceProposals } from './hardware/useDeviceProposals'

vi.mock('../../lib/api/projectEvents', () => ({ streamProjectEvents: vi.fn() }))

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
  createHardwarePart: vi.fn(),
  listDetectedDevices: vi.fn(),
  proposeDetected: vi.fn(),
  confirmDetected: vi.fn(),
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
  // The robot sidebar's per-robot reads: nothing streaming, nothing pending, no config.
  vi.mocked(resources.listBenchSessions).mockResolvedValue([])
  vi.mocked(resources.listAllSources).mockResolvedValue([])
  vi.mocked(hardwareApi.listHardwareSuggestions).mockResolvedValue([])
  vi.mocked(hardwareApi.getHardwareConfig).mockRejectedValue(new Error('no config'))
  vi.mocked(streamProjectEvents).mockImplementation(async function* () {
    /* no frames by default */
  })
  vi.mocked(hardwareApi.listDetectedDevices).mockResolvedValue([])
  vi.mocked(hardwareApi.proposeDetected).mockImplementation((_p, ref) =>
    Promise.resolve({
      device_ref: ref,
      level: 'protocol',
      summary: `M1 bus on ${ref}`,
      driver_id: 'serial_bus',
      params: {},
      rows: [],
      repo_matches: [],
      disambiguation: null,
      confidence: 0.9,
      evidence: [],
      tone: 'probably'
    })
  )
  useDetectedDevicesStore.getState().reset()
  resetDeviceProposals()
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

  registerRobotChildCreationTests()

  registerRootRobotCreationTests()

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
    const navigator = within(screen.getByRole('region', { name: 'Project graph navigator' }))
    expect(navigator.getAllByText('EMPTY')).toHaveLength(5)
    // Entering .solus selects it, so its sidebar lists the same five sections — honest counts twice.
    expect(
      within(screen.getByRole('complementary', { name: 'Sidebar' })).getAllByText('EMPTY')
    ).toHaveLength(5)
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

  it('renders no Unassigned parts banner even when orphans exist', async () => {
    signIn()
    vi.mocked(robotApi.listRobotOrphans).mockResolvedValue({
      data: [entity('orphan', 'Drive motor')],
      meta: { has_next: false }
    })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select elbow motor' })
    expect(screen.queryByText('Unassigned parts')).not.toBeInTheDocument()
    expect(robotApi.listRobotOrphans).not.toHaveBeenCalled()
  })

  it('seeds the device store on ready and applies device frames without refetching the graph', async () => {
    signIn()
    vi.mocked(hardwareApi.listDetectedDevices).mockResolvedValue([
      { ...device, device_ref: 'seed' }
    ])
    let release: () => void = () => undefined
    vi.mocked(streamProjectEvents).mockImplementation(async function* () {
      yield 'ready' as ProjectEvent
      await new Promise<void>((resolve) => {
        release = resolve
      })
      yield { type: 'hardware.devices_changed', devices: [device] }
    })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select elbow motor' })
    await waitFor(() =>
      expect(useDetectedDevicesStore.getState().devices).toEqual([
        { ...device, device_ref: 'seed' }
      ])
    )
    expect(hardwareApi.listDetectedDevices).toHaveBeenCalledExactlyOnceWith('p1')
    const listCalls = vi.mocked(resources.listAllEntities).mock.calls.length
    await act(async () => release())
    await waitFor(() => expect(useDetectedDevicesStore.getState().devices).toEqual([device]))
    expect(resources.listAllEntities).toHaveBeenCalledTimes(listCalls)
  })
})

describe('WorkspaceScreen — the canvas-edge device rail', () => {
  const { signIn, leader, boundPart, rail } = deviceRailFixture()

  it('shows a card for an unbound device and none for a device a part already binds', async () => {
    signIn()
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select Leader' })
    expect(await screen.findByText('Probably · M1 bus on usb_serial:FREE')).toBeInTheDocument()
    expect(within(rail()).getAllByRole('article')).toHaveLength(1)
    expect(screen.queryByText(/usb_serial:BOUND/)).toBeNull()
    expect(hardwareApi.proposeDetected).toHaveBeenCalledExactlyOnceWith('p1', 'usb_serial:FREE')
  })

  it('confirms from the rail, shows the robot before the refetch resolves, reveals it and places it near the rail once', async () => {
    signIn()
    const arm: resources.Entity = { ...leader, id: 'arm', name: 'Bench arm' }
    const armPart: resources.Entity = { ...boundPart, id: 'm2', source_key: 'usb_serial:FREE/1' }
    vi.mocked(hardwareApi.confirmDetected).mockResolvedValue({
      robot: arm,
      part_ids: ['m2'],
      config_entry_id: 'c',
      session_id: 's',
      session_error: null
    })
    vi.mocked(workspaceApi.saveWorkspaceLayout).mockImplementation(async (_p, layout) => layout)
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [arm],
      edges: [],
      truncated: false
    })
    render(<WorkspaceScreen />)
    await userEvent.type(await screen.findByRole('textbox', { name: 'Robot name' }), 'Bench arm')
    // The refetch is held: the robot must come from the wire's ConfirmOut, not the snapshot.
    let releaseRefetch: () => void = () => undefined
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(4, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseRefetch = () => resolve([leader, boundPart, arm, armPart])
        })
    )
    await userEvent.click(within(rail()).getByRole('button', { name: 'Add' }))
    expect(hardwareApi.confirmDetected).toHaveBeenCalledExactlyOnceWith(
      'p1',
      'usb_serial:FREE',
      expect.objectContaining({ target: { kind: 'new', name: 'Bench arm' }, start_session: true })
    )
    expect(await screen.findByRole('button', { name: 'Select Bench arm' })).toBeInTheDocument()
    expect(screen.getByTestId('graph-node-arm')).toHaveAttribute('data-domain', 'project')
    await waitFor(() => expect(resources.listAllEntities).toHaveBeenCalledTimes(2))
    // Not live yet: no position is saved for an optimistic id.
    expect(workspaceApi.saveWorkspaceLayout).not.toHaveBeenCalled()
    await act(async () => releaseRefetch())
    // The authoritative robot replaces the optimistic one — still one card, same name.
    expect(screen.getAllByRole('button', { name: 'Select Bench arm' })).toHaveLength(1)
    await waitFor(() =>
      expect(workspaceApi.saveWorkspaceLayout).toHaveBeenCalledWith(
        'p1',
        expect.objectContaining({
          positions: expect.objectContaining({ arm: placementNearRail() })
        }),
        expect.anything()
      )
    )
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('arm'))
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Robot name' })).toBeNull())
    expect(workspaceApi.saveWorkspaceLayout).toHaveBeenCalledTimes(1)
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
    expect(screen.getByRole('tab', { name: 'Integrations', selected: true })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    // A keyboard nudge on the anchor's handle is a session preview only: nothing is saved.
    screen.getByRole('button', { name: 'Move octocat' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    await act(async () => {})
    expect(workspaceApi.saveWorkspaceLayout).not.toHaveBeenCalled()
    // Entering the account shows the document as a card, packed around the account's point.
    await userEvent.click(screen.getByRole('button', { name: 'Zoom into octocat' }))
    expect(await screen.findByRole('button', { name: 'Select rover' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back to octocat' })).toBeInTheDocument()
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

function registerRobotDeletionTests(): void {
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

function registerRobotChildCreationTests(): void {
  it('describes something new under the robot through Add › Hardware and reveals it', async () => {
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
    const camera = { ...entity('cam', 'Wrist camera'), origin: 'manual', project_id: 'p1' }
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([leader])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [leader, camera],
      edges: [],
      truncated: false
    })
    vi.mocked(hardwareApi.createHardwarePart).mockResolvedValue({
      entity: camera,
      config_entry_id: 'entry-1'
    })
    render(<WorkspaceScreen />)
    await screen.findByRole('button', { name: 'Select Leader' })
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Hardware' }))
    const describe = within(screen.getByRole('region', { name: 'Describe something new' }))
    await userEvent.type(describe.getByRole('textbox', { name: 'What is it?' }), 'Wrist camera')
    expect(describe.getByRole('combobox', { name: 'Category' })).toHaveValue('sensors')
    expect(describe.getByRole('combobox', { name: 'Part of' })).toHaveValue('leader')
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 1))
    vi.mocked(resources.listAllEntities).mockResolvedValue([leader, camera])
    vi.mocked(workspaceApi.listAllRelations).mockResolvedValue([
      { id: 'r1', type: 'contains', from_entity_id: 'leader', to_entity_id: 'cam' }
    ])
    await userEvent.click(describe.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(hardwareApi.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', 'leader', {
        name: 'Wrist camera',
        category: 'sensors',
        specs: {},
        lifecycle: 'planned'
      })
    )
    expect(robotApi.createPhysicalRobot).not.toHaveBeenCalled()
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('cam'))
    expect(await screen.findByRole('button', { name: 'Select Wrist camera' })).toBeInTheDocument()
  })
}

function registerRootRobotCreationTests(): void {
  it('makes the described thing the robot when the project has none', async () => {
    linkProject()
    const rover: resources.Entity = {
      ...entity('rover', 'Rover MK2'),
      type: 'physical_robot',
      domain: 'project',
      origin: 'manual',
      source_id: null,
      project_id: 'p1',
      version: 1
    }
    const bracket = entity('bracket', 'Bracket')
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([bracket])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [rover],
      edges: [],
      truncated: false
    })
    vi.mocked(robotApi.createPhysicalRobot).mockResolvedValue(rover)
    render(<WorkspaceScreen />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Hardware' }))
    const describe = within(screen.getByRole('region', { name: 'Describe something new' }))
    await userEvent.type(describe.getByRole('textbox', { name: 'What is it?' }), 'Rover MK2')
    expect(describe.queryByRole('combobox', { name: 'Part of' })).not.toBeInTheDocument()
    expect(describe.getByText('No robot yet — this becomes the robot.')).toBeInTheDocument()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([bracket, rover])
    await userEvent.click(describe.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(robotApi.createPhysicalRobot).toHaveBeenCalledExactlyOnceWith(
        'p1',
        undefined,
        'Rover MK2'
      )
    )
    expect(hardwareApi.createHardwarePart).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: 'Select Rover MK2' })).toBeInTheDocument()
    await waitFor(() => expect(useFocusStore.getState().focusedEntityId).toBe('rover'))
  })
}

function registerContainmentFocusTests(): void {
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

function deviceRailFixture() {
  const device = (ref: string): hardwareApi.DetectedDeviceOut => ({
    transport: 'usb_serial',
    device_ref: ref,
    identity: null,
    level: 'transport',
    board: null,
    board_class: 'usb_bridge',
    mcu_known: false,
    confidence: 0.4,
    evidence: [],
    ambiguous: false,
    last_seen_path: null
  })
  const leader: resources.Entity = {
    ...entity('leader', 'Leader'),
    type: 'physical_robot',
    domain: 'project',
    origin: 'manual',
    source_id: null,
    project_id: 'p1',
    version: 1
  }
  const boundPart: resources.Entity = {
    ...entity('m1', 'M1'),
    domain: 'runtime',
    source_key: 'usb_serial:BOUND/1'
  }
  const rail = (): HTMLElement => {
    const overlay = document.querySelector('.graph-overlay')
    if (!(overlay instanceof HTMLElement)) throw new Error('no rail')
    return overlay
  }
  function signIn(): void {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'robot-qa@example.invalid' },
      accessToken: 'robot-qa'
    })
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([leader, boundPart])
    vi.mocked(hardwareApi.listDetectedDevices).mockResolvedValue([
      device('usb_serial:BOUND'),
      device('usb_serial:FREE')
    ])
    vi.mocked(streamProjectEvents).mockImplementation(async function* () {
      yield 'ready' as ProjectEvent
    })
  }

  return { signIn, leader, boundPart, rail }
}
