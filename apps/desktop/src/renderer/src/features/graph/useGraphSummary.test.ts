// Live graph summary for the Context Model screen (SOLUSDEV-152): real
// entity/relation/source counts via getProject + listSources. Degrades to
// `offline` (dev bypass / no project / unreachable API) so callers render an
// honest empty state, never placeholder robot data.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useGraphSummary } from './useGraphSummary'
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
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: '',
  stats: { entities: 12, relations: 30 },
  sources: []
}

const SOURCE = { id: 's1' } as resources.Source

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('useGraphSummary', () => {
  it('reports offline when the workspace is not linked (dev bypass)', () => {
    const { result } = renderHook(() => useGraphSummary())
    expect(result.current.status).toBe('offline')
    expect(vi.mocked(resources.getProject)).not.toHaveBeenCalled()
  })

  it('reports offline when linked but no project is selected', () => {
    useWorkspaceStore.setState({ linked: true, project: null })
    const { result } = renderHook(() => useGraphSummary())
    expect(result.current.status).toBe('offline')
  })

  it('loads real entity, relation, and source counts for the linked project', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    const { result } = renderHook(() => useGraphSummary())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entityCount).toBe(12)
    expect(result.current.relationCount).toBe(30)
    expect(result.current.sourceCount).toBe(1)
    expect(vi.mocked(resources.getProject)).toHaveBeenCalledWith('p1')
    expect(vi.mocked(resources.listSources)).toHaveBeenCalledWith('p1')
  })

  it('degrades to offline when the API is unreachable', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    vi.mocked(resources.getProject).mockRejectedValue(new Error('unreachable'))
    vi.mocked(resources.listSources).mockRejectedValue(new Error('unreachable'))
    const { result } = renderHook(() => useGraphSummary())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.entityCount).toBe(0)
  })
})
