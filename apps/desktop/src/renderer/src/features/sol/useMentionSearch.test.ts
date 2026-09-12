import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { listEntities, type Entity } from '../../lib/api/resources'
import { useMentionSearch } from './useMentionSearch'

vi.mock('../../lib/api/resources', () => ({ listEntities: vi.fn() }))
const row: Entity = {
  id: 'old',
  name: 'index.ts',
  type: 'code_file',
  domain: 'code',
  source_key: 'src/index.ts'
}
afterEach(() => {
  vi.useRealTimers()
  vi.resetAllMocks()
})

it('hides previous project results immediately and ignores late responses', async () => {
  vi.useFakeTimers()
  let resolveOld!: (rows: Entity[]) => void
  vi.mocked(listEntities)
    .mockResolvedValueOnce([row])
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve
        })
    )
    .mockResolvedValueOnce([])
  const { result, rerender } = renderHook(
    ({ project, query }) => useMentionSearch(project, query),
    { initialProps: { project: 'p1', query: 'index' } }
  )
  await act(() => vi.advanceTimersByTimeAsync(400))
  expect(result.current).toEqual([row])
  rerender({ project: 'p1', query: 'src' })
  expect(result.current).toEqual([])
  await act(() => vi.advanceTimersByTimeAsync(400))
  rerender({ project: 'p2', query: 'src' })
  expect(result.current).toEqual([])
  await act(async () => {
    resolveOld([row])
  })
  expect(result.current).toEqual([])
  await act(() => vi.advanceTimersByTimeAsync(400))
  expect(result.current).toEqual([])
})

it('discards rows when leaving a project even if the user returns before the debounce', async () => {
  vi.useFakeTimers()
  vi.mocked(listEntities).mockResolvedValue([row])
  const { result, rerender } = renderHook(({ project }) => useMentionSearch(project, 'index'), {
    initialProps: { project: 'p1' }
  })
  await act(() => vi.advanceTimersByTimeAsync(400))
  expect(result.current).toEqual([row])
  rerender({ project: 'p2' })
  expect(result.current).toEqual([])
  rerender({ project: 'p1' })
  expect(result.current).toEqual([])
})

it('invalidates the same query when this user changes a repository view', async () => {
  const { notifySourceViewChanged } = await import('../graph/sourceViewEvents')
  vi.useFakeTimers()
  vi.mocked(listEntities)
    .mockResolvedValueOnce([row])
    .mockResolvedValueOnce([{ ...row, id: 'new-branch-file' }])
  const { result } = renderHook(() => useMentionSearch('p1', 'index'))
  await act(() => vi.advanceTimersByTimeAsync(400))
  expect(result.current).toEqual([row])
  act(() => notifySourceViewChanged('p1'))
  expect(result.current).toEqual([])
  await act(() => vi.advanceTimersByTimeAsync(400))
  expect(result.current[0]?.id).toBe('new-branch-file')
})
