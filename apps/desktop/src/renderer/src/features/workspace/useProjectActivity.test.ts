import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useProjectActivity } from './useProjectActivity'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, listActivityPage: vi.fn() }
})

const row = (id: string): resources.ActivityApi => ({
  id,
  type: 'project.updated',
  domain: null,
  actor_id: null,
  project_id: 'p1',
  payload: {},
  created_at: ''
})

beforeEach(() => vi.clearAllMocks())

describe('useProjectActivity', () => {
  it('loads the project-filtered feed with the server total', async () => {
    vi.mocked(resources.listActivityPage).mockResolvedValue({
      data: [row('a')],
      meta: { total: 7, has_next: true, next_cursor: 'c2' }
    })
    const { result } = renderHook(() => useProjectActivity('t1', 'p1'))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(vi.mocked(resources.listActivityPage)).toHaveBeenCalledWith('t1', { projectId: 'p1' })
    expect(result.current.activity.map((a) => a.id)).toEqual(['a'])
    expect(result.current.total).toBe(7)
    expect(result.current.hasMore).toBe(true)
  })

  it('appends the next cursor page and keeps the feed when a page fails', async () => {
    vi.mocked(resources.listActivityPage)
      .mockResolvedValueOnce({
        data: [row('a')],
        meta: { total: 3, has_next: true, next_cursor: 'c2' }
      })
      .mockResolvedValueOnce({
        data: [row('b')],
        meta: { total: 3, has_next: true, next_cursor: 'c3' }
      })
      .mockRejectedValueOnce(new Error('down'))
    const { result } = renderHook(() => useProjectActivity('t1', 'p1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(() => result.current.loadMore())
    expect(vi.mocked(resources.listActivityPage)).toHaveBeenLastCalledWith('t1', {
      projectId: 'p1',
      cursor: 'c2'
    })
    expect(result.current.activity.map((a) => a.id)).toEqual(['a', 'b'])
    await act(() => result.current.loadMore())
    expect(result.current.activity.map((a) => a.id)).toEqual(['a', 'b'])
    expect(result.current.hasMore).toBe(true)
  })

  it('reports offline when the first page fails', async () => {
    vi.mocked(resources.listActivityPage).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useProjectActivity('t1', 'p1'))
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.activity).toEqual([])
  })
})
