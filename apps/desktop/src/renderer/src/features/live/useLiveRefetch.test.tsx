import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import {
  LIVE_COALESCE_MS,
  resetLiveRevisions,
  useLiveRevisionStore
} from '../../store/liveRevisionStore'
import { useLiveRefetch } from './useLiveRefetch'

beforeEach(() => {
  vi.useFakeTimers()
  resetLiveRevisions()
})
afterEach(() => {
  resetLiveRevisions()
  vi.useRealTimers()
})
const bump = (...keys: string[]): void => {
  useLiveRevisionStore.getState().bump(keys)
  act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
}

it('does not fire on mount, fires once when a watched key bumps', () => {
  const refetch = vi.fn()
  renderHook(() => useLiveRefetch(['a', 'b'], refetch))
  expect(refetch).not.toHaveBeenCalled()
  bump('a')
  expect(refetch).toHaveBeenCalledTimes(1)
  bump('c')
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('two watched keys bumped in one burst cause one refetch', () => {
  const refetch = vi.fn()
  renderHook(() => useLiveRefetch(['a', 'b'], refetch))
  bump('a', 'b')
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('does not fire when the watched keys themselves change (a different team)', () => {
  const refetch = vi.fn()
  bump('b')
  const view = renderHook(({ key }) => useLiveRefetch([key], refetch), {
    initialProps: { key: 'a' }
  })
  view.rerender({ key: 'b' })
  expect(refetch).not.toHaveBeenCalled()
  bump('b')
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('is inert while disabled, and calls the latest callback', () => {
  const first = vi.fn()
  const second = vi.fn()
  const view = renderHook(({ cb, enabled }) => useLiveRefetch(['a', null], cb, enabled), {
    initialProps: { cb: first, enabled: false }
  })
  expect(first).not.toHaveBeenCalled()
  view.rerender({ cb: second, enabled: true })
  expect(second).not.toHaveBeenCalled()
  bump('a')
  expect(first).not.toHaveBeenCalled()
  expect(second).toHaveBeenCalledTimes(1)
})

it('refetches once on enable when the revision moved while disabled', () => {
  const refetch = vi.fn()
  const view = renderHook(({ enabled }) => useLiveRefetch(['a'], refetch, enabled), {
    initialProps: { enabled: false }
  })
  bump('a')
  bump('a')
  expect(refetch).not.toHaveBeenCalled()
  view.rerender({ enabled: true })
  expect(refetch).toHaveBeenCalledTimes(1)
  view.rerender({ enabled: false })
  view.rerender({ enabled: true })
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('does not refetch on enable when nothing moved while disabled', () => {
  const refetch = vi.fn()
  const view = renderHook(({ enabled }) => useLiveRefetch(['a'], refetch, enabled), {
    initialProps: { enabled: false }
  })
  view.rerender({ enabled: true })
  expect(refetch).not.toHaveBeenCalled()
})
