// Workspace screen: honest empty states (SOLUSDEV-152) plus the entity
// list (SOLUSDEV-70) — the project's entities render as selectable rows, and
// selecting one drives the shared focus store (one bounded neighbourhood
// fetch re-scopes every mounted widget).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkspaceScreen } from './WorkspaceScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import { graphCache } from './graphCache'

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
  vi.mocked(resources.getSolus).mockResolvedValue({
    entity_id: 'solus-1',
    sections: { hardware: [], details: [], errors: [], docs: [], code: [] }
  })
  graphCache.clear()
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
  it('prompts to connect a source when none are connected', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(
      await screen.findByText("Connect a source to start building your robot's graph")
    ).toBeInTheDocument()
  })

  it('renders the .solus panel beside the canvas', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(await screen.findByText('Hardware configs')).toBeInTheDocument()
    expect(screen.getByTestId('solus-panel')).toBeInTheDocument()
  })

  it('calls a project with only the .solus node empty — on purpose — and still lists it', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0))
    vi.mocked(resources.listAllEntities).mockResolvedValue([
      { id: 'solus-1', type: 'solus_config', domain: 'project', name: '.solus', source_key: '' }
    ])
    render(<WorkspaceScreen />)
    expect(await screen.findByText('An empty project — on purpose')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /\.solus/ })).toBeInTheDocument()
    expect(screen.getByText(/right-click a \.solus section to import/)).toBeInTheDocument()
  })

  it('counts imported files honestly in the on-purpose copy', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(2, 1))
    vi.mocked(resources.listAllEntities).mockResolvedValue([
      { id: 'solus-1', type: 'solus_config', domain: 'project', name: '.solus', source_key: '' },
      { id: 'd1', type: 'document', domain: 'project', name: 'rules.pdf', source_key: '' }
    ])
    render(<WorkspaceScreen />)
    expect(
      await screen.findByText(/Only the \.solus node and its imported file are here/)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /rules\.pdf/ })).toBeInTheDocument()
  })

  it('prompts to sync when sources exist but no entities do', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    render(<WorkspaceScreen />)
    expect(await screen.findByText('Waiting for your first sync')).toBeInTheDocument()
  })

  it('lists entities sorted by name, with real counts in the corner', async () => {
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
    const rows = screen.getAllByRole('button', { name: /elbow motor|wrist servo/ })
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('elbow motor'),
      expect.stringContaining('wrist servo')
    ])
    expect(screen.queryByText('Your graph is taking shape')).not.toBeInTheDocument()
  })

  it('selecting a row drives the shared focus store', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(1, 0, [{ id: 's1' }]))
    vi.mocked(resources.listAllEntities).mockResolvedValue([entity('e1', 'elbow motor')])
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
      entities: [entity('e1', 'elbow motor')],
      edges: [],
      truncated: false
    })
    render(<WorkspaceScreen />)
    await userEvent.click(await screen.findByRole('button', { name: /elbow motor/ }))
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

  it('shows a loading line while the summary fetches', () => {
    linkProject()
    vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
    vi.mocked(resources.listAllEntities).mockReturnValue(new Promise(() => undefined))
    render(<WorkspaceScreen />)
    expect(screen.getByText(/LOADING WORKSPACE/)).toBeInTheDocument()
  })
})
