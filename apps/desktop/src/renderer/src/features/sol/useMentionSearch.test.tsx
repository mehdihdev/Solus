import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MENTION_DEBOUNCE_MS, MENTION_LIMIT, useMentionSearch } from './useMentionSearch'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  listEntities: vi.fn()
}))

const { listEntities } = await import('../../lib/api/resources')
const mockListEntities = vi.mocked(listEntities)

function Probe({ query }: { query: string | null }): React.JSX.Element {
  const results = useMentionSearch('p1', query)
  return <div data-testid="names">{results.map((r) => r.name).join(',')}</div>
}

const names = (): string => screen.getByTestId('names').textContent ?? ''

function entity(name: string): { id: string; name: string } {
  return { id: `id-${name}`, name }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMentionSearch', () => {
  it('debounces rather than searching per keystroke', async () => {
    mockListEntities.mockResolvedValue([entity('Camera Bracket')] as never)
    const { rerender } = render(<Probe query="c" />)
    rerender(<Probe query="ca" />)
    rerender(<Probe query="cam" />)

    expect(mockListEntities).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(mockListEntities).toHaveBeenCalledTimes(1)
    expect(mockListEntities).toHaveBeenCalledWith('p1', { q: 'cam', limit: MENTION_LIMIT })
    expect(names()).toBe('Camera Bracket')
  })

  it('drops a slow response that a newer query has already superseded', async () => {
    let resolveSlow: (rows: unknown) => void = () => {}
    mockListEntities
      .mockReturnValueOnce(new Promise((res) => (resolveSlow = res)) as never)
      .mockResolvedValueOnce([entity('Motor Mount')] as never)

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
      resolveSlow([entity('Camera Bracket')])
    })

    expect(names()).toBe('Motor Mount')
  })

  it('shows nothing when there is no open token', async () => {
    render(<Probe query={null} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(mockListEntities).not.toHaveBeenCalled()
    expect(names()).toBe('')
  })

  it('treats a failed search as an empty list, never a thrown error', async () => {
    mockListEntities.mockRejectedValue(new Error('offline'))
    render(<Probe query="cam" />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(names()).toBe('')
  })
})
