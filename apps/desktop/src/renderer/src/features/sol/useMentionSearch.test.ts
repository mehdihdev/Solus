// SOLUSDEV-320 P2-T1 — the `@` picker rides the shared search hook and maps
// hits into the Entity shape the picker and MentionList already consume.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { searchProject, type SearchResponse } from '../../lib/api/search'
import { clearSearchCache, SEARCH_DEBOUNCE_MS } from '../workspace/useProjectSearch'
import { MENTION_DEBOUNCE_MS, MENTION_LIMIT, useMentionSearch } from './useMentionSearch'

vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))

const RESPONSE: SearchResponse = {
  entities: [
    {
      id: 'e1',
      kind: 'part',
      domain: 'mechanical',
      name: 'Camera Bracket',
      snippet: '',
      score: 1,
      why: 'name_match'
    }
  ],
  solus: [
    {
      id: 's1',
      entity_id: 'e2',
      section: 'identity',
      subsection: null,
      kind: 'note',
      name: 'cam note',
      snippet: '',
      score: 0.5,
      why: 'text_match'
    },
    {
      id: 's2',
      entity_id: 'e1',
      section: 'identity',
      subsection: null,
      kind: 'note',
      name: 'dup of e1',
      snippet: '',
      score: 0.4,
      why: 'text_match'
    },
    {
      id: 's3',
      entity_id: null,
      section: 'free',
      subsection: null,
      kind: 'note',
      name: 'unanchored',
      snippet: '',
      score: 0.3,
      why: 'text_match'
    }
  ],
  truncated: false
}

beforeEach(() => {
  vi.useFakeTimers()
  clearSearchCache()
})
afterEach(() => {
  vi.useRealTimers()
  vi.resetAllMocks()
})

it('searches every scope at the mention limit on the shared debounce', async () => {
  vi.mocked(searchProject).mockResolvedValue(RESPONSE)
  const { result } = renderHook(() => useMentionSearch('p1', 'cam'))
  expect(result.current).toEqual([])
  await act(() => vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS))
  expect(MENTION_DEBOUNCE_MS).toBe(SEARCH_DEBOUNCE_MS)
  expect(searchProject).toHaveBeenCalledWith('p1', 'cam', { scope: 'all', limit: MENTION_LIMIT })
  expect(result.current).toEqual([
    { id: 'e1', name: 'Camera Bracket', type: 'part', domain: 'mechanical', source_key: null },
    { id: 'e2', name: 'cam note', type: 'solus_entry', domain: 'project', source_key: null }
  ])
})

it('returns nothing without a project or an open token', async () => {
  vi.mocked(searchProject).mockResolvedValue(RESPONSE)
  const { result, rerender } = renderHook(({ p, q }) => useMentionSearch(p, q), {
    initialProps: { p: null as string | null, q: 'cam' as string | null }
  })
  await act(() => vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS))
  expect(result.current).toEqual([])
  rerender({ p: 'p1', q: null })
  await act(() => vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS))
  expect(result.current).toEqual([])
  expect(searchProject).not.toHaveBeenCalled()
})
