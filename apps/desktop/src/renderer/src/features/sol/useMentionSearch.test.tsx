import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SearchResponse } from '../../lib/api/search'
import { clearSearchCache } from '../workspace/useProjectSearch'
import { MENTION_DEBOUNCE_MS, MENTION_LIMIT, useMentionSearch } from './useMentionSearch'

vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))

const { searchProject } = await import('../../lib/api/search')
const mockSearch = vi.mocked(searchProject)

function Probe({ query }: { query: string | null }): React.JSX.Element {
  const results = useMentionSearch('p1', query)
  return <div data-testid="names">{results.map((r) => r.name).join(',')}</div>
}

const names = (): string => screen.getByTestId('names').textContent ?? ''

function hits(...names: string[]): SearchResponse {
  return {
    entities: names.map((name) => ({
      id: `id-${name}`,
      kind: 'part',
      domain: 'mechanical',
      name,
      snippet: '',
      score: 1,
      why: 'name_match'
    })),
    solus: [],
    truncated: false
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  clearSearchCache()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMentionSearch', () => {
  it('debounces rather than searching per keystroke', async () => {
    mockSearch.mockResolvedValue(hits('Camera Bracket'))
    const { rerender } = render(<Probe query="c" />)
    rerender(<Probe query="ca" />)
    rerender(<Probe query="cam" />)

    expect(mockSearch).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(mockSearch).toHaveBeenCalledTimes(1)
    expect(mockSearch).toHaveBeenCalledWith('p1', 'cam', { scope: 'all', limit: MENTION_LIMIT })
    expect(names()).toBe('Camera Bracket')
  })

  it('drops a slow response that a newer query has already superseded', async () => {
    let resolveSlow: (rows: SearchResponse) => void = () => {}
    mockSearch
      .mockReturnValueOnce(new Promise((res) => (resolveSlow = res)))
      .mockResolvedValueOnce(hits('Motor Mount'))

    const { rerender } = render(<Probe query="cam" />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })
    rerender(<Probe query="motor" />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    // The first query now answers, late. It must not repopulate the list.
    await act(async () => {
      resolveSlow(hits('Camera Bracket'))
    })

    expect(names()).toBe('Motor Mount')
  })

  it('shows nothing when there is no open token', async () => {
    render(<Probe query={null} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(mockSearch).not.toHaveBeenCalled()
    expect(names()).toBe('')
  })

  it('treats a failed search as an empty list, never a thrown error', async () => {
    mockSearch.mockRejectedValue(new Error('offline'))
    render(<Probe query="cam" />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(names()).toBe('')
  })
})
