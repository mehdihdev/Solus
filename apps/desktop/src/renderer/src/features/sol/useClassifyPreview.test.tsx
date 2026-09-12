// MO-04: debounced classify preview — debounce, latest-wins, fail-to-null.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ClassifyPreview } from '../../lib/api/resources'
import * as resources from '../../lib/api/resources'
import { useClassifyPreview } from './useClassifyPreview'

vi.mock('../../lib/api/resources', () => ({ classifyQuery: vi.fn() }))
const classifyQuery = vi.mocked(resources.classifyQuery)

function preview(tokens: number): ClassifyPreview {
  return {
    complexity: 'standard',
    type: 'code',
    reasoner: { name: 'sol-reasoner-1', effort: 'standard' },
    cost_tier: 'standard',
    source: { complexity: 'estimator', type: 'estimator' },
    tokens_estimate: tokens,
    viable: true,
    reason: null,
    escalated: false,
    options: { complexities: [], types: [] }
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  classifyQuery.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
})

it('debounces: one call after the pause, none per keystroke', async () => {
  classifyQuery.mockResolvedValue(preview(1))
  const { rerender } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'w' }
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200)
  })
  rerender({ q: 'why' }) // typing again before the pause elapses
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200)
  })
  expect(classifyQuery).not.toHaveBeenCalled()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(classifyQuery).toHaveBeenCalledTimes(1)
  expect(classifyQuery).toHaveBeenCalledWith({ query: 'why' })
})

it('applies only the latest response when requests race', async () => {
  let resolveFirst: (p: ClassifyPreview) => void = () => {}
  classifyQuery
    .mockImplementationOnce(
      () => new Promise<ClassifyPreview>((resolve) => (resolveFirst = resolve))
    )
    .mockResolvedValueOnce(preview(2))
  const { result, rerender } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'first question' }
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400) // fires request 1 (unresolved)
  })
  rerender({ q: 'second question' })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400) // fires request 2, resolves 'newer'
  })
  expect(result.current.preview?.tokens_estimate).toBe(2)
  await act(async () => {
    resolveFirst(preview(3)) // request 1 arrives late
  })
  expect(result.current.preview?.tokens_estimate).toBe(2) // stale dropped
})

it('classify failure shows nothing and never throws', async () => {
  classifyQuery.mockRejectedValue(new Error('api down'))
  const { result } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'hello there' }
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(result.current.preview).toBeNull()
})

it('empty input clears the preview and makes no call', async () => {
  classifyQuery.mockResolvedValue(preview(1))
  const { result, rerender } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'hello' }
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(result.current.preview).not.toBeNull()
  rerender({ q: '   ' })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(result.current.preview).toBeNull()
  expect(classifyQuery).toHaveBeenCalledTimes(1)
})

it('overrides re-classify with explicit values and reset clears them', async () => {
  classifyQuery.mockResolvedValue(preview(1))
  const { result } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'hello world' }
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  act(() => {
    result.current.setOverride({ complexity: 'hard' })
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(classifyQuery).toHaveBeenLastCalledWith({ query: 'hello world', complexity: 'hard' })
  expect(result.current.override.complexity).toBe('hard')
  act(() => {
    result.current.resetOverride()
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(classifyQuery).toHaveBeenLastCalledWith({ query: 'hello world' })
  expect(result.current.override).toEqual({ complexity: null, type: null, thinkHarder: false })
})

it('sends think_harder only when the toggle is on', async () => {
  classifyQuery.mockResolvedValue(preview(1))
  const { result } = renderHook(({ q }) => useClassifyPreview(q), {
    initialProps: { q: 'hello world' }
  })
  act(() => {
    result.current.setOverride({ thinkHarder: true })
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
  expect(classifyQuery).toHaveBeenLastCalledWith({ query: 'hello world', think_harder: true })
})
