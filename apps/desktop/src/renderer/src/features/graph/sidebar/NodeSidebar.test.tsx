// The right sidebar (SOLUSDEV-250 P4): idle explains itself; a focused entity is routed
// by type — robots and categories to the robots hook, .solus nodes to the solus hook,
// everything else to the WS-01 widgets, status-branched at the rail so a load in flight
// never reads as "Nothing focused" and an error prints once.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMarks } from '../../../lib/perf/marks'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Entity } from '../../../lib/api/resources'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useFocusStore } from '../../workspace/focusStore'
import { emptySections } from '../useSolusConfig'
import { NodeSidebar, type RobotsSidebarApi, type SolusSidebarApi } from './NodeSidebar'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return { ...actual, getGraphNeighborhood: vi.fn() }
})

const openSol = vi.hoisted(() => vi.fn())
vi.mock('../../../lib/desktopBridge', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/desktopBridge')>()),
  getDesktopSolBridge: () => ({ open: openSol })
}))

const part = (over: Partial<Entity>): Entity => ({
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1',
  ...over
})
const E1 = part({})
const E2 = part({ id: 'e2', name: 'wrist servo', source_key: 'onshape:e2' })

const robots: RobotsSidebarApi = {
  renderSidebar: vi.fn((entity: Entity) => <div data-testid="robot-sidebar">{entity.name}</div>)
}
const nodes: SolusSidebarApi = {
  state: {
    status: 'ready',
    entityId: 'solus-1',
    sections: {
      ...emptySections(),
      details: [
        {
          id: 'n1',
          section: 'details',
          kind: 'text',
          author: 'user',
          text: 'Spec',
          name: null,
          artifact_id: null,
          entity_id: 'note-1',
          media_type: null,
          size_bytes: null,
          created_by: null,
          created_at: '',
          updated_at: ''
        }
      ]
    },
    refetch: vi.fn()
  },
  renderSidebar: vi.fn((entity: Entity) => <div data-testid="solus-sidebar">{entity.name}</div>)
}

function mount(entity: Entity | null): void {
  render(<NodeSidebar projectId="p1" entity={entity} robots={robots} nodes={nodes} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  resetMarks()
  performance.clearMarks()
  performance.clearMeasures()
})

describe('NodeSidebar — perf marks (SOLUSDEV-250 P6)', () => {
  it('does not reuse a completed click when another entity is revealed later', () => {
    performance.mark('ws:select_clicked')
    mount(part({ id: 'r1', type: 'physical_robot', domain: 'project', name: 'Rover' }))
    mount(part({ id: 'r2', type: 'physical_robot', domain: 'project', name: 'Arm' }))
    expect(performance.getEntriesByName('ws:click_to_sidebar')).toHaveLength(1)
  })

  it('marks ws:sidebar_ready when an owned sidebar renders and closes ws:click_to_sidebar', () => {
    performance.mark('ws:select_clicked')
    mount(part({ id: 'r1', type: 'physical_robot', domain: 'project', name: 'Rover' }))
    expect(performance.getEntriesByName('ws:sidebar_ready')).toHaveLength(1)
    expect(performance.getEntriesByName('ws:click_to_sidebar')).toHaveLength(1)
  })

  it('waits for the neighbourhood before marking a widget-routed entity ready', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'loading' })
    mount(E1)
    expect(performance.getEntriesByName('ws:sidebar_ready')).toHaveLength(0)
    mount(null)
    expect(performance.getEntriesByName('ws:sidebar_ready')).toHaveLength(0)
  })
})

describe('NodeSidebar — idle', () => {
  it('explains what the sidebar will show', () => {
    mount(null)
    expect(screen.getByText(/properties, sources, and links across domains/i)).toBeInTheDocument()
  })

  it('contains no fabricated node data or tool buttons', () => {
    const { container } = render(
      <NodeSidebar projectId="p1" entity={null} robots={robots} nodes={nodes} />
    )
    expect(container.textContent ?? '').not.toMatch(/DRV8316C|leg_ik\.c|Open in KiCad|Ask SOL/)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('NodeSidebar — focused entity', () => {
  it('shows a loading line while the neighbourhood fetches', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'loading' })
    mount(E1)
    expect(screen.getByText(/LOADING NEIGHBOURHOOD/)).toBeInTheDocument()
  })

  it('shows ONE error line when the neighbourhood fetch fails', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'error', error: 'timed out' })
    mount(E1)
    expect(screen.getAllByText(/Could not load the neighbourhood/)).toHaveLength(1)
    expect(screen.getByText(/timed out/)).toBeInTheDocument()
  })

  it('renders the focus summary and selectable neighbours once ready', () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    useFocusStore.setState({
      focusedEntityId: 'e1',
      status: 'ready',
      cache: { 'p1:e1@1': { entities: [E1, E2], edges: [], truncated: false } }
    })
    mount(E1)
    expect(screen.getByTestId('focused-name')).toHaveTextContent('elbow motor')
    expect(screen.getByTestId('neighbour-count')).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: 'wrist servo' })).toBeInTheDocument()
    expect(robots.renderSidebar).not.toHaveBeenCalled()
    expect(nodes.renderSidebar).not.toHaveBeenCalled()
  })
})

describe('NodeSidebar — routing by type', () => {
  it.each(['physical_robot', 'robot_category'])('routes a %s to the robots hook', (type) => {
    useFocusStore.setState({ focusedEntityId: 'r1', status: 'loading' })
    mount(part({ id: 'r1', type, domain: 'project', name: 'Rover' }))
    expect(screen.getByTestId('robot-sidebar')).toHaveTextContent('Rover')
    expect(screen.queryByText(/LOADING NEIGHBOURHOOD/)).not.toBeInTheDocument()
  })

  it('routes an integration_account anchor to the account sidebar', () => {
    const anchor = part({
      id: 'account:c1',
      type: 'integration_account',
      domain: 'integration',
      name: 'octocat',
      source_key: null,
      properties: { provider: 'github', account_login: 'octocat', source_ids: ['s1'] }
    })
    render(
      <NodeSidebar
        projectId="p1"
        entity={anchor}
        robots={robots}
        nodes={nodes}
        account={{ entities: [E1, anchor], relations: [], onReveal: vi.fn(), onOpenAdd: vi.fn() }}
      />
    )
    expect(screen.getByRole('heading', { name: /octocat/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add another/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask SOL about selected node' })).toBeNull()
    expect(screen.queryByText(/properties, sources, and links/i)).not.toBeInTheDocument()
    expect(robots.renderSidebar).not.toHaveBeenCalled()
    expect(nodes.renderSidebar).not.toHaveBeenCalled()
  })

  it.each([
    ['solus_config', 'solus-1'],
    ['solus_section', 'section-details'],
    ['solus_note', 'note-1']
  ])('routes a %s (%s) to the solus hook', (type, id) => {
    mount(part({ id, type, domain: 'project', name: type }))
    expect(screen.getByTestId('solus-sidebar')).toHaveTextContent(type)
    expect(robots.renderSidebar).not.toHaveBeenCalled()
  })
})

it('opens SOL only after the selected subject is focused', async () => {
  const focus = vi.spyOn(useFocusStore.getState(), 'focus').mockImplementation(async (id) => {
    useFocusStore.setState({ focusedEntityId: id, status: 'ready' })
  })
  mount(E1)
  fireEvent.click(screen.getByRole('button', { name: 'Ask SOL about selected node' }))
  await waitFor(() => expect(openSol).toHaveBeenCalledOnce())
  expect(focus).toHaveBeenCalledWith(E1.id)
  focus.mockRestore()
})

it('does not open SOL when selected entity focus failed', async () => {
  const focus = vi.spyOn(useFocusStore.getState(), 'focus').mockImplementation(async (id) => {
    useFocusStore.setState({ focusedEntityId: id, status: 'error', error: 'missing' })
  })
  mount(E1)
  fireEvent.click(screen.getByRole('button', { name: 'Ask SOL about selected node' }))
  await waitFor(() => expect(useFocusStore.getState().status).toBe('error'))
  expect(openSol).not.toHaveBeenCalled()
  focus.mockRestore()
})

it('routes the existing ready-focus Ask SOL control without a duplicate action', async () => {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
  useFocusStore.setState({
    focusedEntityId: E1.id,
    status: 'ready',
    cache: { 'p1:e1@1': { entities: [E1], edges: [], truncated: false } }
  })
  const focus = vi.spyOn(useFocusStore.getState(), 'focus').mockResolvedValue(undefined)
  mount(E1)
  const actions = screen.getAllByRole('button', { name: /Ask SOL/ })
  expect(actions).toHaveLength(1)
  fireEvent.click(actions[0])
  await waitFor(() => expect(openSol).toHaveBeenCalledOnce())
  focus.mockRestore()
})

vi.mock('../SourceRevisionPicker', () => ({
  SourceRevisionPicker: ({ sourceId }: { sourceId: string }) => (
    <div data-testid="branch-picker">{sourceId}</div>
  )
}))

it('keeps the personal branch picker attached to the original repository on a snapshot', () => {
  mount(
    part({ type: 'code_repo', source_id: 'snapshot', properties: { base_source_id: 'original' } })
  )
  expect(screen.getByTestId('branch-picker')).toHaveTextContent('original')
})
