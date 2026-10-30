// SOLUSDEV-320 P2-T1 — the shared search hook behind ⌘K and the `@` picker:
// debounce, stale-response guard, per-project cache and view invalidation.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { searchProject, type SearchResponse, type SearchScope } from '../../lib/api/search'
import { useAuthStore } from '../../store/authStore'
import { notifySourceViewChanged } from '../graph/sourceViewEvents'
import { SEARCH_DEBOUNCE_MS, clearSearchCache, useProjectSearch } from './useProjectSearch'

vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))

const hit = (id: string): SearchResponse['entities'][number] => ({
  id,
  kind: 'part',
  domain: 'mechanical',
  name: id,
  snippet: '',
  score: 1,
  why: 'name_match'
})
const response = (...ids: string[]): SearchResponse => ({
  entities: ids.map(hit),
  solus: [],
  truncated: false
})
const tick = (): Promise<void> =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
  })

beforeEach(() => {
  vi.useFakeTimers()
  clearSearchCache()
})
afterEach(() => {
  vi.useRealTimers()
  vi.resetAllMocks()
})

it('debounces keystrokes into one request and reports pending meanwhile', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q, { scope: 'all' }), {
    initialProps: { q: 'c' }
  })
  rerender({ q: 'ca' })
  rerender({ q: 'cam' })
  expect(result.current.pending).toBe(true)
  expect(searchProject).not.toHaveBeenCalled()
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(1)
  expect(searchProject).toHaveBeenCalledWith('p1', 'cam', { scope: 'all', limit: undefined })
  expect(result.current.entities.map((e) => e.id)).toEqual(['cam'])
  expect(result.current.pending).toBe(false)
})

it('drops a slow response that a newer query has superseded', async () => {
  let resolveSlow!: (r: SearchResponse) => void
  vi.mocked(searchProject)
    .mockImplementationOnce(() => new Promise((res) => (resolveSlow = res)))
    .mockResolvedValueOnce(response('motor'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q), {
    initialProps: { q: 'cam' }
  })
  await tick()
  rerender({ q: 'motor' })
  await tick()
  await act(async () => resolveSlow(response('cam')))
  expect(result.current.entities.map((e) => e.id)).toEqual(['motor'])
})

it('serves a repeated query from the cache without a request', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q), {
    initialProps: { q: 'cam' }
  })
  await tick()
  rerender({ q: 'ca' })
  rerender({ q: 'cam' })
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(1)
  expect(result.current.entities.map((e) => e.id)).toEqual(['cam'])
})

it('keys the cache by scope and limit', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  const { rerender } = renderHook(({ scope }) => useProjectSearch('p1', 'cam', { scope }), {
    initialProps: { scope: 'all' as SearchScope }
  })
  await tick()
  rerender({ scope: 'entities' })
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(2)
})

it('clears the project cache when a source view changes', async () => {
  vi.mocked(searchProject)
    .mockResolvedValueOnce(response('old'))
    .mockResolvedValueOnce(response('renamed'))
  const { result } = renderHook(() => useProjectSearch('p1', 'cam'))
  await tick()
  expect(result.current.entities[0]?.id).toBe('old')
  act(() => notifySourceViewChanged('p1'))
  expect(result.current.entities).toEqual([])
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(2)
  expect(result.current.entities[0]?.id).toBe('renamed')
})

it('does not cache a response that was in flight when the view changed', async () => {
  let resolveSlow!: (r: SearchResponse) => void
  vi.mocked(searchProject)
    .mockImplementationOnce(() => new Promise((res) => (resolveSlow = res)))
    .mockResolvedValueOnce(response('renamed'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q), {
    initialProps: { q: 'cam' }
  })
  await tick()
  act(() => notifySourceViewChanged('p1'))
  await act(async () => resolveSlow(response('old')))
  // The bump already refetched; the late pre-change rows must not overwrite
  // that in the cache, so the same text afterwards still shows the rename.
  rerender({ q: 'ca' })
  rerender({ q: 'cam' })
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(2)
  expect(result.current.entities[0]?.id).toBe('renamed')
})

it('trims the query, skips whitespace and caps it at the route limit', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q), {
    initialProps: { q: '   ' }
  })
  await tick()
  expect(searchProject).not.toHaveBeenCalled()
  expect(result.current.pending).toBe(false)
  rerender({ q: ` ${'x'.repeat(300)} ` })
  await tick()
  expect(searchProject).toHaveBeenCalledWith('p1', 'x'.repeat(255), expect.anything())
})

it('returns the same empty arrays across renders', () => {
  const { result, rerender } = renderHook(() => useProjectSearch('p1', 'cam'))
  const first = result.current
  rerender()
  expect(result.current.entities).toBe(first.entities)
  expect(result.current.solus).toBe(first.solus)
})

it('forgets everything when the account ends', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.test' } })
  const { unmount } = renderHook(() => useProjectSearch('p1', 'cam'))
  await tick()
  unmount()
  act(() => useAuthStore.setState({ status: 'unauthenticated', user: null }))
  renderHook(() => useProjectSearch('p1', 'cam'))
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(2)
})

it('hides the previous project results and refetches on project change', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('cam'))
  const { result, rerender } = renderHook(({ p }) => useProjectSearch(p, 'cam'), {
    initialProps: { p: 'p1' as string | null }
  })
  await tick()
  rerender({ p: 'p2' })
  expect(result.current.entities).toEqual([])
  await tick()
  expect(searchProject).toHaveBeenLastCalledWith('p2', 'cam', expect.anything())
  rerender({ p: null })
  expect(result.current).toEqual({ entities: [], solus: [], pending: false })
})

it('treats an empty query and a failed request as no results', async () => {
  vi.mocked(searchProject).mockRejectedValue(new Error('offline'))
  const { result, rerender } = renderHook(({ q }) => useProjectSearch('p1', q), {
    initialProps: { q: '' }
  })
  await tick()
  expect(searchProject).not.toHaveBeenCalled()
  expect(result.current.pending).toBe(false)
  rerender({ q: 'cam' })
  await tick()
  expect(result.current).toEqual({ entities: [], solus: [], pending: false })
})

it('clearSearchCache(projectId) forgets only that project', async () => {
  vi.mocked(searchProject).mockResolvedValue(response('x'))
  const a = renderHook(() => useProjectSearch('p1', 'x'))
  const b = renderHook(() => useProjectSearch('p2', 'x'))
  await tick()
  clearSearchCache('p1')
  a.unmount()
  b.unmount()
  renderHook(() => useProjectSearch('p1', 'x'))
  renderHook(() => useProjectSearch('p2', 'x'))
  await tick()
  expect(searchProject).toHaveBeenCalledTimes(3)
})
