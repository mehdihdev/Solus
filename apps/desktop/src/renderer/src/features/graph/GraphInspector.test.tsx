// Inspector rail of the Context Model screen: idle explains itself honestly;
// once a selection lands (via the shared focus store) it mounts the WS-01
// widgets — focus summary + selectable neighbours — under WidgetHost, so
// "selecting a part re-scopes every mounted widget" holds on this screen too.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GraphInspector } from './GraphInspector'
import { useFocusStore } from '../workspace/focusStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Entity } from '../../lib/api/resources'
import type { LocalFolderView } from '../../lib/api/resources.localfolder'
import * as localFolderHook from '../project/useLocalFolder'
import { useProjectFolderStore } from '../project/projectFolderStore'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getGraphNeighborhood: vi.fn() }
})
// This machine's local-folder view has its own tests (useLocalFolder); here it
// is stubbed so the inspector's decision — show Open-in only for an entity
// the view carries — is what's under test.
vi.mock('../project/useLocalFolder', () => ({ useLocalFolder: vi.fn() }))

const E1: Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}
const E2: Entity = {
  id: 'e2',
  type: 'part',
  domain: 'mechanical',
  name: 'wrist servo',
  source_key: 'onshape:e2'
}
/** A KiCad project a local folder on this machine landed (SOLUSDEV-249). */
const E3: Entity = {
  id: 'e3',
  type: 'kicad_project',
  domain: 'electrical',
  name: 'main',
  source_key: 'kicad:hw/main'
}

const LOCAL_VIEW: LocalFolderView = {
  source: null,
  bridge: { connected: true, tools_installed: { kicad: true, vscode: true } },
  detected: [
    {
      entity_id: 'e3',
      entity_key: 'kicad:hw/main',
      tool: 'kicad',
      name: 'main',
      path: 'hw/main/main.kicad_pro',
      open_targets: ['kicad', 'vscode', 'system']
    }
  ]
}

const open = vi.fn(async () => ({ launched: true, tool: 'kicad' as const, reason: null }))

function mockLocalFolder(view: LocalFolderView | null): void {
  vi.mocked(localFolderHook.useLocalFolder).mockReturnValue({
    view,
    status: view ? 'ready' : 'idle',
    machineAvailable: true,
    link: vi.fn(async () => undefined),
    unlink: vi.fn(async () => undefined),
    open,
    refresh: vi.fn(async () => undefined)
  })
}

function focusReady(entity: Entity): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
  useProjectFolderStore.setState({ folders: { p1: { path: '/home/u/rover' } } })
  useFocusStore.setState({
    focusedEntityId: entity.id,
    status: 'ready',
    cache: { [`p1:${entity.id}@1`]: { entities: [E1, E2, E3], edges: [], truncated: false } }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  useProjectFolderStore.setState({ folders: {} })
  mockLocalFolder(LOCAL_VIEW)
})

describe('GraphInspector — idle', () => {
  it('explains what the inspector will show', () => {
    render(<GraphInspector />)
    expect(screen.getByText(/properties, sources, and links across domains/i)).toBeInTheDocument()
  })

  it('contains no fabricated node data or tool buttons', () => {
    const { container } = render(<GraphInspector />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/DRV8316C|leg_ik\.c|Ask SOL/)
    expect(text).not.toMatch(/CONNECTED ACROSS DOMAINS/)
  })
})

describe('GraphInspector — open on this machine (SOLUSDEV-249)', () => {
  it('does not offer Open in KiCad for a non-local entity', () => {
    focusReady(E1)
    render(<GraphInspector />)
    expect(screen.queryByRole('button', { name: /Open in KiCad/ })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Open on this machine' })).toBeNull()
  })

  it('offers Open in KiCad for a kicad_project this machine’s local folder carries', async () => {
    focusReady(E3)
    render(<GraphInspector />)
    const panel = screen.getByRole('region', { name: 'Open on this machine' })
    const kicad = within(panel).getByRole('button', { name: 'Open in KiCad' })
    expect(kicad).toBeEnabled()
    expect(within(panel).getByRole('button', { name: 'Open in editor' })).toBeEnabled()
    await userEvent.click(kicad)
    expect(open).toHaveBeenCalledWith('e3', 'kicad')
  })

  it('stays silent for a local kind the view does not carry (another machine’s folder)', () => {
    mockLocalFolder({ ...LOCAL_VIEW, detected: [] })
    focusReady(E3)
    render(<GraphInspector />)
    expect(screen.queryByRole('button', { name: /Open in KiCad/ })).toBeNull()
  })

  it('disables the buttons with the reason while the companion is offline', () => {
    mockLocalFolder({ ...LOCAL_VIEW, bridge: { connected: false, tools_installed: {} } })
    focusReady(E3)
    render(<GraphInspector />)
    const kicad = screen.getByRole('button', { name: 'Open in KiCad' })
    expect(kicad).toBeDisabled()
    expect(screen.getByRole('note')).toHaveTextContent('Solus companion is offline on this machine')
  })
})

describe('GraphInspector — focused', () => {
  it('shows a loading line while the neighbourhood fetches', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'loading' })
    render(<GraphInspector />)
    expect(screen.getByText(/LOADING NEIGHBOURHOOD/)).toBeInTheDocument()
  })

  it('shows ONE error line when the neighbourhood fetch fails', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'error', error: 'timed out' })
    render(<GraphInspector />)
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
    render(<GraphInspector />)
    expect(screen.getByTestId('focused-name')).toHaveTextContent('elbow motor')
    expect(screen.getByTestId('neighbour-count')).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: 'wrist servo' })).toBeInTheDocument()
  })
})
