// Project hub overview data (SOLUSDEV-164): project detail + sources for the
// open project, degrading to offline like useGraphSummary (SOLUSDEV-152).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useProjectOverview } from './useProjectOverview'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getProject: vi.fn(), listSources: vi.fn() }
})

const DETAIL: resources.ProjectDetail = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: 'a quadruped',
  archived_at: null,
  created_at: '',
  updated_at: '',
  stats: { entities: 12, relations: 30 },
  sources: []
}

const SOURCE = {
  id: 's1',
  name: 'octo/arm',
  type: 'github',
  status: 'connected'
} as resources.Source

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('useProjectOverview', () => {
  it('reports offline when no project is selected', () => {
    useWorkspaceStore.setState({ linked: true, project: null })
    const { result } = renderHook(() => useProjectOverview())
    expect(result.current.status).toBe('offline')
    expect(vi.mocked(resources.getProject)).not.toHaveBeenCalled()
  })

  it('loads the project detail and its sources', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    const { result } = renderHook(() => useProjectOverview())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.name).toBe('Rover MK2')
    expect(result.current.description).toBe('a quadruped')
    expect(result.current.entityCount).toBe(12)
    expect(result.current.relationCount).toBe(30)
    expect(result.current.sources).toHaveLength(1)
  })

  it('falls back to the stored project name while offline', () => {
    useWorkspaceStore.setState({ linked: false, project: { id: 'p1', name: 'Rover MK2' } })
    const { result } = renderHook(() => useProjectOverview())
    expect(result.current.status).toBe('offline')
    expect(result.current.name).toBe('Rover MK2')
  })

  it('degrades to offline when the API is unreachable', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    vi.mocked(resources.getProject).mockRejectedValue(new Error('unreachable'))
    vi.mocked(resources.listSources).mockRejectedValue(new Error('unreachable'))
    const { result } = renderHook(() => useProjectOverview())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.sources).toHaveLength(0)
  })
})

describe('useProjectOverview — project switch mid-flight (SOLUSDEV-242)', () => {
  it('drops a response for a project the user has since left', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    let resolveA: (detail: resources.ProjectDetail) => void = () => undefined
    // A's detail hangs until we release it; B's answers at once.
    vi.mocked(resources.getProject).mockImplementation((id) =>
      id === 'p1'
        ? new Promise<resources.ProjectDetail>((resolve) => (resolveA = resolve))
        : Promise.resolve({
            ...DETAIL,
            id: 'p2',
            name: 'Arm',
            stats: { entities: 1, relations: 0 }
          })
    )
    vi.mocked(resources.listSources).mockResolvedValue([])
    const { result, rerender } = renderHook(() => useProjectOverview())
    act(() => {
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'Arm' } })
    })
    rerender()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.name).toBe('Arm')
    await act(async () => {
      resolveA(DETAIL)
      await Promise.resolve()
    })
    expect(result.current.name).toBe('Arm')
    expect(result.current.entityCount).toBe(1)
  })
})
