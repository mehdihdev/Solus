// Live summary for the Context Model screen: real counts from getProject
// (whose payload already carries the sources array) plus the full entity list
// via the cursor-following listAllEntities. Failures are classified with
// classifyFetchError so an answering-but-refusing API is never rendered as
// "backend unreachable" — and a failed list never hides honest counts.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useGraphSummary } from './useGraphSummary'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getProject: vi.fn(), listAllEntities: vi.fn() }
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
  sources: [{ id: 's1' }]
}

const ENTITY: resources.Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}

function linkProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

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

  it('loads counts from the project detail and the full entity list', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
    vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
    const { result } = renderHook(() => useGraphSummary())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entityCount).toBe(12)
    expect(result.current.relationCount).toBe(30)
    expect(result.current.sourceCount).toBe(1)
    expect(result.current.entities).toEqual([ENTITY])
    expect(vi.mocked(resources.getProject)).toHaveBeenCalledWith('p1')
    expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledWith('p1')
  })

  it('degrades to offline when the API is unreachable', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockRejectedValue(new Error('unreachable'))
    vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('unreachable'))
    const { result } = renderHook(() => useGraphSummary())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.entityCount).toBe(0)
  })

  it('reports error — not offline — when the API answers with a refusal', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockRejectedValue(new ApiError(403, 'forbidden', 'nope'))
    vi.mocked(resources.listAllEntities).mockResolvedValue([])
    const { result } = renderHook(() => useGraphSummary())
    await waitFor(() => expect(result.current.status).toBe('error'))
  })

  it('keeps honest counts with a null entity list when only the list call fails', async () => {
    linkProject()
    vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
    vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useGraphSummary())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entityCount).toBe(12)
    expect(result.current.entities).toBeNull()
  })
})
