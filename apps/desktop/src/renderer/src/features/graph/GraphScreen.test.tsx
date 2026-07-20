// Context Model screen (SOLUSDEV-152): the prototype demo graph is gone.
// The screen keeps its layout shell (canvas backdrop + inspector rail),
// renders an honest empty state, and shows REAL counts from the graph API
// where the prototype displayed fabricated ones.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { GraphScreen } from './GraphScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getProject: vi.fn(), listSources: vi.fn() }
})

function detailWith(entities: number, relations: number): resources.ProjectDetail {
  return {
    id: 'p1',
    team_id: 't1',
    name: 'Rover MK2',
    description: null,
    archived_at: null,
    created_at: '',
    updated_at: '',
    stats: { entities, relations },
    sources: []
  }
}

function linkProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('GraphScreen — unlinked (dev bypass)', () => {
  it('shows the honest sign-in/connect empty state', () => {
    render(<GraphScreen />)
    expect(screen.getByText('Your context model will live here')).toBeInTheDocument()
    expect(
      screen.getByText(/connect a source to start building your robot's graph/i)
    ).toBeInTheDocument()
  })

  it('contains no fabricated nodes, alerts, or counts', () => {
    const { container } = render(<GraphScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES/)
    expect(text).not.toMatch(/leg_ik\.c|DRV8316C|motor_driver\.c/)
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/SYNCED 2 MIN AGO/)
  })
})

describe('GraphScreen — linked', () => {
  it('prompts to connect a source when none are connected', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0))
    vi.mocked(resources.listSources).mockResolvedValue([])
    render(<GraphScreen />)
    expect(
      await screen.findByText("Connect a source to start building your robot's graph")
    ).toBeInTheDocument()
  })

  it('prompts to sync when sources exist but no entities do', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(0, 0))
    vi.mocked(resources.listSources).mockResolvedValue([{ id: 's1' } as resources.Source])
    render(<GraphScreen />)
    expect(await screen.findByText('Waiting for your first sync')).toBeInTheDocument()
  })

  it('shows real entity and relation counts once the graph has data', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(detailWith(12, 30))
    vi.mocked(resources.listSources).mockResolvedValue([{ id: 's1' } as resources.Source])
    render(<GraphScreen />)
    await waitFor(() =>
      expect(screen.getByText('12 ENTITIES · 30 RELATIONS · 1 SOURCE')).toBeInTheDocument()
    )
    expect(screen.getByText('Your graph is taking shape')).toBeInTheDocument()
  })

  it('shows a loading line while the summary fetches', () => {
    linkProject()
    vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
    vi.mocked(resources.listSources).mockReturnValue(new Promise(() => undefined))
    render(<GraphScreen />)
    expect(screen.getByText(/LOADING CONTEXT MODEL/)).toBeInTheDocument()
  })
})
